"""编排层：读盘、等待、执行、验证。CLI 和 GUI 共用这一套。"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np

from . import board, capture, constants as C, mouse, solver

Logger = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def read_state(win: capture.Window):
    img = capture.grab(win)
    grid = board.fit_grid(img)
    return img, grid, board.read_board(img, grid)


def count_changed(a: list[list[str]], b: list[list[str]]) -> int:
    return sum(1 for ra, rb in zip(a, b) for x, y in zip(ra, rb) if x != y)


def wait_settled(win, timeout: float = C.SETTLE_TIMEOUT,
                 poll: float = C.SETTLE_POLL, log: Logger | None = None):
    """等到棋盘静止可决策，返回 (img, grid, cells)，超时抛 TimeoutError。

    稳定 = 连续两次读数一致 + 无未识别格。"盘面上还有三连"只作为动画未结束的
    提示，不当作硬条件 —— 一旦某格被认错就会永远等不到"无三连"而卡死
    （终极棋子被认成白兔时就是这么卡住的）。同样的状态持续超过 4 秒，
    就判为识别误判，继续往下走。
    """
    log = log or _noop
    deadline = time.time() + timeout
    prev: list[list[str]] | None = None
    stable_since: float | None = None
    reason = "刚开始"

    while True:
        mouse.check_abort()
        img, grid, cells = read_state(win)
        unknown = sum(row.count(C.WALL) for row in cells)
        pending = solver.has_match(cells)

        if unknown == 0 and cells == prev:
            if not pending:
                return img, grid, cells
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since > 4.0:
                log("注意: 稳定盘面上仍有残留三连，按识别误判继续。")
                return img, grid, cells
            reason = "盘面稳定但有三连，可能是识别误判"
        else:
            stable_since = None
            if unknown:
                reason = f"有 {unknown} 格没认出来（可能被弹窗遮挡）"
            elif pending:
                reason = "盘面还有三连在消，动画没结束"
            else:
                reason = "两次读数还在变化"

        if time.time() >= deadline:
            raise TimeoutError(reason)
        prev = cells
        time.sleep(poll)


def wait_effect(win, before: list[list[str]],
                timeout: float = C.EFFECT_TIMEOUT,
                min_changed: int = C.MIN_CHANGED_CELLS,
                poll: float = C.EFFECT_POLL) -> bool:
    """确认这次拖拽真的生效。

    只比"有没有变化"不够：上一步的连锁可能延迟补下一颗棋子，那一格的变化会被
    误当成生效。真实的一步至少消掉 3 个棋子，盘面变化必定 ≥3 格。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        mouse.check_abort()
        _, _, cells = read_state(win)
        if count_changed(before, cells) >= min_changed:
            return True
        time.sleep(poll)
    return False


def perform(win: capture.Window, grid: board.Grid, mv: solver.Move,
            mode: str = "drag") -> None:
    ax, ay = grid.to_screen(mv.a[0], mv.a[1], win.left, win.top)
    bx, by = grid.to_screen(mv.b[0], mv.b[1], win.left, win.top)
    if not mouse.focus_window(win.hwnd):
        raise RuntimeError("切不到游戏前台，游戏会无视所有点击")
    mouse.pre_drag_pause()
    with mouse.preserve_cursor():
        if mode == "drag":
            mouse.drag(ax, ay, bx, by)
        else:
            mouse.click(ax, ay)
            mouse.human_pause()
            mouse.click(bx, by)


# ---------------------------------------------------------------- 文案

def direction(a: tuple[int, int], b: tuple[int, int]) -> str:
    (c1, r1), (c2, r2) = a, b
    if r2 > r1:
        return "往下"
    if r1 > r2:
        return "往上"
    return "往右" if c2 > c1 else "往左"


def instruction(mv: solver.Move, cells: list[list[str]]) -> str:
    (c1, r1), (c2, r2) = mv.a, mv.b
    return (f"把 第{r1 + 1}行第{c1 + 1}列 的【{board.name_of(cells[r1][c1])}】"
            f"{direction(mv.a, mv.b)}拖一格，和 第{r2 + 1}行第{c2 + 1}列 的"
            f"【{board.name_of(cells[r2][c2])}】交换")


def describe(mv: solver.Move) -> str:
    groups = " + ".join(f"{c}x{n}" for c, n in mv.groups)
    extra = ""
    if mv.specials:
        extra += f"  造出[{''.join(mv.specials)}]"
    if mv.energy:
        extra += f"  能量+{mv.energy}"
    return (f"{mv.label:<16} 分数≈{mv.score:>5.0f} 消除={mv.cleared:>2} "
            f"连锁={mv.cascades}  [{groups}]{extra}")


# ---------------------------------------------------------------- 一整个回合

def open_session(log: Logger | None = None):
    """做 DPI 声明并找窗口，返回 Window；找不到返回 None。"""
    capture.make_dpi_aware()
    return capture.find_window()


def play_step(win, log: Logger, retries: int = C.RETRIES,
              mode: str = "drag") -> bool:
    """从"等稳定"开始打一步，含重试。返回是否成功。"""
    _, grid, cells = wait_settled(win, log=log)
    moves = solver.best_moves(cells, top_n=1)
    if not moves:
        log("没有有效走法，停止。")
        return False

    mv = moves[0]
    for attempt in range(1, retries + 2):
        if attempt > 1:
            # 上一把可能没生效，重读重算，别用过期走法
            _, grid, cells = wait_settled(win, log=log)
            again = solver.best_moves(cells, top_n=1)
            if not again:
                log("重算后没有有效走法，停止。")
                return False
            mv = again[0]
        log(f"执行 {mv.label}" + (f"（第 {attempt} 次）" if attempt > 1 else ""))
        perform(win, grid, mv, mode)
        if wait_effect(win, cells):
            log("→ 动作生效")
            return True
        log("→ 盘面几乎没变，这一步大概没点上")
    return False
