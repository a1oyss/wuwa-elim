"""棋盘几何与棋子识别。

fit_grid():
  周期用缝隙色的自相关求，很稳；相位必须用"亮像素"投影 —— 方块本体是画面里最亮
  的东西，它的投影峰正好落在格子中心。用缝隙色定相位会被方块边缘阴影带偏。

read_board():
  每格取中心 62% 的框（避开格缝），按中心均色做最近邻分类，再用几个专门的
  信号区分容易混的几类：终极棋子看品红占比，能量瓶看头顶金心数，
  爆炸/十字看黄色小三角是否在四角/四边对称出现。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import constants as C


@dataclass(frozen=True)
class Grid:
    cell_x: list[int]
    cell_y: list[int]
    pitch_x: int
    pitch_y: int

    @property
    def n_cols(self) -> int:
        return len(self.cell_x)

    @property
    def n_rows(self) -> int:
        return len(self.cell_y)

    def center(self, col: int, row: int) -> tuple[int, int]:
        return self.cell_x[col], self.cell_y[row]

    def to_screen(self, col: int, row: int,
                  win_left: int, win_top: int) -> tuple[int, int]:
        cx, cy = self.center(col, row)
        return win_left + cx, win_top + cy


# ---------------------------------------------------------------- 网格拟合

def _color_mask(img: np.ndarray, rgb: tuple[int, int, int], tol: int) -> np.ndarray:
    d = np.abs(img.astype(np.int16) - np.array(rgb, dtype=np.int16))
    return d.max(axis=2) <= tol


def _period(profile: np.ndarray, lo: int, hi: int) -> int:
    p = profile - profile.mean()
    return max(range(lo, hi + 1), key=lambda s: float(np.dot(p[:-s], p[s:])))


def _phase(profile: np.ndarray, period: int) -> int:
    n = (len(profile) // period) * period
    folded = profile[:n].reshape(-1, period).mean(axis=0)
    return int(np.argmax(folded))


def _lattice(start: int, end: int, period: int, phase: int) -> list[int]:
    out = []
    v = phase
    while v - period >= start:
        v -= period
    while v <= end:
        if start <= v <= end:
            out.append(int(round(v)))
        v += period
    return out


def _calibrated_grid() -> Grid:
    px, py = C.CALIB_PITCH
    x0, y0 = C.CALIB_FIRST
    return Grid([x0 + i * px for i in range(C.CALIB_SHAPE[0])],
                [y0 + j * py for j in range(C.CALIB_SHAPE[1])], px, py)


def _plausible(g: Grid) -> bool:
    return ((g.n_cols, g.n_rows) == C.CALIB_SHAPE
            and C.PERIOD_LO <= g.pitch_x <= C.PERIOD_HI
            and C.PERIOD_LO <= g.pitch_y <= C.PERIOD_HI)


def _fit_auto(img: np.ndarray) -> Grid:
    bx0, by0, bx1, by1 = C.BOARD_ROUGH
    gap = _color_mask(img, C.GAP_RGB, C.GAP_TOL)

    gap_cs = gap[by0:by1, :].sum(axis=0).astype(float)
    gap_rs = gap[:, bx0:bx1].sum(axis=1).astype(float)
    pitch_x = _period(gap_cs[bx0:bx1], C.PERIOD_LO, C.PERIOD_HI)
    pitch_y = _period(gap_rs[by0:by1], C.PERIOD_LO, C.PERIOD_HI)

    lum = img.mean(axis=2)
    bright = (lum > C.BRIGHT_LUM).astype(float)
    bright[:, :bx0] = 0
    bright[:, bx1:] = 0
    bright[:by0, :] = 0
    bright[by1:, :] = 0
    br_cs = bright.sum(axis=0)
    br_rs = bright.sum(axis=1)

    phase_x = bx0 + _phase(br_cs[bx0:bx1], pitch_x)
    phase_y = by0 + _phase(br_rs[by0:by1], pitch_y)

    return Grid(_lattice(bx0, bx1, pitch_x, phase_x),
                _lattice(by0, by1, pitch_y, phase_y), pitch_x, pitch_y)


def fit_grid(img: np.ndarray) -> Grid:
    """拟合棋盘晶格。

    自动拟合假定"棋盘是画面里最亮的一块"。一旦有弹窗（效果说明、结算界面）
    压在棋盘上并压暗背景，拟合会跑偏（实测出现过 11x9）。所以结果必须过校验，
    不合理就退回实测标定的晶格；退回后若画面仍是压暗状态，格子会大面积认不出来，
    调用方据此拒绝行动 —— 这是期望行为。
    """
    try:
        fitted = _fit_auto(img)
        if _plausible(fitted):
            return fitted
    except Exception:                      # noqa: BLE001
        pass
    return _calibrated_grid()


# ---------------------------------------------------------------- 特征提取

@dataclass
class CellFeature:
    col: int
    row: int
    mean_rgb: tuple[int, int, int]
    sat_mean: float
    val_mean: float
    bright_frac: float
    magenta_frac: float
    hearts: int
    marker: str | None


def _yellow(patch: np.ndarray) -> np.ndarray:
    r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    return (r > 0.78) & (g > 0.55) & (b < 0.45)


def _zone_hit(mask: np.ndarray, zone: tuple[float, float, float, float]) -> bool:
    y0, y1, x0, x1 = zone
    h, w = mask.shape
    part = mask[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
    return part.size > 0 and part.mean() >= C.ZONE_MIN_FRAC


def detect_marker(tile_patch: np.ndarray) -> str | None:
    """四角黄三角=爆炸，四边中点黄三角=十字。

    要求四个位置**同时**命中：方块本身常有一两块金色装饰，对称出现几乎不可能，
    这样就把误判压下去了。
    """
    mask = _yellow(tile_patch)
    if all(_zone_hit(mask, z) for z in C.CORNER_ZONES):
        return C.MARK_BOMB
    if all(_zone_hit(mask, z) for z in C.EDGE_ZONES):
        return C.MARK_CROSS
    return None


def _count_hearts(top: np.ndarray) -> int:
    """数格子顶部那一排金色心。"""
    r, g, b = top[:, :, 0], top[:, :, 1], top[:, :, 2]
    on = ((r > 0.78) & (g > 0.55) & (b < 0.55)).sum(axis=0) >= 2
    hearts, prev = 0, False
    for v in on:
        if v and not prev:
            hearts += 1
        prev = bool(v)
    return min(hearts, 3)


def sample_cell(img: np.ndarray, grid: Grid, col: int, row: int) -> CellFeature:
    cx, cy = grid.center(col, row)
    hw = int(grid.pitch_x * C.CELL_BOX / 2)
    hh = int(grid.pitch_y * C.CELL_BOX / 2)
    patch = img[cy - hh:cy + hh, cx - hw:cx + hw].astype(np.float32) / 255.0

    r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    mx, mn = patch.max(axis=2), patch.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

    magenta = ((r > 0.75) & (g < 0.63) & (b > 0.43) & (b < 0.92)).mean()
    hearts = _count_hearts(patch[: max(1, int(patch.shape[0] * C.HEART_TOP))])

    mh_w = int(grid.pitch_x * C.MARKER_BOX)
    mh_h = int(grid.pitch_y * C.MARKER_BOX)
    big = (img[cy - mh_h:cy + mh_h, cx - mh_w:cx + mh_w]
           .astype(np.float32) / 255.0)
    marker = detect_marker(big) if big.size else None

    return CellFeature(
        col=col, row=row,
        mean_rgb=tuple(int(v * 255) for v in patch.reshape(-1, 3).mean(axis=0)),
        sat_mean=float(sat.mean()),
        val_mean=float(mx.mean()),
        bright_frac=float((mx > 0.55).mean()),
        magenta_frac=float(magenta),
        hearts=hearts,
        marker=marker,
    )


def scan_board(img: np.ndarray, grid: Grid) -> list[list[CellFeature]]:
    return [[sample_cell(img, grid, c, r) for c in range(grid.n_cols)]
            for r in range(grid.n_rows)]


# ---------------------------------------------------------------- 分类

TILE_NAMES = {
    "G": "绿水晶", "R": "白兔", "M": "紫面具", "D": "橙鬼脸",
    "L": "蓝水滴", "C": "青冰块",
    "O3": "能量瓶(3心)", "O2": "能量瓶(2心)", "O1": "能量瓶(1心)",
    "u": "终极棋子", "b": "爆炸标记", "x": "十字标记",
    "?": "未识别", ".": "空位",
}


def name_of(code: str) -> str:
    if code in TILE_NAMES:
        return TILE_NAMES[code]
    if len(code) == 2 and code[1] in (C.MARK_BOMB, C.MARK_CROSS):
        base = TILE_NAMES.get(code[0], code[0])
        kind = "爆炸" if code[1] == C.MARK_BOMB else "十字"
        return f"{base}-{kind}"
    return TILE_NAMES.get(code, code)


def label(feat: CellFeature) -> str:
    if feat.magenta_frac >= C.MAGENTA_ULTIMATE:
        return C.ULT
    if feat.val_mean < C.DARK_VAL:
        return C.WALL

    best, best_d = C.WALL, float("inf")
    for name, rgb in C.TILE_COLORS.items():
        d = float(np.linalg.norm(np.array(feat.mean_rgb, dtype=float)
                                 - np.array(rgb, dtype=float)))
        if d < best_d:
            best, best_d = name, d
    if best_d > C.UNKNOWN_DIST:
        return C.WALL

    if best == "U":
        return C.ULT
    if best == "O":
        return f"{C.BOTTLE}{feat.hearts or 3}"
    if best == "C":
        return C.ICE
    return f"{best}{feat.marker}" if feat.marker else best


def read_board(img: np.ndarray, grid: Grid) -> list[list[str]]:
    return [[label(f) for f in row] for row in scan_board(img, grid)]
