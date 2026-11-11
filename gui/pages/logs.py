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
        self._auto_task = None
        self._busy = False
        self._search_timer = 0
        self._records: list[dict[str, Any]] = []
        self._entries: list[tuple[int, list[Gtk.Widget]]] = []
        self._active_signature = ""
        self._last_seen_seq = 0
        self._display_since = 0
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
        toolbar.append(self.level_dropdown)
        toolbar.append(self.module_entry)
        toolbar.append(self.search_entry)
        toolbar.append(self.auto_switch)
        clear = widgets.button("清屏")
        clear.connect("clicked", lambda _b: self._clear_view())
        toolbar.append(clear)
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

    def _search_fired(self) -> bool:
        self._search_timer = 0
        self.refresh()
        return False

    def _clear_view(self) -> None:
        self._display_since = self._last_seen_seq
        self._entries = []
        widgets.clear(self.log_box)
        self.count_label.set_text(
            f"已清屏（本地仍保留最近 {len(self._records)} 行，缓冲上限 "
            f"{self.MAX_LINES}）"
        )

    def _schedule_auto(self, *_args: Any) -> None:
        if self._auto_task is not None:
            return
        self._auto_task = GLib.timeout_add_seconds(2, self._auto_tick)

    def _auto_tick(self) -> bool:
        if not self.get_mapped() or not self.auto_switch.get_active():
            self._auto_task = None
            return False
        if not self._busy:
            self.refresh()
        return True

    def refresh(self) -> None:
        if self.api is None or self._busy:
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
            on_error=self._error,
        )

    def _error(self, exc: BaseException) -> None:
        self._busy = False
        self._entries = []
        widgets.clear(self.log_box)
        self.log_box.append(widgets.muted(f"读取日志失败：{exc}"))

    def _render(self, data: dict[str, Any], signature: str) -> None:
        self._busy = False
        if signature != self._active_signature:
            return
        records = data.get("records") or []
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
        rebuild = len(new_records) > 100 or (
            new_records and not self._entries and not self._records
        )
        if rebuild or (new_records and not self._entries and not self.log_box.get_first_child()):
            # Too many new records (or the first batch) to append cheaply.
            self._entries = []
            widgets.clear(self.log_box)
            visible = [
                record
                for record in self._records
                if _log_seq(record) > self._display_since
            ]
            for record in visible:
                nodes = self._record_nodes(record)
                for node in nodes:
                    self.log_box.append(node)
                self._entries.append((_log_seq(record), nodes))
        elif new_records or (not self._entries and self._records):
            if not new_records:
                visible = [
                    record
                    for record in self._records
                    if _log_seq(record) > self._display_since
                ]
                new_records = visible
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
        self.count_label.set_text(
            f"显示 {shown} 行（本地缓冲 {len(self._records)} / 上限 "
            f"{self.MAX_LINES}）"
        )
        if shown == 0:
            if not self.log_box.get_first_child():
                self.log_box.append(
                    widgets.muted("当前过滤条件下没有日志，等待新日志…")
                )
        else:
            # Drop an old status message (empty/error) before the first real row.
            first = self.log_box.get_first_child()
            while isinstance(first, Gtk.Label):
                self.log_box.remove(first)
                first = self.log_box.get_first_child()
        GLib.timeout_add(
            50,
            lambda: self._restore_scroll(at_bottom, old_value),
        )

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
