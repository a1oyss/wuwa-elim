"""构建身份：让每个 exe 都能说清自己是哪一次代码打的。

之前版本号一直是 1.0.0，代码改了一轮又一轮，产物名字、标题栏全都一样，
根本分不清手上这个是新版还是旧版。打包脚本会把版本 + git 短 SHA 写进
build-info.json 一起打进包里，这里负责读出来。
"""

from __future__ import annotations

import json

from . import __version__, paths


def build_info() -> dict:
    """打包时写进去的 build-info.json；源码运行没有这个文件。"""
    try:
        text = (paths.resource_dir() / "build-info.json").read_text("utf-8")
        return json.loads(text)
    except (OSError, ValueError):
        return {}


def describe() -> str:
    """一行能看懂的身份：1.1.0 · d16113a（未提交改动会带 -dirty）。"""
    info = build_info()
    commit = str(info.get("commit") or "")
    if not commit:
        return f"{__version__}（源码）"
    if info.get("dirty"):
        commit += "-dirty"
    built = str(info.get("built_at") or "")
    return f"{__version__} · {commit}" + (f" · {built}" if built else "")
