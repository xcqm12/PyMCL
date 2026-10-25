"""启动流程：参数拼装、令牌替换、进程启动。"""
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from . import config, versions
from .downloads import DownloadManager

CREATE_NO_WINDOW = 0x08000000


class LaunchError(Exception):
    pass


def _fmt_mb(v):
    return f"{int(v)}M"


def build_tokens(merged: dict, vid: str, auth, game_dir: Path,
                 natives_dir: Path, legacy: bool) -> dict:
    ai = merged.get("assetIndex", {})
    assets_root = config.mc_root() / "assets"
    idx_id = merged.get("assets") or ai.get("id", "legacy")
    index_path = assets_root / "indexes" / f"{idx_id}.json"
    virtual = False
    try:
        if index_path.exists():
            import json
            idx = json.loads(index_path.read_text("utf-8"))
            if idx.get("virtual"):
                virtual = True
    except Exception:
        pass
    game_assets = (assets_root / "virtual" / idx_id) if virtual else (assets_root / "virtual" / "legacy")
    uuid = auth.uuid or ""
    return {
        "auth_player_name": auth.name,
        "auth_uuid": uuid.replace("-", "") if legacy else uuid,
        "auth_access_token": auth.access_token or "0",
        "auth_session": auth.access_token or "0",
        "auth_xuid": getattr(auth, "xuid", "") or "",
        "clientid": "pymcl-" + secrets.token_hex(8),
        "user_type": auth.user_type or "msa",
        "user_properties": "{}",
        "version_name": vid,
        "version_type": merged.get("type", "release"),
        "game_directory": str(game_dir),
        "assets_root": str(assets_root),
        "assets_index_name": idx_id,
        "game_assets": str(game_assets),
        "natives_directory": str(natives_dir),
        "launcher_name": "PyMCL",
        "launcher_version": "1.0.0",
        "classpath_separator": ";",
        "library_directory": str(config.mc_root() / "libraries"),
    }


def _substitute(arg: str, tokens: dict) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda m: str(tokens.get(m.group(1), m.group(0))), arg)


def _eval_args(arglist: list, tokens: dict, features: dict) -> list:
    out = []
    for item in arglist:
        if isinstance(item, str):
            out.append(_substitute(item, tokens))
        elif isinstance(item, dict):
            if versions.rule_ok(item.get("rules"), features):
                v = item.get("value")
                if isinstance(v, list):
                    out.extend(_substitute(x, tokens) if isinstance(x, str) else str(x) for x in v)
                elif v is not None:
                    out.append(_substitute(str(v), tokens))
    return [a for a in out if a]


def classpath_of(merged: dict, vid: str) -> list:
    libdir = config.mc_root() / "libraries"
    cps = []
    for lib in merged.get("libraries", []):
        if not versions.lib_allowed(lib) or versions.native_classifier(lib):
            continue
        url, path, _, _ = versions.lib_artifact_info(lib)
        jar = libdir / path
        if jar.exists():
            cps.append(str(jar))
    base = merged.get("_base_id") or merged.get("id")
    client = config.mc_root() / "versions" / str(base) / f"{base}.jar"
    if client.exists():
        cps.append(str(client))
    return cps


def build_command(vid: str, auth, java_path: str, width=None, height=None) -> tuple:
    chain = versions.load_chain(vid)
    merged = versions.merge_chain(chain)
    game_dir = config.game_dir_for(vid)

    natives = versions.extract_natives(merged, vid)
    tokens = build_tokens(merged, vid, auth, game_dir, natives,
                          legacy="minecraftArguments" in merged and "arguments" not in merged)
    features = {"has_custom_resolution": bool(width and height)}
    tokens["classpath"] = ";".join(classpath_of(merged, vid))
    if width and height:
        tokens["resolution_width"] = str(width)
        tokens["resolution_height"] = str(height)

    # JVM 参数
    jvm = [java_path, "-Xms" + _fmt_mb(config.get("jvm_xms_mb", 512)),
           "-Xmx" + _fmt_mb(config.get("jvm_xmx_mb", 2048))]
    extra = (config.get("extra_jvm_args") or "").split()
    jvm.extend(extra)
    args = merged.get("arguments", {})
    if "jvm" in args:
        jvm.extend(_eval_args(args["jvm"], tokens, features))
    else:
        jvm.extend(["-Djava.library.path=" + str(natives),
                    "-Dminecraft.launcher.brand=PyMCL",
                    "-Dminecraft.launcher.version=1.0.0",
                    "-cp", tokens["classpath"]])
    # 保证 classpath 一定存在
    if "-cp" not in jvm and "--class-path" not in jvm:
        jvm.extend(["-cp", tokens["classpath"]])

    main_class = merged.get("mainClass", "net.minecraft.client.main.Main")

    # 游戏参数
    if "game" in args:
        game = _eval_args(args["game"], tokens, features)
    elif "minecraftArguments" in merged:
        game = _substitute(merged["minecraftArguments"], tokens).split()
    else:
        raise LaunchError("版本 JSON 中没有游戏参数")
    if width and height and "--width" not in game:
        game.extend(["--width", str(width), "--height", str(height)])

    argv = jvm + [main_class] + game
    return argv, game_dir


def launch(vid: str, auth, manager: DownloadManager, java_path: str,
           on_status=None, on_update=None, width=None, height=None):
    """完整启动：文件校验 -> 拼参数 -> 启动进程，返回 (proc, game_dir, argv)。"""
    if on_status:
        on_status("校验游戏文件…")
    game_dir = config.game_dir_for(vid)
    versions.ensure_version(vid, manager, on_status, on_update, game_dir=game_dir)
    if on_status:
        on_status("生成启动参数…")
    argv, game_dir = build_command(vid, auth, java_path, width, height)
    logs = game_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_file = logs / f"launch-{time.strftime('%Y%m%d-%H%M%S')}.log"
    if on_status:
        on_status(f"启动游戏…（日志: {log_file.name}）")
    proc = subprocess.Popen(argv, cwd=str(game_dir), stdout=open(log_file, "w", encoding="utf-8",
                                                                 errors="replace"),
                            stderr=subprocess.STDOUT,
                            creationflags=CREATE_NO_WINDOW)
    return proc, game_dir, argv
