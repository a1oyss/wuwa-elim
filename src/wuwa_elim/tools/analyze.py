"""网格拟合自检：画一张带网格和编号的叠加图，肉眼确认对齐。

用法:  python -m wuwa_elim.tools.analyze
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

from .. import board, capture, paths


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.make_dpi_aware()
    win = capture.find_window()
    if win is None:
        print("没找到鸣潮窗口")
        return 2

    img = capture.grab(win)
    grid = board.fit_grid(img)
    print(f"网格 = {grid.n_cols} 列 x {grid.n_rows} 行  "
          f"周期 = {grid.pitch_x}x{grid.pitch_y}")
    print("列中心 x:", grid.cell_x)
    print("行中心 y:", grid.cell_y)

    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    for j, cy in enumerate(grid.cell_y):
        for i, cx in enumerate(grid.cell_x):
            d.rectangle([cx - grid.pitch_x // 2 + 8, cy - grid.pitch_y // 2 + 8,
                         cx + grid.pitch_x // 2 - 8, cy + grid.pitch_y // 2 - 8],
                        outline=(255, 40, 40), width=5)
            d.text((cx - 18, cy - 44), f"{i},{j}", fill=(255, 255, 0))

    out = paths.app_dir() / "grid-check.png"
    pil.resize((pil.width // 2, pil.height // 2)).save(out)
    print(f"\n已保存 {out}\n红框应正好压住每个方块；压歪说明需要重新标定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
