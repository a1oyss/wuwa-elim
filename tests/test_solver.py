"""回归测试：用一局真实盘面验证引擎，并核对游戏自带提示的合法性。

用法:  python tests/test_solver.py
"""

from __future__ import annotations

import sys

import conftest  # noqa: F401  (把 src 加进 sys.path)
from wuwa_elim import solver

RAW = [
    "GGRMMDMR",
    "RLCDLCDG",
    "DCRCCRCM",
    "GCGOOGCG",
    "LLCLGCRL",
    "MLDCCDRM",
    "DMLMDRDR",
]

# 游戏自带的黄框提示：把 (6,5) 的白兔往下和 (6,6) 交换
HINT = ((6, 5), (6, 6))


def build() -> list[list[str]]:
    return [["O3" if ch == "O" else ch for ch in row] for row in RAW]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    grid = build()
    print(solver.render(grid))

    ok = True

    def check(name: str, cond: bool, extra: str = "") -> None:
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {extra}" if extra else ""))
        ok &= cond

    check("开局没有现成三连", not solver.has_match(grid))

    pairs = solver.legal_pairs(grid)
    check("提示走法在可交换集合里", HINT in pairs, f"可交换对={len(pairs)}")

    mv = solver.evaluate(grid, *HINT)
    check("提示走法合法", mv is not None)
    if mv:
        # 这一步游戏实际给了 60 分，引擎应当复现
        check("提示走法预测 60 分", abs(mv.score - 60) < 1e-6, f"score={mv.score}")
        print(f"      明细={mv.groups}")

    moves = [m for m in (solver.evaluate(grid, a, b)
                         for a, b in pairs) if m]
    moves.sort(key=lambda m: m.value, reverse=True)
    print(f"\n  有效走法 {len(moves)} 个，前 3：")
    for m in moves[:3]:
        print(f"      {m.label} 分数={m.score:.0f} 消除={m.cleared} 特效={m.specials}")
    check("提示走法排在前 3", HINT == moves[0].a and HINT == moves[0].b
          or mv in moves[:3], f"第一名={moves[0].label if moves else None}")

    print("\n结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
