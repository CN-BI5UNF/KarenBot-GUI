# Changelog

## v0.1.1-alpha.2 — 2026-11-21

过渡版本：GUI 模块 `0.1.1-alpha.2`，应用代码 `1.0.1-alpha.2`。更新页已适配 KarenBot 统一发行版；请更新后端与本前端后，手动选择 `v2.0.0-alpha`。

- 更新页在 `distribution=true` 时显示单一「KarenBot 发行版」列表；任何版本都会同时更新后端与当前前端，旧后端自动回退双组件列表。
- 修复 pythonw 下启动器 `sys.stderr is None` 崩溃、子进程输出重定向与失败弹窗；关闭时后台停止 Runtime，避免 GTK 主线程卡死。
- 设置页新增「外部程序」：随 KarenBot 启动多个自定义程序，支持端口探测、自动重启、环境变量/工作目录和「随 KarenBot 关闭」；保存后热应用，启动失败按 `failure_seq` 只弹一次聚合提醒。
- 移除旧 NapCat 专用 `manage_process` 设置，旧配置由后端自动迁移到外部程序列表。

## v0.1.1-alpha.1 — 2026-11-15

- 与 `KarenBot-backend`、`KarenBot-WebUI` 的 v0.1.1-alpha.1 配套。
- GUI 注册为前端插件：`gui/plugin.json` + `gui/plugin.py`，支持 `python main.py --frontend gui` 统一入口。
- 更新页把“后端更新”和“GUI 前端更新”拆成独立区块，分别展示版本、状态和 Release 列表。
- 新增启动器渲染回退（`gui/launcher.py`）、字体/fontconfig、主题管理；设置页增加外观主题。
- 聊天页支持分页、附件图片预览/大图、文件默认应用打开或定位目录。
- 附件原文件被存储清理后显示清理原因，不再退回 workspace 裸路径；本地图片预览和文件打开/定位逻辑保持不变。
- 同步最新页面修复与设置兼容性改动。

## v0.1.1-alpha — 2026-11-13

首个公开发布版本。

- 与 `KarenBot-backend`、`KarenBot-GUI`、`KarenBot-WebUI` 的 v0.1.1-alpha 配套。
- 后端新增分模块更新器：同时检查 backend 与前端仓库，Latest 自动提示，Pre-release 仅允许手动选择并强制警告。
- 修复设置、聊天、容器、存储与人格页面的多处数据覆盖、竞态和交互问题。
- GUI 与 WebUI 的更新页支持组件化版本、Pre-release 标识和按组件重启提示。

## v0.0.1-dev — 2026-11-11

首个私有开发版。

- 从 KarenBot GUI 工程拆出原生 GTK4 前端模块 `gui/`。
- 通过共享 `backend.app.create_control_app()` 使用本机回环控制面。
- 包含全部控制台页面、设置热应用提示、聊天折叠、人格后台标签页、分步首次配置向导、
  日志环形缓冲和危险操作预览。
- 与 `KarenBot-backend`、`KarenBot-WebUI` 的 v0.0.1-dev 配套。
