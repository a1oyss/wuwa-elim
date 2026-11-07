"""规则测试：用构造盘面验证爆炸/十字/终极/冰块/能量瓶的行为。

用法:  python tests/test_rules.py
"""

from __future__ import annotations

import sys

import conftest  # noqa: F401  (把 src 加进 sys.path)
from wuwa_elim import board, constants as C, solver

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

    print("\n[顶行冰块：这一列补不进新棋子]")
    # 实测关卡：(0,0) 是冰块，它下面消空之后留下的就是槽底，不是新棋子
    out = solver.collapse(T(["C"], ["."], ["G"], ["G"]))
    col0 = [out[i][0] for i in range(ROWS)]
    ok &= check("冰块钉在顶行，整列沉到底，空位留在冰块正下方",
                col0 == ["C"] + [C.EMPTY] * 4 + ["G", "G"], f"col0={col0}")
    ok &= check("空位不算棋子，不能靠它连成三连",
                not solver.find_runs(B("GG.GG")),
                f"runs={solver.find_runs(B('GG.GG'))}")
    mv = solver.evaluate(B("G."), (0, 0), (1, 0))
    ok &= check("不能把棋子换进空位", mv is None, f"evaluate={mv}")

    print("\n[空位 vs 没认出来]")
    hole = board.CellFeature(0, 1, C.GAP_RGB, 0.36, 0.23, 0.00, 0.0, 0, None)
    ok &= check("槽底背景格 -> 空位 .（当成 ? 会永远等不到稳定）",
                board.label(hole) == C.EMPTY, f"label={board.label(hole)}")
    dimmed = board.CellFeature(0, 1, (68, 97, 107), 0.36, 0.42, 0.00, 0.0, 0, None)
    ok &= check("弹窗把棋盘压暗 -> 仍算没认出来，不误判成空位",
                board.label(dimmed) == C.WALL, f"label={board.label(dimmed)}")

    print("\n[沙漏：第五关目标棋子]")
    ok &= check("沙漏没有颜色，连不成三连", not solver.find_runs(B("HHH")),
                f"runs={solver.find_runs(B('HHH'))}")
    out = solver.collapse(T(["H"], ["G"]))
    ok &= check("沙漏会随重力下落（不是冰块那种钉死的障碍）",
                out[6][0] == "G" and out[5][0] == "H",
                f"col0={[out[i][0] for i in range(7)]}")
    r = solver.resolve(T(["."], ["."], ["."], ["."], ["."], ["H"],
                         ["G", "G", "G"]))
    ok &= check("下面的棋子消掉后沙漏触底 -> 消失并计数",
                r.hourglasses == 1 and "H" not in flat(r.board),
                f"hourglasses={r.hourglasses}")
    g = T(["G", "G", "Gb", "H"],
          [".", ".", ".", "D"], [".", ".", ".", "R"], [".", ".", ".", "D"],
          [".", ".", ".", "R"], [".", ".", ".", "D"], [".", ".", ".", "R"])
    r = solver.resolve(g)
    ok &= check("爆炸波及也不消沙漏，只认触底",
                "H" in flat(r.board) and r.hourglasses == 0,
                f"hourglasses={r.hourglasses}")
    mv = solver.Move(a=(0, 0), b=(1, 0), score=30, cleared=3, cascades=1,
                     hourglasses=1)
    ok &= check("触底一颗沙漏在排序里值 20 格（=多 2 回合）",
                mv.value == 30 + C.HOURGLASS_DROP_WORTH * C.SCORE_WEIGHTS.per_tile,
                f"value={mv.value}")

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
