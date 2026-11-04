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

# ---------------------------------------------------------------- GDI 常驻抓图
#
# mss 每次调用都会重建 DC 和位图，实测 36ms；把这几样资源建一次反复用，
# 同一区域只要 17ms。棋盘几何不变，所以资源可以一直复用。

_GDI32 = ctypes.WinDLL("gdi32", use_last_error=True)
_USER32 = ctypes.WinDLL("user32", use_last_error=True)

SRCCOPY = 0x00CC0020


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


_USER32.GetDC.argtypes = [wt.HWND]
_USER32.GetDC.restype = wt.HDC
_GDI32.CreateCompatibleDC.argtypes = [wt.HDC]
_GDI32.CreateCompatibleDC.restype = wt.HDC
_GDI32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
_GDI32.CreateCompatibleBitmap.restype = wt.HBITMAP
_GDI32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
_GDI32.SelectObject.restype = wt.HGDIOBJ
_GDI32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int,
                          wt.DWORD]
_GDI32.BitBlt.restype = wt.BOOL
_GDI32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(_BITMAPINFO), wt.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                    wt.DWORD]
_GDI32.CreateDIBSection.restype = wt.HBITMAP
_GDI32.DeleteObject.argtypes = [wt.HGDIOBJ]
_GDI32.DeleteDC.argtypes = [wt.HDC]
_USER32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]


class _GdiCapturer:
    """常驻的屏幕抓取器：尺寸不变时复用 DC 和位图。

    用 CreateDIBSection 而不是"兼容位图 + GetDIBits"：后者要求位图**没有**被
    选进 DC，而 BitBlt 又必须选进去，属于自相矛盾的用法，实测会偶发失败。
    DIB section 直接给出内存指针，BitBlt 完就能读，还省掉一次拷贝。
    """

    def __init__(self) -> None:
        self._screen = None
        self._mem = None
        self._bmp = None
        self._arr = None
        self.size: tuple[int, int] | None = None

    def reset(self) -> None:
        """显示状态变化（分辨率、锁屏、独占全屏）后 DC 会失效，丢弃重建。"""
        if self._bmp:
            _GDI32.DeleteObject(self._bmp)
        if self._mem:
            _GDI32.DeleteDC(self._mem)
        if self._screen:
            _USER32.ReleaseDC(None, self._screen)
        self._screen = self._mem = self._bmp = self._arr = None
        self.size = None

    def _setup(self, w: int, h: int) -> None:
        self.reset()
        self._screen = _USER32.GetDC(None)
        self._mem = _GDI32.CreateCompatibleDC(self._screen)

        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = w
        info.bmiHeader.biHeight = -h          # 负数 = 自上而下
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0      # BI_RGB

        bits = ctypes.c_void_p()
        self._bmp = _GDI32.CreateDIBSection(
            self._screen, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not self._bmp or not bits.value:
            raise OSError(ctypes.get_last_error(), "CreateDIBSection 失败")
        _GDI32.SelectObject(self._mem, self._bmp)

        buf = (ctypes.c_ubyte * (w * h * 4)).from_address(bits.value)
        self._arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        self.size = (w, h)

    def grab(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        if self.size != (w, h):
            self._setup(w, h)
        if not _GDI32.BitBlt(self._mem, 0, 0, w, h, self._screen, x, y, SRCCOPY):
            raise OSError(ctypes.get_last_error(), "BitBlt 失败")
        return np.ascontiguousarray(self._arr[:, :, [2, 1, 0]])


_CAPTURER = _GdiCapturer()


def grab(win: Window, rect: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """返回 HxWx3 的 RGB numpy 数组。

    rect 是窗口内的 (left, top, width, height)；不传就抓整个窗口。
    棋盘只占整窗的一半左右，读盘时只抓棋盘区域能省掉一半的像素搬运。

    优先用常驻 GDI（约 17ms）。GDI 失败先重建资源重试一次（分辨率变化、锁屏
    之后 DC 会失效），仍失败才退回 mss（约 36ms）。
    """
    global _SCT

    if rect is None:
        x, y, w, h = 0, 0, win.width, win.height
    else:
        x, y, w, h = rect

    for attempt in range(2):
        try:
            return _CAPTURER.grab(win.left + x, win.top + y, w, h)
        except OSError:
            _CAPTURER.reset()          # 丢掉可能失效的 DC，下次重建
            if attempt:
                break

    if _SCT is None:
        _SCT = mss.MSS()
    try:
        shot = _SCT.grab({"left": win.left + x, "top": win.top + y,
                          "width": w, "height": h})
    except Exception as exc:           # noqa: BLE001
        _SCT = None
        raise RuntimeError(
            f"抓屏失败（{exc}）。常见原因：屏幕已锁定、UAC 授权弹窗正在显示、"
            f"或游戏切到了独占全屏。") from exc

    arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
        shot.height, shot.width, 4)
    return np.ascontiguousarray(arr[:, :, [2, 1, 0]])


# ---------------------------------------------------------------- 遮挡检查

GA_ROOT = 2
_USER32.WindowFromPoint.argtypes = [wt.POINT]
_USER32.WindowFromPoint.restype = wt.HWND
_USER32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
_USER32.GetAncestor.restype = wt.HWND


def board_covered(win: Window, rect: tuple[int, int, int, int]) -> bool:
    """采样棋盘内的几个点，判断上面盖的是不是别的窗口。

    游戏被切到后台、或者有别的窗口压上来时，抓到的会是那些窗口的像素 ——
    分类器照样能"认出"一堆棋子，喂给引擎就是纯粹的垃圾。这里先挡掉。
    """
    x0, y0, w, h = rect
    for fx, fy in ((0.5, 0.5), (0.25, 0.35), (0.75, 0.65)):
        px = win.left + x0 + int(w * fx)
        py = win.top + y0 + int(h * fy)
        hwnd = _USER32.WindowFromPoint(wt.POINT(px, py))
        root = _USER32.GetAncestor(hwnd, GA_ROOT) or hwnd
        if root != win.hwnd:
            return True
    return False


def monitors() -> list[dict]:
    """所有显示器。monitors[0] 是合并出来的虚拟桌面，从 [1] 开始才是真实屏幕。"""
    with mss.MSS() as sct:
        return [dict(m) for m in sct.monitors]
