"""标定用：打印每个格子四个角 / 四条边的黄色占比。

拿到一张带爆炸或十字棋子的截图后跑这个，看那一格的数值离普通格子有多远，
再调 constants.py 里的 ZONE_MIN_FRAC。

用法:  python -m wuwa_elim.tools.marker_probe
"""

from __future__ import annotations

import sys

import numpy as np

from .. import board, capture, constants as C

SHOW = 12


def _frac(mask: np.ndarray, zone: tuple[float, float, float, float]) -> float:
    y0, y1, x0, x1 = zone
    h, w = mask.shape
    part = mask[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
    return float(part.mean()) if part.size else 0.0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.make_dpi_aware()
    win = capture.find_window()
    if win is None:
        print("没找到鸣潮窗口")
        return 2

    img = capture.grab(win)
    grid = board.fit_grid(img)

    rows = []
    for j, cy in enumerate(grid.cell_y):
        for i, cx in enumerate(grid.cell_x):
            hw = int(grid.pitch_x * C.MARKER_BOX)
            hh = int(grid.pitch_y * C.MARKER_BOX)
            patch = (img[cy - hh:cy + hh, cx - hw:cx + hw]
                     .astype(np.float32) / 255.0)
            mask = board._yellow(patch)
            corners = [_frac(mask, z) for z in C.CORNER_ZONES]
            edges = [_frac(mask, z) for z in C.EDGE_ZONES]
            rows.append((min(corners), min(edges), corners, edges, i, j))

    rows.sort(reverse=True)
    print(f"当前阈值 ZONE_MIN_FRAC = {C.ZONE_MIN_FRAC}")
    print("「四角最小占比」越大越像爆炸，「四边最小占比」越大越像十字。\n")
    print(f"{'格':<10}{'四角min':>9}{'四边min':>9}   四角明细 / 四边明细")
    for cmin, emin, corners, edges, i, j in rows[:SHOW]:
        cs = " ".join(f"{v:.2f}" for v in corners)
        es = " ".join(f"{v:.2f}" for v in edges)
        print(f"({i},{j})".ljust(10) + f"{cmin:>9.3f}{emin:>9.3f}   [{cs}] / [{es}]")

    print(f"\n全场最高的四角最小占比 = {rows[0][0]:.3f}")
    print(f"全场最高的四边最小占比 = {max(r[1] for r in rows):.3f}")
    if rows[0][0] < C.ZONE_MIN_FRAC and max(r[1] for r in rows) < C.ZONE_MIN_FRAC:
        print("盘面上大概没有爆炸/十字棋子——先造一个出来再跑本脚本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
