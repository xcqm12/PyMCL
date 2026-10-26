"""加载器与游戏版本安装：原版 / Forge / NeoForge / Fabric / Quilt / LegacyFabric /
OptiFine / LiteLoader / Cleanroom / LabyMod。"""
import json
import os
import re
import subprocess
import urllib.parse
import zipfile
from pathlib import Path

from . import config, javafind, net, versions
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
    """下载安装器并 headless 安装（Forge/NeoForge/Cleanroom 家族），返回新版本 id。
    安装前先通过镜像预取 install_profile.json 里声明的全部依赖库——
    官方安装器直连 maven.minecraftforge.net，国内经常被阻断（exit=1 的主因）。"""
    root = config.mc_root()
    idir = root / "cache" / "installers"
    idir.mkdir(parents=True, exist_ok=True)
    jar = idir / name
    if on_status:
        on_status(f"下载安装器 {name} …")
    net.download_stream(installer_url, jar)
    # Forge 安装器要求存在 launcher_profiles.json（官方启动器档案文件），缺失会报
    # "There is no Minecraft launcher profile"。写一个最小桩文件（HMCL/PCL 同款做法）。
    profiles = root / "launcher_profiles.json"
    if not profiles.exists():
        profiles.write_text(json.dumps(
            {"profiles": {}, "settings": {}, "version": 3}), "utf-8")
    # 预取依赖（镜像加速）；失败不阻断——安装器还会自行校验/下载
    try:
        n = _prefetch_installer_libraries(jar, root, on_status)
        if n and on_status:
            on_status(f"已通过镜像预取 {n} 个安装器依赖（跳过被墙的直连下载）")
    except Exception:
        pass
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


def _prefetch_installer_libraries(installer_jar: Path, root: Path, on_status=None) -> int:
    """解析安装器的 install_profile.json，经镜像预取全部依赖库到 libraries/。
    安装器对已存在且校验通过的文件会跳过下载，从而不依赖直连 forge maven。"""
    with zipfile.ZipFile(installer_jar) as z:
        profile = json.loads(z.read("install_profile.json").decode("utf-8", "replace"))
    libdir = root / "libraries"
    tasks, seen = [], set()

    def add_lib(lib: dict):
        name = lib.get("name") or ""
        if not name or name in seen:
            return
        seen.add(name)
        dl = (lib.get("downloads") or {}).get("artifact") or {}
        path = dl.get("path")
        if not path:
            try:
                path = versions.maven_path(name)
            except Exception:
                return
        dest = libdir / path
        if dest.exists():
            return
        url = (dl.get("url") or "").strip()
        if url:
            # install_profile 里的 url 可能是完整 URL（含文件名）或基目录，判断区分
            if Path(urllib.parse.urlparse(url).path).name == Path(path).name:
                pass  # 已是完整 URL
            else:
                url = url.rstrip("/") + "/" + path
        else:
            url = f"https://maven.minecraftforge.net/{path}"
        sha1 = dl.get("sha1")
        tasks.append(Task(url, dest, sha1=sha1, label=path))

    for lib in profile.get("libraries", []):
        add_lib(lib)
    vi = profile.get("versionInfo") or {}
    if isinstance(vi, dict):
        for lib in vi.get("libraries", []):
            add_lib(lib)

    ok, fail = 0, 0
    for t in tasks:
        try:
            net.download_stream(t.url, t.dest, sha1=t.sha1)
            ok += 1
        except net.NetError:
            fail += 1  # 安装器随后自行重试直连（可能成功）
    if fail and on_status:
        on_status(f"警告：{fail} 个依赖镜像预取失败，将由安装器直连重试")
    return ok


def _pick_java_for(mc: str, fallback: str | None) -> str | None:
    """为加载器安装器挑选 Java：旧版（<1.17）优先 Java 8（老安装器在新 Java 上易崩），
    新版挑满足要求的最低版本。"""
    fallback = fallback or (javafind.detect_javas() or [{}])[0].get("path")
    try:
        javas = javafind.detect_javas()
        if not javas:
            return fallback
        need = javafind.required_major(mc)
        if need <= 8:
            j8 = [j for j in javas if j["major"] == 8]
            if j8:
                return j8[0]["path"]
            return fallback  # 没有 8 就用现成的（老安装器可能仍可运行）
        ok = [j for j in javas if j["major"] >= need]
        if ok:
            ok.sort(key=lambda x: x["major"])
            return ok[0]["path"]
        return fallback
    except Exception:
        return fallback


def _ensure_vanilla_for_installer(mc: str, on_status=None):
    """安装器需要原版 client jar 与相关库；先用镜像准备好（失败不阻断）。"""
    try:
        if versions.load_json(mc) is None:
            versions.fetch_version_json(mc)
        versions.ensure_version(mc, DownloadManager(), skip_assets=True,
                                on_status=on_status)
    except Exception as e:
        if on_status:
            on_status(f"原版文件预下载失败（安装器将自行下载）: {e}")


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
    _ensure_vanilla_for_installer(mc, on_status)
    installer = (f"{BMCLAPI}/maven/net/minecraftforge/forge/{full}/"
                 f"forge-{full}-installer.jar")
    return run_installer(installer, f"forge-{full}-installer.jar",
                         _pick_java_for(mc, java), on_status)


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
    _ensure_vanilla_for_installer(mc, on_status)
    return run_installer(installer, f"neoforge-{full}-installer.jar",
                         _pick_java_for(mc, java), on_status)


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
    return run_installer(latest["url"], latest["name"],
                         _pick_java_for("1.12.2", java), on_status)


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
