"""运行时路径：源码运行和打包成 exe 后都能找到该写文件的地方。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "WuwaElim"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """可写目录：日志、截图等运行产物。

    exe 常常放在 Program Files 这种不可写的地方，所以统一写到
    %LOCALAPPDATA%\\WuwaElim；源码运行时也不污染仓库。
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = app_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resource_dir() -> Path:
    """只读资源目录。PyInstaller 单文件模式会解包到 sys._MEIPASS。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent


def new_log_path(prefix: str = "run") -> Path:
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return log_dir() / f"{prefix}-{stamp}.log"
