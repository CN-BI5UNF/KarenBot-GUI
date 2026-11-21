from __future__ import annotations

import sys
import traceback


def _entry() -> int:
    from .launcher import main

    return main(sys.argv)


try:
    raise SystemExit(_entry())
except SystemExit:
    raise
except BaseException:  # noqa: BLE001 - pythonw has nowhere else to report
    detail = "未捕获的启动异常：\n\n" + traceback.format_exc()
    try:
        from .launcher import prepare_process, report_fatal

        prepare_process()
        report_fatal("KarenBot GUI 启动失败", detail)
    except Exception:  # noqa: BLE001, S110 - launcher import itself failed
        if sys.platform.startswith("win"):
            # 连 launcher 都导入失败时，直接用最小化的 Win32 弹窗，
            # 避免 pythonw 下再次静默退出。
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(
                    None, detail, "KarenBot GUI 启动失败", 0x10
                )
            except Exception:  # noqa: BLE001, S110
                pass
    raise SystemExit(1)
