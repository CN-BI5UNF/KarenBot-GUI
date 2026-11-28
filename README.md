# KarenBot-GUI

KarenBot 的**原生 GTK4 / libadwaita 桌面控制台**模块。仓库已公开，当前版本 **v2.1.3-alpha**（KarenBot 统一发行版）。

> 这是模块源码仓库，不是完整的独立 KarenBot 应用。运行前需要 KarenBot 宿主和兼容的
> `KarenBot-backend`（v2.1.3-alpha）。

## 这是什么

`gui/` 使用原生 GTK4 控件，不使用浏览器、WebView 或 WebUI 静态页面。它通过进程内的
回环 HTTP 控制服务连接共享后端：

```text
GTK4 原生控件
  │  127.0.0.1 + 随机端口 + 随机 Bearer 令牌
  ▼
backend.app.create_control_app()
  ▼
KarenBot RuntimeHost / core.Runtime
```

模块包括：

- 主窗口、导航、主题与全屏控制：`app.py`
- 本机控制服务适配器：`local_server.py`
- 阻塞式 JSON 客户端：`api.py`
- GTK 通用控件：`widgets.py`
- 各页面：`pages/`（总览、对话、记忆、人格后台、日志、人格、黑话、知识、模型管理、
  表情包、容器、存储与数据、黑白名单、群聊触发、设置）
- WebUI 对齐样式：`style.css`
- 应用 ID 隔离：`identity.py`
- 前端插件清单：`plugin.json` + `plugin.py`，由 `main.py --frontend gui` 统一启动
- 更新页：优先显示 KarenBot 统一发行版，同时更新后端与当前前端
- 启动器渲染回退、字体与主题管理

## 兼容性

| 项目 | 版本 |
|---|---|
| 本模块 release | `v2.1.3-alpha`（统一发行版） |
| 配套后端 | `v2.1.3-alpha` |
| 配套 WebUI | `v2.1.3-alpha` |
| 过渡版 | 前端 `v0.1.1-alpha.2` / 后端 `v0.1.11-alpha.1` |

## 系统要求

- Linux（主要在 Armbian / Allwinner H618 aarch64 上开发和验证）
- Python 3.10+（推荐与宿主一致的 3.12）
- GTK4、libadwaita、PyGObject、Gdk 4
- 其余 Python 依赖由 KarenBot 宿主提供

Debian/Ubuntu/Armbian 系统包示例：

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

虚拟环境必须能看到系统 PyGObject，例如使用：

```bash
uv venv --python 3.12 --system-site-packages .venv
```

## 集成方式

把 `gui/` 放到 KarenBot 宿主项目根目录，并确保宿主已有 `backend/`：

```bash
cp -a /path/to/KarenBot-GUI/gui ./gui
cd /path/to/KarenBot
```

直接启动：

```bash
.venv/bin/python -m gui
# 或
.venv/bin/python -m gui --data-dir /path/to/data --theme dark
```

可选参数：

```text
--data-dir PATH   指定数据目录
--theme auto      跟随系统
--theme light     浅色
--theme dark      深色
```

如果宿主提供 `karen-gui` 入口，也可以使用该入口。不同 `--data-dir` 会生成不同的
GApplication ID，可并存运行；同一个数据目录同一时间只允许一个 GUI/Runtime。

首次向导默认暂不连接 QQ，可先在控制台试跑人格，再到「设置 → 渠道」启用 NapCat。
确认页支持直接修改模型、功能、记忆、渠道和人格；修改后可直接返回确认。
读取或提交失败时保留填写内容并提供重试；重新读取向导前会提示清空草稿。

设置页的开关和下拉选项立即保存，文本在回车或离开输入框时保存；多行文本和 JSON
也可点击保存或按 Ctrl+Enter。未保存或正在保存的内容会显示提示，刷新和离开页面时
会检查草稿；保存失败后可以继续修改并重试。
保存请求进行中会提示等待完成，再离开、刷新或放弃草稿；已发送的保存请求无法撤销。

## 备份与恢复

在「设置 → 备份」中选择配置、凭据、聊天、RAG、工作区、表情包、Provider 和人格等
备份类别。界面展示各类源数据大小估算及所选总量；任务进度中展示每类处理量与归档大小。
可以单独选择是否纳入入站媒体。

恢复前可深度校验备份，然后选择要恢复的类别，并预览每类备份大小、当前目标大小和文件
覆盖/新增/删除数量。输入确认短语“恢复备份”后启动一键恢复。服务会先创建恢复前回滚备份，
短暂停止 Runtime，再恢复选中类别并尝试重启。未选中的类别不变；所选类别按归档内容覆盖并
补齐，归档中不存在的当前文件保留。备份 ZIP 未加密，可能包含可用于恢复模型凭据的密钥材料，
请像密码一样保管。

## 数据与安全

- GUI 自己启动本机控制 API，只监听 `127.0.0.1`，端口和 Bearer 令牌每次进程随机生成。
- 不启动浏览器、不加载 WebUI 静态资源。
- 仓库不包含 `config.yaml`、`secrets.enc`、API Key、聊天记录、日志或数据目录。
- 不要提交私钥、密钥、`.env` 或运行时数据；`.gitignore` 已覆盖常见敏感文件。
- 危险数据操作（人格运行数据清理、卸载）需要服务端预览、确认短语和显式确认，不会静默执行。

## 已知边界

- 当前主要面向 Linux/X11；其它平台需要自行准备 GTK4 运行库。
- 更新页只展示版本与日志，不直接更新 GUI 开发树；源码更新请使用 git。
- 窄窗口响应式表格和角色形象拖拽上传仍在后续计划中。
- 冷启动会加载完整 KarenBot Runtime，ARM 设备上约需 20–30 秒。

## 版本与发布

- 版本标签格式：`vMAJOR.MINOR.PATCH[-dev]`
- 当前 `v2.1.3-alpha` 为 KarenBot 统一发行版；备份格式与恢复接口需使用兼容版本的 backend。
- 更新前可在「设置 → 备份」选择所需数据类别，创建后检查各类别大小和备份校验结果。
- Release 自动提供源码归档，并附带模块源码 zip。
- 与后端模块的兼容关系见上表。

## 许可证与来源

沿用 KarenBot 的 **Apache-2.0** 许可证，并保留上游 Debata_Agent 的版权声明，
详见 `LICENSE` 与 `NOTICE`。

相关仓库：

- [KarenBot-backend](https://github.com/CN-BI5UNF/KarenBot-backend)
- [KarenBot-WebUI](https://github.com/CN-BI5UNF/KarenBot-WebUI)
