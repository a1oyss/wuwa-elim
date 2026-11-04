"""等稳定逻辑的回归测试：用假的读盘管线，不依赖游戏。

覆盖两种情况：
  1. 画面像素一直在变（选中框呼吸、光影流动），但盘面内容不变 -> 应判稳成功
  2. 盘面内容确实在变 -> 应超时

这正是线上出现过的问题：早期用像素指纹判稳，画面有细碎动画时永远等不到，
一直耗到 12 秒超时。

用法:  python tests/test_settle.py
"""

from __future__ import annotations

import os
import sys
import time
from unittest import mock

import conftest  # noqa: F401  (把 src 加进 sys.path)
from wuwa_elim import constants as C, engine

# 两张没有三连的盘面：行内不重样，列内上下交替
EVEN = "GRMDLGRM"
ODD = "RMGLDRMG"
BOARD_A = [[EVEN[c] if r % 2 == 0 else ODD[c] for c in range(8)] for r in range(7)]
BOARD_B = [[ODD[c] if r % 2 == 0 else EVEN[c] for c in range(8)] for r in range(7)]


def run(cells_sequence, seconds=10.0, covered=False):
    """cells_sequence: 每次读盘返回哪一个盘面（按调用序号循环）。"""
    calls = {"n": 0}

    def fake_grab(win):
        return None, None, object()

    def fake_read(_img, _grid):
        i = calls["n"]
        calls["n"] += 1
        pattern = cells_sequence[i % len(cells_sequence)]
        return [row[:] for row in pattern]

    with mock.patch.object(engine, "grab_board", fake_grab), \
         mock.patch.object(engine, "board_view",
                           lambda _w: (None, (0, 0, 10, 10), None)), \
         mock.patch.object(engine.capture, "board_covered",
                           lambda _w, _r: covered), \
         mock.patch.object(engine, "board_signature",
                           lambda _img: os.urandom(8)), \
         mock.patch.object(engine.board, "read_board", fake_read):
        t0 = time.time()
        try:
            engine.wait_settled(None, timeout=seconds)
            return True, time.time() - t0
        except TimeoutError:
            return False, time.time() - t0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ok = True

    settled, dt = run([BOARD_A])
    good = settled and dt < C.SETTLE_CONTENT_FALLBACK + 4.0
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  画面一直在变但内容不变 -> 应判稳"
          f"（{dt:.1f}s，阈值 {C.SETTLE_CONTENT_FALLBACK}s）")

    settled, dt = run([BOARD_A, BOARD_B], seconds=7.0)
    good = not settled
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  内容持续变化 -> 应超时（{dt:.1f}s）")

    settled, dt = run([BOARD_A, BOARD_A], seconds=4.0, covered=True)
    good = not settled
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  游戏窗口被遮挡 -> 应超时（{dt:.1f}s）")

    empty = [["?" * 8 for _ in range(7)]]
    settled, dt = run(empty, seconds=4.0)
    good = not settled
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  有未识别格 -> 应超时（{dt:.1f}s）")

    print("\n结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
