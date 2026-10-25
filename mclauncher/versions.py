"""版本管理：清单、版本 JSON、继承链合并、库/资源收集、启动前完整性校验。"""
import json
import re
import struct
import time
import zipfile
from pathlib import Path

from . import config, net
from .downloads import DownloadManager, Job, Task

ARCH_BITS = struct.calcsize("P") * 8  # 64 / 32


# ---------------- 官方版本清单 ----------------

def manifest(force: bool = False) -> dict:
    cache = config.CACHE_DIR / "version_manifest.json"
    data = None
    try:
        if cache.exists():
            blob = json.loads(cache.read_text("utf-8"))
            if time.time() - blob.get("_fetched", 0) < 600:
                data = blob["data"]
    except Exception:
        data = None
    if data is None or force:
        try:
            data = net.get_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
            config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"_fetched": time.time(), "data": data}), "utf-8")
        except net.NetError:
            if data is None and cache.exists():
                data = json.loads(cache.read_text("utf-8"))["data"]  # 离线用旧缓存
            elif data is None:
                raise
    return data


def manifest_entry(vid: str) -> dict | None:
    for e in manifest().get("versions", []):
        if e.get("id") == vid:
            return e
    return None


def fetch_version_json(vid: str, status=None) -> dict:
    """下载版本 JSON 到 versions/<vid>/<vid>.json 并返回。"""
    entry = manifest_entry(vid)
    if not entry:
        raise net.NetError(f"未在官方清单中找到版本 {vid}")
    vj = net.get_json(entry["url"])
    vj.setdefault("id", vid)
    path = version_json_path(vid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(vj, ensure_ascii=False, indent=2), "utf-8")
    return vj


# ---------------- 已安装版本 ----------------

def version_dir(vid: str) -> Path:
    return config.mc_root() / "versions" / vid


def version_json_path(vid: str) -> Path:
    return version_dir(vid) / f"{vid}.json"


def load_json(vid: str) -> dict | None:
    p = version_json_path(vid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def installed_versions() -> list:
    out = []
    vdir = config.mc_root() / "versions"
    if vdir.exists():
        for d in vdir.iterdir():
            if not d.is_dir():
                continue
            j = d / f"{d.name}.json"
            if not j.exists():
                continue
            try:
                vj = json.loads(j.read_text("utf-8"))
            except Exception:
                continue
            out.append({
                "id": d.name,
                "type": vj.get("type", "?"),
                "inheritsFrom": vj.get("inheritsFrom"),
                "custom_dir": d.name in config.get("game_dirs", {}),
            })
    out.sort(key=lambda x: x["id"].lower())
    return out


def load_chain(vid: str) -> list:
    """返回 [自身, ..., 继承根] 的版本 JSON 链。"""
    chain, seen = [], set()
    cur = vid
    while cur and cur not in seen:
        seen.add(cur)
        vj = load_json(cur)
        if vj is None:
            raise FileNotFoundError(f"缺少版本文件: {version_json_path(cur)}")
        chain.append(vj)
        cur = vj.get("inheritsFrom")
    if not chain:
        raise FileNotFoundError(f"版本不存在: {vid}")
    return chain


def merge_chain(chain: list) -> dict:
    """从根(原版)到子版本逐层覆盖合并；库列表合并去重。"""
    merged: dict = {}
    for vj in reversed(chain):  # 根在前，子在后 -> 子覆盖父
        for k, v in vj.items():
            if k in ("libraries", "inheritsFrom"):
                continue
            if v is not None and v != "":
                merged[k] = v
    libs = []
    names = set()
    for vj in reversed(chain):
        for lib in vj.get("libraries", []):
            key = lib.get("name", "")
            if key in names:
                continue
            names.add(key)
            libs.append(lib)
    merged["libraries"] = libs
    merged["_base_id"] = chain[-1].get("id", chain[-1].get("_base_id", ""))
    return merged


# ---------------- 规则判定 ----------------

def os_ok(osd: dict) -> bool:
    if not osd:
        return True
    name = osd.get("name")
    if name and name != "windows":
        return False
    arch = osd.get("arch")
    if arch:
        # Mojang 用 "x86" 规则表示仅 32 位可用（如 twitch 库）
        return arch == "x86" if ARCH_BITS == 32 else arch != "x86"
    return True


def rule_ok(rules, features: dict | None = None) -> bool:
    if not rules:
        return True
    allowed = False
    for r in rules:
        osd = r.get("os") or {}
        if osd and not os_ok(osd):
            continue
        feats = r.get("features")
        if feats:
            ok = True
            for k, v in feats.items():
                if bool((features or {}).get(k)) != bool(v):
                    ok = False
                    break
            if not ok:
                continue
        allowed = (r.get("action") == "allow")
    return allowed


# ---------------- 库与资源 ----------------

def maven_path(name: str) -> str:
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    fname = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "") + ".jar"
    return "/".join([group.replace(".", "/"), artifact, version, fname])


def lib_allowed(lib: dict, features: dict | None = None) -> bool:
    return rule_ok(lib.get("rules"), features)


def lib_artifact_info(lib: dict) -> tuple[str | None, str, str | None, int | None]:
    """返回 (url 或 None, maven 相对路径, sha1, size)。"""
    dl = lib.get("downloads", {}).get("artifact", {})
    path = dl.get("path") or maven_path(lib["name"])
    url = dl.get("url")
    sha1, size = dl.get("sha1"), dl.get("size")
    if not url and lib.get("url"):
        base = lib["url"].rstrip("/")
        url = f"{base}/{path}"
    return url, path, sha1, size


def native_classifier(lib: dict) -> str | None:
    n = lib.get("natives")
    if not n:
        return None
    cls = n.get("windows")
    if not cls:
        return None
    return cls.replace("${arch}", "64" if ARCH_BITS == 64 else "32")


def native_jar_path(lib: dict, cls: str) -> str:
    dl = lib.get("downloads", {}).get("classifiers", {}).get(cls, {})
    return dl.get("path") or maven_path(f"{lib['name']}:{cls}")


def lib_tasks(merged: dict, features: dict | None = None) -> list:
    """所有需要下载的库文件（含 natives jar）。"""
    tasks = []
    libdir = config.mc_root() / "libraries"
    for lib in merged.get("libraries", []):
        if not lib_allowed(lib, features):
            continue
        url, path, sha1, size = lib_artifact_info(lib)
        if url:
            tasks.append(Task(url, libdir / path, sha1=sha1, size=size, label=path))
        cls = native_classifier(lib)
        if cls:
            dl = lib.get("downloads", {}).get("classifiers", {}).get(cls, {})
            if dl.get("url"):
                tasks.append(Task(dl["url"], libdir / dl.get("path", maven_path(f"{lib['name']}:{cls}")),
                                  sha1=dl.get("sha1"), size=dl.get("size"), label=dl.get("path", cls)))
    return tasks


def client_jar_task(merged: dict) -> Task | None:
    dl = merged.get("downloads", {}).get("client")
    if not dl:
        return None
    base = merged.get("_base_id") or merged.get("id")
    path = f"versions/{base}/{base}.jar"
    return Task(dl["url"], config.mc_root() / path, sha1=dl.get("sha1"), size=dl.get("size"),
                label=f"{base}.jar")


def asset_index(merged: dict) -> dict:
    """确保 assets/indexes/<id>.json 存在并返回其内容。"""
    ai = merged.get("assetIndex")
    if not ai:
        raise FileNotFoundError("版本 JSON 缺少 assetIndex")
    p = config.mc_root() / "assets" / "indexes" / f"{ai['id']}.json"
    if not p.exists():
        net.download_stream(ai["url"], p, sha1=ai.get("sha1"), size=ai.get("size"))
    return json.loads(p.read_text("utf-8"))


def asset_tasks(index: dict) -> list:
    tasks = []
    root = config.mc_root() / "assets" / "objects"
    for name, obj in index.get("objects", {}).items():
        h = obj["hash"]
        tasks.append(Task(
            f"https://resources.download.minecraft.net/{h[:2]}/{h}",
            root / h[:2] / h, sha1=h, size=obj.get("size"), label=name))
    return tasks


def prepare_virtual_assets(merged: dict, index: dict, game_dir: Path | None = None):
    """老版本(1.6~1.7)虚拟资源目录 / map_to_resources。"""
    if index.get("virtual"):
        vdir = config.mc_root() / "assets" / "virtual" / index.get("id", merged.get("assets", "legacy"))
    elif index.get("map_to_resources") and game_dir is not None:
        vdir = Path(game_dir) / "resources"
    else:
        return
    objects = config.mc_root() / "assets" / "objects"
    for name, obj in index.get("objects", {}).items():
        h = obj["hash"]
        src = objects / h[:2] / h
        if not src.exists():
            continue
        dst = vdir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            try:
                dst.hardlink_to(src)
            except Exception:
                import shutil
                shutil.copy2(src, dst)


def extract_natives(merged: dict, vid: str) -> Path:
    """解压 natives 到 versions/<vid>/natives，返回目录。"""
    out = version_dir(vid) / "natives"
    out.mkdir(parents=True, exist_ok=True)
    libdir = config.mc_root() / "libraries"
    for lib in merged.get("libraries", []):
        cls = native_classifier(lib)
        if not cls or not lib_allowed(lib):
            continue
        jar = libdir / native_jar_path(lib, cls)
        if not jar.exists():
            continue
        try:
            with zipfile.ZipFile(jar) as z:
                for n in z.namelist():
                    if n.startswith("META-INF/") or n.endswith("/"):
                        continue
                    try:
                        z.extract(n, out)
                    except Exception:
                        pass
        except zipfile.BadZipFile:
            continue
    return out


# ---------------- 完整性校验 / 补全下载 ----------------

def ensure_version(vid: str, manager: DownloadManager, on_status=None,
                   on_update=None, skip_assets: bool = False, game_dir: Path | None = None) -> str:
    """确保该版本所有文件就绪（版本 jar/库/资源），返回汇总描述。"""
    chain = load_chain(vid)
    merged = merge_chain(chain)

    if on_status:
        on_status(f"正在检查 {vid} 的文件…")
    missing_hint = []
    tasks = []
    t = client_jar_task(merged)
    if t:
        tasks.append(t)
    tasks.extend(lib_tasks(merged))

    total_lib = len(tasks)
    if on_status:
        on_status(f"下载运行库与客户端文件（{total_lib} 项）…")
    job = Job(tasks, on_update=on_update)
    manager.run_blocking(job)
    if not job.ok:
        raise RuntimeError(job.error or "文件下载失败")

    if not skip_assets:
        if on_status:
            on_status("正在处理资源索引…")
        idx = asset_index(merged)
        atasks = asset_tasks(idx)
        if on_status:
            on_status(f"下载游戏资源（{len(atasks)} 项，已存在的会跳过）…")
        ajob = Job(atasks, on_update=on_update)
        manager.run_blocking(ajob)
        if not ajob.ok:
            raise RuntimeError(ajob.error or "资源下载失败")
        prepare_virtual_assets(merged, idx, game_dir)

    # 校验关键文件存在
    t = client_jar_task(merged)
    if t and not t.dest.exists():
        missing_hint.append(str(t.dest))
    if missing_hint:
        raise FileNotFoundError("缺少关键文件: " + "; ".join(missing_hint))
    return f"{vid} 文件校验完成（{total_lib} 个库文件）"
