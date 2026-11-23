# Changelog

## v2.1.0-alpha — 2026-11-23

- 修复 GUI 后端重启时重复进入启动器、Windows 子进程退出码和渲染参数残留问题；由外层启动器统一拉起新进程。
- 补齐页面加载失败卡片的 `dispose()` 与 `is_dirty()` 生命周期契约。
- 增加跨平台字体配置和启动器故障回退处理，覆盖审计回归场景。

## v2.0.1-alpha.1 — 2026-11-23

- 仅同步统一发行版版本号；本组件无代码变更。

## v2.0.1-alpha — 2026-11-22

- 「工具 schema 档位」从 设置 → 软件行为 移到 容器 → Agent 模式；保存后热重建工具注册表。

## v2.0.0-alpha.1 — 2026-11-21

更新页支持分开更新后端与当前前端。

- 统一发行版卡片提供「重新安装全部 / 重新安装后端 / 重新安装<前端>」或「更新到此版本 / 仅更新后端 / 仅更新<前端>」。
- 检查和应用更新时传递所选组件；只更新前端时不要求重启后端。
- 更新结果展示本次实际更新的组件。
- 修正发行版说明中「不能只更新其中一个组件」的旧文案。

## v2.0.0-alpha — 2026-11-21

首个 KarenBot 统一发行版。GUI、WebUI、后端版本均为 `2.0.0-alpha`；安装/更新入口为 `CN-BI5UNF/KarenBot` 主仓库。

- GUI 作为 KarenBot 主仓库的 `modules/KarenBot-GUI` submodule 维护。
- 更新页只读 KarenBot 统一发行版，后端与当前前端一起更新。
- 从 0.1.x 升级必须先安装过渡版 `v0.1.1-alpha.2`；旧 1.0.x 绑定版本不再支持。

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
