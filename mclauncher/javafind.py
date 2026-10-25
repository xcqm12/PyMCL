"""Java 检测、版本推荐与自动下载（Adoptium）。"""
import platform
import re
import subprocess
import zipfile
from pathlib import Path

from . import config, net

CREATE_NO_WINDOW = 0x08000000


def _java_version(path: str) -> str | None:
    try:
        p = subprocess.run([path, "-version"], capture_output=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW)
        out = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")
        m = re.search(r'version "([^"]+)"', out)
        return m.group(1) if m else None
    except Exception:
        return None


def detect_javas() -> list:
    """扫描常见安装位置与注册表，返回 [{path, version, major}]。"""
    found = {}

    def add(p: Path | str):
        p = Path(p)
        try:
            if p.exists() and str(p).lower() not in found:
                v = _java_version(str(p))
                if v:
                    m = re.match(r"(\d+)", v)
                    found[str(p).lower()] = {"path": str(p), "version": v,
                                             "major": int(m.group(1)) if m else 0}
        except Exception:
            pass

    import os
    if os.environ.get("JAVA_HOME"):
        add(Path(os.environ["JAVA_HOME"]) / "bin" / "java.exe")

    try:
        import winreg
        for root_key in (winreg.HKEY_LOCAL_MACHINE,):
            for sub in (r"SOFTWARE\JavaSoft\Java Runtime Environment",
                        r"SOFTWARE\JavaSoft\Java Development Kit",
                        r"SOFTWARE\JavaSoft\JDK",
                        r"SOFTWARE\JavaSoft\JRE"):
                try:
                    key = winreg.OpenKey(root_key, sub)
                except OSError:
                    continue
                try:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            k = winreg.OpenKey(key, winreg.EnumKey(key, i))
                            val, _ = winreg.QueryValueEx(k, "JavaHome")
                            add(Path(val) / "bin" / "java.exe")
                        except OSError:
                            pass
                finally:
                    key.Close()
    except Exception:
        pass

    globs = [
        r"C:\Program Files\Java\*\bin\java.exe",
        r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
        r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
        r"C:\Program Files\Zulu\*\bin\java.exe",
        r"C:\Program Files\Amazon Corretto\*\bin\java.exe",
        r"C:\Program Files\BellSoft\*\bin\java.exe",
        r"C:\Program Files (x86)\Java\*\bin\java.exe",
        str(Path.home() / ".jdks" / "*" / "bin" / "java.exe"),
        str(Path.home() / "AppData/Local/Programs/Eclipse Adoptium" / "*" / "bin" / "java.exe"),
        str(config.LAUNCHER_DIR / "runtime" / "*" / "bin" / "java.exe"),
        str(config.LAUNCHER_DIR / "runtime" / "*" / "*" / "bin" / "java.exe"),
        str(config.mc_root() / "runtime" / "*" / "*" / "*" / "bin" / "java.exe"),
    ]
    import glob as _g
    for pattern in globs:
        for hit in _g.glob(pattern):
            add(hit)

    out = sorted(found.values(), key=lambda x: (x["major"], x["version"]), reverse=True)
    return out


def required_major(mc_version: str) -> int:
    try:
        parts = [int(x) for x in re.findall(r"\d+", mc_version)[:3]]
    except Exception:
        return 8
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts
    if (major, minor, patch) >= (1, 20, 5):
        return 21
    if (major, minor) >= (1, 18):
        return 17
    if (major, minor) >= (1, 17):
        return 16
    return 8


def pick_java(javas: list, mc_version: str) -> dict | None:
    need = required_major(mc_version)
    ok = [j for j in javas if j["major"] >= need]
    if ok:
        ok.sort(key=lambda x: x["major"])
        return ok[0]
    return javas[0] if javas else None


def java_for_installer(javas: list) -> str | None:
    if javas:
        return javas[0]["path"]  # 最新版本跑安装器
    return None


def download_jre(major: int, on_status=None, on_progress=None) -> str:
    """从 Adoptium 下载 JRE 到 runtime/jre-<major>，返回 java.exe 路径。"""
    arch = "x64" if platform.machine().endswith("64") else "x86"
    dest_dir = config.LAUNCHER_DIR / "runtime" / f"jre-{major}"
    marker = dest_dir / ".ok"
    java = dest_dir / "bin" / "java.exe"
    if marker.exists() and java.exists():
        return str(java)
    url = (f"https://api.adoptium.net/v3/binary/latest/{major}/ga/windows/{arch}/"
           f"jre/hotspot/normal/eclipse")
    if on_status:
        on_status(f"下载 Java {major} 运行时…")
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.LAUNCHER_DIR / "cache" / f"jre-{major}.zip"
    net.download_stream(url, tmp, progress=on_progress)
    if on_status:
        on_status("解压 Java …")
    import shutil
    shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True)
    with zipfile.ZipFile(tmp) as z:
        names = z.namelist()
        roots = {n.split("/")[0] for n in names if "/" in n}
        for n in names:
            if n.endswith("/"):
                continue
            rel = n
            if len(roots) == 1 and n.startswith(list(roots)[0] + "/"):
                rel = n[len(list(roots)[0]) + 1:]
            out = dest_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as fsrc, open(out, "wb") as fout:
                shutil.copyfileobj(fsrc, fout)
    marker.write_text("ok", "utf-8")
    tmp.unlink(missing_ok=True)
    v = _java_version(str(java))
    if not v:
        raise RuntimeError("Java 下载后校验失败")
    if on_status:
        on_status(f"Java {v} 安装完成")
    return str(java)
