"""三消引擎：匹配检测、特殊棋子连锁、下坠、走法搜索。

规则（游戏内「效果说明」+ 实物核对）：
  爆炸棋子  直线消除 4 个时生成，保留原颜色，四个角有黄色小三角；
           被消除时炸掉周围 3×3
  十字棋子  T 形或 L 形消除 5 个及以上生成，保留原颜色，上下左右四边有黄三角；
           被消除时清掉同行同列
  终极棋子  直线消除 5 个及以上生成，无颜色；与任意棋子交换可消除全盘同类型，
           两个终极棋子交换清空整个棋盘
  冰块棋子  不可移动、不会下落；周围完成一次消除时碎掉，并把所在列切段
  能量瓶    周围完成三次消除后消失，给角色 80 能量；会像普通棋子一样下落
  沙漏      第五关目标棋子；不参与三连、不被爆炸波及，会随重力下落，
           触底自动消失并 +2 操作回合

编码：G R M D L 五色 / Gb Gx 带标记 / u 终极 / C 冰块 / O3 O2 O1 能量瓶 /
      H 沙漏 / . 空位 / ? 未识别
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import constants as C


@dataclass
class Move:
    a: tuple[int, int]
    b: tuple[int, int]
    score: float
    cleared: int
    cascades: int
    groups: list[tuple[str, int]] = field(default_factory=list)
    specials: list[str] = field(default_factory=list)
    energy: int = 0
    hourglasses: int = 0
    fallen: int = 0

    @property
    def label(self) -> str:
        (c1, r1), (c2, r2) = self.a, self.b
        return f"({c1},{r1})<->({c2},{r2})"

    @property
    def value(self) -> float:
        """排序用的综合价值：分数 + 造出特效的期望收益 + 沙漏进度。"""
        v = self.score
        for s in self.specials:
            kind = s[-1] if len(s) == 2 else s
            v += C.SPECIAL_WORTH_TILES.get(kind, 0.0) * C.SCORE_WEIGHTS.per_tile
        v += (self.hourglasses * C.HOURGLASS_DROP_WORTH
              + self.fallen * C.HOURGLASS_FALL_WORTH) * C.SCORE_WEIGHTS.per_tile
        return v


@dataclass
class Resolution:
    score: float
    cleared: int
    cascades: int
    detail: list[tuple[str, int]] = field(default_factory=list)
    specials: list[str] = field(default_factory=list)
    energy: int = 0
    hourglasses: int = 0
    fallen: int = 0
    board: list[list[str]] = field(default_factory=list)


# ---------------------------------------------------------------- 基础判定

def base_color(t: str) -> str | None:
    """棋子的颜色。爆炸/十字带颜色，终极、冰块、能量瓶没有。"""
    return t[0] if t and t[0] in C.COLORS else None


def special_kind(t: str) -> str | None:
    if len(t) == 2 and t[0] in C.COLORS and t[1] in C.SPECIALS:
        return t[1]
    return None


def is_bottle(t: str) -> bool:
    return t.startswith(C.BOTTLE) and len(t) == 2 and t[1].isdigit()


def bottle_hearts(t: str) -> int:
    return int(t[1]) if is_bottle(t) else 0


def is_blocker(t: str) -> bool:
    """真正不动、不下落、会挡列的只有冰块。能量瓶会随补充落到新位置。"""
    return t == C.ICE


def is_hourglass(t: str) -> bool:
    return t == C.HOURGLASS


def _hourglass_rows(g: list[list[str]]) -> dict[tuple[int, int], int]:
    return {(x, y): y for y, row in enumerate(g)
            for x, t in enumerate(row) if is_hourglass(t)}


def _drop_bottom(g: list[list[str]], rows: int,
                 cols: int) -> tuple[list[list[str]], int]:
    """沙漏触底自动消失，消失后上面的棋子继续落。返回 (盘面, 触底个数)。"""
    dropped = 0
    while True:
        bottom = [x for x in range(cols) if is_hourglass(g[rows - 1][x])]
        if not bottom:
            return g, dropped
        for x in bottom:
            g[rows - 1][x] = C.EMPTY
        dropped += len(bottom)
        g = collapse(g)


def is_ultimate(t: str) -> bool:
    return t == C.ULT


def _matchable(t: str) -> bool:
    return base_color(t) is not None


# ---------------------------------------------------------------- 匹配检测

@dataclass
class Run:
    horizontal: bool
    color: str
    cells: list[tuple[int, int]]


@dataclass
class Match:
    color: str
    cells: list[tuple[int, int]]
    horizontal_run: int
    vertical_run: int
    crosses: bool

    @property
    def straight(self) -> int:
        return max(self.horizontal_run, self.vertical_run)


def find_runs(grid: list[list[str]]) -> list[Run]:
    rows, cols = len(grid), len(grid[0])
    runs: list[Run] = []

    for r in range(rows):
        c = 0
        while c < cols:
            color = base_color(grid[r][c])
            if color is None:
                c += 1
                continue
            start = c
            while c + 1 < cols and base_color(grid[r][c + 1]) == color:
                c += 1
            if c - start + 1 >= 3:
                runs.append(Run(True, color, [(x, r) for x in range(start, c + 1)]))
            c += 1

    for c in range(cols):
        r = 0
        while r < rows:
            color = base_color(grid[r][c])
            if color is None:
                r += 1
                continue
            start = r
            while r + 1 < rows and base_color(grid[r + 1][c]) == color:
                r += 1
            if r - start + 1 >= 3:
                runs.append(Run(False, color, [(c, y) for y in range(start, r + 1)]))
            r += 1

    return runs


def find_matches(grid: list[list[str]]) -> list[Match]:
    """把同色且相连的横/竖连串合并成"一次消除"，并判定生成哪种特殊棋子。"""
    runs = find_runs(grid)
    used = [False] * len(runs)
    matches: list[Match] = []

    for i, run in enumerate(runs):
        if used[i]:
            continue
        comp = [i]
        used[i] = True
        changed = True
        while changed:
            changed = False
            cells = {cell for k in comp for cell in runs[k].cells}
            for j, other in enumerate(runs):
                if used[j] or other.color != run.color:
                    continue
                if cells & set(other.cells):
                    used[j] = True
                    comp.append(j)
                    changed = True

        cells: list[tuple[int, int]] = []
        h_max = v_max = 0
        for k in comp:
            for cell in runs[k].cells:
                if cell not in cells:
                    cells.append(cell)
            if runs[k].horizontal:
                h_max = max(h_max, len(runs[k].cells))
            else:
                v_max = max(v_max, len(runs[k].cells))

        matches.append(Match(
            color=run.color, cells=cells,
            horizontal_run=h_max, vertical_run=v_max,
            crosses=h_max >= 3 and v_max >= 3 and len(cells) >= 5,
        ))
    return matches


def has_match(grid: list[list[str]]) -> bool:
    return bool(find_runs(grid))


# ---------------------------------------------------------------- 消除结算

def collapse(grid: list[list[str]]) -> list[list[str]]:
    """下坠：可移动的棋子沉到段底；冰块钉死并把列切成一段段。"""
    rows, cols = len(grid), len(grid[0])
    out = [[C.EMPTY] * cols for _ in range(rows)]
    for c in range(cols):
        r = rows - 1
        while r >= 0:
            if is_blocker(grid[r][c]):
                out[r][c] = grid[r][c]
                r -= 1
                continue
            end = r
            while r >= 0 and not is_blocker(grid[r][c]):
                r -= 1
            start = r + 1
            stack = [grid[i][c] for i in range(start, end + 1)
                     if grid[i][c] != C.EMPTY]
            write = end
            for t in reversed(stack):
                out[write][c] = t
                write -= 1
    return out


def _blast(rows: int, cols: int, kind: str, at: tuple[int, int]):
    c, r = at
    if kind == C.MARK_BOMB:
        return {(x, y) for x in range(c - 1, c + 2) for y in range(r - 1, r + 2)
                if 0 <= x < cols and 0 <= y < rows}
    if kind == C.MARK_CROSS:
        return {(x, r) for x in range(cols)} | {(c, y) for y in range(rows)}
    return {(c, r)}


def _neighbors(cell: tuple[int, int], rows: int, cols: int):
    c, r = cell
    for dc, dr in C.NEIGHBORS_8:
        x, y = c + dc, r + dr
        if 0 <= x < cols and 0 <= y < rows:
            yield x, y


def _spawn_choice(match: Match, prefer: set[tuple[int, int]]) -> tuple[int, int]:
    """特殊棋子放在哪格：优先玩家刚动过的那格，否则放连串中间。"""
    for cell in match.cells:
        if cell in prefer:
            return cell
    return match.cells[len(match.cells) // 2]


def resolve(grid: list[list[str]],
            prefer: set[tuple[int, int]] | None = None) -> Resolution:
    """反复消除直到稳定。"""
    g = [row[:] for row in grid]
    prefer = prefer or set()
    rows, cols = len(g), len(g[0])
    w = C.SCORE_WEIGHTS

    total = 0.0
    cleared_total = 0
    cascade = 0
    detail: list[tuple[str, int]] = []
    spawned: list[str] = []
    energy = 0
    dropped = 0
    fallen = 0

    while True:
        matches = find_matches(g)
        if not matches:
            break
        hg_before = _hourglass_rows(g)

        # 1) 这次生成哪些特殊棋子、落在哪一格（保留颜色）
        pending: dict[tuple[int, int], str] = {}
        for m in matches:
            if m.crosses:
                pending[_spawn_choice(m, prefer)] = f"{m.color}{C.MARK_CROSS}"
            elif m.straight >= 5:
                pending[_spawn_choice(m, prefer)] = C.ULT
            elif m.straight == 4:
                pending[_spawn_choice(m, prefer)] = f"{m.color}{C.MARK_BOMB}"

        # 2) 波及范围。特殊棋子是带颜色的，随三连被清掉并触发。
        hit: set[tuple[int, int]] = {cell for m in matches for cell in m.cells}
        triggered: set[tuple[int, int]] = set()
        frontier = {c for c in hit if special_kind(g[c[1]][c[0]])}
        while frontier:
            s = frontier.pop()
            if s in triggered:
                continue
            triggered.add(s)
            for cell in _blast(rows, cols, special_kind(g[s[1]][s[0]]), s):
                if cell not in hit:
                    hit.add(cell)
                    if special_kind(g[cell[1]][cell[0]]):
                        frontier.add(cell)

        # 3) 冰块碎裂 / 能量瓶掉一颗心（一次结算里同一瓶最多掉一颗）
        ice_hit: set[tuple[int, int]] = {c for c in hit if g[c[1]][c[0]] == C.ICE}
        bottles: set[tuple[int, int]] = {c for c in hit if is_bottle(g[c[1]][c[0]])}
        for (x, y) in hit:
            for nx, ny in _neighbors((x, y), rows, cols):
                t = g[ny][nx]
                if t == C.ICE:
                    ice_hit.add((nx, ny))
                elif is_bottle(t):
                    bottles.add((nx, ny))

        # 4) 计分
        color_cells = sum(1 for (x, y) in hit if base_color(g[y][x]))
        round_score = color_cells * w.per_tile
        for m in matches:
            round_score += max(0, len(m.cells) - 3) * w.length_bonus
            detail.append((m.color, len(m.cells)))
        total += round_score * (w.cascade_mult ** cascade)
        cleared_total += color_cells
        cascade += 1

        # 5) 执行消除。沙漏是目标棋子，爆炸波及也不消它，只认触底。
        for (x, y) in hit:
            if not is_hourglass(g[y][x]):
                g[y][x] = C.EMPTY
        for (x, y) in ice_hit:
            g[y][x] = C.EMPTY
        for (x, y) in bottles:
            left = bottle_hearts(g[y][x]) - 1
            if left <= 0:
                g[y][x] = C.EMPTY
                energy += C.BOTTLE_ENERGY
            else:
                g[y][x] = f"{C.BOTTLE}{left}"

        # 6) 放下新生成的特殊棋子
        for (x, y), kind in pending.items():
            g[y][x] = kind
            spawned.append(kind)

        g = collapse(g)
        g, d = _drop_bottom(g, rows, cols)
        dropped += d
        hg_after = _hourglass_rows(g)
        fallen += sum(max(0, hg_after.get(pos, rows - 1) - y)
                      for pos, y in hg_before.items())

    g, d = _drop_bottom(g, rows, cols)
    dropped += d

    return Resolution(score=total, cleared=cleared_total, cascades=cascade,
                      detail=detail, specials=spawned, energy=energy,
                      hourglasses=dropped, fallen=fallen, board=g)


# ---------------------------------------------------------------- 走法枚举

def _swappable(t: str) -> bool:
    return base_color(t) is not None or is_ultimate(t)


def legal_pairs(grid: list[list[str]]):
    rows, cols = len(grid), len(grid[0])
    pairs = []
    for r in range(rows):
        for c in range(cols):
            if not _swappable(grid[r][c]):
                continue
            for dc, dr in ((1, 0), (0, 1)):
                nc, nr = c + dc, r + dr
                if nc < cols and nr < rows and _swappable(grid[nr][nc]):
                    pairs.append(((c, r), (nc, nr)))
    return pairs


def _clear_ultimate_type(g, a, b) -> int:
    """终极棋子与普通棋子交换：清掉全盘该颜色。返回额外清除的颜色格数。"""
    for pos, other in ((a, b), (b, a)):
        if g[pos[1]][pos[0]] == C.ULT:
            color = base_color(g[other[1]][other[0]])
            if color is None:
                continue
            extra = 0
            for y, row in enumerate(g):
                for x, v in enumerate(row):
                    if base_color(v) == color:
                        g[y][x] = C.EMPTY
                        extra += 1
            return extra
    return 0


def evaluate(grid: list[list[str]], a: tuple[int, int],
             b: tuple[int, int]) -> Move | None:
    (c1, r1), (c2, r2) = a, b
    ta, tb = grid[r1][c1], grid[r2][c2]

    if is_ultimate(ta) or is_ultimate(tb):
        swapped = [row[:] for row in grid]
        swapped[r1][c1], swapped[r2][c2] = swapped[r2][c2], swapped[r1][c1]
        extra = _clear_ultimate_type(swapped, a, b)
        swapped[r1][c1] = C.EMPTY
        swapped[r2][c2] = C.EMPTY
        res = resolve(swapped, {a, b})
        return Move(a=a, b=b, score=res.score + extra * C.SCORE_WEIGHTS.per_tile,
                    cleared=res.cleared + extra, cascades=res.cascades + 1,
                    groups=res.detail, specials=res.specials, energy=res.energy,
                    hourglasses=res.hourglasses, fallen=res.fallen)

    g = [row[:] for row in grid]
    g[r1][c1], g[r2][c2] = tb, ta
    matches = find_matches(g)
    # 合法走法 = 产生的消除必须牵涉被交换的两格之一
    if not any(a in m.cells or b in m.cells for m in matches):
        return None

    res = resolve(g, {a, b})
    return Move(a=a, b=b, score=res.score, cleared=res.cleared,
                cascades=res.cascades, groups=res.detail,
                specials=res.specials, energy=res.energy,
                hourglasses=res.hourglasses, fallen=res.fallen)


def best_moves(grid: list[list[str]], top_n: int = 5) -> list[Move]:
    moves = [m for m in (evaluate(grid, a, b) for a, b in legal_pairs(grid)) if m]
    moves.sort(key=lambda m: (m.value, m.cleared), reverse=True)
    return moves[:top_n]


# ---------------------------------------------------------------- 显示

def render(grid: list[list[str]]) -> str:
    head = "    " + " ".join(f"c{c}" for c in range(len(grid[0])))
    lines = [head]
    for r, row in enumerate(grid):
        lines.append(f"r{r:>2}  " + "  ".join(row))
    return "\n".join(lines)
