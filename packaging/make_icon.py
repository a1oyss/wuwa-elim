"""生成应用图标：直接截取游戏画面里的人物原画，圆角裁切，不重绘、不抠图。

清晰度的关键有三条：
  1. 取景要够近。整颗头 + 伞 + 身体的构图在 32px 下会糊成一个红团，
     所以取的是**脸部特写**，五官和发饰尽量占满画面。
  2. 每个尺寸单独降采样再锐化，而不是让系统从 256 直接缩。
  3. 手写 ICO 容器（PNG 压缩帧），保证每个尺寸用的都是我们处理过的那张图。

产物：
  packaging/app.ico                  打包进 EXE 的图标
  src/wuwa_elim/assets/app.ico       运行时用（标题栏 / 任务栏）
  src/wuwa_elim/assets/icon-256.png  运行时用（iconphoto）

用法:
  python packaging/make_icon.py              从当前游戏窗口取图
  python packaging/make_icon.py 某截图.png    从已有截图取图
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
ASSETS = HERE.parent / "src" / "wuwa_elim" / "assets"

# 3840x2160 游戏画面里的脸特写取景框
CROP = (380, 1330, 980, 1930)

SIZES = [256, 128, 64, 48, 32, 16]
RADIUS_RATIO = 0.20


def load_screen(path: str | None) -> Image.Image:
    if path:
        return Image.open(path).convert("RGB")
    sys.path.insert(0, str(HERE.parent / "src"))
    from wuwa_elim import capture
    capture.make_dpi_aware()
    win = capture.find_window()
    if win is None:
        raise SystemExit("没找到鸣潮窗口，请先把游戏打开，或把截图路径作为参数传入")
    return Image.fromarray(capture.grab(win))


def rounded(img: Image.Image, radius: float) -> Image.Image:
    out = img.convert("RGBA")
    mask = Image.new("L", out.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, out.width - 1, out.height - 1), radius=int(radius), fill=255)
    out.putalpha(mask)
    return out


def render(piece: Image.Image, size: int) -> Image.Image:
    """从原图直接缩到这个尺寸，再按尺寸强弱锐化。"""
    img = piece.resize((size, size), Image.LANCZOS)
    if size <= 64:
        # 小图缩下去细节全糊在一起，锐化力度要更大一点
        img = img.filter(ImageFilter.UnsharpMask(radius=0.7, percent=110, threshold=1))
    else:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.3, percent=125, threshold=2))
    return rounded(img, size * RADIUS_RATIO)


def save_ico(frames: list[Image.Image], path: Path) -> None:
    """手写 ICO 容器，每帧用 PNG 压缩 —— 这样每个尺寸都是单独处理过的。"""
    blobs = []
    for im in frames:
        import io
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        blobs.append(buf.getvalue())

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    for im, blob in zip(frames, blobs):
        w = 0 if im.width >= 256 else im.width
        h = 0 if im.height >= 256 else im.height
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)

    path.write_bytes(header + entries + b"".join(blobs))


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else None
    screen = load_screen(src)

    piece = screen.crop(CROP)
    if piece.width != piece.height:
        side = min(piece.size)
        piece = piece.crop((0, 0, side, side))
    piece.save(HERE / "icon-source.png")

    frames = [render(piece, s) for s in SIZES]

    ASSETS.mkdir(parents=True, exist_ok=True)
    for target in (HERE / "app.ico", ASSETS / "app.ico"):
        save_ico(frames, target)
    frames[0].save(ASSETS / "icon-256.png")
    frames[0].save(HERE / "icon-preview.png")

    print("已生成:")
    print(f"  {HERE / 'app.ico'}")
    print(f"  {ASSETS / 'app.ico'}")
    print(f"  {ASSETS / 'icon-256.png'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
