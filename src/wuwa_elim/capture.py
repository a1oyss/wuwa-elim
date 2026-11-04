"""抓屏：定位游戏窗口，按物理像素抓取画面。

要点：进程必须先声明 DPI 感知，否则 150% 缩放下 GetWindowRect 给的是逻辑像素，
和真实屏幕像素差 1.5 倍，所有坐标都会整体偏移。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

import mss
import numpy as np

from .constants import GAME_TITLE

USER32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def make_dpi_aware() -> None:
    """声明按物理像素工作。-4 = PER_MONITOR_AWARE_V2。

    DPI 感知每个进程只能设置一次：第二次会失败并返回 ERROR_ACCESS_DENIED(5)，
    那是"已经设过了"，不是错误。
    """
    if USER32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        return
    if ctypes.get_last_error() == 5:
        return
    USER32.SetProcessDPIAware()


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def region(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top,
                "width": self.width, "height": self.height}


def find_window(title: str = GAME_TITLE) -> Window | None:
    buf = ctypes.create_unicode_buffer(512)
    found: list[Window] = []

    def cb(hwnd, _):
        if not USER32.IsWindowVisible(hwnd):
            return True
        if USER32.GetWindowTextW(hwnd, buf, 512) == 0:
            return True
        if buf.value.strip() != title:
            return True
        r = RECT()
        USER32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left < 400:
            return True
        pid = wt.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(Window(hwnd, pid.value, title,
                            r.left, r.top, r.right, r.bottom))
        return True

    USER32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


_SCT = None


def grab(win: Window, rect: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """返回 HxWx3 的 RGB numpy 数组。

    rect 是窗口内的 (left, top, width, height)；不传就抓整个窗口。
    棋盘只占整窗的一半左右，读盘时只抓棋盘区域能省掉一半的像素搬运。

    全程不经过 PIL：mss 给的是一块 BGRA 缓冲，直接 frombuffer 取视图再换通道，
    省掉一次解码 + 一次拷贝。
    """
    global _SCT
    if _SCT is None:
        _SCT = mss.MSS()

    if rect is None:
        region = win.region
    else:
        x, y, w, h = rect
        region = {"left": win.left + x, "top": win.top + y,
                  "width": w, "height": h}

    shot = _SCT.grab(region)
    arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
        shot.height, shot.width, 4)
    return np.ascontiguousarray(arr[:, :, [2, 1, 0]])


def monitors() -> list[dict]:
    """所有显示器。monitors[0] 是合并出来的虚拟桌面，从 [1] 开始才是真实屏幕。"""
    with mss.MSS() as sct:
        return [dict(m) for m in sct.monitors]
