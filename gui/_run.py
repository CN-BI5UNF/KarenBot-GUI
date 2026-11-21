"""由启动器调用的真实 GUI 入口；不要从这里再进入 launcher。"""

from __future__ import annotations


def _entry() -> int:
    # 子进程通常由 pythonw.exe 启动，标准流可能全是 None。必须在导入
    # gui.app（它会配置 logging）之前替换掉，否则第一个日志/print 就会
    # 让窗口无声消失。
    from .launcher import prepare_process

    prepare_process()
    from .app import main

    return main()


raise SystemExit(_entry())
