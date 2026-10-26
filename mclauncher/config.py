"""配置与账号持久化（便携式：保存在启动器目录）。"""
import json
import sys
import threading
from pathlib import Path

_lock = threading.RLock()
_cache = None


def launcher_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


LAUNCHER_DIR = launcher_dir()
CONFIG_FILE = LAUNCHER_DIR / "launcher.json"
ACCOUNTS_FILE = LAUNCHER_DIR / "accounts.json"
CACHE_DIR = LAUNCHER_DIR / "cache"

DEFAULTS = {
    "mc_root": str(LAUNCHER_DIR / ".minecraft"),
    "java_path": "",
    "jvm_xms_mb": 512,
    "jvm_xmx_mb": 2048,
    "download_threads": 16,
    "use_mirror": True,
    "msa_client_id": "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb",
    "extra_jvm_args": "",
    "game_dirs": {},          # version_id -> 该版本独立游戏目录（整合包用）
    "active_account": 0,
    "window_width": 1020,
    "window_height": 660,
    "isolate_all": False,
    # 正式打包版默认隐藏备用授权设置，开发运行默认显示；账户页可手动切换
    "show_backup_auth": not getattr(sys, "frozen", False),
}


def load() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            data = dict(DEFAULTS)
            try:
                if CONFIG_FILE.exists():
                    data.update(json.loads(CONFIG_FILE.read_text("utf-8")))
            except Exception:
                pass
            _cache = data
        return _cache


def get(key, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def set(key, value):
    with _lock:
        load()[key] = value
        try:
            CONFIG_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass


def set_many(updates: dict):
    with _lock:
        load().update(updates)
        try:
            CONFIG_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass


def mc_root() -> Path:
    root = Path(get("mc_root"))
    for sub in ("versions", "libraries", "assets", "modpacks", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def game_dir_for(version_id: str) -> Path:
    """版本对应的游戏目录：启用了版本隔离的版本（或全局默认隔离）使用
    versions/<id> 独立目录（整合包为其注册的目录），否则共用 mc 根目录。"""
    rel = get("game_dirs", {}).get(version_id)
    if rel:
        p = Path(rel)
        if not p.is_absolute():
            p = mc_root() / p
        p.mkdir(parents=True, exist_ok=True)
        return p
    if get("isolate_all", False) and version_id:
        d = mc_root() / "versions" / version_id
        d.mkdir(parents=True, exist_ok=True)
        return d
    return mc_root()


def is_isolated(version_id: str) -> bool:
    if version_id in get("game_dirs", {}):
        return True
    return bool(get("isolate_all", False)) and bool(version_id)


def set_isolated(version_id: str, isolated: bool):
    """设置/取消某版本的独立目录；isolated=True 时把根目录里的
    saves/config/mods 等迁移过去（不删除原目录本身）。"""
    dirs = dict(get("game_dirs", {}))
    root = mc_root()
    target = root / "versions" / version_id
    if isolated:
        if dirs.get(version_id):
            return
        dirs[version_id] = str(target)
        target.mkdir(parents=True, exist_ok=True)
        import shutil
        for name in ("saves", "config", "mods", "resourcepacks", "shaderpacks",
                     "options.txt", "servers.dat", "servers.dat_old", "usercache.json"):
            src = root / name
            dst = target / name
            try:
                if src.exists() and not dst.exists():
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
            except Exception:
                pass
    else:
        dirs.pop(version_id, None)
    set("game_dirs", dirs)


# ---------------- 账号 ----------------

def load_accounts() -> list:
    try:
        if ACCOUNTS_FILE.exists():
            data = json.loads(ACCOUNTS_FILE.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_accounts(accounts: list):
    try:
        ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def active_account() -> dict | None:
    accounts = load_accounts()
    idx = int(get("active_account", 0))
    if 0 <= idx < len(accounts):
        return accounts[idx]
    return accounts[0] if accounts else None
