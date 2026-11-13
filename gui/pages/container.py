"""Docker container control, Agent modes and read-only file browsers."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from ..api import q  # noqa: E402
from .base import Page  # noqa: E402
from .container_files import WorkspaceBrowser  # noqa: E402


class ContainerPage(Page):
    refresh_on_activate = True
    page_id = "container"
    page_title = "受控容器"
    page_subtitle = (
        "Docker 容器只提供资源/文件隔离，不是对抗恶意代码的绝对安全边界。"
        "默认无网络、无特权、非 root、只挂载专用 workspace。首次使用直接点"
        "「一键准备 / 启动」；可在下方文件管理中只读浏览容器文件系统。"
        "这里的 /workspace 是容器存储，不是本机 AI 工作区。"
    )
    page_icon = "package-x-generic-symbolic"

    def build(self) -> None:
        self._status: dict[str, Any] = {}
        self._storage_payload: dict[str, Any] = {}
        self._agent_status: dict[str, Any] = {}
        self._refreshing = False
        self._agent_busy = False
        self._reset_busy = False
        self._host_saving = False
        self._agent_action_buttons: list[Gtk.Button] = []
        self._agents_seq = 0
        self._last_error: dict[str, Any] | None = None
        self._pending_storage_prompt = False
        self.body.append(self.header(refresh=False))
        self._build_actions()
        self.summary_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.summary_row.set_homogeneous(True)
        self.body.append(self.summary_row)
        self.problem_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.problem_box.append(widgets.muted("正在读取容器状态…"))
        self.body.append(self.problem_box)
        self._build_agent_card()
        self.file_browser = WorkspaceBrowser(self)
        self.body.append(self.file_browser)
        self.diagnostics_card = widgets.card(spacing=6)
        self.body.append(self.diagnostics_card)
        self.storage_card = widgets.card(spacing=6)
        self.body.append(self.storage_card)

    def _build_actions(self) -> None:
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.add_css_class("page-actions")
        self.refresh_button = widgets.button(
            "刷新", icon="view-refresh-symbolic"
        )
        self.refresh_button.connect("clicked", lambda _b: self.refresh())
        self.test_button = widgets.button(
            "一键准备 / 启动", css="suggested-action"
        )
        self.test_button.connect("clicked", lambda _b: self._test())
        self.setup_button = widgets.button(
            "初始化 C 存储", css="suggested-action"
        )
        self.setup_button.set_visible(False)
        self.setup_button.connect("clicked", lambda _b: self._open_storage_setup())
        self.reset_button = widgets.button(
            "重建容器", css="destructive-action"
        )
        self.reset_button.connect("clicked", lambda _b: self._reset())
        self.config_button = widgets.button("打开容器设置")
        self.config_button.connect(
            "clicked",
            lambda _b: self.app.show_page("settings", section="container"),
        )
        for widget in (
            self.refresh_button,
            self.test_button,
            self.setup_button,
            self.reset_button,
            self.config_button,
        ):
            actions.append(widget)
        self.body.append(actions)

    def _build_agent_card(self) -> None:
        self.agent_card = widgets.card(spacing=6)
        self.agent_card.append(widgets.label("Agent 模式", css="card-title"))
        self.agent_card.append(
            widgets.label(
                "仅向 KarenBot 的 LLM 提供 Pi / DSH / Claude Code 的工具语义，"
                "不启动它们的 TUI/GUI/WebUI。容器可安装多个模式，但同一时间"
                "只能激活一个；本机固定使用 Claude Code。",
                css="card-sub",
                wrap=True,
            )
        )
        self.agent_table_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0
        )
        self.agent_table_host.append(
            widgets.muted("正在读取 Agent 模式…")
        )
        self.agent_card.append(self.agent_table_host)
        self.agent_note = widgets.muted(
            "安装只写入 /workspace/.karen-agents，不会重建容器或删除 "
            "/workspace 文件。原生工具不需要外部 CLI 或额外依赖。建议在 "
            "设置 → 软件行为 → 工具 schema 档位 选择 agent。",
            wrap=True,
        )
        self.agent_note.set_margin_top(10)
        self.agent_card.append(self.agent_note)
        host_title = widgets.label(
            "本机 Claude Code 执行方式", css="section-title"
        )
        host_title.set_margin_top(14)
        self.agent_card.append(host_title)
        self.host_controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12
        )
        self.agent_card.append(self.host_controls)
        self.host_note = widgets.muted("", wrap=True)
        self.agent_card.append(self.host_note)
        self.agent_card.append(
            widgets.muted(
                "沙箱模式：只读系统目录 + workspace 可写，默认联网；host 模式："
                "命令直接以当前用户控制整台电脑。host 模式风险很高，只在明确"
                "需要时使用。",
                wrap=True,
            )
        )
        self.body.append(self.agent_card)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.api is None or self._refreshing:
            return
        self._refreshing = True
        self.refresh_button.set_sensitive(False)
        # Agent 模式接口依赖容器探测，可能比状态/存储慢；先并行发起，
        # 状态返回后立刻绘制上半页，不等待 Agent 表。
        self._refresh_agents()

        def _fetch() -> dict[str, Any]:
            from concurrent.futures import ThreadPoolExecutor

            api = self.api
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {
                    "status": pool.submit(
                        api.get, "/api/container/status", timeout=60
                    ),
                    "storage": pool.submit(
                        api.get, "/api/container/storage", timeout=30
                    ),
                }
                result: dict[str, Any] = {}
                for key, future in futures.items():
                    try:
                        result[key] = future.result()
                    except BaseException as exc:  # noqa: BLE001
                        result[key] = {"error": str(exc)}
            return result

        def _done(data: dict[str, Any]) -> None:
            self._refreshing = False
            self.refresh_button.set_sensitive(True)
            self._render_core(data)

        def _failed(exc: BaseException) -> None:
            self._refreshing = False
            self.refresh_button.set_sensitive(True)
            self._error(exc)

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def _refresh_agents(self) -> None:
        if self.api is None:
            return
        self._agents_seq += 1
        token = self._agents_seq

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/container/agents", timeout=60)

        def _done(data: dict[str, Any]) -> None:
            if token != self._agents_seq:
                return
            self._agent_status = data
            self._render_agents(data)

        def _failed(exc: BaseException) -> None:
            if token != self._agents_seq:
                return
            self._render_agents({"error": str(exc)})

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.summary_row)
        widgets.clear(self.problem_box)
        self.problem_box.append(widgets.muted(f"读取容器状态失败：{exc}"))
        # 状态读取失败时，Agent/诊断/存储区块的旧数据已经不可信，不能继续
        # 显示成可操作状态。
        for host in (
            getattr(self, "agent_table_host", None),
            getattr(self, "diagnostics_card", None),
            getattr(self, "storage_card", None),
        ):
            if host is None:
                continue
            widgets.clear(host)
            host.append(widgets.muted("容器状态不可用；恢复后重新读取。"))
        if hasattr(self, "file_browser"):
            self.file_browser.set_container_running(False)

    def _render_core(self, data: dict[str, Any]) -> None:
        status_payload = data.get("status") or {}
        if status_payload.get("error"):
            self._error(RuntimeError(status_payload["error"]))
            return
        info = status_payload.get("status") or status_payload
        if not isinstance(info, dict):
            info = {}
        self._status = info
        storage_payload = data.get("storage") or {}
        self._storage_payload = (
            {} if storage_payload.get("error") else storage_payload
        )
        docker = info.get("docker") or {}
        storage = info.get("storage") or {}
        box = info.get("container") or {}
        self._render_summary(info, docker, storage)
        self._render_problems(info, docker, storage)
        self._render_diagnostics(info, docker, storage)
        self._render_storage(storage)
        self._maybe_open_requested_storage_setup(storage)
        self.file_browser.set_container_running(box.get("state") == "running")

    # ------------------------------------------------------------------
    # Summary / problems
    # ------------------------------------------------------------------
    def _render_summary(
        self,
        info: dict[str, Any],
        docker: dict[str, Any],
        storage: dict[str, Any],
    ) -> None:
        widgets.clear(self.summary_row)
        for label_text, text, tone in (
            (
                "功能",
                "已启用" if info.get("enabled") else "未启用",
                "badge badge-ok" if info.get("enabled") else "badge",
            ),
            (
                "就绪",
                "可用" if info.get("ready") else "未就绪",
                "badge badge-ok" if info.get("ready") else "badge badge-warn",
            ),
            (
                "Docker",
                "可用" if docker.get("available") else "不可用",
                "badge badge-ok" if docker.get("available") else "badge badge-bad",
            ),
            (
                "存储",
                "C 固定大小"
                if storage.get("mode") == "image_fixed"
                else "B 软配额",
                "badge badge-ok" if storage.get("ready") else "badge badge-bad",
            ),
        ):
            tile = widgets.card(spacing=5, padding=10)
            tile.set_hexpand(True)
            tile.append(widgets.label(label_text, css="stat-label"))
            tile.append(widgets.badge(text, css=tone))
            self.summary_row.append(tile)

    def _render_problems(
        self,
        info: dict[str, Any],
        docker: dict[str, Any],
        storage: dict[str, Any],
    ) -> None:
        widgets.clear(self.problem_box)
        mismatch = (
            storage.get("code") == "container_storage_size_mismatch"
            and storage.get("marker_size_mb")
        )
        buttons: list[Gtk.Widget] = []
        message = ""
        title = "需要处理"
        description = "先修复下面这一项，再点「一键准备 / 启动」。"
        setup_visible = False
        setup_label = (
            "重新挂载 C 存储"
            if storage.get("code") == "container_storage_not_mounted"
            else "初始化 C 存储"
        )
        if mismatch:
            size = int(storage.get("marker_size_mb") or 0)
            message = str(
                storage.get("error")
                or f"存储镜像实际为 {size} MiB，与当前配置不一致。"
            )
            adopt = widgets.button(
                f"采用 {size} MiB", css="suggested-action"
            )
            adopt.connect("clicked", lambda _b, value=size: self._adopt_size(value))
            buttons.append(adopt)
            buttons.append(self._settings_button("修改存储设置"))
            restart = widgets.button("重启 Runtime")
            restart.connect(
                "clicked", lambda b: self._restart_runtime(b)
            )
            buttons.append(restart)
        elif not info.get("enabled"):
            message = "容器功能未启用。请到设置 → 容器启用并重启 Runtime。"
            buttons.append(self._settings_button("打开容器设置"))
        elif not docker.get("available"):
            message = str(
                docker.get("error")
                or "Docker 不可用；请先安装并启动 Docker Engine / Docker Desktop。"
            )
        elif not info.get("image_present"):
            message = (
                f"镜像 {info.get('image') or ''} 缺失。点「一键准备 / 启动」"
                "会自动拉取；如果 Docker Hub 不通，可在设置 → 容器填写"
                "「Docker 镜像加速前缀」。"
            )
            buttons.append(self._settings_button("配置镜像加速"))
        elif storage.get("mode") == "image_fixed" and not storage.get("ready"):
            message = str(storage.get("error") or "C 固定大小存储尚未初始化。")
            setup = self._storage_payload.get("setup") or {}
            admin = self._storage_payload.get("admin") or {}
            setup_visible = bool(admin.get("available", True))
            setup_label = (
                "重新挂载 C 存储"
                if storage.get("code") == "container_storage_not_mounted"
                else "初始化 C 存储"
            )
            if admin.get("available", True):
                buttons.append(
                    self._button_action(
                        setup_label,
                        self._open_storage_setup,
                        css="suggested-action",
                    )
                )
            elif setup.get("command"):
                message += "\n请以管理员身份手动运行安装命令（见下方存储信息）。"
        elif self._last_error:
            message = str(self._last_error.get("message") or "容器准备失败")
            tail = str(self._last_error.get("tail") or "")
            if tail:
                message += "\n\n" + tail
            if not info.get("image_present"):
                buttons.append(self._settings_button("配置镜像加速"))
        elif info.get("config_warning"):
            title = "配置提示"
            description = "当前容器可以继续使用；设置只影响显式重建。"
            warning = info.get("config_warning") or {}
            message = str(warning.get("message") or "容器创建后设置发生变化。")
            buttons.append(self._settings_button("查看容器设置"))
        self.setup_button.set_visible(setup_visible)
        if setup_visible:
            self.setup_button.set_label(setup_label)
        if not message:
            return
        card = widgets.card(spacing=6)
        card.append(widgets.label(title, css="card-title"))
        card.append(widgets.muted(description))
        card.append(widgets.label(message, wrap=True))
        if buttons:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            for button in buttons:
                row.append(button)
            card.append(row)
        self.problem_box.append(card)

    def _button_action(
        self, text: str, callback: Any, *, css: str = ""
    ) -> Gtk.Button:
        button = widgets.button(text, css=css)
        button.connect("clicked", lambda _b: callback())
        return button

    def _settings_button(self, text: str) -> Gtk.Button:
        button = widgets.button(text)
        button.connect(
            "clicked",
            lambda _b: self.app.show_page("settings", section="container"),
        )
        return button

    # ------------------------------------------------------------------
    # Agent card
    # ------------------------------------------------------------------
    def _render_agents(self, data: dict[str, Any]) -> None:
        widgets.clear(self.agent_table_host)
        if data.get("error"):
            self.agent_table_host.append(
                widgets.muted(f"读取 Agent 模式失败：{data['error']}")
            )
            widgets.clear(self.host_controls)
            return
        modes = data.get("agents") or []
        self._agent_action_buttons = []
        rows: list[list[Any]] = []
        for agent in modes:
            mode = str(agent.get("id") or "")
            label_text = str(agent.get("label") or mode)
            installed = bool(agent.get("installed"))
            active = bool(agent.get("active"))
            version = str(agent.get("version") or "")
            head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            head.append(widgets.label(label_text, css="table-name"))
            description = str(agent.get("description") or "")
            if description:
                head.append(widgets.label(description, css="field-help", wrap=True))
            status_badge = widgets.badge(
                "使用中" if active else ("已安装" if installed else "未安装"),
                css=(
                    "badge badge-ok"
                    if active
                    else ("badge" if installed else "badge badge-warn")
                ),
            )
            version_text = (
                f"已安装{f' · {version}' if version else ''}"
                if installed
                else "未安装"
            )
            dependencies = agent.get("dependencies") or []
            dependency_text = (
                "、".join(str(item) for item in dependencies)
                if dependencies
                else "内置回退"
            )
            actions = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=4
            )
            install = widgets.button(
                "重装" if installed else "安装", css="compact-button"
            )
            install.set_sensitive(not self._agent_busy)
            install.connect(
                "clicked", lambda _b, m=mode: self._agent_action("install", m)
            )
            actions.append(install)
            self._agent_action_buttons.append(install)
            activate = widgets.button(
                "当前使用" if active else "激活",
                css="compact-button" + (" suggested-action" if not active else ""),
            )
            activate.set_sensitive(
                not self._agent_busy and installed and not active
            )
            activate.connect(
                "clicked", lambda _b, m=mode: self._agent_action("activate", m)
            )
            actions.append(activate)
            self._agent_action_buttons.append(activate)
            deactivate = widgets.button("停用", css="compact-button")
            deactivate.set_sensitive(not self._agent_busy and active)
            deactivate.connect(
                "clicked", lambda _b: self._agent_action("deactivate", "")
            )
            actions.append(deactivate)
            self._agent_action_buttons.append(deactivate)
            uninstall = widgets.button(
                "卸载", css="compact-button destructive-action"
            )
            uninstall.set_sensitive(
                not self._agent_busy and installed and not active
            )
            uninstall.connect(
                "clicked", lambda _b, m=mode: self._confirm_uninstall(m)
            )
            actions.append(uninstall)
            self._agent_action_buttons.append(uninstall)
            rows.append(
                [
                    head,
                    status_badge,
                    version_text,
                    dependency_text,
                    actions,
                ]
            )
        self.agent_table_host.append(
            widgets.table(
                ["模式", "状态", "版本", "依赖", "操作"],
                rows,
                weights=[3.2, 1.1, 1.6, 1.7, 3.2],
                empty_text="正在读取 Agent 模式…" if not modes else "暂无 Agent 模式",
            )
        )
        # ``host`` 是执行策略，``host_runtime`` 是 rg/bubblewrap 探测结果；
        # 后者才包含 rg_available/rg_path。
        host_view = {
            **(data.get("host_runtime") or {}),
            **(data.get("host") or {}),
        }
        self._render_host(host_view)

    def _set_agent_buttons(self, enabled: bool) -> None:
        for button in self._agent_action_buttons:
            button.set_sensitive(enabled and not self._agent_busy)

    def _render_host(self, host: dict[str, Any]) -> None:
        widgets.clear(self.host_controls)
        mode = str(host.get("execution_mode") or "sandbox")
        self.host_mode = widgets.dropdown(
            [
                ("sandbox", "沙箱联网（bubblewrap，推荐）"),
                ("host", "直接控制整台电脑（高风险）"),
            ],
            mode,
        )
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        mode_box.append(widgets.label("命令执行", css="field-label"))
        mode_box.append(self.host_mode)
        self.host_controls.append(mode_box)
        network_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4
        )
        network_box.append(widgets.label("沙箱联网", css="field-label"))
        self.sandbox_network = Gtk.Switch()
        self.sandbox_network.set_active(
            bool(host.get("sandbox_network", True))
        )
        self.sandbox_network.set_halign(Gtk.Align.START)
        network_box.append(self.sandbox_network)
        self.host_controls.append(network_box)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.host_controls.append(spacer)
        save = widgets.button("保存本机设置")
        save.connect("clicked", lambda _b: self._save_host())
        self.host_save_button = save
        self.host_controls.append(save)
        if host:
            self.host_note.set_text(
                f"rg: {'可用' if host.get('rg_available') else '不可用'}"
                f" · {host.get('rg_path') or ''}"
            )
        else:
            self.host_note.set_text("")

    def _agent_action(self, action: str, mode: str) -> None:
        if self.api is None or self._agent_busy:
            return
        if action == "install":
            path = f"/api/container/agents/{q(mode)}/install"
            method = "post"
            label = "安装完成"
        elif action == "activate":
            path = f"/api/container/agents/{q(mode)}/activate"
            method = "post"
            label = "已激活"
        elif action == "uninstall":
            path = f"/api/container/agents/{q(mode)}"
            method = "delete"
            label = "已卸载"
        else:
            path = "/api/container/agents/deactivate"
            method = "post"
            label = "已停用"
        self._agent_busy = True
        # Buttons were rendered while idle. Disable all of them now so a
        # second click does not look like a silent no-op.
        self._set_agent_buttons(False)

        def _do() -> Any:
            if method == "delete":
                return self.api.delete(path, timeout=120)
            return self.api.post(path, {}, timeout=180)

        def _done(_result: Any) -> None:
            self._agent_busy = False
            self.toast(label)
            self.refresh()

        def _failed(exc: BaseException) -> None:
            self._agent_busy = False
            self.toast(f"操作失败：{exc}")
            self.refresh()

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _confirm_uninstall(self, mode: str) -> None:
        widgets.ConfirmDialog(
            self.app.window,
            heading=f"卸载 {mode} 的容器运行时？",
            body="只删除该 Agent 模式的文件，不会删除 /workspace 数据。",
            confirm_label="卸载",
            destructive=True,
            on_confirm=lambda: self._agent_action("uninstall", mode),
        )

    def _save_host(self) -> None:
        if self.api is None or self._host_saving:
            return
        payload = {
            "execution_mode": widgets.dropdown_value(self.host_mode),
            "sandbox_network": self.sandbox_network.get_active(),
        }
        self._host_saving = True
        if getattr(self, "host_save_button", None) is not None:
            self.host_save_button.set_sensitive(False)

        def _do() -> Any:
            return self.api.patch("/api/container/agents/host", payload, timeout=60)

        def _done(_result: Any) -> None:
            self._host_saving = False
            self.toast("本机 Claude Code 执行方式已保存")
            self.refresh()

        def _failed(exc: BaseException) -> None:
            self._host_saving = False
            if getattr(self, "host_save_button", None) is not None:
                self.host_save_button.set_sensitive(True)
            self.toast(f"保存失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    # ------------------------------------------------------------------
    # Diagnostics / storage
    # ------------------------------------------------------------------
    def _render_diagnostics(
        self,
        info: dict[str, Any],
        docker: dict[str, Any],
        storage: dict[str, Any],
    ) -> None:
        widgets.clear(self.diagnostics_card)
        self.diagnostics_card.append(widgets.label("运行诊断", css="card-title"))
        limits = info.get("limits") or {}
        box = info.get("container") or {}
        values = [
            (
                "Docker Server",
                str(docker.get("server_version") or docker.get("error") or "—"),
            ),
            (
                "镜像",
                f"{info.get('image') or '—'} "
                f"({'已存在' if info.get('image_present') else '缺失'})",
            ),
            ("容器名", str(info.get("container_name") or "—")),
            ("容器状态", str(box.get("state") or "—")),
            (
                "内存 / CPU",
                f"{limits.get('memory_mb', '—')} MiB / {limits.get('cpus', '—')}",
            ),
            (
                "pids / 单文件",
                f"{limits.get('pids_limit', '—')} / "
                f"{limits.get('file_size_mb', '—')} MiB",
            ),
            ("网络", str(limits.get("network") or "—")),
            ("exec 超时", f"{limits.get('exec_timeout_seconds', '—')} 秒"),
            ("存储就绪", "是" if storage.get("ready") else str(storage.get("error") or "否")),
            (
                "存储大小",
                f"{storage.get('size_mb', '—')} MiB"
                + (
                    ""
                    if storage.get("mode") == "image_fixed"
                    else " 软配额"
                ),
            ),
            (
                "镜像实际大小",
                (
                    f"{storage.get('marker_size_mb')} MiB"
                    if storage.get("marker_size_mb") is not None
                    else "—"
                ),
            ),
            (
                "剩余空间",
                (
                    widgets.format_bytes(storage.get("free_bytes"))
                    if storage.get("free_bytes") is not None
                    else "—"
                ),
            ),
            ("平台", str(info.get("platform") or "—")),
        ]
        self.diagnostics_card.append(
            widgets.table(
                ["项目", "值"],
                [[name, value] for name, value in values],
                weights=[1.6, 4.4],
            )
        )

    def _render_storage(self, storage: dict[str, Any]) -> None:
        widgets.clear(self.storage_card)
        setup = self._storage_payload.get("setup") or {}
        admin = self._storage_payload.get("admin") or {}
        merged = dict(storage)
        if isinstance(self._storage_payload.get("storage"), dict):
            for key, value in self._storage_payload["storage"].items():
                if merged.get(key) in (None, "", 0, False):
                    merged[key] = value
        storage = merged
        self.storage_card.append(
            widgets.label("存储与安装", css="card-title")
        )
        self.storage_card.append(
            widgets.label(
                admin.get("note")
                or setup.get("note")
                or "B 模式使用 Docker 命名卷；C 模式需要一次性管理员初始化。",
                css="card-sub",
                wrap=True,
            )
        )
        rows: list[list[str]] = []
        if storage.get("mountpoint"):
            rows.append(["挂载点", str(storage.get("mountpoint"))])
        if storage.get("image_path"):
            rows.append(["镜像文件", str(storage.get("image_path"))])
        method = str(admin.get("method") or "")
        if method:
            rows.append(
                [
                    "初始化方式",
                    (
                        "Windows UAC 管理员确认"
                        if method == "uac"
                        else (
                            "sudo 密码（仅本次）"
                            if method == "sudo_password"
                            else "手动命令"
                        )
                    ),
                ]
            )
        if setup.get("command"):
            rows.append(["安装命令", str(setup.get("command"))])
        self.storage_card.append(
            widgets.table(
                ["项目", "值"],
                rows,
                weights=[1.5, 4.5],
                empty_text="暂无存储路径信息",
            )
        )
        if storage.get("error"):
            self.storage_card.append(
                widgets.label(
                    str(storage["error"]), css="danger-text", wrap=True
                )
            )
        if storage.get("mode") != "image_fixed":
            self.storage_card.append(
                widgets.muted(
                    "B 模式使用 Docker 命名卷软配额，无需管理员初始化。"
                )
            )

    # ------------------------------------------------------------------
    # Container actions
    # ------------------------------------------------------------------
    def _test(self) -> None:
        if self.api is None:
            return
        self._last_error = None
        self.toast("正在准备容器；首次可能需要下载镜像，请稍候")
        self.test_button.set_sensitive(False)
        self.test_button.set_label("准备中…")

        def _do() -> dict[str, Any]:
            return self.api.post("/api/container/test", {}, timeout=600)

        def _done(result: dict[str, Any]) -> None:
            self.test_button.set_sensitive(True)
            self.test_button.set_label("一键准备 / 启动")
            inner = result.get("result") or {}
            if result.get("ok"):
                self._last_error = None
                self.toast("容器已启动并通过测试")
            else:
                message = "容器测试未通过"
                if inner.get("timed_out"):
                    message += "（执行超时）"
                elif inner.get("exit_code") is not None:
                    message += f"（退出码 {inner.get('exit_code')}）"
                self._last_error = {
                    "message": message,
                    "tail": _result_output_tail(inner),
                }
                self.toast(message)
            self.refresh()

        def _failed(exc: BaseException) -> None:
            self.test_button.set_sensitive(True)
            self.test_button.set_label("一键准备 / 启动")
            self._last_error = {
                "message": f"容器准备失败：{exc}",
                "tail": _container_error_tail(exc),
            }
            self.toast(f"容器准备失败：{exc}")
            self.refresh()

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _reset(self) -> None:
        if self._reset_busy:
            return
        self._reset_busy = True
        self.reset_button.set_sensitive(False)

        def _cancel() -> None:
            self._reset_busy = False
            self.reset_button.set_sensitive(True)

        def _reset_now() -> None:
            if self.api is None:
                _cancel()
                return

            def _do() -> Any:
                return self.api.post("/api/container/reset", {}, timeout=180)

            def _done(_result: Any) -> None:
                self._reset_busy = False
                self.reset_button.set_sensitive(True)
                self._last_error = None
                self.toast("容器已重建")
                self.file_browser.reset()
                self.refresh()

            def _failed(exc: BaseException) -> None:
                self._reset_busy = False
                self.reset_button.set_sensitive(True)
                self.toast(f"重建失败：{exc}")

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        widgets.ConfirmDialog(
            self.app.window,
            heading="只重建容器，不删除持久 workspace。确定继续？",
            body="容器层会被重建；/workspace 持久数据会保留。",
            confirm_label="重建",
            destructive=True,
            on_confirm=_reset_now,
            on_cancel=_cancel,
        )

    def _adopt_size(self, size: int) -> None:
        if size <= 0 or self.api is None:
            return

        def _apply() -> None:
            def _do() -> dict[str, Any]:
                return self.api.patch(
                    "/api/settings",
                    {"path": "features.container.workspace_size_mb", "value": size},
                    timeout=60,
                )

            def _done(_result: dict[str, Any]) -> None:
                self._last_error = None
                self.toast(f"已采用 {size} MiB；需要重启 Runtime 生效")
                self.refresh()
                widgets.ConfirmDialog(
                    self.app.window,
                    heading="存储大小已更新",
                    body="需要重启 Runtime 才能使用新的存储大小。现在重启？",
                    confirm_label="重启 Runtime",
                    on_confirm=self._do_restart_runtime,
                )

            widgets.run_async(
                _do,
                on_success=_done,
                on_error=lambda exc: self.toast(f"修改存储大小失败：{exc}"),
            )

        widgets.ConfirmDialog(
            self.app.window,
            heading=f"把存储大小改为 {size} MiB？",
            body="这是已有镜像的实际大小；修改后需要重启 Runtime。",
            confirm_label="采用",
            on_confirm=_apply,
        )

    def _restart_runtime(self, button: Gtk.Button | None = None) -> None:
        if self.api is None:
            return
        widgets.ConfirmDialog(
            self.app.window,
            heading="重启 Runtime？",
            body="正在进行的请求会被中断，通常需要几秒到一分钟。"
            "这只是重建运行时，不会加载新的 Python 代码。",
            confirm_label="重启 Runtime",
            destructive=True,
            on_confirm=lambda: self._do_restart_runtime(button),
        )

    def _do_restart_runtime(
        self, button: Gtk.Button | None = None
    ) -> None:
        if self.api is None:
            return
        if button is not None:
            button.set_sensitive(False)

        def _do() -> Any:
            return self.api.post("/api/system/restart", {}, timeout=180)

        def _done(_result: Any) -> None:
            self._last_error = None
            self.toast("Runtime 已重启")
            self.refresh()

        def _failed(exc: BaseException) -> None:
            if button is not None:
                button.set_sensitive(True)
            self.toast(f"重启失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    # ------------------------------------------------------------------
    # C storage setup
    # ------------------------------------------------------------------
    def prompt_storage_setup(self) -> None:
        """Refresh and, if C storage is unready, open the setup dialog.

        Called by the settings page after enabling the container or switching
        to ``image_fixed``; the save itself only writes config.
        """
        self._pending_storage_prompt = True
        if self._refreshing:
            return
        self.refresh()

    def _maybe_open_requested_storage_setup(
        self, storage: dict[str, Any]
    ) -> None:
        if not self._pending_storage_prompt:
            return
        self._pending_storage_prompt = False
        merged = dict(storage or {})
        payload_storage = self._storage_payload.get("storage")
        if isinstance(payload_storage, dict):
            for key, value in payload_storage.items():
                if merged.get(key) in (None, "", 0, False):
                    merged[key] = value
        mode = str(merged.get("mode") or "")
        if mode != "image_fixed":
            self.toast(
                "当前运行中的存储仍是 B 命名卷；如刚修改了容器设置，"
                "请先重启 Runtime，再初始化 C 存储。"
            )
            return
        if merged.get("ready"):
            self.toast("C 固定大小存储已经就绪")
            return
        if merged.get("code") == "container_storage_size_mismatch":
            self.toast(
                "C 存储的实际大小与配置不一致，请先在问题卡片里"
                "「采用实际大小」。"
            )
            return
        admin = self._storage_payload.get("admin") or {}
        if not admin.get("available", True):
            self.toast(
                "没有可用的 sudo/PowerShell 提权方式；"
                "请到容器页查看手动初始化命令。"
            )
            return
        self._open_storage_setup()

    def _open_storage_setup(self) -> None:
        payload = self._storage_payload
        if not payload:
            self.toast("正在读取存储初始化信息…")

            def _fetch() -> dict[str, Any]:
                return self.api.get("/api/container/storage", timeout=60)

            def _loaded(data: dict[str, Any]) -> None:
                self._storage_payload = data
                self._open_storage_setup()

            widgets.run_async(
                _fetch,
                on_success=_loaded,
                on_error=lambda exc: self.toast(f"读取失败：{exc}"),
            )
            return
        storage = payload.get("storage") or {}
        setup = payload.get("setup") or {}
        admin = payload.get("admin") or {}
        method = str(admin.get("method") or "manual")
        remount = storage.get("code") == "container_storage_not_mounted"

        window = Gtk.Window()
        window.set_title(
            "重新挂载 C 固定大小存储" if remount else "初始化 C 固定大小存储"
        )
        window.set_default_size(680, 560)
        window.set_transient_for(self.app.window)
        window.set_modal(True)
        window.set_titlebar(Adw.HeaderBar())
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(16)
        body.set_margin_bottom(16)
        body.set_margin_start(18)
        body.set_margin_end(18)
        body.append(
            widgets.muted(
                "挂载已有 ext4 镜像；不会格式化、重建或删除已有数据。"
                if remount
                else "一次性操作；只创建/挂载固定的 workspace 文件系统，"
                "不删除已有数据。"
            )
        )
        body.append(
            widgets.muted(
                admin.get("note")
                or "C 模式需要一次性管理员初始化；应用不会静默降级到 B。"
            )
        )
        rows = [
            [
                name,
                (
                    "C 固定大小"
                    if name == "模式"
                    else f"{storage.get('size_mb', '—')} MiB"
                    if name == "大小"
                    else str(value or "—")
                ),
            ]
            for name, value in (
                ("模式", storage.get("mode")),
                ("大小", storage.get("size_mb")),
                ("挂载点", storage.get("mountpoint")),
                ("镜像文件", storage.get("image_path")),
            )
        ]
        body.append(
            widgets.table(["项目", "值"], rows, weights=[1.4, 4.6])
        )
        password_entry: Gtk.Entry | None = None
        if method == "sudo_password":
            body.append(
                widgets.muted(
                    "密码只用于本次 sudo -S，不保存、不写日志，也不会出现在"
                    "命令行参数中。"
                )
            )
            password_entry = Gtk.Entry()
            password_entry.set_visibility(False)
            password_entry.set_placeholder_text("当前用户的 sudo 密码")
            body.append(widgets.label("sudo 密码", css="field-label"))
            body.append(password_entry)
        elif method == "uac":
            body.append(
                widgets.muted(
                    "点击初始化后，Windows 会弹出 UAC 管理员确认；这里不需要"
                    "输入密码。"
                )
            )
        else:
            body.append(
                widgets.muted(
                    "没有找到可用的 sudo/UAC 提权方式。请复制下方命令以管理员"
                    "身份手动执行。"
                )
            )
        if setup.get("command") and not admin.get("available"):
            command = widgets.label(str(setup["command"]), wrap=True, selectable=True)
            command.add_css_class("monospace")
            body.append(command)
        status = widgets.muted("")
        body.append(status)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        cancel = widgets.button("取消")
        cancel.connect("clicked", lambda _b: window.close())
        submit = widgets.button(
            "重新挂载" if remount else "初始化存储", css="suggested-action"
        )
        submit.set_sensitive(bool(admin.get("available", False)))
        if not admin.get("available", False):
            submit.set_tooltip_text("当前没有可用的提权方式")
        actions.append(cancel)
        actions.append(submit)
        body.append(actions)
        window.set_child(body)

        def _clear_password(*_args: Any) -> bool:
            if password_entry is not None:
                password_entry.set_text("")
            return False

        window.connect("close-request", _clear_password)
        window.present()
        if password_entry is not None:
            password_entry.grab_focus()

        def _do_setup() -> None:
            if self.api is None:
                return
            password = (
                password_entry.get_text() if password_entry is not None else None
            )
            if method == "sudo_password" and not password:
                status.set_text("请输入 sudo 密码。")
                return
            submit.set_sensitive(False)
            submit.set_label(
                "等待 UAC 确认…" if method == "uac" else "正在初始化…"
            )
            status.set_text(
                "已请求管理员权限；请在弹出的 UAC 窗口确认。"
                if method == "uac"
                else "正在通过 sudo 执行固定安装脚本…"
            )
            payload_body = {"password": password} if password is not None else {}

            def _do() -> dict[str, Any]:
                return self.api.post(
                    "/api/container/storage/setup", payload_body, timeout=600
                )

            def _done(result: dict[str, Any]) -> None:
                if password_entry is not None:
                    password_entry.set_text("")
                self._last_error = None
                window.close()
                self.toast(
                    "存储已经就绪"
                    if result.get("already_ready")
                    else "C 存储已初始化"
                )
                self.refresh()

            def _failed(exc: BaseException) -> None:
                if password_entry is not None:
                    password_entry.set_text("")
                message = f"初始化失败：{exc}"
                tail = _container_error_tail(exc)
                if tail:
                    message += "\n\n" + tail
                status.set_text(message)
                submit.set_label("重试")
                submit.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        submit.connect("clicked", lambda _b: _do_setup())



def _result_output_tail(result: dict[str, Any]) -> str:
    parts = []
    for key in ("stderr", "stdout", "output_tail"):
        text = str(result.get(key) or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)[-2000:]


def _container_error_tail(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    if not isinstance(detail, dict):
        return ""
    details = detail.get("details")
    tail = ""
    if isinstance(details, dict):
        tail = str(details.get("output_tail") or "")
    if not tail:
        tail = str(detail.get("output_tail") or "")
    return tail.strip()[-2000:]
