"""整合包导出：把已安装版本的游戏目录打包为
Modrinth .mrpack（自动解析 Modrinth 下载地址）/ CurseForge .zip / 纯备份 .zip。"""
import hashlib
import json
import time
import zipfile
from pathlib import Path

from . import config, net, versions

INCLUDE_DIRS = ["mods", "config", "resourcepacks", "shaderpacks"]
INCLUDE_FILES = ["options.txt", "servers.dat"]


class ExportError(Exception):
    pass


def _hash_file(path: Path) -> tuple:
    h1, h512 = hashlib.sha1(), hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h1.update(chunk)
            h512.update(chunk)
    return h1.hexdigest(), h512.hexdigest()


def loader_dependencies(vid: str) -> dict:
    """从版本链推断加载器依赖，如 {"minecraft": "1.20.1", "fabric-loader": "0.16.14"}。"""
    try:
        chain = versions.load_chain(vid)
    except Exception:
        return {}
    merged = versions.merge_chain(chain)
    deps = {}
    for lib in merged.get("libraries", []):
        name = lib.get("name", "")
        if name.startswith("net.fabricmc:fabric-loader:"):
            deps["fabric-loader"] = name.split(":")[-1]
        elif name.startswith("org.quiltmc:quilt-loader:"):
            deps["quilt-loader"] = name.split(":")[-1]
        elif name.startswith("net.minecraftforge:forge:"):
            deps["forge"] = name.split(":")[-1]
        elif name.startswith("net.neoforged:neoforge:"):
            deps["neoforge"] = name.split(":")[-1]
        elif name.startswith("net.neoforged:forge:"):
            deps["forge"] = name.split(":")[-1]
    # 精确一点的 minecraft 版本：取继承根
    base = chain[-1].get("id") if chain else vid
    deps["minecraft"] = base
    return deps


def _modrinth_url_for_sha1(sha1: str) -> tuple | None:
    """通过哈希反查 Modrinth 文件下载地址。返回 (url, filename) 或 None。"""
    try:
        data = net.get_json(f"https://api.modrinth.com/v2/version_file/{sha1}"
                            f"?algorithm=sha1", mirror=False, timeout=15)
        for f in data.get("files", []):
            if (f.get("hashes") or {}).get("sha1") == sha1 and f.get("url"):
                return f["url"], f.get("filename", "")
    except Exception:
        return None
    return None


def _collect_files(game_dir: Path, includes: dict) -> list:
    """收集要打包的文件，返回 [(绝对路径, 相对路径)]。"""
    out = []
    for d in INCLUDE_DIRS:
        if not includes.get(d, True):
            continue
        root = game_dir / d
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                out.append((p, p.relative_to(game_dir)))
    for fname in INCLUDE_FILES:
        if includes.get(fname, True):
            p = game_dir / fname
            if p.exists():
                out.append((p, Path(fname)))
    return out


def export_modpack(vid: str, out_path: Path, fmt: str, name: str, author: str,
                   version: str, summary: str, includes: dict | None = None,
                   on_status=None, on_progress=None) -> dict:
    """导出整合包。fmt: 'mrpack' | 'curseforge' | 'backup'。返回统计。"""
    includes = includes or {k: True for k in INCLUDE_DIRS + INCLUDE_FILES}
    game_dir = config.game_dir_for(vid)
    if on_status:
        on_status("收集文件…")
    files = _collect_files(game_dir, includes)
    if not files:
        raise ExportError("所选版本的游戏目录里没有可打包的文件（mods/config 等为空）")
    deps = loader_dependencies(vid)
    stats = {"total": len(files), "resolved": 0, "overrides": 0, "out": str(out_path)}

    if fmt == "mrpack":
        index_files = []
        overrides = []
        for i, (abs_p, rel) in enumerate(files):
            if on_status:
                on_status(f"解析文件 {i + 1}/{len(files)}: {rel.name}")
            if on_progress:
                on_progress((i + 1) / len(files))
            sha1, sha512 = _hash_file(abs_p)
            hit = _modrinth_url_for_sha1(sha1)
            if hit:
                url, _fname = hit
                index_files.append({
                    "path": rel.as_posix(),
                    "hashes": {"sha1": sha1, "sha512": sha512},
                    "env": {"client": "required", "server": "required"},
                    "downloads": [url],
                    "fileSize": abs_p.stat().st_size,
                })
                stats["resolved"] += 1
            else:
                overrides.append((abs_p, rel))
                stats["overrides"] += 1
            time.sleep(0.05)  # 温和限速
        index = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": version or f"{name}-export",
            "name": name,
            "summary": summary,
            "files": index_files,
            "dependencies": deps,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("modrinth.index.json", json.dumps(index, ensure_ascii=False, indent=2))
            for abs_p, rel in overrides:
                z.write(abs_p, (Path("overrides") / rel).as_posix())

    elif fmt == "curseforge":
        # 无 CurseForge API 时无法把任意 jar 解析为 projectID/fileID，
        # 因此全部文件放入 overrides（该格式仍可被主流启动器导入）。
        loader_id = ""
        mc = deps.get("minecraft", "")
        if "fabric-loader" in deps:
            loader_id = "fabric-" + deps["fabric-loader"]
        elif "quilt-loader" in deps:
            loader_id = "quilt-" + deps["quilt-loader"]
        elif "forge" in deps:
            loader_id = "forge-" + deps["forge"]
        elif "neoforge" in deps:
            loader_id = "neoforge-" + deps["neoforge"]
        manifest = {
            "minecraft": {"version": mc,
                          "modLoaders": ([{"id": loader_id, "primary": True}]
                                         if loader_id else [])},
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": name,
            "version": version or "1.0.0",
            "author": author or "PyMCL",
            "files": [],
            "overrides": "overrides",
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr("modlist.html",
                       f"<html><body><h1>{name}</h1><p>{summary}</p>"
                       f"<p>文件清单见 overrides 目录（由 PyMCL 导出）。</p></body></html>")
            for i, (abs_p, rel) in enumerate(files):
                z.write(abs_p, (Path("overrides") / rel).as_posix())
                if on_status:
                    on_status(f"写入 overrides {i + 1}/{len(files)}")
                if on_progress:
                    on_progress((i + 1) / len(files))
            stats["overrides"] = len(files)

    elif fmt == "backup":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"name": name, "author": author, "version": version,
                "summary": summary, "source_version": vid, "exported_at": time.time(),
                "dependencies": deps, "app": "PyMCL"}
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("pymcl-backup.json", json.dumps(meta, ensure_ascii=False, indent=2))
            for i, (abs_p, rel) in enumerate(files):
                z.write(abs_p, rel.as_posix())
                if on_status:
                    on_status(f"备份 {i + 1}/{len(files)}")
                if on_progress:
                    on_progress((i + 1) / len(files))
    else:
        raise ExportError(f"未知导出格式: {fmt}")

    stats["size"] = out_path.stat().st_size
    return stats
