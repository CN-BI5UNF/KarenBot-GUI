# Changelog

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
