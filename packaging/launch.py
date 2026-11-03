"""打包专用入口。

不用 src/wuwa_elim/__main__.py 当入口：PyInstaller 会把入口脚本当独立脚本分析，
里面的相对导入 `from .ui import run` 解析不了，导致整个 UI 分支（含 tkinter）
都不会被打进包里。这里用绝对导入，分析器才能顺着找到。

用法由 packaging/wuwa_elim.spec 引用，不对外发布。
"""

from wuwa_elim.ui import run

if __name__ == "__main__":
    run()
