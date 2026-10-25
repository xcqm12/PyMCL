"""网络层：带 BMCLAPI 镜像回退的 HTTP 客户端与文件下载。"""
import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import config

USER_AGENT = "PyMCL/1.0 (Minecraft Launcher; +https://github.com)"

# 官方源 -> BMCLAPI 镜像映射（国内加速）
MIRROR_MAP = {
    "piston-meta.mojang.com": "bmclapi2.bangbang93.com",
    "piston-data.mojang.com": "bmclapi2.bangbang93.com",
    "launcher.mojang.com": "bmclapi2.bangbang93.com",
    "launchermeta.mojang.com": "bmclapi2.bangbang93.com",
    "resources.download.minecraft.net": "bmclapi2.bangbang93.com/resources",
    "meta.fabricmc.net": "bmclapi2.bangbang93.com/fabric-meta",
    "maven.fabricmc.net": "bmclapi2.bangbang93.com/maven",
    "meta.quiltmc.org": "bmclapi2.bangbang93.com/quilt-meta",
    "maven.quiltmc.org": "bmclapi2.bangbang93.com/maven",
    "maven.neoforged.net": "bmclapi2.bangbang93.com/maven",
    "maven.minecraftforge.net": "bmclapi2.bangbang93.com/maven",
    "files.minecraftforge.net": "bmclapi2.bangbang93.com/maven",
}

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


class NetError(Exception):
    pass


def mirror_url(url: str) -> str:
    if not config.get("use_mirror", True):
        return url
    try:
        parts = urlparse(url)
        mapped = MIRROR_MAP.get(parts.netloc)
        if mapped:
            return parts._replace(netloc=mapped, scheme="https").geturl()
    except Exception:
        pass
    return url


def candidates(url: str) -> list:
    m = mirror_url(url)
    return [m, url] if m != url else [url]


def get_json(url: str, params=None, timeout=20, mirror=True):
    errors = []
    urls = candidates(url) if mirror else [url]
    for u in urls:
        for attempt in range(2):
            try:
                r = session.get(u, params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                errors.append(f"{u} -> HTTP {r.status_code}")
                break
            except Exception as e:
                errors.append(f"{u} -> {type(e).__name__}: {e}")
                if attempt == 0:
                    time.sleep(0.8)
    raise NetError("；".join(errors[:4]))


def post_json(url: str, payload: dict, headers=None, timeout=25, form: bool = False):
    """form=True 时发送 application/x-www-form-urlencoded（MSA 端点只认表单），
    否则发送 JSON（Xbox/Minecraft 服务端点）。"""
    body = payload if form else None
    kwargs = {"headers": headers, "timeout": timeout}
    if form:
        kwargs["data"] = body
    else:
        kwargs["json"] = payload
    r = session.post(url, **kwargs)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return r.status_code, data


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_stream(url: str, dest: Path, sha1: str | None = None, size: int | None = None,
                    progress=None, chunk: int = 1 << 18, cancelled=None) -> int:
    """流式下载单个文件：镜像回退 + sha1 校验 + 原子写入，返回字节数。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for u in candidates(url):
        for attempt in range(3):
            tmp = dest.with_suffix(dest.suffix + ".part")
            try:
                with session.get(u, stream=True, timeout=(12, 60)) as r:
                    if r.status_code != 200:
                        errors.append(f"{u} -> HTTP {r.status_code}")
                        break
                    got = 0
                    with open(tmp, "wb") as f:
                        for data in r.iter_content(chunk):
                            if cancelled is not None and cancelled.is_set():
                                raise NetError("已取消")
                            f.write(data)
                            got += len(data)
                            if progress:
                                progress(len(data))
                if size is not None and got != size:
                    errors.append(f"{u} -> 大小不符({got}/{size})")
                    continue
                if sha1:
                    h = hashlib.sha1()
                    with open(tmp, "rb") as f:
                        for data in iter(lambda: f.read(1 << 20), b""):
                            h.update(data)
                    if h.hexdigest() != sha1:
                        errors.append(f"{u} -> sha1 校验失败")
                        continue
                tmp.replace(dest)
                return got
            except NetError:
                tmp.unlink(missing_ok=True)
                raise
            except Exception as e:
                errors.append(f"{u} -> {type(e).__name__}: {e}")
                tmp.unlink(missing_ok=True)
                if attempt == 0:
                    time.sleep(0.8)
    raise NetError("；".join(errors[:4]))
