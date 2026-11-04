# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台、启动即请求管理员权限。

由 packaging/build.ps1 调用：
    py -3.14 -m PyInstaller --noconfirm --clean packaging/wuwa_elim.spec
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
SRC = ROOT / "src"
ICON = SPEC_DIR / "app.ico"
BUILD_INFO = SPEC_DIR / "build-info.json"      # 由 build.ps1 生成

datas = [(str(SRC / "wuwa_elim" / "assets"), "wuwa_elim/assets")]
# 构建身份（版本 + commit）：运行时靠它回答"这个 exe 到底是哪次代码"
if BUILD_INFO.exists():
    datas.append((str(BUILD_INFO), "."))

a = Analysis(
    # 必须用绝对导入的启动脚本当入口，不能直接拿 __main__.py：
    # PyInstaller 把入口当独立脚本分析，相对导入会解析失败，UI 整条依赖链都会丢。
    [str(SPEC_DIR / "launch.py")],
    pathex=[str(SRC)],
    binaries=[],
    # 运行时要读的图标（标题栏/任务栏），必须一起打进去
    datas=datas,
    hiddenimports=["tkinter", "_tkinter"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "pydoc_data"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="无音消除助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # 不弹黑窗口
    uac_admin=True,         # 双击即请求管理员权限（鸣潮是管理员进程）
    icon=str(ICON) if ICON.exists() else None,
)
