# KarenBot GUI 后端适配与界面更新报告

- 报告日期：2026-11-20
- GUI 模块仓库：`/root/karenbot-mod-GUI`
- 当前分支：`feat/adapter-protocol-settings`
- 基线提交：`origin/fix/setup-ux-and-stability`（`39e82ac`）
- 目标后端：`/root/karenbot-mod-backend`（`v0.1.11-alpha`，`1.0.11-alpha`）
- 后端接口依据：
  - `docs/protocols/backend-api-report.md`
  - `docs/protocols/frontend-integration.md`

> 说明：GUI 模块仓库当前改动尚未提交，工作树保留在 `feat/adapter-protocol-settings` 分支上。

---

## 1. 摘要

本轮工作分为两部分：

1. **后端协议适配**：让 GUI 支持 `v0.1.11-alpha` 新增的渠道/协议接口，包括协议卡片、动态配置表单、完整适配器保存、密钥引用、能力表、字符串/负数 ID 等。
2. **界面与交互更新**：设置入口、设置全屏与返回、外观主题独立页、图标回退、键盘/滚轮焦点、容器页文案与网络设置收敛。

适配遵循「新接口优先、旧后端自动回退」原则：当后端没有 `/api/adapters/*` 时，GUI 继续使用原 `/api/settings` 字段编辑器，不会导致旧部署直接不可用。

---

## 2. 后端接口适配矩阵

| 接口 | GUI 使用位置 | 适配内容 |
| :--- | :--- | :--- |
| `GET /api/adapters/protocols` | 设置 → 渠道 | 渲染协议卡片；显示 stable/beta/planned；`planned` 禁止保存；读取 `config_schema.$defs` |
| `GET /api/adapters/config` | 设置 → 渠道 | 回填完整适配器配置；识别 `default` 适配器 key；切换协议时保留黑白名单 |
| `PUT /api/adapters/{name}` | 设置 → 渠道 | 整份保存动态表单；处理 `needs_restart`、`hot_applied`、`reload.errors`；保存后刷新状态 |
| `GET /api/adapters/status` | 设置 → 渠道 | 显示适配器连接状态、类型、传输、方言、地址、能力表；支持手动刷新 |
| `GET /api/settings` | 设置页 / 旧后端回退 | 读取分组字段、`secrets_index`、路径诊断；新协议字段不再重复渲染 |
| `PATCH /api/settings` | 旧后端回退 / 通用字段 | 兼容旧字段编辑；渠道字段优先走完整适配器保存 |
| `PUT /api/settings/secrets` | 设置 → 渠道 | 密钥选择/新建；保存后如被适配器引用会触发热重载 |
| `GET/PUT /api/settings/lists` | 主界面 → 黑白名单 | ID 统一字符串；支持 Telegram 负数群/频道 ID；`0` 丢弃 |
| `GET/PUT /api/settings/group-triggers` | 主界面 → 群聊触发 | `group_id` 支持负数；仍拒绝 `0` |
| `GET /api/status` | 顶栏 / 总览 | 展示 `adapter.type/transport/dialect`；旧后端回退 `mode://host:port` |
| `POST /api/chats/send` | GUI 当前未使用 | 无需前端改动 |

---

## 3. 渠道 / 协议设置

### 3.1 协议卡片

- 从 `GET /api/adapters/protocols` 动态生成，不在前端硬编码协议列表。
- 卡片显示协议名称、状态徽标（稳定 / Beta / 即将支持）、说明与支持的接入方式。
- `status: planned` 的卡片（如 QQ 官方 Bot、Satori）显示「即将支持」，按钮禁用，不允许保存。
- 切换协议时提示会整份替换 `default` 适配器配置，确认后才执行保存。

### 3.2 动态配置表单

- 根据协议 `config_model` 从 `config_schema.$defs` 取字段定义。
- 支持：
  - `bool` → 开关
  - `enum` → 下拉框（传输方式、方言、消息格式、解析模式等）
  - `integer` / `number` → 数字输入
  - `string` / nullable string → 文本框，空值按 `null` 处理
  - `array` → 逗号分隔列表（如 `allowed_updates`、`process_args`）
  - `*_id` / `*_secret_*` → 密钥引用选择器 + 新密钥保存
- `whitelist` / `blacklist` 不在表单中修改，保存时保留当前值；黑白名单仍由独立页面管理。
- `type` 固定为当前协议，不允许用户编辑。
- 字段说明复用后端 JSON Schema 的 `description`，并做长度裁剪。

### 3.3 密钥保存

- 已有密钥从 `/api/settings` 的 `secrets_index` 读取，可直接选择。
- 支持直接输入新密钥值并保存到 `PUT /api/settings/secrets`。
- 保存顺序符合后端文档：先保存密钥，再用 `PUT /api/adapters/{name}` 保存完整配置。
- 密钥字段只保存引用 ID，不把真实密钥写入 `config.yaml`。
- `Access Token` 字段增加详细中文说明：说明它是 NapCat / OneBot 协议端鉴权令牌、这里填密钥引用 ID 而不是 Token 本身，并给出「NapCat 配置 Token → 填写引用 ID → 保存密钥 → 保存渠道配置」的步骤，以及 Token 不一致导致 401/403、`ws_server` 非回环地址必须配置 Token 等提示。
- 首次配置向导的 NapCat 步骤同样提供 **Access Token（鉴权令牌）** 输入框，并说明填写后会写入加密密钥库、自动绑定渠道，配置完成即可使用，无需再到设置页补填。
- 密钥下拉只显示渠道相关密钥：包含当前适配器字段引用的 ID，以及名称含 `token` / `access` / `webhook` / `secret` / `telegram` / `bot` 的 ID；`deepseek_main_key`、`vision_key`、`tts_key` 等 Provider/功能密钥会被过滤，不再出现在 Access Token 菜单里。没有匹配项时提示可直接输入引用 ID 新建。

### 3.4 保存与热重载

- 保存前在 GUI 内校验数字/数组格式；后端返回 400 时展示 `detail`，保留表单内容。
- `needs_restart: true`：提示需要重启 Runtime，并显示页面顶部重启提示。
- `reload.errors`：逐条 toast 展示，便于排查。
- 保存后重新拉取 `/api/adapters/status`，刷新连接状态与能力表。

### 3.5 单适配器约束

- 当前只编辑已存在的 `default` 适配器，不提供多实例并行 UI。
- 符合后端报告中的「单主适配器」约束。

### 3.6 旧后端回退

- `GET /api/adapters/protocols` 或 `/config` 返回 404/405 时，自动回退到旧 `/api/settings` 字段编辑器。
- 回退模式显示提示：「当前后端未提供 /api/adapters 协议接口，已回退到旧字段编辑器」。
- 旧后端不会因为缺少新接口而崩溃。

---

## 4. 顶栏 / 总览 / 状态展示

- 顶栏渠道徽标改为 `type · transport · dialect` 组合，不再强行读取 OneBot 的 `mode/host/port`。
- 旧后端没有 `type/transport` 时，回退到 `mode://host:port`。
- 总览页的渠道卡片同步使用新状态字段；不再对 Telegram 显示不适用的 WS 地址。
- HTTP 传输会显示 Webhook 监听地址，而不是遗留的 WS host/port。
- 状态卡片展示能力表（图片、语音、视频、撤回、群管理等），用于前端判断可用功能。
- 适配器状态为 `null`、Runtime 未就绪或状态接口失败时，均有对应空态/错误提示。

---

## 5. 黑白名单与群聊触发

### 5.1 黑白名单

- ID 组件从「仅正整数」改为「字符串 ID」。
- 支持：
  - QQ 数字 ID
  - Telegram 用户 ID
  - Telegram 群/频道负数 ID（如 `-1001234567890`）
  - 未来非数字平台 ID
- `0` 会被丢弃，重复 ID 自动去重并排序。
- 提交到 `/api/settings/lists` 的 `qq_ids` / `group_ids` 均为字符串数组。
- 页面文案更新为「用户 ID / 群/频道 ID」，并说明 Telegram 负数规则。

### 5.2 群聊触发

- `group_id` 允许负数（Telegram 群/频道），仍拒绝 `0`。
- 提示文案与校验同步更新。

---

## 6. 设置入口与设置页布局

### 6.1 左下角齿轮入口

- 从侧栏导航中移除「设置」文字项。
- 侧栏底部新增纯齿轮图标按钮（`emblem-system-symbolic`），位于左下角。
- 展开/折叠侧栏时都保持可点击；打开设置时齿轮显示选中态。
- 点击齿轮进入专门的设置页；`Ctrl+,` 也可打开/退出设置。

### 6.2 设置全屏与返回

- 打开设置时隐藏侧栏，设置页铺满窗口，顶部栏保留。
- 设置页取消默认 1100px 限宽，分组导航与内容区可占满宽度。
- 左上角新增「← 返回」按钮。
- 返回方式：
  - 左上角返回按钮
  - `Esc`
  - `Alt+←`
  - 再次按 `Ctrl+,`
- 返回目标为进入设置前的页面；若无法确定则回退到总览。

### 6.3 外观主题独立页

- 移除设置页顶部常驻的「外观主题」大卡片，避免占用所有设置分组的空间。
- 在设置左侧分组列表新增「外观」分组（位于「日志与诊断」之后、「路径与诊断」之前）。
- 独立页采用紧凑布局：
  - 主题选择 + 刷新图标
  - 字体大小（80%–160%）+ 恢复 100%
  - 修改后立即生效
- 外观页最大宽度 820px，居中显示，不再让其他设置页被顶部卡片挤占。

### 6.4 容器网络设置收敛

- 设置 →「容器」中移除 `features.container.network`（网络）字段。
- 主界面「容器」页的「沙箱联网」开关保留，作为 GUI 中唯一的网络相关开关。
- 后端字段仍存在，但 GUI 设置页不再展示/修改它。

---

## 7. 图标与键盘交互修复

### 7.1 图标异常修复

问题原因：当前桌面图标主题缺少部分 Adwaita 图标名，GTK 显示破图/占位图。

修复：

| 位置 | 原图标 | 现图标 |
| :--- | :--- | :--- |
| 侧栏折叠/展开 | `sidebar-show-symbolic`（缺失） | `go-previous-symbolic` / `go-next-symbolic` |
| 黑话 | `chat-message-new-symbolic`（缺失） | `accessories-text-editor-symbolic`（带回退列表） |
| 总览 | `speedometer-symbolic`（缺失） | `view-app-grid-symbolic` |
| 对话页 | `chat-bubbles-symbolic`（缺失） | `mail-unread-symbolic` |

- 新增 `widgets.icon_image()`：按候选列表选择当前主题存在的图标，避免不同 Linux 主题下出现破图。
- 导航项通过 `NAV_ICON_FALLBACKS` 配置多个候选图标。

### 7.2 右侧内容焦点与 ↑/↓ 滚动

- 点击右侧非控件区域（标题、说明、卡片空白处）后，焦点从左侧列表移到右侧页面滚动区。
- 此时 `↑` / `↓` 与鼠标滚轮使用同一档位滚动右侧内容。
- 支持 `PageUp` / `PageDown` / `Home` / `End`。
- 点击真实控件（输入框、下拉框、开关、按钮）时，焦点保留在控件上，方向键操作控件本身。
- 点击左侧导航行时，焦点仍在左侧列表，`↑` / `↓` 继续移动左侧选择。
- 设置页左侧分组列表与右侧分组内容同样遵循该规则。
- 修复了 `Gtk.Widget.pick()` 缺少 `Gtk.PickFlags.DEFAULT` 导致点击处理抛异常的问题。

---

## 8. 容器页文案调整

| 原文案 | 新文案 |
| :--- | :--- |
| 命令执行 | Agent 工作方式 |
| 沙箱联网（bubblewrap，推荐） | 沙箱内运行（bubblewrap，推荐） |
| 本机 Claude Code 执行方式 | 本机 Agent 限制 |
| Agent 模式说明中的「本机固定使用 Claude Code。」 | 删除 |
| 保存提示「本机 Claude Code 执行方式已保存」 | 「本机 Agent 限制已保存」 |

「沙箱联网」开关名称保留不变。

---

## 9. 文件清单

| 文件 | 主要变更 |
| :--- | :--- |
| `gui/adapter_spec.py` | 新增：协议字段、枚举标签、表单值转换、保存载荷构造、状态摘要等纯数据辅助 |
| `gui/app.py` | 设置齿轮入口、设置全屏/返回、顶栏 type/transport/dialect、图标回退、错误态恢复 |
| `gui/widgets.py` | 字符串/负数 ChipList、`icon_image()`、`enable_scroll_focus()`、焦点辅助 |
| `gui/pages/base.py` | 页面点击焦点、设置分组滚动焦点、`Gtk.PickFlags` 修复 |
| `gui/pages/settings.py` | 渠道面板接入、外观独立页、容器网络字段隐藏、设置分组处理 |
| `gui/pages/settings_panels.py` | 新增 `AdapterSettingsPanel`：协议卡片、动态表单、密钥、保存/热重载 |
| `gui/pages/setup.py` | 首次配置向导的 Access Token（鉴权令牌）字段、占位提示与详细说明 |
| `gui/pages/overview.py` | 渠道状态新字段、地址与能力展示 |
| `gui/pages/access.py` | 黑白名单字符串/负数 ID 文案与交互 |
| `gui/pages/triggers.py` | 群 ID 负数支持、校验与文案 |
| `gui/pages/chats.py` | 对话页图标修正 |
| `gui/pages/slang.py` | 黑话页图标修正 |
| `gui/pages/container.py` | Agent 工作方式、本机 Agent 限制、沙箱内运行等文案 |
| `gui/style.css` | 设置齿轮、返回按钮、协议卡片样式 |
| `tests/test_gui_helpers.py`（主仓库） | 新增 4 项协议载荷、负数 ID、图标/摘要相关测试 |

---

## 10. 验证记录

### 10.1 静态检查

- `python3 -m compileall -q gui`：通过
- `ruff check`（E/F/W/I/B/UP，忽略 E501）：通过

### 10.2 测试

- 主仓库 `tests/test_gui_helpers.py`：**32 passed**
  - 包含新增的协议切换载荷、黑白名单负数 ID、状态摘要、值转换测试

### 10.3 无头 GTK 实机验证

使用 Xvfb + 真实 GTK 4.24.1 环境验证：

- NapCat 协议表单渲染
- Telegram 协议表单渲染
- 协议切换后保存载荷正确、黑白名单保留
- 密钥保存请求正确
- 旧后端 404 自动回退
- Runtime 未就绪错误态
- 完整主窗口 + 齿轮跳转
- 点击右侧内容后 `↑/↓` 滚动，左侧选择不变
- 设置页全屏 + 返回按钮

### 10.4 本机运行环境

- 系统 GTK：`4.8.3`（Debian 12 官方/backports 无更新）
- 独立 GTK 环境：`/opt/karenbot-gtk`，**GTK 4.24.1 + libadwaita 1.10.0 + PyGObject 3.58.1**
- GUI 启动方式：桌面快捷方式 `/root/桌面/KarenBot GUI.desktop`
- 启动脚本：`/root/karenbot-review/launch-gui.sh`
- 渲染器：`KAREN_GUI_RENDERER=cairo`（该 VNC/X 环境下 GTK 4.24 的 GL 路径会黑屏）
- 审查数据目录：`/root/karenbot-review-data`
- 审查环境当前适配器：本机 HTTP Webhook（不连接真实 QQ）
- 审查环境模型：本地 mock provider

---

## 11. 已知限制与注意事项

1. **远端部署仍是旧后端**
   - 远端 `~/tf/KarenBot-GUI` 与 `~/KarenBot` 实际后端仍是 `v0.1.3-alpha`，没有 `/api/adapters/*`。
   - GUI 会自动回退到旧字段编辑器；部署 `v0.1.11-alpha` 后端后新协议 UI 自动启用。

2. **容器网络字段**
   - 设置 → 容器已隐藏 `features.container.network`。
   - 主界面「沙箱联网」开关对应的是 `features.coding_agent.host.sandbox_network`（本机 Agent 沙箱联网）。
   - 如果希望 Docker 容器网络也跟随主界面开关，需要后端把两个配置项联动；当前 GUI 只做了入口收敛。

3. **fcitx 输入法**
   - 独立 GTK 4.24 环境缺少 fcitx5 的 GTK4 输入模块，日志会出现 `GTK_IM_MODULE=fcitx` 提示。
   - 如需在 GUI 内输入中文，需要补充 fcitx5 GTK4 前端模块。

4. **提交状态**
   - `/root/karenbot-mod-GUI` 工作树改动未提交，分支 `feat/adapter-protocol-settings`。
   - 远端旧 GUI 修改前备份：`/home/kickpi/tf/KarenBot-GUI/gui.bak-20261119-224934`。

---

## 12. 结论

GUI 已完成对 `v0.1.11-alpha` 后端协议接口的适配，并保留旧后端回退能力；同时完成了设置入口、设置全屏/返回、外观独立页、图标修复、键盘滚动、容器页文案与网络设置收敛等界面更新。

当前主要待办是：

1. 将 `v0.1.11-alpha` 后端部署到远端运行环境，使新协议 UI 在远端生效。
2. 根据审查意见决定是否提交/合并 `feat/adapter-protocol-settings` 分支。
3. 如需中文输入，补充 fcitx5 GTK4 输入模块。
