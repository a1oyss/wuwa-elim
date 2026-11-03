"""鼠标控制：SendInput 注入、前台切换、权限检查、光标还原。

鸣潮以管理员身份运行，Windows 的 UIPI 会静默丢弃低权限进程注入的鼠标事件，
所以调用前必须先确认权限（见 check_privilege）。
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import random
import time
from ctypes import wintypes

from .constants import PRE_DRAG_PAUSE

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_MENU = 0x12
VK_F8 = 0x77
SW_SHOW = 5
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


class AbortRequested(RuntimeError):
    pass


# ---------------------------------------------------------------- 光标

def cursor_pos() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor(x: int, y: int) -> bool:
    return bool(user32.SetCursorPos(int(x), int(y)))


@contextlib.contextmanager
def preserve_cursor():
    """用完把鼠标放回原处 —— 用户平时也要用鼠标。"""
    x, y = cursor_pos()
    try:
        yield (x, y)
    finally:
        set_cursor(x, y)


# ---------------------------------------------------------------- 注入

def _virtual_desk() -> tuple[int, int, int, int]:
    return (user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))


def _norm(abs_x: int, abs_y: int) -> tuple[int, int]:
    """物理像素 -> SendInput 要的 0..65535 归一化坐标（相对整个虚拟桌面）。"""
    vx, vy, vw, vh = _virtual_desk()
    nx = int(((abs_x - vx) * 65535) / max(vw - 1, 1))
    ny = int(((abs_y - vy) * 65535) / max(vh - 1, 1))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _send(x: int, y: int, flags: int) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(x, y, 0,
                        flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                        0, None)
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def _send_key(vk: int, flags: int) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def check_abort() -> None:
    if user32.GetAsyncKeyState(VK_F8) & 0x8000:
        raise AbortRequested("F8 被按下，已中止")


def human_pause(lo: float = 0.06, hi: float = 0.16) -> None:
    time.sleep(random.uniform(lo, hi))


def pre_drag_pause() -> None:
    lo, hi = PRE_DRAG_PAUSE
    time.sleep(random.uniform(lo, hi))


def move_to(abs_x: int, abs_y: int) -> None:
    nx, ny = _norm(abs_x, abs_y)
    _send(nx, ny, MOUSEEVENTF_MOVE)


def click(abs_x: int, abs_y: int) -> None:
    nx, ny = _norm(abs_x, abs_y)
    _send(nx, ny, MOUSEEVENTF_MOVE)
    human_pause()
    check_abort()
    _send(nx, ny, MOUSEEVENTF_LEFTDOWN)
    human_pause(0.04, 0.09)
    _send(nx, ny, MOUSEEVENTF_LEFTUP)


def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 8) -> None:
    """按住 A 拖到 B 再松开 —— 三消里交换相邻方块的手势。"""
    nx1, ny1 = _norm(x1, y1)
    nx2, ny2 = _norm(x2, y2)
    _send(nx1, ny1, MOUSEEVENTF_MOVE)
    human_pause()
    check_abort()
    _send(nx1, ny1, MOUSEEVENTF_LEFTDOWN)
    human_pause(0.03, 0.07)
    for i in range(1, steps + 1):
        t = i / steps
        check_abort()
        _send(int(nx1 + (nx2 - nx1) * t), int(ny1 + (ny2 - ny1) * t),
              MOUSEEVENTF_MOVE)
        human_pause(0.008, 0.02)
    _send(nx2, ny2, MOUSEEVENTF_LEFTUP)


# ---------------------------------------------------------------- 焦点与权限

def tap_alt() -> None:
    """Windows 有前台锁：后台进程调 SetForegroundWindow 会被静默忽略。
    模拟按一次 ALT 会让系统认为用户刚有输入，从而放行这次切换。"""
    _send_key(VK_MENU, KEYEVENTF_EXTENDEDKEY)
    _send_key(VK_MENU, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP)


def focus_window(hwnd: int) -> bool:
    """把窗口切到前台。虚幻引擎在失焦时完全不处理鼠标。"""
    if user32.GetForegroundWindow() == hwnd:
        return True

    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    my_tid = user32.GetWindowThreadProcessId(hwnd, None)

    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)

    if user32.GetForegroundWindow() != hwnd:
        tap_alt()
        user32.SetForegroundWindow(hwnd)

    if user32.GetForegroundWindow() != hwnd:
        user32.SwitchToThisWindow(hwnd, True)

    if user32.GetForegroundWindow() != hwnd and my_tid != cur_tid:
        if user32.AttachThreadInput(cur_tid, my_tid, True):
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(cur_tid, my_tid, False)

    return user32.GetForegroundWindow() == hwnd


def is_elevated(pid: int) -> bool | None:
    """进程是否以管理员身份运行。拿不到令牌时返回 None。"""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            value = wintypes.DWORD()
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(tok, TOKEN_ELEVATION,
                                         ctypes.byref(value),
                                         ctypes.sizeof(value),
                                         ctypes.byref(size))
            return bool(value.value)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def self_elevated() -> bool:
    return bool(is_elevated(os.getpid()))


def check_privilege(game_pid: int) -> str | None:
    """返回一句人话说明为什么不满足条件；没问题则返回 None。"""
    if os.name != "nt":
        return None
    mine = is_elevated(os.getpid())
    game = is_elevated(game_pid)
    if mine is None:
        return "读不到本进程的权限信息，无法确认能否点击。"
    if game is None:
        return None
    if game and not mine:
        return ("鸣潮以管理员身份运行，本程序不是。Windows 会静默丢弃注入给"
                "高权限窗口的输入，点击不会有任何反应。\n\n"
                "请右键程序 → 以管理员身份运行。")
    return None
