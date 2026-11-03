"""环境探测：窗口位置、显示器、DPI、抓一张图。

用法:  python -m wuwa_elim.tools.probe
"""

from __future__ import annotations

import json
import sys

import mss
from PIL import Image

from .. import capture, paths


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.make_dpi_aware()

    win = capture.find_window()
    if win is None:
        print(f"没找到标题为 {capture.GAME_TITLE!r} 的窗口。鸣潮开了吗？")
        return 2

    print("== 游戏窗口 ==")
    print("  " + json.dumps({
        "hwnd": win.hwnd, "pid": win.pid, "title": win.title,
        "rect": [win.left, win.top, win.right, win.bottom],
        "size": [win.width, win.height],
    }, ensure_ascii=False))

    with mss.MSS() as sct:
        print("\n== 显示器 ==")
        for i, mon in enumerate(sct.monitors):
            print(f"  monitor[{i}] left={mon['left']} top={mon['top']} "
                  f"{mon['width']}x{mon['height']} name={mon.get('name')!r}")

    img = capture.grab(win)
    out = paths.app_dir() / "probe-window.png"
    Image.fromarray(img).save(out)
    print(f"\n已保存 {out}  尺寸 {img.shape[1]}x{img.shape[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
