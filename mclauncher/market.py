"""资源市场：Modrinth 搜索与安装（模组/光影/材质包/整合包）、
CurseForge 整合包 zip 导入、世界导入、项目图标缓存。"""
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from . import config, net, versions, installers
from .downloads import DownloadManager, Job, Task

MODRINTH = "https://api.modrinth.com/v2"

PROJECT_TYPES = {
    "mod": "mod",
    "shader": "shader",
    "resourcepack": "resourcepack",
    "modpack": "modpack",
    "datapack": "datapack",
}


def list_worlds(game_dir: Path) -> list:
    """列出存档世界 [(名称, 目录)]，按最近修改排序。"""
    saves = game_dir / "saves"
    out = []
    try:
        if saves.exists():
            worlds = [d for d in saves.iterdir()
                      if d.is_dir() and (d / "level.dat").exists()]
            worlds.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            out = [(d.name, d) for d in worlds]
    except Exception:
        pass
    return out


def icon_file(url: str | None, size: int = 52) -> Path | None:
    """下载项目图标并转为 size 大小的 PNG 缓存；失败返回 None。"""
    if not url:
        return None
    try:
        cache = config.CACHE_DIR / "icons"
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        dest = cache / f"{key}.png"
        if dest.exists():
            return dest
        raw = cache / f"{key}.raw"
        net.download_stream(url, raw)
        from PIL import Image
        img = Image.open(raw).convert("RGBA")
        img.thumbnail((size, size))
        img.save(dest)
        raw.unlink(missing_ok=True)
        return dest
    except Exception:
        return None


# ---------------- Modrinth 搜索 ----------------

# 各类型的 Modrinth 分类标签（中文 -> slug），用于市场筛选
TAGS = {
    "mod": [("全部", None), ("优化", "optimization"), ("技术", "technology"),
            ("魔法", "magic"), ("冒险", "adventure"), ("装饰", "decoration"),
            ("装备", "equipment"), ("食物", "food"), ("实用", "utility"),
            ("存储", "storage"), ("世界生成", "worldgen"), ("生物", "mobs"),
            ("工具库", "library"), ("经济", "economy"), ("社交", "social"),
            ("小游戏", "minigame")],
    "shader": [("全部", None), ("写实", "realistic"), ("半写实", "semi-realistic"),
               ("卡通", "cartoon"), ("二次元", "anime"), ("原版风格", "vanilla"),
               ("梦幻", "fancy"), ("大气", "atmospheric"), ("程序化", "procedural")],
    "resourcepack": [("全部", None), ("16x", "16x"), ("32x", "32x"), ("64x", "64x"),
                     ("128x", "128x"), ("256x+", "256x+"), ("原版增强", "vanilla-like"),
                     ("简约", "simplistic"), ("动画", "animated"), ("实用", "utility"),
                     ("音效", "audio"), ("字体", "fonts"), ("GUI", "gui")],
    "modpack": [("全部", None), ("生存", "survival"), ("科技", "technology"),
                ("魔法", "magic"), ("冒险", "adventure"), ("空岛", "skyblock"),
                ("探索", "exploration"), ("多人", "multiplayer"), ("轻量", "light"),
                ("硬核", "hardcore"), ("任务", "quest"), ("科幻", "sci-fi")],
}

TAGS["datapack"] = TAGS["mod"]

SORTS = [("默认", None), ("最多下载", "downloads"), ("最近更新", "updated"),
         ("最新发布", "newest"), ("最多关注", "follows")]


def search(query: str, ptype: str, game_version: str | None = None,
           loader: str | None = None, category: str | None = None,
           sort: str | None = None, offset: int = 0, limit: int = 20) -> list:
    if ptype == "datapack":
        # Modrinth 上数据包是带 datapack 加载器标签的 mod 项目
        facets = [["project_type:mod"], ["loaders:datapack"]]
    else:
        facets = [["project_type:" + PROJECT_TYPES[ptype]]]
    if game_version:
        facets.append(["versions:" + game_version])
    if loader and ptype in ("mod", "modpack"):
        facets.append(["loaders:" + loader])
    if category:
        facets.append(["categories:" + category])
    index = sort or ("relevance" if query else "downloads")
    params = {"query": query, "limit": limit, "offset": offset, "index": index,
              "facets": json.dumps(facets)}
    data = net.get_json(f"{MODRINTH}/search", params=params, mirror=False)
    return data.get("hits", [])


def project_versions(project_id: str, game_version: str | None = None,
                     loader: str | None = None) -> list:
    params = {}
    loaders = []
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    if loader:
        params["loaders"] = json.dumps([loader])
    data = net.get_json(f"{MODRINTH}/project/{project_id}/version", params=params, mirror=False)
    return data


def pick_version_file(pv: dict) -> dict | None:
    for f in pv.get("files", []):
        if f.get("primary"):
            return f
    files = pv.get("files", [])
    return files[0] if files else None


def install_asset(project: dict, pv: dict, target_dir: Path) -> Path:
    """安装模组/光影/材质包文件到目标目录。"""
    f = pick_version_file(pv)
    if not f:
        raise RuntimeError("该版本没有可下载文件")
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / f["filename"]
    net.download_stream(f["url"], dest, sha1=(f.get("hashes") or {}).get("sha1"))
    return dest


# ---------------- Modrinth 整合包 (.mrpack) ----------------

def install_mrpack(mrpack_path: Path, manager: DownloadManager, java: str,
                   on_status=None, on_update=None) -> tuple:
    """安装 .mrpack 整合包，返回 (version_id, game_dir)。"""
    name_base = mrpack_path.stem
    slug = re.sub(r"[^\w\-]+", "_", name_base)[:40] or "modpack"
    tmp = Path(tempfile.mkdtemp(prefix="mrpack_"))
    with zipfile.ZipFile(mrpack_path) as z:
        z.extractall(tmp)
    idx_path = tmp / "modrinth.index.json"
    if not idx_path.exists():
        raise RuntimeError("无效的 mrpack 整合包：缺少 modrinth.index.json")
    idx = json.loads(idx_path.read_text("utf-8"))
    deps = idx.get("dependencies", {})
    mc = deps.get("minecraft")
    if not mc:
        raise RuntimeError("整合包未声明 Minecraft 版本")
    game_dir = config.mc_root() / "modpacks" / slug
    game_dir.mkdir(parents=True, exist_ok=True)

    if on_status:
        on_status(f"准备安装 {name_base}（MC {mc}）…")
    if versions.load_json(mc) is None:
        versions.fetch_version_json(mc)

    vid = None
    fl = deps.get("fabric-loader")
    ql = deps.get("quilt-loader")
    lf = deps.get("legacyfabric-loader")
    nf = deps.get("neoforge")
    fg = deps.get("forge")
    if fl:
        vid = installers.install_fabric_like("fabric", mc, fl, version_id=f"{slug}-{mc}-fabric")
    elif ql:
        vid = installers.install_fabric_like("quilt", mc, ql, version_id=f"{slug}-{mc}-quilt")
    elif lf:
        vid = installers.install_fabric_like("legacyfabric", mc, lf, version_id=f"{slug}-{mc}-lf")
    elif nf:
        vid = installers.install_neoforge(mc, nf, java, on_status)
    elif fg:
        vid = installers.install_forge(mc, fg, java, on_status)
    else:
        vid = f"{slug}-{mc}"
        versions.merge_chain([versions.load_json(mc)])
        import shutil as _s
        src = config.mc_root() / "versions" / mc
        dst = config.mc_root() / "versions" / vid
        if not dst.exists():
            _s.copytree(src, dst)
            vj = versions.load_json(vid)
            if vj:
                vj["id"] = vid
                (dst / f"{vid}.json").write_text(json.dumps(vj), "utf-8")

    # 下载整合包声明的文件
    tasks = []
    for f in idx.get("files", []):
        env = (f.get("env") or {}).get("client", "required")
        if env == "unsupported":
            continue
        path = f.get("path", "")
        if not path or ".." in path:
            continue
        urls = f.get("downloads") or []
        if not urls:
            continue
        dest = game_dir / path
        tasks.append(Task(urls[0], dest, sha1=(f.get("hashes") or {}).get("sha1"), label=path))
    if tasks and on_status:
        on_status(f"下载整合包文件（{len(tasks)} 项）…")
    if tasks:
        job = Job(tasks, on_update=on_update)
        manager.run_blocking(job)
        if not job.ok and not job.cancelled.is_set():
            raise RuntimeError(job.error)

    # overrides 目录
    ov = tmp / "overrides"
    if ov.exists():
        if on_status:
            on_status("应用整合包配置…")
        for item in ov.iterdir():
            dst = game_dir / item.name
            try:
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
                shutil.move(str(item), str(dst))
            except Exception:
                pass

    config.set("game_dirs", {**config.get("game_dirs", {}), vid: str(game_dir)})
    shutil.rmtree(tmp, ignore_errors=True)
    if on_status:
        on_status(f"整合包安装完成：{name_base}（版本 {vid}）")
    return vid, game_dir


# ---------------- CurseForge 整合包 zip 导入 ----------------

def _cf_filename(project_id: int, file_id: int) -> str | None:
    """通过 cfwidget 公共 API 查询 CurseForge 文件名。"""
    try:
        data = net.get_json(f"https://api.cfwidget.com/{project_id}", mirror=False, timeout=25)
        for f in data.get("files", []):
            if int(f.get("id", -1)) == file_id:
                return f.get("name")
        # 版本过新时从 downloads 里找
        for d in data.get("downloads", []):
            if int(d.get("id", -1)) == file_id:
                return d.get("name")
    except Exception:
        return None
    return None


def import_curseforge_zip(zip_path: Path, manager: DownloadManager, java: str,
                          on_status=None, on_update=None) -> tuple:
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "manifest.json" not in names:
            raise RuntimeError("无效的 CurseForge 整合包：缺少 manifest.json")
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    mc = manifest.get("minecraft", {}).get("version")
    if not mc:
        raise RuntimeError("整合包未声明 Minecraft 版本")
    name_base = re.sub(r"[^\w\-]+", "_", manifest.get("name") or zip_path.stem)[:40]
    slug = name_base or "cf_modpack"
    game_dir = config.mc_root() / "modpacks" / slug
    game_dir.mkdir(parents=True, exist_ok=True)

    if versions.load_json(mc) is None:
        versions.fetch_version_json(mc)
    loader_id = ""
    for ml in manifest.get("minecraft", {}).get("modLoaders", []):
        if ml.get("primary"):
            loader_id = ml.get("id", "")
            break
    vid = None
    if loader_id.startswith("fabric-"):
        vid = installers.install_fabric_like("fabric", mc, loader_id[7:],
                                             version_id=f"{slug}-{mc}-fabric")
    elif loader_id.startswith("quilt-"):
        vid = installers.install_fabric_like("quilt", mc, loader_id[6:],
                                             version_id=f"{slug}-{mc}-quilt")
    elif loader_id.startswith("forge-"):
        vid = installers.install_forge(mc, loader_id[6:], java, on_status)
    elif loader_id.startswith("neoforge-"):
        vid = installers.install_neoforge(mc, loader_id[9:], java, on_status)
    else:
        vid = f"{slug}-{mc}"
        dst = config.mc_root() / "versions" / vid
        src = config.mc_root() / "versions" / mc
        if not dst.exists() and src.exists():
            shutil.copytree(src, dst)
            vj = versions.load_json(vid)
            if vj:
                vj["id"] = vid
                (dst / f"{vid}.json").write_text(json.dumps(vj), "utf-8")

    # 解析并下载 mod 文件
    tasks, misses = [], []
    for f in manifest.get("files", []):
        pid, fid = f.get("projectID"), f.get("fileID")
        if not pid or not fid or not f.get("required", True):
            continue
        fname = _cf_filename(pid, fid)
        if not fname:
            misses.append(f"{pid}/{fid}")
            continue
        url = f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{fname}"
        tasks.append(Task(url, game_dir / "mods" / fname, label=fname))
    if misses and on_status:
        on_status(f"警告：{len(misses)} 个文件无法解析文件名，已跳过")
    if tasks and on_status:
        on_status(f"下载 CurseForge 文件（{len(tasks)} 项）…")
    if tasks:
        job = Job(tasks, on_update=on_update)
        manager.run_blocking(job)

    # overrides
    with zipfile.ZipFile(zip_path) as z:
        ov_names = [n for n in z.namelist() if n.startswith("overrides/")]
        if ov_names and on_status:
            on_status("应用整合包配置…")
        for n in ov_names:
            rel = n[len("overrides/"):]
            if not rel:
                continue
            dest = game_dir / rel
            if n.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)

    config.set("game_dirs", {**config.get("game_dirs", {}), vid: str(game_dir)})
    if on_status:
        on_status(f"整合包导入完成：{slug}（版本 {vid}）")
    return vid, game_dir


# ---------------- 世界导入 ----------------

def import_world(source: str | Path, saves_dir: Path) -> Path:
    """从 zip/mcworld 文件或 URL 导入世界到 saves/<名称>。返回世界目录。"""
    saves_dir.mkdir(parents=True, exist_ok=True)
    src = Path(source)
    if re.match(r"^https?://", str(source)):
        import urllib.parse
        fname = Path(urllib.parse.urlparse(str(source)).path).name or "world.zip"
        tmp = Path(tempfile.mkdtemp(prefix="world_")) / fname
        net.download_stream(str(source), tmp)
        src = tmp
    if not src.exists():
        raise RuntimeError(f"文件不存在: {src}")
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            entries = [n for n in z.namelist() if not n.endswith("/")]
            level = next((n for n in entries if Path(n).name == "level.dat"), None)
            if not level:
                raise RuntimeError("压缩包中没有找到 level.dat，不是有效的世界文件")
            root = str(Path(level).parent)
            base = src.stem or "World"
            dest = saves_dir / base
            i = 1
            while dest.exists():
                dest = saves_dir / f"{base} ({i})"
                i += 1
            dest.mkdir(parents=True)
            for n in entries:
                rel = n[len(root):].lstrip("/\\") if root else n
                if not rel:
                    continue
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as fsrc, open(out, "wb") as fout:
                    shutil.copyfileobj(fsrc, fout)
            return dest
    raise RuntimeError("仅支持 .zip / .mcworld 世界文件")
