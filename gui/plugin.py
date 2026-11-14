"""GUI 前端插件入口。

只负责把统一入口的上下文转成 GUI launcher 的参数；真正的 GTK 子进程仍由
``gui.launcher`` 启动，保证渲染器环境变量在导入 ``gi`` 之前设置。
"""

from __future__ import annotations

from backend.plugin_host import FrontendPlugin, PluginContext


class GuiFrontendPlugin(FrontendPlugin):
    def run(self, context: PluginContext) -> int:
        from .launcher import main as launcher_main

        code = launcher_main(["karen-gui", *context.argv])
        return int(code or 0)


__all__ = ["GuiFrontendPlugin"]
