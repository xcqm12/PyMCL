"""AI 助手（mineflayer 机器人）随游戏启动的集成层。

- 启动游戏时自动拉起 Node 子进程（assistant/bot.js），加入同一服务器陪玩；
- 自动把 CustomSkinLoader jar 与助手皮肤部署到游戏目录，
  玩家客户端经 CSL LocalSkin/<助手ID>.png 渲染皮肤。
"""
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config

CREATE_NO_WINDOW = 0x08000000

# 随包分发的资源（开发模式在仓库 assistant/；PyInstaller 打包后在 _MEIPASS/assistant）
_ASSETS = ("bot.js", "package.json", "AuroraAI.png", "CustomSkinLoader_Universal-15.1.jar")

_proc = None
_lock = threading.RLock()


def _log_safe(on_log, msg, level="dim"):
    if not on_log:
        return
    try:
        on_log(msg, level)
    except Exception:
        pass


def _asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") \
            else Path(sys.executable).resolve().parent
        d = base / "assistant"
        if d.is_dir():
            return d
        return Path(sys.executable).resolve().parent / "assistant"
    return Path(__file__).resolve().parent.parent / "assistant"


def find_node():
    p = shutil.which("node")
    if p:
        return p
    for c in (Path("C:/Program Files/nodejs/node.exe"),
              Path("C:/Program Files (x86)/nodejs/node.exe")):
        if c.exists():
            return str(c)
    return None


def _find_npm(node: str):
    p = shutil.which("npm")
    if p:
        return p
    bin_dir = Path(node).parent
    for name in ("npm.cmd", "npm"):
        f = bin_dir / name
        if f.exists():
            return str(f)
    return None


def _npm_proxy_args(npm: str) -> list:
    """npm 配置了代理但代理不可达时（如 Clash/V2Ray 未启动）返回清空代理的参数，
    否则 npm 会静默挂死。"""
    try:
        r = subprocess.run([npm, "config", "get", "proxy"], capture_output=True,
                           text=True, timeout=10, creationflags=CREATE_NO_WINDOW)
        proxy = (r.stdout or "").strip()
        if proxy and "://" in proxy:
            from urllib.parse import urlparse
            u = urlparse(proxy)
            s = socket.socket()
            s.settimeout(1.5)
            try:
                s.connect((u.hostname or "127.0.0.1", u.port or 80))
                return []          # 代理存活，正常走代理
            except Exception:
                return ["--proxy=null", "--https-proxy=null"]  # 代理死了，绕过
            finally:
                s.close()
    except Exception:
        pass
    return []


def _deps_ok(adir: Path, node: str) -> bool:
    """require 冒烟：npm 安装成功且模块可加载（镜像大包残缺时也能发现）。"""
    try:
        r = subprocess.run(
            [node, "-e", "require('mineflayer');require('mineflayer-pathfinder');"
                        "require('mineflayer-collectblock');require('adm-zip')"],
            cwd=str(adir), capture_output=True, text=True, timeout=60,
            creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def _npm_install(npm: str, adir: Path, mirror: bool) -> subprocess.CompletedProcess:
    cmd = [npm, "install", "--no-audit", "--no-fund"] + _npm_proxy_args(npm)
    if mirror:
        cmd += ["--registry", "https://registry.npmmirror.com"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                          cwd=str(adir), creationflags=CREATE_NO_WINDOW)


def assistant_dir(mc_root) -> Path:
    return Path(mc_root) / "assistant"


def ensure_env(mc_root, on_log=None) -> tuple:
    """准备 bot.js/依赖，返回 (node.exe 路径, assistant 目录)。"""
    node = find_node()
    if not node:
        raise RuntimeError(
            "未找到 Node.js（需要 18+），请到 nodejs.org 安装后重启 PyMCL")
    adir = assistant_dir(mc_root)
    adir.mkdir(parents=True, exist_ok=True)
    src_dir = _asset_dir()
    for name in _ASSETS:
        src = src_dir / name
        dst = adir / name
        if not src.exists():
            continue
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)

    if not _deps_ok(adir, node):
        npm = _find_npm(node)
        if not npm:
            raise RuntimeError("未找到 npm，无法安装 AI 助手依赖")
        _log_safe(on_log, "AI 助手首次运行：正在安装依赖（约 20MB，稍等片刻）…")
        try:
            r = _npm_install(npm, adir, bool(config.get("use_mirror", True)))
        except Exception as e:
            raise RuntimeError(f"AI 助手依赖安装失败: {e}")
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "")[-400:]
            raise RuntimeError(f"AI 助手依赖安装失败: {tail}")
        # 镜像源偶发大包残缺（如 minecraft-data）：自检不过就换官方源重装一次
        if not _deps_ok(adir, node):
            _log_safe(on_log, "镜像源安装不完整，改用官方源重试…", "warn")
            r = _npm_install(npm, adir, False)
            if r.returncode != 0:
                tail = (r.stderr or r.stdout or "")[-400:]
                raise RuntimeError(f"AI 助手依赖安装失败: {tail}")
            if not _deps_ok(adir, node):
                raise RuntimeError("AI 助手依赖安装后自检失败，请检查网络后重试")
        _log_safe(on_log, "AI 助手依赖安装完成", "ok")
    return node, adir


def _parse_server(raw):
    s = (raw or "").strip()
    if not s:
        return None, None
    if ":" in s:
        host, _, port = s.rpartition(":")
        if port.isdigit() and host.strip():
            return host.strip(), int(port)
    parts = s.split()
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return s, 25565


def ensure_skin(mc_root, game_dir, bot_name, on_log=None) -> list:
    """把 CSL jar 与助手皮肤部署到游戏目录（幂等），返回安装路径列表。"""
    src = _asset_dir()
    jar = src / "CustomSkinLoader_Universal-15.1.jar"
    skin = src / "AuroraAI.png"
    installed = []
    targets = []
    for d in (Path(mc_root), Path(game_dir)):
        d = Path(d)
        if d not in targets:
            targets.append(d)
    for d in targets:
        if jar.exists():
            mods = d / "mods"
            mods.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jar, mods / jar.name)
            installed.append(str(mods / jar.name))
        if skin.exists():
            local = d / "CustomSkinLoader" / "LocalSkin"
            local.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skin, local / f"{bot_name}.png")
            installed.append(str(local / f"{bot_name}.png"))
    return installed


def build_config(game_dir, player_name) -> tuple:
    """按设置页配置生成 assistant_config.json，返回 (路径, 助手ID)。"""
    raw = config.get("assistant_server", "")
    host, port = _parse_server(raw)
    if not host:
        raise RuntimeError("AI 助手未配置服务器地址（设置页 → AI 助手）")
    provider = str(config.get("assistant_provider", "deepseek")).lower()
    provider = "glm" if provider.startswith(("glm", "zhipu", "bigmodel")) else "deepseek"
    key = config.get("assistant_api_key_glm", "") if provider == "glm" \
        else config.get("assistant_api_key_deepseek", "")
    name = (config.get("assistant_name", "") or "AuroraAI").strip()
    # 配方知识库要扫描的模组目录：当前游戏目录 + 启动器根目录 + 设置页可选目录
    mods_dirs = []
    for d in (Path(game_dir) / "mods", config.mc_root() / "mods",
              Path(config.get("assistant_mods_dir", "") or "")):
        if str(d) not in ("", ".") and d.is_dir() and str(d) not in mods_dirs:
            mods_dirs.append(str(d))
    data = {
        "name": name,
        "host": host,
        "port": port,
        "provider": provider,
        "api_key": key,
        "model": config.get("assistant_model", ""),
        "persona": config.get("assistant_persona", ""),
        "player_name": player_name,
        "mods_dirs": mods_dirs,
    }
    path = Path(game_dir) / "assistant_config.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    return path, name


def start_assistant(game_dir, player_name, on_log=None) -> subprocess.Popen:
    """启动助手进程（会先停掉旧实例）。"""
    global _proc
    stop_assistant()
    mc_root = config.mc_root()
    node, adir = ensure_env(mc_root, on_log)
    cfg_path, name = build_config(game_dir, player_name)
    on_log_safe = lambda m, l="dim": _log_safe(on_log, m, l)
    installed = ensure_skin(mc_root, game_dir, name)
    on_log_safe(f"助手皮肤/CSL 已部署到游戏目录（{len(installed)} 个文件）", "dim")
    logs_dir = Path(game_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"assistant-{time.strftime('%Y%m%d-%H%M%S')}.log"
    argv = [node, str(Path(adir) / "bot.js"), "--config", str(cfg_path)]
    with _lock:
        _proc = subprocess.Popen(argv, cwd=str(game_dir),
                                 stdout=open(log_path, "w", encoding="utf-8",
                                             errors="replace"),
                                 stderr=subprocess.STDOUT,
                                 creationflags=CREATE_NO_WINDOW)
        proc = _proc
    on_log_safe(f"AI 助手 {name} 进程已启动 (PID {proc.pid})，日志 {log_path}", "dim")
    return proc


def stop_assistant():
    global _proc
    with _lock:
        proc = _proc
        _proc = None
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def is_running() -> bool:
    with _lock:
        return _proc is not None and _proc.poll() is None


def start_with_game(game_dir, player_name, player_proc, on_log=None):
    """随游戏启动助手（独立线程，不阻塞启动流程），并随游戏退出自动停止。"""
    def task():
        try:
            start_assistant(game_dir, player_name, on_log)
        except Exception as e:
            _log_safe(on_log, f"AI 助手启动失败: {e}", "warn")

    def monitor():
        try:
            player_proc.wait()
        except Exception:
            pass
        stop_assistant()
        _log_safe(on_log, "游戏已退出，AI 助手已停止", "dim")

    threading.Thread(target=task, daemon=True, name="assistant-start").start()
    threading.Thread(target=monitor, daemon=True, name="assistant-monitor").start()
