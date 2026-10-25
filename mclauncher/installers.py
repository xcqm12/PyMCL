"""加载器与游戏版本安装：原版 / Forge / NeoForge / Fabric / Quilt / LegacyFabric /
OptiFine / LiteLoader / Cleanroom / LabyMod。"""
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

from . import config, net, versions
from .downloads import DownloadManager, Job, Task

BMCLAPI = "https://bmclapi2.bangbang93.com"
CREATE_NO_WINDOW = 0x08000000


class InstallError(Exception):
    pass


# ---------------- 通用工具 ----------------

def save_version_json(vj: dict, vid: str) -> Path:
    p = versions.version_json_path(vid)
    p.parent.mkdir(parents=True, exist_ok=True)
    vj["id"] = vid
    p.write_text(json.dumps(vj, ensure_ascii=False, indent=2), "utf-8")
    return p


def run_installer(installer_url: str, name: str, java: str,
                  on_status=None, timeout: int = 1800) -> str:
    """下载安装器并 headless 安装（Forge/NeoForge/Cleanroom 家族），返回新版本 id。"""
    root = config.mc_root()
    idir = root / "cache" / "installers"
    idir.mkdir(parents=True, exist_ok=True)
    jar = idir / name
    if on_status:
        on_status(f"下载安装器 {name} …")
    net.download_stream(installer_url, jar)
    if on_status:
        on_status("运行安装器（可能需要几分钟）…")
    before = {d.name for d in (root / "versions").iterdir() if d.is_dir()}
    cmd = [java, "-jar", str(jar), "--installClient", str(root)]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW)
    out = ((proc.stdout or b"") + (proc.stderr or b"")).decode("utf-8", "replace")
    (idir / (name + ".log")).write_text(out, "utf-8", errors="replace")
    after = {d.name for d in (root / "versions").iterdir() if d.is_dir()}
    new = sorted(after - before)
    if new:
        if on_status:
            on_status(f"安装完成：{new[0]}")
        return new[0]
    raise InstallError(f"安装器未产生新版本 (exit={proc.returncode})。\n{out[-800:]}")


# ---------------- 原版 ----------------

def install_vanilla(vid: str, manager: DownloadManager, on_status=None, on_update=None) -> str:
    versions.fetch_version_json(vid)
    versions.ensure_version(vid, manager, on_status, on_update)
    return vid


# ---------------- Fabric / Quilt / LegacyFabric ----------------

FABRIC_METAS = {
    "fabric": "https://meta.fabricmc.net/v2",
    "quilt": "https://meta.quiltmc.org/v3",
    "legacyfabric": "https://meta.legacyfabric.net/v2",
}


def list_fabric_like(kind: str, mc: str) -> list:
    base = FABRIC_METAS[kind]
    data = net.get_json(f"{base}/versions/loader/{mc}")
    out = []
    for e in data:
        v = (e.get("loader") or {}).get("version")
        if v:
            out.append(v)
    return out


def install_fabric_like(kind: str, mc: str, loader: str, version_id: str | None = None,
                        manager: DownloadManager | None = None,
                        on_status=None, on_update=None) -> str:
    base = FABRIC_METAS[kind]
    if versions.load_json(mc) is None:
        versions.fetch_version_json(mc)
    vj = net.get_json(f"{base}/versions/loader/{mc}/{loader}/profile/json")
    vid = version_id or f"{mc}-{kind}-{loader}"
    vj.setdefault("inheritsFrom", mc)
    save_version_json(vj, vid)
    if manager:
        try:
            versions.ensure_version(vid, manager, on_status, on_update, skip_assets=True)
        except Exception as e:
            if on_status:
                on_status(f"预下载失败（启动时会重试）: {e}")
    return vid


# ---------------- Forge ----------------

def list_forge(mc: str) -> list:
    data = net.get_json(f"{BMCLAPI}/forge/minecraft/{mc}")
    entries = []
    for e in data:
        v = e.get("version")
        if v:
            entries.append({"version": v, "build": e.get("build", 0)})
    entries.sort(key=lambda x: x["build"], reverse=True)
    return [e["version"] for e in entries]


def install_forge(mc: str, ver: str, java: str, on_status=None) -> str:
    full = f"{mc}-{ver}"
    installer = (f"{BMCLAPI}/maven/net/minecraftforge/forge/{full}/"
                 f"forge-{full}-installer.jar")
    return run_installer(installer, f"forge-{full}-installer.jar", java, on_status)


# ---------------- NeoForge ----------------

def list_neoforge(mc: str) -> list:
    data = net.get_json(f"{BMCLAPI}/neoforge/list/{mc}")
    out = []
    for e in data:
        v = e.get("version")
        if v:
            out.append(v)
    return out


def install_neoforge(mc: str, ver: str, java: str, on_status=None) -> str:
    if ver.startswith(mc + "-"):  # 1.20.1 时代 artifact 是 net/neoforged:forge
        full = ver
        artifact = "forge"
    else:
        full = ver
        artifact = "neoforge"
    installer = (f"{BMCLAPI}/maven/net/neoforged/{artifact}/{full}/"
                 f"{artifact}-{full}-installer.jar")
    return run_installer(installer, f"neoforge-{full}-installer.jar", java, on_status)


# ---------------- OptiFine ----------------

def list_optifine(mc: str) -> list:
    data = net.get_json(f"{BMCLAPI}/optifine/{mc}")
    out = []
    for e in data:
        t, p = e.get("type"), e.get("patch")
        if t and p:
            out.append({"type": t, "patch": p, "filename": e.get("filename", "")})
    out.sort(key=lambda x: x["patch"], reverse=True)
    return out


def install_optifine(mc: str, oftype: str, patch: str, java: str,
                     manager: DownloadManager | None = None,
                     on_status=None, on_update=None) -> str:
    """用 OptiFine 自带 headless 安装器（optifine.Installer QUIET）安装。

    安装器固定从 APPDATA 解析游戏目录，因此子进程里重定向 APPDATA。
    需要先装好对应原版（安装器要给 client jar 打补丁）。
    """
    if java is None:
        raise InstallError("OptiFine 安装需要 Java，请先在「设置」中配置 Java。")
    root = config.mc_root()
    if versions.load_json(mc) is None:
        versions.fetch_version_json(mc)
    if manager:
        try:
            versions.ensure_version(mc, manager, on_status, on_update, skip_assets=True)
        except Exception as e:
            if on_status:
                on_status(f"原版文件预下载失败: {e}")
    client_jar = root / "versions" / mc / f"{mc}.jar"
    if not client_jar.exists():
        raise InstallError(f"缺少原版 {mc} 的 client jar，无法安装 OptiFine")

    installer_url = f"{BMCLAPI}/optifine/{mc}/{oftype}/{patch}"
    idir = root / "cache" / "installers"
    idir.mkdir(parents=True, exist_ok=True)
    installer = idir / f"OptiFine_{mc}_{oftype}_{patch}_Install.jar"
    if on_status:
        on_status("下载 OptiFine 安装器…")
    net.download_stream(installer_url, installer)

    before = {d.name for d in (root / "versions").iterdir() if d.is_dir()}
    if on_status:
        on_status("运行 OptiFine 无头安装器…")
    env = {**os.environ, "APPDATA": str(root.parent)}
    proc = subprocess.run([java, "-cp", str(installer), "optifine.Installer", "QUIET"],
                          cwd=str(idir), capture_output=True, timeout=600,
                          creationflags=CREATE_NO_WINDOW, env=env)
    out = ((proc.stdout or b"") + (proc.stderr or b"")).decode("utf-8", "replace")
    (idir / (installer.name + ".log")).write_text(out, "utf-8", errors="replace")
    after = {d.name for d in (root / "versions").iterdir() if d.is_dir()}
    new = sorted(after - before)
    if new:
        if on_status:
            on_status(f"OptiFine 安装完成：{new[0]}")
        return new[0]
    raise InstallError(f"OptiFine 安装器未产生新版本 (exit={proc.returncode})。\n{out[-600:]}")


# ---------------- LiteLoader ----------------

def list_liteloader() -> list:
    data = net.get_json("https://dl.liteloader.com/versions/versions.json")
    return sorted(data.get("versions", {}).keys(), reverse=True)


def install_liteloader(mc: str, manager: DownloadManager | None = None,
                       on_status=None, on_update=None) -> str:
    """按 LiteLoader versions.json 结构安装：
    versions/<mc>/<stream>/["com.mumfrey:liteloader"][md5|latest] -> {tweakClass, libraries, file, version}
    """
    data = net.get_json("https://dl.liteloader.com/versions/versions.json")
    v = data.get("versions", {}).get(mc)
    if not v:
        raise InstallError(f"LiteLoader 不支持 {mc}")
    if versions.load_json(mc) is None:
        versions.fetch_version_json(mc)
    parent = versions.load_json(mc)

    stream = next((v[s] for s in ("snapshots", "release", "dev") if v.get(s)), None)
    if not stream:
        raise InstallError(f"LiteLoader 没有可用于 {mc} 的版本")
    repo = v.get("repo", {})
    artifact = stream.get("com.mumfrey:liteloader", {})
    entry = artifact.get("latest") or (next(iter(artifact.values()), None) if artifact else None)
    if not entry:
        raise InstallError(f"LiteLoader {mc} 版本条目缺失")
    ll_ver = entry.get("version", mc)
    fname = entry.get("file") or f"liteloader-{mc}-{ll_ver}.jar"
    tweak = entry.get("tweakClass", "com.mumfrey.liteloader.launch.LiteLoaderTweaker")

    libs = [{
        "name": "com.mumfrey:liteloader:" + ll_ver,
        "downloads": {"artifact": {
            "path": f"com/mumfrey/liteloader/{ll_ver}/{fname}",
            "url": (repo.get("url") or "http://repo.mumfrey.com/content/repositories/"
                    "snapshots/").rstrip("/") + "/",
            "sha1": entry.get("md5", ""), "size": 0}},
    }]
    for extra in entry.get("libraries", []):
        name = extra.get("name")
        if not name or name == "com.mumfrey:liteloader:" + ll_ver:
            continue
        lib = {"name": name}
        if extra.get("url"):
            lib["url"] = extra["url"].rstrip("/") + "/"
        libs.append(lib)

    vid = f"{mc}-LiteLoader"
    vj = {
        "id": vid,
        "type": "release",
        "inheritsFrom": mc,
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "minecraftArguments": (parent.get("minecraftArguments", "")
                               + " --tweakClass " + tweak).strip(),
        "libraries": libs,
        "releaseTime": parent.get("releaseTime", "1970-01-01T00:00:00+00:00"),
        "time": parent.get("time", "1970-01-01T00:00:00+00:00"),
    }
    save_version_json(vj, vid)
    if manager:
        try:
            versions.ensure_version(vid, manager, on_status, on_update, skip_assets=True)
        except Exception as e:
            if on_status:
                on_status(f"预下载失败（启动时会重试）: {e}")
    if on_status:
        on_status(f"LiteLoader 安装完成：{vid}")
    return vid


# ---------------- Cleanroom ----------------

def list_cleanroom() -> list:
    data = net.get_json("https://api.github.com/repos/CleanroomMC/Cleanroom/releases?per_page=30",
                        mirror=False)
    out = []
    for rel in data:
        for a in rel.get("assets", []):
            if a.get("name", "").endswith("-installer.jar"):
                out.append({"tag": rel.get("tag_name", ""), "url": a["browser_download_url"],
                            "name": a["name"]})
    return out


def install_cleanroom(java: str, on_status=None) -> str:
    rels = list_cleanroom()
    if not rels:
        raise InstallError("未能获取 Cleanroom 版本列表")
    latest = rels[0]
    return run_installer(latest["url"], latest["name"], java, on_status)


# ---------------- LabyMod ----------------

LABYMOD_INSTALLER = "https://dl.labymod.net/latest/install/LabyMod3_Installer.jar"


def install_labymod(java: str, on_status=None) -> str:
    """LabyMod 官方为图形安装器：下载后自动运行，由用户在窗口中选择版本完成安装。"""
    dest = config.LAUNCHER_DIR / "cache" / "LabyMod_Installer.jar"
    if on_status:
        on_status("下载 LabyMod 官方安装器…")
    net.download_stream(LABYMOD_INSTALLER, dest)
    if on_status:
        on_status("已打开 LabyMod 官方安装器，请在弹出的窗口中选择版本并安装…")
    subprocess.Popen([java, "-jar", str(dest)], cwd=str(dest.parent),
                     creationflags=CREATE_NO_WINDOW)
    return "labymod-official-installer"
