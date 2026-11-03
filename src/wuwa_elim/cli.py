"""命令行入口：打印推荐走法，或自动执行。"""

from __future__ import annotations

import argparse
import sys

from . import board, capture, constants as C, engine, mouse, paths, solver


class Tee:
    """把输出同时写到控制台和文件。"""

    def __init__(self, path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("w", encoding="utf-8")

    def write(self, s: str) -> None:
        self.fh.write(s)
        self.fh.flush()
        try:
            sys.__stdout__.write(s)
            sys.__stdout__.flush()
        except Exception:                    # noqa: BLE001
            pass

    def flush(self) -> None:
        self.fh.flush()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wuwa-elim",
        description="鸣潮·无音消除 助手（命令行版）。不给 --run 时只提示不动手。")
    ap.add_argument("--run", action="store_true", help="真的执行走法")
    ap.add_argument("--loop", type=int, default=1, help="连续执行多少步")
    ap.add_argument("--top", type=int, default=5, help="打印前几个候选")
    ap.add_argument("--mode", choices=["drag", "click"], default="drag")
    ap.add_argument("--timeout", type=float, default=C.SETTLE_TIMEOUT,
                    help="等棋盘稳定的最长秒数")
    ap.add_argument("--retries", type=int, default=C.RETRIES,
                    help="点击没生效时重试几次")
    ap.add_argument("--log", default="", help="把输出同时写到文件")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.log:
        sys.stdout = Tee(paths.app_dir() / args.log)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    win = engine.open_session()
    if win is None:
        print("没找到标题为「鸣潮」的窗口。游戏开了吗？")
        return 2
    print(f"窗口 hwnd={win.hwnd} pid={win.pid} "
          f"{win.left},{win.top} {win.width}x{win.height}")

    dry = not args.run
    print("模式:", "提示（不碰鼠标）" if dry else "拖拽执行   按 F8 随时中止")
    if not dry:
        problem = mouse.check_privilege(win.pid)
        if problem:
            print(problem)
            return 3
        print(f"鼠标原位置 {mouse.cursor_pos()}，每步结束都会放回去\n")

    for step in range(1, args.loop + 1):
        print(f"\n########## 第 {step}/{args.loop} 步 ##########")
        try:
            _, grid, cells = engine.wait_settled(win, args.timeout)
        except TimeoutError as e:
            print(f"棋盘一直没稳定：{e}。停止。")
            break

        print(solver.render(cells))
        moves = solver.best_moves(cells, top_n=args.top)
        if not moves:
            print("没有有效走法。可能已经死局，或规则还有没建模的情况。")
            break

        print(f"\n推荐（前 {len(moves)}）:")
        for i, mv in enumerate(moves, 1):
            sx1, sy1 = grid.to_screen(*mv.a, win.left, win.top)
            sx2, sy2 = grid.to_screen(*mv.b, win.left, win.top)
            print(f"  {i}. {engine.describe(mv)}")
            print(f"     {engine.instruction(mv, cells)}")
            print(f"     屏幕坐标 A=({sx1},{sy1})  B=({sx2},{sy2})")

        if dry:
            print("\n提示模式结束。加 --run 才会真的拖。")
            return 0

        try:
            if not engine.play_step(win, print, args.retries, args.mode):
                break
        except mouse.AbortRequested:
            print("F8 中止")
            return 0

    print("\n结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
