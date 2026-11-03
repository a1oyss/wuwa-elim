"""规则测试：用构造盘面验证爆炸/十字/终极/冰块/能量瓶的行为。

用法:  python tests/test_rules.py
"""

from __future__ import annotations

import sys

import conftest  # noqa: F401  (把 src 加进 sys.path)
from wuwa_elim import constants as C, solver

COLS = 8
ROWS = 7


def B(*rows: str) -> list[list[str]]:
    """单字符棋子的盘面。O3 这种两字符编码要用 T()。"""
    g = [list(r.ljust(COLS, ".")[:COLS]) for r in rows]
    while len(g) < ROWS:
        g.append(list("." * COLS))
    return g


def T(*rows: list[str]) -> list[list[str]]:
    g = [list(r) + ["."] * (COLS - len(r)) for r in rows]
    while len(g) < ROWS:
        g.append(["."] * COLS)
    return g


def flat(g: list[list[str]]) -> str:
    return "".join("".join(r) for r in g)


def check(name: str, cond: bool, extra: str = "") -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {extra}" if extra else ""))
    return cond


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ok = True

    print("\n[特殊棋子生成]")
    r = solver.resolve(B("GGGG"))
    ok &= check("直线 4 连 -> 爆炸（保留颜色 G）", r.specials == ["Gb"],
                f"specials={r.specials}")

    r = solver.resolve(B("GGGGG"))
    ok &= check("直线 5 连 -> 终极", r.specials == ["u"], f"specials={r.specials}")

    g = B("..G", ".GGG", "..G")
    ms = solver.find_matches(g)
    ok &= check("T 形判为十字", len(ms) == 1 and ms[0].crosses,
                f"matches={[(m.color, len(m.cells), m.crosses) for m in ms]}")
    ok &= check("T 形生成十字棋子（保留颜色 G）", solver.resolve(g).specials == ["Gx"],
                f"specials={solver.resolve(g).specials}")

    print("\n[特殊棋子是带颜色的，靠参与三连触发]")
    r = solver.resolve(T(["G", "G", "Gb", "D"]))
    ok &= check("爆炸棋子被消掉时波及 3x3（D 被连带）", r.cleared == 4,
                f"cleared={r.cleared}（不炸只会是 3）")

    r = solver.resolve(T(["G", "G", "Gx", "D"]))
    ok &= check("十字棋子被消掉时清整行整列（D 在同一行）", r.cleared == 4,
                f"cleared={r.cleared}")

    r = solver.resolve(T(["D", "D", "Db"]))
    ok &= check("爆炸棋子也能用别的颜色触发", "Db" not in flat(r.board), flat(r.board))

    print("\n[终极棋子交换]")
    mv = solver.evaluate(B("uD", "DD", "D"), (0, 0), (1, 0))
    ok &= check("终极与 D 交换 -> 清掉全盘 D",
                mv is not None and mv.cleared >= 4,
                f"cleared={mv.cleared if mv else 0}")

    print("\n[冰块]")
    r = solver.resolve(B("GGG", ".C"))
    ok &= check("相邻消除 -> 冰块碎裂", "C" not in flat(r.board))
    out = solver.collapse(B("G", "C"))
    ok &= check("冰块不下落，且挡住上方棋子",
                out[0][0] == "G" and out[1][0] == "C",
                f"col0={[out[i][0] for i in range(3)]}")

    print("\n[能量瓶]")
    r = solver.resolve(T(["G", "G", "G"], [".", "O3"]))
    ok &= check("挨一次消除 -> 3 心掉到 2 心", "O2" in flat(r.board), flat(r.board))
    r = solver.resolve(T(["G", "G", "G"], [".", "O1"]))
    ok &= check("最后 1 心被打掉 -> 消失并给 80 能量",
                "O1" not in flat(r.board) and r.energy == C.BOTTLE_ENERGY,
                f"energy={r.energy}")

    print("\n[排序：优先造特效]")
    g = T([".", ".", "G", ".", ".", ".", ".", "G"],
          ["G", "G", "R", "G", ".", ".", ".", "G"],
          [".", ".", ".", ".", ".", ".", ".", "R"],
          [".", ".", ".", ".", ".", ".", ".", "G"])
    moves = solver.best_moves(g, 5)
    for m in moves:
        print(f"      {m.label} 分数={m.score:.0f} 消除={m.cleared} "
              f"特效={m.specials} value={m.value:.0f}")
    ok &= check("造爆炸的走法排在普通三连前面",
                bool(moves) and moves[0].a == (2, 0) and moves[0].b == (2, 1)
                and any(s.endswith("b") for s in moves[0].specials),
                f"第一名={moves[0].label if moves else None}")

    print("\n结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
