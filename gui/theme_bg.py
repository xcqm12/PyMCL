"""樱花二次元主题背景：随机图 API 下载、压暗合成、按控件尺寸裁剪渲染。"""
import threading
import time
from pathlib import Path

from mclauncher import config, net

DEFAULT_URL = "https://www.dmoe.cc/random.php"
_photo_refs = set()      # 防止 PhotoImage 被 GC
_source_img = None       # 压暗后的全尺寸 PIL 图像
_fetch_lock = threading.Lock()


def enabled() -> bool:
    return bool(config.get("anime_bg"))


def url() -> str:
    return (config.get("bg_url") or "").strip() or DEFAULT_URL


def cache_dir() -> Path:
    d = config.CACHE_DIR / "bg"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cached_image() -> Path | None:
    files = sorted(cache_dir().glob("bg_*.*"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    return files[0] if files else None


def _prune(keep: int = 3):
    files = sorted(cache_dir().glob("bg_*.*"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def fetch_random(force: bool = False) -> Path | None:
    """下载一张随机背景图（可在线程中调用），返回本地文件路径。"""
    if not force:
        cur = cached_image()
        if cur:
            return cur
    dest = cache_dir() / f"bg_{int(time.time() * 1000)}.jpg"
    try:
        net.download_stream(url(), dest)
        from PIL import Image
        img = Image.open(dest)
        img.verify()
        _prune()
        return dest
    except Exception:
        dest.unlink(missing_ok=True)
        return None


def ensure_source(force: bool = False, on_status=None) -> bool:
    """确保压暗后的全尺寸源图就绪；线程安全。"""
    global _source_img
    with _fetch_lock:
        if _source_img is not None and not force:
            return True
        if on_status:
            on_status("下载主题背景图…")
        path = fetch_random(force=force)
        if not path:
            return False
        from PIL import Image
        img = Image.open(path).convert("RGB")
        img.thumbnail((1600, 1600))
        overlay = Image.new("RGB", img.size, (15, 18, 23))
        _source_img = Image.blend(img, overlay, 0.45)
        return True


def photo_for(size_wh) -> object | None:
    """按目标尺寸（cover 裁剪）渲染主题背景 PhotoImage；须在主线程调用。"""
    if _source_img is None:
        return None
    w, h = max(240, int(size_wh[0])), max(100, int(size_wh[1]))
    img = _source_img.copy()
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    img = img.resize((int(sw * scale) + 1, int(sh * scale) + 1))
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    tmp = cache_dir() / "_render.png"
    img.save(tmp)
    import tkinter
    ph = tkinter.PhotoImage(file=str(tmp))
    _photo_refs.add(ph)
    return ph


def reset_source():
    global _source_img
    _source_img = None
