# KarenBot-GUI

KarenBot 的**原生 GTK4 / libadwaita 桌面控制台**模块。仓库已公开，当前版本 **v0.1.1-alpha**。

> 这是模块源码仓库，不是完整的独立 KarenBot 应用。运行前需要 KarenBot 宿主和兼容的
> `KarenBot-backend`（v0.1.1-alpha）。

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

## 兼容性

| 项目 | 版本 |
|---|---|
| 本模块 release | `v0.1.1-alpha`（预发布） |
| 配套后端 | `KarenBot-backend` `v0.1.1-alpha` |
| KarenBot 宿主 | `1.0.1-alpha.1` 拆分版本及后续兼容版本 |
| 配套 WebUI | `KarenBot-WebUI` `v0.1.1-alpha` |

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
- 当前 `v0.1.1-alpha` 为预发布开发版，界面与接口可能调整。
- Release 自动提供源码归档，并附带模块源码 zip。
- 与后端模块的兼容关系见上表。

## 许可证与来源

沿用 KarenBot 的 **Apache-2.0** 许可证，并保留上游 Debata_Agent 的版权声明，
详见 `LICENSE` 与 `NOTICE`。

相关仓库：

- [KarenBot-backend](https://github.com/CN-BI5UNF/KarenBot-backend)
- [KarenBot-WebUI](https://github.com/CN-BI5UNF/KarenBot-WebUI)
