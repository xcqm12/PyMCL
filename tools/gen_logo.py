"""自动生成启动器 Logo（苦力怕像素脸）与图标。"""
import random
from pathlib import Path

FACE = [
    "........",
    "........",
    ".##..##.",
    ".##..##.",
    "...##...",
    "..####..",
    "..####..",
    "..#..#..",
]

GREENS = ["#4f9e3f", "#57a844", "#47923a", "#5cb04a", "#4aa03e", "#529f41"]
DARK = "#163017"


def render_logo(size=512, seed=20260404):
    from PIL import Image, ImageDraw
    rnd = random.Random(seed)
    margin = size // 8
    cell = (size - 2 * margin) // 8
    span = cell * 8
    off = (size - span) // 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角深色背景 + 绿色描边
    d.rounded_rectangle([3, 3, size - 4, size - 4], radius=size // 5,
                        fill="#17181c", outline="#3fb57c", width=max(3, size // 150))
    for y, row in enumerate(FACE):
        for x, ch in enumerate(row):
            color = DARK if ch == "#" else rnd.choice(GREENS)
            d.rectangle([off + x * cell, off + y * cell,
                         off + (x + 1) * cell - 1, off + (y + 1) * cell - 1],
                        fill=color)
    return img


def ensure_logo(assets_dir: Path) -> Path | None:
    """不存在时生成 logo.png 与 logo.ico；返回 logo.png 路径或 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    assets_dir.mkdir(parents=True, exist_ok=True)
    png = assets_dir / "logo.png"
    ico = assets_dir / "logo.ico"
    if not png.exists() or not ico.exists():
        img = render_logo()
        if not png.exists():
            img.save(png)
        if not ico.exists():
            img.resize((256, 256), Image.NEAREST).save(
                ico, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return png


if __name__ == "__main__":
    p = ensure_logo(Path(__file__).resolve().parent.parent / "assets")
    print("logo:", p)
