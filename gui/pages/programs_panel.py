"""设置 → 外部程序：批量编辑随 KarenBot 启动的程序。"""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import quote

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import widgets  # noqa: E402

_PROGRAM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_STATE_LABELS = {
    "running": ("运行中", "badge badge-green"),
    "starting": ("启动中", "badge badge-idle"),
    "restarting": ("重启中", "badge badge-orange"),
    "external": ("外部已运行", "badge badge-idle"),
    "failed": ("启动失败", "badge badge-red"),
    "exited": ("已退出", "badge badge-idle"),
    "disabled": ("已禁用", "badge badge-idle"),
    "launcher_exited": ("启动器已退出", "badge badge-orange"),
    "stopping": ("停止中", "badge badge-orange"),
    "stopped": ("未运行", "badge badge-idle"),
}


def _empty(message: str) -> Gtk.Label:
    return widgets.label(message, css="empty-state", wrap=True)


def _spacer() -> Gtk.Box:
    spacer = Gtk.Box()
    spacer.set_hexpand(True)
    return spacer


def _field(label_text: str, control: Gtk.Widget, help_text: str = "") -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(widgets.label(label_text, css="field-label"))
    if help_text:
        box.append(widgets.muted(help_text))
    box.append(control)
    return box


def _switch_row(text: str, active: bool) -> tuple[Gtk.Box, Gtk.Switch]:
    control = widgets.switch(active)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.append(control)
    row.append(widgets.label(text))
    return row, control


def _parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"环境变量第 {line_no} 行缺少 '='：{line}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"环境变量第 {line_no} 行缺少变量名")
        env[key] = value.strip()
    return env


def _env_text(env: dict[str, Any] | None) -> str:
    return "\n".join(f"{key}={value}" for key, value in (env or {}).items())


class ProgramsSettingsPanel(Gtk.Box):
    """Repeatable cards for user-defined external programs."""

    def __init__(self, page: Any, group: dict[str, Any] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.page = page
        self.group = group or {}
        self.dirty = False
        self._loaded = False
        self._loading = False
        self._saving = False
        self._rows: list[dict[str, Any]] = []
        self._status_by_id: dict[str, dict[str, Any]] = {}
        self._action_inflight = False
        self._build_chrome()
        self._load()

    @property
    def api(self) -> Any:
        return self.page.api

    # ------------------------------------------------------------------
    # Static chrome
    # ------------------------------------------------------------------
    def _build_chrome(self) -> None:
        info = widgets.card(spacing=6, padding=14)
        info.append(
            widgets.muted(
                "程序以 KarenBot 的用户权限运行；参数不经过 shell，不支持管道和"
                "重定向。启动失败只写 ERROR 日志并弹窗提醒，不会影响 KarenBot "
                "正常运行。"
            )
        )
        info.append(
            widgets.muted(
                "“随 KarenBot 关闭”只影响由 Karen 成功拉起且仍存活的进程；"
                "启动失败、端口上已存在的外部实例永远不会被停止。Windows 的 "
                ".bat/.cmd 若只是启动器，Karen 无法跟踪其子进程，建议直接填 .exe。"
            )
        )
        self.append(info)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_button = widgets.button("添加程序", icon="list-add-symbolic")
        self.add_button.connect("clicked", lambda _b: self._add_program())
        toolbar.append(self.add_button)
        self.refresh_button = widgets.button("刷新状态", icon="view-refresh-symbolic")
        self.refresh_button.connect("clicked", lambda _b: self._refresh_status())
        toolbar.append(self.refresh_button)
        toolbar.append(_spacer())
        self.dirty_badge = widgets.badge("未保存", css="badge badge-orange")
        self.dirty_badge.set_visible(False)
        toolbar.append(self.dirty_badge)
        self.save_button = widgets.button("保存并应用", css="suggested-action")
        self.save_button.set_sensitive(False)
        self.save_button.connect("clicked", lambda _b: self._save())
        toolbar.append(self.save_button)
        self.append(toolbar)

        self.status_label = widgets.muted("")
        self.append(self.status_label)

        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.rows_box)
        self.empty_label = _empty(
            "还没有外部程序。点击「添加程序」配置 NapCat、旁路服务或其他启动项。"
        )
        self.rows_box.append(self.empty_label)

    # ------------------------------------------------------------------
    # Load / render
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self._loading:
            return
        if self.api is None:
            self._on_load_error(RuntimeError("本地控制服务尚未连接"))
            return
        self._loading = True
        self._render_loading()

        def _do() -> dict[str, Any]:
            return self.api.get("/api/settings/programs", timeout=30)

        widgets.run_async(
            _do,
            on_success=self._on_loaded,
            on_error=self._on_load_error,
        )

    def _render_loading(self) -> None:
        widgets.clear(self.rows_box)
        self.rows_box.append(widgets.muted("正在读取外部程序配置…"))
        self._set_controls_enabled(False)

    def _on_loaded(self, payload: dict[str, Any]) -> None:
        self._loading = False
        self._render(payload)

    def _on_load_error(self, exc: BaseException) -> None:
        self._loading = False
        self._loaded = False
        widgets.clear(self.rows_box)
        card = widgets.card(spacing=8, padding=14)
        card.append(widgets.section_header("读取外部程序失败", str(exc)))
        retry = widgets.button("重试", icon="view-refresh-symbolic")
        retry.connect("clicked", lambda _b: self._load())
        card.append(retry)
        self.rows_box.append(card)
        self._set_controls_enabled(False)
        self._set_dirty(False)

    def _render(self, payload: dict[str, Any]) -> None:
        self._loading = True
        try:
            programs = payload.get("programs") or []
            self._status_by_id = {
                str(item.get("id")): item
                for item in payload.get("status") or []
                if isinstance(item, dict) and item.get("id")
            }
            widgets.clear(self.rows_box)
            self._rows = []
            for program in programs:
                if isinstance(program, dict):
                    self._append_program(program)
            if not self._rows:
                self.empty_label = _empty(
                    "还没有外部程序。点击「添加程序」配置 NapCat、旁路服务或其他启动项。"
                )
                self.rows_box.append(self.empty_label)
        finally:
            self._loading = False
            self._loaded = True
            self._set_controls_enabled(True)
            self._set_dirty(False)

    # ------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------
    def _append_program(self, program: dict[str, Any] | None = None) -> None:
        data = dict(program or {})
        existing = bool(data.get("id"))
        program_id = str(data.get("id") or f"program_{uuid.uuid4().hex[:12]}")
        card = widgets.card(spacing=8, padding=14)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = widgets.entry(
            str(data.get("name") or ""), placeholder="显示名称（可留空）"
        )
        name.set_width_chars(18)
        name.connect("changed", lambda *_: self._mark_dirty())
        if existing:
            # 已有条目的 ID 是稳定身份，用只读标签展示；不再允许编辑。
            id_widget: Gtk.Widget = widgets.label(program_id, css="monospace")
            id_widget.set_selectable(True)
            id_widget.set_tooltip_text("稳定 ID；要更换请删除后重新添加")
            id_entry = None

            def _existing_id(pid: str = program_id) -> str:
                return pid
        else:
            id_entry = widgets.entry(program_id, placeholder="程序 ID")
            id_entry.set_width_chars(16)
            id_entry.connect("changed", lambda *_: self._mark_dirty())
            id_widget = id_entry

            def _new_id(entry: Gtk.Entry = id_entry) -> str:
                return entry.get_text().strip()
        head.append(widgets.label("名称", css="field-label"))
        head.append(name)
        head.append(widgets.label("ID", css="field-label"))
        head.append(id_widget)
        head.append(_spacer())

        enabled_row, enabled = _switch_row(
            "启用", bool(data.get("enabled", True))
        )
        enabled.connect("notify::active", lambda *_: self._mark_dirty())
        head.append(enabled_row)
        stop_row, stop_with_karen = _switch_row(
            "随 KarenBot 关闭", bool(data.get("stop_with_karen", True))
        )
        stop_with_karen.connect("notify::active", lambda *_: self._mark_dirty())
        head.append(stop_row)
        card.append(head)

        executable = widgets.entry(
            str(data.get("executable") or ""),
            placeholder="可执行文件或启动脚本路径",
        )
        executable.set_hexpand(True)
        executable.connect("changed", lambda *_: self._mark_dirty())
        exe_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        exe_row.append(executable)
        browse = widgets.button("浏览…", icon="document-open-symbolic")
        browse.connect(
            "clicked",
            lambda _b: self._pick_path(executable, folders=False),
        )
        exe_row.append(browse)
        card.append(
            _field(
                "可执行文件",
                exe_row,
                "绝对路径或 PATH 中的命令名；配置保存时不检查文件是否存在。",
            )
        )

        args = widgets.text_view(
            "\n".join(str(item) for item in data.get("args") or []),
            height=68,
            monospace=True,
        )
        args.get_child().get_buffer().connect(
            "changed", lambda *_: self._mark_dirty()
        )
        card.append(
            _field(
                "启动参数",
                args,
                "一行一个参数，不按逗号拆分；不支持管道/重定向。",
            )
        )

        cwd = widgets.entry(
            str(data.get("cwd") or ""), placeholder="留空使用程序所在目录"
        )
        cwd.set_hexpand(True)
        cwd.connect("changed", lambda *_: self._mark_dirty())
        cwd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cwd_row.append(cwd)
        cwd_browse = widgets.button("浏览…", icon="folder-open-symbolic")
        cwd_browse.connect(
            "clicked",
            lambda _b: self._pick_path(cwd, folders=True),
        )
        cwd_row.append(cwd_browse)
        card.append(_field("工作目录", cwd_row))

        advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        env = widgets.text_view(
            _env_text(data.get("env")), height=68, monospace=True
        )
        env.get_child().get_buffer().connect(
            "changed", lambda *_: self._mark_dirty()
        )
        advanced_box.append(
            _field("环境变量", env, "一行一个 KEY=VALUE；值以明文保存在 config.yaml。")
        )
        probe_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        probe_host = widgets.entry(
            str(data.get("probe_host") or "127.0.0.1"), placeholder="127.0.0.1"
        )
        probe_host.set_width_chars(16)
        probe_host.connect("changed", lambda *_: self._mark_dirty())
        probe_port = widgets.spin_button(
            0,
            65535,
            1,
            value=int(data.get("probe_port") or 0),
        )
        probe_port.set_tooltip_text("0 表示不探测；端口已监听则跳过启动")
        probe_port.connect("value-changed", lambda *_: self._mark_dirty())
        probe_row.append(widgets.label("探测地址", css="field-label"))
        probe_row.append(probe_host)
        probe_row.append(widgets.label("端口", css="field-label"))
        probe_row.append(probe_port)
        advanced_box.append(
            _field(
                "启动前端口探测",
                probe_row,
                "端口已有服务响应时视为外部已运行：Karen 不启动、也不会停止它。",
            )
        )
        auto_row, auto_restart = _switch_row(
            "异常退出后自动重启", bool(data.get("auto_restart", False))
        )
        auto_restart.connect("notify::active", lambda *_: self._mark_dirty())
        advanced_box.append(auto_row)
        wait = widgets.spin_button(
            0,
            300,
            0.5,
            value=float(data.get("startup_wait_seconds") or 2.0),
            digits=1,
        )
        wait.set_tooltip_text("启动后等待多久判定没有快速退出")
        wait.connect("value-changed", lambda *_: self._mark_dirty())
        advanced_box.append(
            _field("启动等待（秒）", wait, "0 表示不等待；进程立即退出视为启动失败。")
        )

        expander = Gtk.Expander(label="高级设置")
        expander.set_child(advanced_box)
        if any(
            [
                data.get("env"),
                data.get("probe_port"),
                data.get("auto_restart"),
                data.get("startup_wait_seconds") not in (None, 2.0),
            ]
        ):
            expander.set_expanded(True)
        card.append(expander)

        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.append(status_box)

        row = {
            "widget": card,
            "existing": existing,
            "name": name,
            "id_getter": _existing_id if existing else _new_id,
            "enabled": enabled,
            "stop_with_karen": stop_with_karen,
            "executable": executable,
            "args": args,
            "cwd": cwd,
            "env": env,
            "probe_host": probe_host,
            "probe_port": probe_port,
            "auto_restart": auto_restart,
            "startup_wait": wait,
            "status_box": status_box,
        }
        remove = widgets.button("移除", css="destructive-action")
        remove.connect("clicked", lambda _b, item=row: self._remove_program(item))
        head.append(remove)
        self._rows.append(row)
        self.rows_box.append(card)
        self._render_status(row)

    def _pick_path(self, target: Gtk.Entry, *, folders: bool) -> None:
        window = getattr(self.page.app, "window", None)
        if window is None:
            return
        path = widgets.path_picker(
            window,
            title_text="选择目录" if folders else "选择可执行文件",
            folders=folders,
        )
        if path:
            target.set_text(path)
            self._mark_dirty()

    def _remove_program(self, row: dict[str, Any]) -> None:
        status = self._status_by_id.get(row["id_getter"]())
        managed = bool(status and status.get("managed"))

        def _remove_now() -> None:
            self.rows_box.remove(row["widget"])
            if row in self._rows:
                self._rows.remove(row)
            if not self._rows:
                self.empty_label = _empty(
                    "还没有外部程序。点击「添加程序」配置 NapCat、旁路服务或其他启动项。"
                )
                self.rows_box.append(self.empty_label)
            self._mark_dirty()

        if managed:
            widgets.ConfirmDialog(
                self.page.app.window,
                heading="移除正在运行的外部程序？",
                body=(
                    f"「{row['name'].get_text().strip() or row['id_getter']()}」"
                    "由 KarenBot 拉起且仍在运行。保存后它会被立即停止。"
                ),
                confirm_label="移除",
                destructive=True,
                on_confirm=_remove_now,
            )
            return
        _remove_now()

    def _add_program(self) -> None:
        if not self._loaded:
            return
        self._append_program(
            {
                "enabled": True,
                "stop_with_karen": True,
                "startup_wait_seconds": 2.0,
            }
        )
        self._rows[-1]["name"].grab_focus()
        self._mark_dirty()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def _render_status(self, row: dict[str, Any]) -> None:
        box: Gtk.Box = row["status_box"]
        widgets.clear(box)
        program_id = row["id_getter"]()
        item = self._status_by_id.get(program_id)
        if item is None:
            box.append(widgets.badge("未保存", css="badge badge-idle"))
            return

        state = str(item.get("state") or "stopped")
        label_text, css = _STATE_LABELS.get(
            state, (state or "未知", "badge badge-idle")
        )
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        line.append(widgets.badge(label_text, css=css))
        bits: list[str] = []
        if item.get("pid"):
            bits.append(f"PID {item['pid']}")
        if item.get("managed"):
            bits.append("由 Karen 启动")
        elif state == "external":
            bits.append("外部实例，不接管")
        if item.get("restarts"):
            bits.append(f"已自动重启 {item['restarts']} 次")
        if bits:
            line.append(widgets.muted(" · ".join(bits)))
        line.append(_spacer())

        if row["existing"] and item.get("enabled"):
            if item.get("managed"):
                stop = widgets.button("停止")
                stop.connect(
                    "clicked", lambda _b, pid=program_id: self._action(pid, "stop")
                )
                line.append(stop)
            elif state in {"failed", "stopped", "exited", "launcher_exited"}:
                start = widgets.button("重试" if state == "failed" else "启动")
                start.connect(
                    "clicked", lambda _b, pid=program_id: self._action(pid, "start")
                )
                line.append(start)
        box.append(line)

        error = str(item.get("error") or "")
        if error:
            box.append(
                widgets.label(error, css="danger-text", wrap=True, selectable=True)
            )

    def _apply_statuses(self, statuses: list[dict[str, Any]]) -> None:
        self._status_by_id = {
            str(item.get("id")): item
            for item in statuses
            if isinstance(item, dict) and item.get("id")
        }
        for row in self._rows:
            self._render_status(row)

    def _refresh_status(self) -> None:
        if self.api is None or not self._loaded or self._saving:
            return
        self.refresh_button.set_sensitive(False)

        def _done(payload: dict[str, Any]) -> None:
            self.refresh_button.set_sensitive(True)
            self._apply_statuses(payload.get("status") or [])

        def _failed(exc: BaseException) -> None:
            self.refresh_button.set_sensitive(True)
            self.page.app.toast(f"刷新外部程序状态失败：{exc}", "error")

        widgets.run_async(
            lambda: self.api.get("/api/settings/programs", timeout=30),
            on_success=_done,
            on_error=_failed,
        )

    def _action(self, program_id: str, action: str) -> None:
        if self.api is None or self._saving or self._action_inflight:
            return
        self._action_inflight = True

        def _done(result: dict[str, Any]) -> None:
            self._action_inflight = False
            item = result.get("program")
            if isinstance(item, dict):
                self._status_by_id[program_id] = item
                for row in self._rows:
                    if row["id_getter"]() == program_id:
                        self._render_status(row)
            message = str(result.get("message") or "")
            if message:
                kind = "error" if (action == "start" and not result.get("started")) else ""
                self.page.app.toast(message, kind)

        def _failed(exc: BaseException) -> None:
            self._action_inflight = False
            self.page.app.toast(
                f"{'启动' if action == 'start' else '停止'}失败：{exc}", "error"
            )

        widgets.run_async(
            lambda: self.api.post(
                f"/api/settings/programs/{quote(str(program_id), safe='')}/{action}",
                {},
                timeout=30,
            ),
            on_success=_done,
            on_error=_failed,
        )

    # ------------------------------------------------------------------
    # Save / dirty
    # ------------------------------------------------------------------
    def _collect(self) -> list[dict[str, Any]]:
        programs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._rows:
            program_id = row["id_getter"]()
            if not _PROGRAM_ID_RE.fullmatch(program_id):
                raise ValueError(
                    f"程序 ID {program_id!r} 不合法：只能使用字母、数字、"
                    "下划线和短横线，且不能以符号开头"
                )
            if program_id in seen:
                raise ValueError(f"程序 ID 重复：{program_id}")
            seen.add(program_id)
            executable = row["executable"].get_text().strip()
            if row["enabled"].get_active() and not executable:
                raise ValueError(f"程序 {program_id} 已启用，但可执行文件为空")
            probe_host = row["probe_host"].get_text().strip() or "127.0.0.1"
            programs.append(
                {
                    "id": program_id,
                    "name": row["name"].get_text().strip(),
                    "enabled": bool(row["enabled"].get_active()),
                    "executable": executable,
                    "args": [
                        line.strip()
                        for line in widgets.text_value(row["args"]).splitlines()
                        if line.strip()
                    ],
                    "cwd": row["cwd"].get_text().strip(),
                    "env": _parse_env(widgets.text_value(row["env"])),
                    "stop_with_karen": bool(
                        row["stop_with_karen"].get_active()
                    ),
                    "probe_host": probe_host,
                    "probe_port": int(row["probe_port"].get_value()),
                    "auto_restart": bool(row["auto_restart"].get_active()),
                    "startup_wait_seconds": float(
                        row["startup_wait"].get_value()
                    ),
                }
            )
        return programs

    def _save(self) -> None:
        if not self._loaded or self._saving:
            return
        try:
            programs = self._collect()
        except ValueError as exc:
            self._show_status(str(exc))
            self.page.app.toast(f"保存失败：{exc}", "error")
            return

        self._saving = True
        self._set_controls_enabled(False)
        self.save_button.set_sensitive(False)
        self._show_status("正在保存并应用外部程序配置…")

        def _done(result: dict[str, Any]) -> None:
            self._saving = False
            self._render(result)
            self._show_status("")
            self.page.app.toast(str(result.get("message") or "外部程序配置已保存"))
            if result.get("needs_restart"):
                self.page.mark_restart()
            for program_id, error in (result.get("errors") or {}).items():
                self.page.app.toast(f"程序 {program_id}：{error}", "error")

        def _failed(exc: BaseException) -> None:
            self._saving = False
            self._set_controls_enabled(True)
            self._set_dirty(True)
            self._show_status(f"保存失败：{exc}")
            self.page.app.toast(f"保存失败：{exc}", "error")

        widgets.run_async(
            lambda: self.api.put(
                "/api/settings/programs", {"programs": programs}, timeout=60
            ),
            on_success=_done,
            on_error=_failed,
        )

    def _show_status(self, message: str) -> None:
        self.status_label.set_text(message or "")
        self.status_label.remove_css_class("danger-text")
        if "失败" in message or "不合法" in message or "不能为空" in message:
            self.status_label.add_css_class("danger-text")

    def _mark_dirty(self) -> None:
        if self._loading or self._saving:
            return
        self._set_dirty(True)

    def _set_dirty(self, value: bool) -> None:
        self.dirty = bool(value)
        self.dirty_badge.set_visible(self.dirty)
        self.save_button.set_sensitive(
            self.dirty and self._loaded and not self._saving
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.add_button.set_sensitive(bool(enabled) and not self._saving)
        self.save_button.set_sensitive(
            bool(enabled) and self.dirty and not self._saving
        )

    # ------------------------------------------------------------------
    # SettingsPage hooks
    # ------------------------------------------------------------------
    def has_unsaved_changes(self) -> bool:
        return self.dirty

    def discard_unsaved_changes(self) -> None:
        self._set_dirty(False)

    def on_show(self) -> None:
        if self._loaded and not self.dirty and not self._saving:
            self._refresh_status()


__all__ = ["ProgramsSettingsPanel"]
