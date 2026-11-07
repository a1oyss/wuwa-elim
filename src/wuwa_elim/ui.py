"""图形界面：棋盘可视化、推荐走法、一键自动。"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from . import board, capture, constants as C, engine, mouse, paths, solver, version

CELL = 56
GAP = 3
PAD = 8

TILE_FILL = {
    "G": "#5C9770", "R": "#C0A6A6", "M": "#9D7A96", "D": "#C35A42",
    "L": "#89C3D6", "C": "#7DDDDE", "O": "#AC82B6", "u": "#D6A1C5",
    "H": "#D9B44A",
    "b": "#2E6B3E", "x": "#2E5E6B", "?": "#3A3540", ".": "#2A2530",
}
TILE_TEXT = {"?": "#FFFFFF", "u": "#5A2050", "H": "#4A3608"}


def fill_of(code: str) -> str:
    if code.startswith(C.BOTTLE):
        return TILE_FILL["O"]
    if len(code) == 2 and code[1] in C.SPECIALS:
        base = TILE_FILL.get(code[0], "#3A3540")
        return base
    return TILE_FILL.get(code, "#3A3540")


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.win: capture.Window | None = None
        self.grid: board.Grid | None = None
        self.cells: list[list[str]] | None = None
        self.moves: list[solver.Move] = []
        self.log_file = paths.new_log_path("ui")

        self._build()
        self._apply_icon()
        self.refresh_env()
        self._place_window()
        self._log(f"版本 {version.describe()}")
        self._write_file(f"界面就绪，日志 {self.log_file}")
        self.root.after(120, self._drain)

    def _apply_icon(self) -> None:
        """设置窗口图标。

        EXE 里嵌的图标只影响资源管理器和任务栏固定项；运行中的窗口默认还是
        Tk 的羽毛图标，必须在这里显式设一次，标题栏和任务栏才会跟着变。
        """
        base = Path(__file__).parent / "assets"
        ico = base / "app.ico"
        png = base / "icon-256.png"
        if ico.exists():
            try:
                self.root.iconbitmap(default=str(ico))
            except tk.TclError:
                pass
        if png.exists():
            try:
                self._icon_photo = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon_photo)
            except tk.TclError:
                pass

    def _move_to(self, x: int, y: int) -> None:
        """把窗口移到虚拟桌面的绝对坐标 (x, y)。

        不能用 Tk 的 geometry 拼负数：Tk 里 "-1040" 表示"距右边缘 1040 像素"，
        不是坐标 -1040。多屏时左侧副屏的 x 是负的，用 geometry 会跑到别的屏去。
        """
        self.root.update_idletasks()
        try:
            hwnd = int(self.root.frame(), 16)
        except (ValueError, tk.TclError):
            hwnd = int(self.root.winfo_id())
        SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, x, y, 0, 0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _place_window(self) -> None:
        """挑一块不和游戏重叠的显示器放窗口。

        给别人的机器用，不能假设布局：
          · 游戏可能是全屏，也可能是窗口模式（此时窗口矩形和任何显示器都不重合）
          · 副屏可能很小，放不下 1000x900
          · 多屏时坐标可能是负数
        所以按"矩形是否相交"来挑屏，并按屏幕尺寸收缩窗口。
        """
        pref_w, pref_h = 1000, 900
        game = self.win
        game_rect = ((game.left, game.top, game.right, game.bottom)
                     if game else None)

        def overlaps(m: dict, rect) -> bool:
            x0, y0, x1, y1 = rect
            return not (x1 <= m["left"] or x0 >= m["left"] + m["width"]
                        or y1 <= m["top"] or y0 >= m["top"] + m["height"])

        screens = capture.monitors()[1:]
        free = [m for m in screens
                if not (game_rect and overlaps(m, game_rect))]

        if free:
            m = max(free, key=lambda s: s["width"] * s["height"])
            w = max(760, min(pref_w, m["width"] - 40))
            h = max(640, min(pref_h, m["height"] - 40))
            x = m["left"] + (m["width"] - w) // 2
            y = m["top"] + (m["height"] - h) // 2
            self.root.minsize(min(820, w), min(720, h))
            self.root.geometry(f"{w}x{h}")
            self.root.attributes("-topmost", False)
            self._move_to(x, y)
            self._write_file(f"窗口放在 {m['width']}x{m['height']} 的屏幕上 "
                             f"@({x},{y}) {w}x{h}")
            return

        # 只剩游戏那一块屏：退回左上角，置顶但不压棋盘（棋盘从 x≈1700 开始）
        w = min(pref_w, max(760, screens[0]["width"] - 40)) if screens else pref_w
        h = min(pref_h, max(640, screens[0]["height"] - 60)) if screens else pref_h
        self.root.minsize(min(820, w), min(720, h))
        self.root.geometry(f"{w}x{h}")
        self.root.attributes("-topmost", True)
        self._move_to(16, 30)
        self._write_file(f"只有一块屏幕，窗口置顶 @(16,30) {w}x{h}")

    # ---------------------------------------------------------- 界面
    def _build(self) -> None:
        self.root.title(f"鸣潮·无音消除 助手  v{version.describe()}")
        self.root.geometry("1000x900+16+30")
        self.root.minsize(820, 720)

        # 快捷键：鼠标万一被全屏游戏抢走，键盘也能操作
        self.root.bind_all("<F5>", lambda _e: self.scan_once())
        self.root.bind_all("<F6>", lambda _e: self.start_auto())
        self.root.bind_all("<Escape>", lambda _e: self.stop())

        # 记录按钮点击：万一又"点了没反应"，日志能直接看出点击有没有到达
        self.root.bind_all("<Button-1>", self._on_click, add="+")

        top = ttk.Frame(self.root, padding=(12, 10))
        top.pack(fill="x")

        ttk.Button(top, text="日志", command=self._open_logs).pack(side="right")
        ttk.Button(top, text="重新检测", command=self.refresh_env).pack(
            side="right", padx=(0, 6))
        self.admin_btn = ttk.Button(top, text="以管理员身份重启",
                                    command=self._relaunch_admin)
        self.admin_btn.pack(side="right", padx=(0, 6))

        self.env_label = ttk.Label(top, text="正在检测…",
                                   font=("Microsoft YaHei UI", 10))
        self.env_label.pack(side="left")

        ttk.Label(self.root,
                  text="提示：把本窗口留在棋盘左侧，别盖住棋盘，否则会识别失败。",
                  foreground="#A0522D", padding=(12, 0, 12, 6)).pack(fill="x")

        body = ttk.Frame(self.root, padding=(12, 0))
        body.pack(fill="x")

        w = (C.CALIB_SHAPE[0] * (CELL + GAP)) + PAD * 2
        h = (C.CALIB_SHAPE[1] * (CELL + GAP)) + PAD * 2
        self.canvas = tk.Canvas(body, width=w, height=h, bg="#221E28",
                                highlightthickness=1,
                                highlightbackground="#4A4450")
        self.canvas.pack(side="left")

        side = ttk.Frame(body, padding=(12, 0, 0, 0))
        side.pack(side="left", fill="both", expand=True)
        ttk.Label(side, text="推荐走法",
                  font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.move_label = tk.Label(side, text="点「识别一次」开始。", justify="left",
                                   anchor="nw", wraplength=380,
                                   font=("Microsoft YaHei UI", 11), fg="#1F3A5F")
        self.move_label.pack(anchor="w", fill="x", pady=(4, 10))
        self.detail_label = ttk.Label(side, text="", foreground="#555",
                                      wraplength=380)
        self.detail_label.pack(anchor="w")

        btns = ttk.Frame(self.root, padding=(12, 10))
        btns.pack(fill="x")
        self.btn_scan = ttk.Button(btns, text="识别一次", command=self.scan_once)
        self.btn_scan.pack(side="left")
        self.btn_auto = ttk.Button(btns, text="开始自动", command=self.start_auto)
        self.btn_auto.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.stop,
                                   state="disabled")
        self.btn_stop.pack(side="left")
        self.state_label = ttk.Label(btns, text="空闲")
        self.state_label.pack(side="right")

        logf = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        logf.pack(fill="both", expand=True)
        self.log_box = scrolledtext.ScrolledText(
            logf, height=12, font=("Consolas", 9), state="disabled",
            bg="#1B1B1B", fg="#D8D8D8", insertbackground="#D8D8D8")
        self.log_box.pack(fill="both", expand=True)

    def _open_logs(self) -> None:
        try:
            os.startfile(paths.log_dir())            # noqa: S606
        except OSError as e:
            self._append_log(f"打不开日志目录：{e}")

    # ---------------------------------------------------------- 环境
    def refresh_env(self) -> None:
        capture.make_dpi_aware()
        self.win = capture.find_window()
        if self.win is None:
            self.env_label.config(text="✗ 没找到「鸣潮」窗口，请先打开游戏",
                                  foreground="#B00020")
            self.admin_btn.config(state="disabled")
            self.btn_auto.config(state="disabled")
            self.btn_scan.config(state="disabled")
            return

        elevated = mouse.self_elevated()
        size = f"{self.win.width}×{self.win.height}"
        if elevated:
            self.env_label.config(text=f"✓ {size}    ✓ 管理员权限",
                                  foreground="#1B6B32")
            self.admin_btn.config(state="disabled")
        else:
            self.env_label.config(text=f"✗ {size}    无管理员权限，点不动",
                                  foreground="#B00020")
            self.admin_btn.config(state="normal")

        self.btn_scan.config(state="normal")
        self.btn_auto.config(state="normal" if elevated else "disabled")

    def _relaunch_admin(self) -> None:
        if paths.is_frozen():
            exe, args = sys.executable, ""
        else:
            exe = sys.executable
            args = "-m wuwa_elim"
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, args, str(Path.cwd()), 1)
        except OSError as e:
            self._append_log(f"提权重启失败：{e}")
            return
        self.root.after(300, self.root.destroy)

    # ---------------------------------------------------------- 线程
    def _log(self, msg: str) -> None:
        self.q.put(("log", msg))

    def _busy(self, on: bool) -> None:
        """工作线程通过队列请求主线程切换忙碌状态（Tk 控件只能在主线程改）。"""
        self.q.put(("busy", on))

    def _start(self, target) -> None:
        if self.worker and self.worker.is_alive():
            self._log("还在跑，先点停止")
            return
        if self.win is None:
            self.refresh_env()
            if self.win is None:
                return
        self.stop_event.clear()

        def runner() -> None:
            # 线程里的异常不会打到界面上，必须在这里兜住并写进日志，
            # 否则表现就是"点了按钮完全没反应"。
            try:
                target()
            except mouse.AbortRequested:
                self._log("已中止")
            except Exception as e:           # noqa: BLE001
                self._log(f"工作线程异常：{e!r}")

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def scan_once(self) -> None:
        self._start(self._scan_worker)

    def start_auto(self) -> None:
        if not mouse.self_elevated():
            self._log("没有管理员权限，点了也没用。请用顶部按钮重启。")
            return
        self._start(self._auto_worker)

    def stop(self) -> None:
        self.stop_event.set()
        self._log("收到停止请求…")

    def _scan_worker(self) -> None:
        self._busy(True)
        try:
            self._log("正在识别棋盘…")
            _, grid, cells = engine.wait_settled(self.win, log=self._log)
            moves = solver.best_moves(cells, top_n=5)
            self.q.put(("board", grid, cells, moves))
            unknown = sum(r.count(C.WALL) for r in cells)
            self._log(f"识别完成：{grid.n_cols}×{grid.n_rows}，未识别 {unknown} 格，"
                      f"有效走法 {len(moves)} 个")
        except TimeoutError as e:
            self._log(f"识别失败：棋盘没稳定（{e}）")
        except mouse.AbortRequested:
            self._log("已中止")
        except Exception as e:                       # noqa: BLE001
            self._log(f"出错：{e!r}")
        finally:
            self._busy(False)

    def _auto_worker(self) -> None:
        self._busy(True)
        step = 0
        try:
            while not self.stop_event.is_set():
                step += 1
                self._log(f"—— 第 {step} 步 ——")
                try:
                    _, grid, cells = engine.wait_settled(self.win, log=self._log)
                except TimeoutError as e:
                    self._log(f"棋盘没稳定（{e}），1 秒后重试")
                    time.sleep(1.0)
                    continue

                moves = solver.best_moves(cells, top_n=1)
                self.q.put(("board", grid, cells, moves))
                if not moves:
                    self._log("没有有效走法，停止")
                    break

                mv = moves[0]
                ok = False
                for attempt in range(1, C.RETRIES + 2):
                    if self.stop_event.is_set():
                        break
                    if attempt > 1:
                        _, grid, cells = engine.wait_settled(
                            self.win, log=self._log)
                        again = solver.best_moves(cells, top_n=1)
                        if not again:
                            self._log("重算后没有有效走法，停止")
                            break
                        mv = again[0]
                        self.q.put(("board", grid, cells, again))

                    self._log(f"执行 {mv.label}"
                              + (f"（第 {attempt} 次）" if attempt > 1 else ""))
                    engine.perform(self.win, grid, mv, "drag")
                    if engine.wait_effect(self.win, cells):
                        ok = True
                        self._log("→ 动作生效")
                        break
                    self._log("→ 盘面几乎没变，重试")
                if not ok:
                    self._log("多次重试无效，停止")
                    break
        except mouse.AbortRequested:
            self._log("按了 F8，已中止")
        except Exception as e:                       # noqa: BLE001
            self._log(f"出错：{e!r}")
        finally:
            self._busy(False)
            self.q.put(("state", "空闲"))

    # ---------------------------------------------------------- 队列
    def _drain(self) -> None:
        # 无论处理过程中出什么问题，都必须重新挂上定时器，
        # 否则队列处理链一断，界面就变成"点什么都没反应"的死样子。
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                try:
                    if kind == "log":
                        self._append_log(msg[1])
                    elif kind == "board":
                        self._draw(*msg[1:])
                    elif kind == "busy":
                        self._set_busy(msg[1])
                    elif kind == "state":
                        self.state_label.config(text=msg[1])
                except Exception as e:       # noqa: BLE001
                    self._write_file(f"处理消息 {kind} 出错：{e!r}")
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._drain)

    def _on_click(self, ev) -> None:
        """把按钮点击记到日志文件。用于排查"点了没反应"。"""
        try:
            cls = ev.widget.winfo_class()
        except Exception:                    # noqa: BLE001
            cls = "?"
        if cls in ("TButton", "Button"):
            self._write_file(f"点击 {cls} @({ev.x_root},{ev.y_root})")

    def _write_file(self, text: str) -> None:
        try:
            with self.log_file.open("a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
        except OSError:
            pass

    def _append_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{stamp}] {text}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        self._write_file(text)

    def _set_busy(self, on: bool) -> None:
        self.state_label.config(text="运行中" if on else "空闲")
        self.btn_auto.config(state="disabled" if on else "normal")
        self.btn_scan.config(state="disabled" if on else "normal")
        self.btn_stop.config(state="normal" if on else "disabled")

    def _draw(self, grid, cells, moves) -> None:
        self.grid, self.cells, self.moves = grid, cells, moves
        self.canvas.delete("all")
        best = moves[0] if moves else None
        hot = {best.a, best.b} if best else set()

        for r, row in enumerate(cells):
            for c, code in enumerate(row):
                x0 = PAD + c * (CELL + GAP)
                y0 = PAD + r * (CELL + GAP)
                self.canvas.create_rectangle(
                    x0, y0, x0 + CELL, y0 + CELL, fill=fill_of(code),
                    outline="#FFFFFF" if (c, r) in hot else "#2E2836",
                    width=3 if (c, r) in hot else 1)
                self.canvas.create_text(
                    x0 + CELL / 2, y0 + CELL / 2, text=code,
                    fill=TILE_TEXT.get(code, "#FFFFFF" if (c, r) in hot else "#1A1A1A"),
                    font=("Consolas", 11 if len(code) > 1 else 16, "bold"))

        if not best:
            self.move_label.config(text="这个盘面没有可用走法。")
            self.detail_label.config(text="")
            return
        self.move_label.config(text=engine.instruction(best, cells))
        self.detail_label.config(text=engine.describe(best))


def run() -> None:
    capture.make_dpi_aware()
    root = tk.Tk()
    app = App(root)

    def report(exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            with paths.new_log_path("crash").open("w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass
        messagebox.showerror("出错了", f"{val}\n\n详细堆栈已写入日志目录。")

    root.report_callback_exception = report

    def on_close() -> None:
        app.stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    if "--scan" in sys.argv:
        root.after(600, app.scan_once)
    root.mainloop()
