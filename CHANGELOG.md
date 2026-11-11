# Changelog

## v0.0.1-dev — 2026-11-11

首个私有开发版。

- 从 KarenBot GUI 工程拆出原生 GTK4 前端模块 `gui/`。
- 通过共享 `backend.app.create_control_app()` 使用本机回环控制面。
- 包含全部控制台页面、设置热应用提示、聊天折叠、人格后台标签页、分步首次配置向导、
  日志环形缓冲和危险操作预览。
- 与 `KarenBot-backend`、`KarenBot-WebUI` 的 v0.0.1-dev 配套。
