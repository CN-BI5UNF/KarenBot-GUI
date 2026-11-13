"""Live log viewer."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class LogsPage(Page):
    refresh_on_activate = True
    page_id = "logs"
    page_title = "日志"
    page_subtitle = "实时跟随 root logger 输出，等级 / 模块 / 关键字三重过滤。"
    page_icon = "utilities-terminal-symbolic"

    MAX_LINES = 2000

    def build(self) -> None:
        self._disposed = False
        self._auto_task = None
        self._busy = False
        self._pending_refresh = False
        self._search_timer = 0
        self._records: list[dict[str, Any]] = []
        self._entries: list[tuple[int, list[Gtk.Widget]]] = []
        self._active_signature = ""
        self._last_seen_seq = 0
        self._display_since = 0
        self._server_buffer_size = 0
        self.body.append(self.header())
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.level_dropdown = widgets.dropdown(
            [
                ("", "全部等级"),
                ("DEBUG", "DEBUG+"),
                ("INFO", "INFO+"),
                ("WARNING", "WARNING+"),
                ("ERROR", "ERROR+"),
            ],
            "INFO",
        )
        self.level_dropdown.connect("notify::selected", lambda *_: self.refresh())
        self.module_entry = Gtk.Entry()
        self.module_entry.set_placeholder_text("模块前缀，如 core.runtime")
        self.module_entry.set_width_chars(24)
        self.module_entry.connect("changed", lambda _e: self._schedule_search())
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("关键字…")
        self.search_entry.connect("search-changed", lambda _e: self._schedule_search())
        self.auto_switch = Gtk.CheckButton(label="自动刷新")
        self.auto_switch.set_active(True)
        self.auto_switch.connect("toggled", self._schedule_auto)
        self.pause_switch = Gtk.CheckButton(label="暂停滚动")
        self.pause_switch.connect("toggled", self._pause_changed)
        toolbar.append(self.level_dropdown)
        toolbar.append(self.module_entry)
        toolbar.append(self.search_entry)
        toolbar.append(self.auto_switch)
        toolbar.append(self.pause_switch)
        clear = widgets.button("清屏")
        clear.connect("clicked", lambda _b: self._clear_view())
        toolbar.append(clear)
        reload_button = widgets.button("重新加载", icon="view-refresh-symbolic")
        reload_button.connect("clicked", lambda _b: self._reload())
        toolbar.append(reload_button)
        self.body.append(toolbar)
        self.count_label = widgets.muted("")
        self.body.append(self.count_label)
        self.log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.log_scroller = Gtk.ScrolledWindow()
        self.log_scroller.set_min_content_height(580)
        self.log_scroller.set_vexpand(True)
        self.log_scroller.set_child(self.log_box)
        self.body.append(self.log_scroller)

    def activate(self) -> None:
        super().activate()
        self._schedule_auto()

    def _schedule_search(self) -> None:
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(300, self._search_fired)

    def dispose(self) -> None:
        self._disposed = True
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = 0
        if self._auto_task:
            GLib.source_remove(self._auto_task)
            self._auto_task = None
        self._pending_refresh = False

    def _search_fired(self) -> bool:
        self._search_timer = 0
        if not self._disposed:
            self.refresh()
        return False

    def refresh_requested(self) -> None:
        self._reload()

    def _reload(self) -> None:
        """Discard the local view and fetch the filtered history again."""
        self._records = []
        self._entries = []
        self._last_seen_seq = 0
        self._display_since = 0
        self._active_signature = ""
        widgets.clear(self.log_box)
        self.count_label.set_text("正在重新加载日志…")
        if self._busy:
            self._pending_refresh = True
        else:
            self.refresh()

    def _clear_view(self) -> None:
        latest = max(
            [self._last_seen_seq]
            + [_log_seq(record) for record in self._records]
        )
        self._display_since = latest
        self._entries = []
        widgets.clear(self.log_box)
        self.count_label.set_text(
            f"已清屏（本地仍保留最近 {len(self._records)} 行，缓冲上限 "
            f"{self.MAX_LINES}；服务端缓冲 {self._server_buffer_size} 行）；"
            "点「重新加载」可恢复"
        )

    def _pause_changed(self, *_args: Any) -> None:
        if not self.pause_switch.get_active():
            self.refresh()

    def _schedule_auto(self, *_args: Any) -> None:
        if self._auto_task is not None:
            return
        self._auto_task = GLib.timeout_add_seconds(2, self._auto_tick)

    def _auto_tick(self) -> bool:
        if (
            self._disposed
            or not self.get_mapped()
            or not self.auto_switch.get_active()
        ):
            self._auto_task = None
            return False
        if not self._busy and not self.pause_switch.get_active():
            self.refresh()
        return True

    def _request_done(self) -> None:
        self._busy = False
        if self._pending_refresh:
            self._pending_refresh = False
            GLib.idle_add(self._run_pending_refresh)

    def _run_pending_refresh(self) -> bool:
        self.refresh()
        return False

    def refresh(self) -> None:
        if self.api is None:
            return
        if self._busy:
            # A dropdown change while a request is in flight used to be
            # dropped, leaving the view on the old filter until the next poll.
            self._pending_refresh = True
            return
        level = widgets.dropdown_value(self.level_dropdown)
        module = self.module_entry.get_text().strip()
        query = self.search_entry.get_text().strip()
        signature = f"{level}\x00{module}\x00{query}"
        if signature != self._active_signature:
            self._active_signature = signature
            self._records = []
            self._entries = []
            self._last_seen_seq = 0
            self._display_since = 0
            widgets.clear(self.log_box)
            self.count_label.set_text("正在载入日志…")
        params = ["limit=600"]
        if level:
            params.append(f"level={level}")
        if module:
            from urllib.parse import quote

            params.append(f"module={quote(module, safe='')}")
        if query:
            from urllib.parse import quote

            params.append(f"q={quote(query, safe='')}")
        path = "/api/logs?" + "&".join(params)
        self._busy = True

        def _fetch() -> dict[str, Any]:
            return self.api.get(path, timeout=20)

        widgets.run_async(
            _fetch,
            on_success=lambda data: self._render(data, signature),
            on_error=lambda exc: self._error(exc, signature),
        )

    def _error(self, exc: BaseException, signature: str) -> None:
        if signature != self._active_signature:
            self._request_done()
            return
        self._entries = []
        widgets.clear(self.log_box)
        self.log_box.append(widgets.muted(f"读取日志失败：{exc}"))
        self.count_label.set_text("读取日志失败")
        self._request_done()

    def _render(self, data: dict[str, Any], signature: str) -> None:
        if signature != self._active_signature:
            self._request_done()
            return
        records = data.get("records") or []
        try:
            self._server_buffer_size = int(data.get("buffer_size") or 0)
        except (TypeError, ValueError):
            self._server_buffer_size = len(records)
        old_seqs = {_log_seq(record) for record in self._records}
        for record in records:
            seq = _log_seq(record)
            if seq <= 0:
                continue
            if seq not in old_seqs:
                self._records.append(record)
                old_seqs.add(seq)
        self._records.sort(key=_log_seq)
        if len(self._records) > self.MAX_LINES:
            del self._records[: len(self._records) - self.MAX_LINES]
        new_records = [
            record
            for record in self._records
            if _log_seq(record) > self._last_seen_seq
            and _log_seq(record) > self._display_since
        ]
        if new_records:
            self._last_seen_seq = max(_log_seq(record) for record in new_records)
        else:
            self._last_seen_seq = max(
                self._last_seen_seq,
                max((_log_seq(record) for record in records), default=0),
            )

        adjustment = self.log_scroller.get_vadjustment()
        old_value = adjustment.get_value()
        at_bottom = (
            adjustment.get_upper() <= 0
            or old_value + adjustment.get_page_size()
            >= adjustment.get_upper() - 30
        )
        visible = [
            record
            for record in self._records
            if _log_seq(record) > self._display_since
        ]
        if (not self._entries and visible) or len(new_records) > 100:
            # First batch, after a filter/reload, or too many rows to append.
            self._entries = []
            widgets.clear(self.log_box)
            for record in visible:
                nodes = self._record_nodes(record)
                for node in nodes:
                    self.log_box.append(node)
                self._entries.append((_log_seq(record), nodes))
        elif new_records:
            for record in new_records:
                nodes = self._record_nodes(record)
                for node in nodes:
                    self.log_box.append(node)
                self._entries.append((_log_seq(record), nodes))
        while len(self._entries) > self.MAX_LINES:
            _seq, nodes = self._entries.pop(0)
            for node in nodes:
                parent = node.get_parent()
                if parent is not None:
                    parent.remove(node)

        shown = len(self._entries)
        if shown == 0:
            widgets.clear(self.log_box)
            if self._records and self._display_since:
                message = "已清屏；点「重新加载」可以恢复过滤后的历史日志。"
                self.count_label.set_text(
                    f"已清屏 · 本地缓冲 {len(self._records)} 行 / 上限 "
                    f"{self.MAX_LINES} · 服务端缓冲 {self._server_buffer_size} 行"
                    " · 点「重新加载」恢复"
                )
            elif self._records:
                message = "当前过滤条件下没有可见日志，等待新日志…"
                self.count_label.set_text(
                    f"显示 0 行（本地缓冲 {len(self._records)} / 上限 "
                    f"{self.MAX_LINES}；服务端缓冲 {self._server_buffer_size} 行）"
                )
            else:
                message = "当前过滤条件下没有日志，等待新日志…"
                self.count_label.set_text("暂无符合条件的日志")
            self.log_box.append(widgets.muted(message))
        else:
            # Drop an old status message (empty/error) before the first real row.
            first = self.log_box.get_first_child()
            while isinstance(first, Gtk.Label):
                self.log_box.remove(first)
                first = self.log_box.get_first_child()
            self.count_label.set_text(
                f"显示 {shown} 行（本地缓冲 {len(self._records)} / 上限 "
                f"{self.MAX_LINES}；服务端缓冲 {self._server_buffer_size} 行）"
            )
        GLib.timeout_add(
            50,
            lambda: self._restore_scroll(at_bottom, old_value),
        )
        self._request_done()

    def _record_nodes(self, record: dict[str, Any]) -> list[Gtk.Widget]:
        level = str(record.get("level") or "INFO")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("log-row")
        if level == "ERROR" or level == "CRITICAL":
            row.add_css_class("log-error")
        elif level == "WARNING":
            row.add_css_class("log-warning")
        elif level == "DEBUG":
            row.add_css_class("log-debug")
        row.append(widgets.label(str(record.get("time_text") or ""), css="muted"))
        row.append(widgets.label(level.ljust(8), css="monospace"))
        row.append(widgets.label(str(record.get("logger") or ""), css="monospace"))
        message = widgets.label(
            str(record.get("message") or ""), wrap=True, selectable=True
        )
        message.set_hexpand(True)
        row.append(message)
        nodes: list[Gtk.Widget] = [row]
        exc = str(record.get("exc") or "")
        if exc:
            detail = widgets.label(exc, css="monospace", wrap=True, selectable=True)
            detail.set_margin_start(100)
            nodes.append(detail)
        return nodes

    def _restore_scroll(self, at_bottom: bool, old_value: float) -> bool:
        adjustment = self.log_scroller.get_vadjustment()
        if at_bottom:
            adjustment.set_value(
                max(0.0, adjustment.get_upper() - adjustment.get_page_size())
            )
        else:
            adjustment.set_value(old_value)
        return False


def _log_seq(record: dict[str, Any]) -> int:
    try:
        return int(record.get("seq") or 0)
    except (TypeError, ValueError):
        return 0
