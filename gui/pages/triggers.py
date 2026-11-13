"""Per-group @-trigger rules."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class TriggersPage(Page):
    refresh_on_activate = True
    page_id = "triggers"
    page_title = "群聊触发"
    page_subtitle = "指定哪些群只在被 @ 时响应，并设置 @ 后继续接收普通消息的条数或时长。"
    page_icon = "preferences-system-notifications-symbolic"

    def build(self) -> None:
        self._loading = False
        self._dirty = False
        self._saving = False
        # 和黑白名单一样：读取成功前不得保存，避免用空规则覆盖服务端。
        self._loaded = False
        self._loading_remote = False
        header_row = self.header()
        self.dirty_badge = widgets.badge("未保存", css="badge badge-orange")
        self.dirty_badge.set_visible(False)
        header_row.append(self.dirty_badge)
        self.save_button = widgets.button(
            "保存并立即生效", css="suggested-action"
        )
        self.save_button.set_sensitive(False)
        self.save_button.connect("clicked", lambda _b: self._save())
        header_row.append(self.save_button)
        self.body.append(header_row)
        info = widgets.card()
        info.append(
            widgets.muted(
                "每个群可以单独设置被 @ 后连续接收的消息数、时间窗口，以及被过滤消息的"
                "内存缓存条数。缓存只存在内存中，不会写入聊天历史。"
            )
        )
        self.body.append(info)
        self.summary_label = widgets.muted("")
        self.body.append(self.summary_label)
        enable_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.enable_switch = widgets.switch(True)
        self.enable_switch.set_sensitive(False)
        enable_row.append(self.enable_switch)
        enable_row.append(widgets.label("启用按群 @ 触发", css="section-title"))
        self.body.append(enable_row)
        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.rows_box.set_sensitive(False)
        self.body.append(self.rows_box)
        add = widgets.button("添加群规则", icon="list-add-symbolic")
        add.set_sensitive(False)
        add.connect("clicked", lambda _b: self._add_rule())
        self._add_button = add
        self.body.append(add)
        self.status_label = widgets.muted("")
        self.body.append(self.status_label)
        self.body.append(
            widgets.section_header(
                "当前窗口",
                "被过滤的普通消息只进入有限内存缓存；关闭窗口后不再接收普通消息。",
            )
        )
        self.windows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.windows_box)
        self.active_label = widgets.muted("")
        self.body.append(self.active_label)
        self.body.append(
            widgets.muted(
                "LLM 可调用 group_trigger_window 临时放行、延长或提前关闭窗口，"
                "最多同时覆盖 2 个群；history_limit 可附带最近几条被过滤消息。"
            )
        )
        self._rules: list[dict[str, Any]] = []
        self._row_widgets: list[dict[str, Any]] = []
        self.enable_switch.connect("notify::active", lambda *_: self._mark_dirty())

    def refresh(self) -> None:
        if self.api is None or self.has_unsaved_changes():
            return
        self._loading_remote = True
        self.save_button.set_sensitive(False)

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/settings/group-triggers", timeout=30)

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        self._loading_remote = False
        self._loaded = False
        self.save_button.set_sensitive(False)
        self.enable_switch.set_sensitive(False)
        self.rows_box.set_sensitive(False)
        self._add_button.set_sensitive(False)
        widgets.clear(self.rows_box)
        self.rows_box.append(widgets.muted(f"读取失败：{exc}。请点击右上角刷新重试。"))
        self.status_label.set_text("尚未读取到服务端规则；保存已禁用，避免覆盖现有配置。")
        self.status_label.add_css_class("danger-text")

    def _render(self, data: dict[str, Any]) -> None:
        self._loading = True
        try:
            self.enable_switch.set_active(bool(data.get("enabled", True)))
        finally:
            self._loading = False
        self._rules = list(data.get("groups") or [])
        self._row_widgets = []
        widgets.clear(self.rows_box)
        for rule in self._rules:
            self._append_rule_widget(rule)
        active = data.get("active_windows") or []
        enabled_text = "已启用" if data.get("enabled", True) else "未启用"
        self.summary_label.set_text(
            f"{enabled_text} · {len(self._rules)} 条群规则 · "
            f"当前活跃窗口 {len(active)} 个 · 模型最多临时打开 "
            f"{data.get('max_llm_groups', 2)} 个群"
        )
        self.active_label.set_text(
            "规则中的 0 表示不限；缓存为 0 表示不保留被过滤消息。"
        )
        self._render_windows(active)
        self._loading_remote = False
        self._loaded = True
        self.enable_switch.set_sensitive(True)
        self.rows_box.set_sensitive(True)
        self._add_button.set_sensitive(True)
        if not self._saving:
            self.save_button.set_sensitive(True)
        self.status_label.set_text("")
        self.status_label.remove_css_class("danger-text")
        self._dirty = False
        self.dirty_badge.set_visible(False)

    def _append_rule_widget(self, rule: dict[str, Any]) -> None:
        card = widgets.card()
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        group_entry = Gtk.Entry()
        group_entry.set_placeholder_text("群号")
        group_entry.set_width_chars(16)
        group_entry.set_text(str(rule.get("group_id") or ""))
        group_entry.set_sensitive(not bool(rule.get("group_id")))
        group_entry.connect("changed", lambda *_: self._mark_dirty())
        if rule.get("group_id"):
            group_entry.set_tooltip_text("群号是规则身份；要修改请移除后重新添加")
        max_spin = Gtk.SpinButton.new_with_range(0, 1000, 1)
        max_spin.set_value(int(rule.get("max_messages") or 0))
        max_spin.set_tooltip_text("0 表示不限条数")
        window_spin = Gtk.SpinButton.new_with_range(0, 1440, 1)
        window_spin.set_value(int(rule.get("window_minutes") or 0))
        window_spin.set_tooltip_text("0 表示不限时间")
        cache_spin = Gtk.SpinButton.new_with_range(0, 500, 1)
        cache_spin.set_value(int(rule.get("cache_messages") or 0))
        cache_spin.set_tooltip_text("0 表示不缓存被过滤消息")
        for spin in (max_spin, window_spin, cache_spin):
            spin.connect("value-changed", lambda *_: self._mark_dirty())
        head.append(widgets.label("群号", css="field-label"))
        head.append(group_entry)
        head.append(widgets.label("条数", css="field-label"))
        head.append(max_spin)
        head.append(widgets.label("分钟", css="field-label"))
        head.append(window_spin)
        head.append(widgets.label("缓存", css="field-label"))
        head.append(cache_spin)
        remove = widgets.button("移除")
        remove.add_css_class("destructive-action")
        card.append(head)
        row = {
            "widget": card,
            "group_id": group_entry,
            "max_messages": max_spin,
            "window_minutes": window_spin,
            "cache_messages": cache_spin,
        }
        self._row_widgets.append(row)
        remove.connect("clicked", lambda _b, r=row: self._remove_row(r))
        head.append(remove)
        self.rows_box.append(card)

    def _add_rule(self) -> None:
        self._append_rule_widget({"cache_messages": 50})
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self.dirty_badge.set_visible(True)

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def discard_unsaved_changes(self) -> None:
        self._dirty = False
        self.dirty_badge.set_visible(False)

    def _render_windows(self, windows: list[dict[str, Any]]) -> None:
        widgets.clear(self.windows_box)
        if not windows:
            self.windows_box.append(
                self.empty("当前没有活动接收窗口；@ 机器人后会出现在这里。")
            )
            return
        for item in windows:
            card = widgets.card(spacing=4, padding=10)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(
                widgets.label(f"群 {item.get('group_id')}", css="section-title")
            )
            head.append(
                widgets.badge(
                    "LLM 临时放行" if item.get("llm_owned") else "@ 触发",
                    css="badge badge-orange" if item.get("llm_owned") else "badge",
                )
            )
            if item.get("near_limit"):
                head.append(widgets.badge("即将结束", css="badge badge-red"))
            card.append(head)
            remaining_messages = item.get("remaining_messages")
            remaining_minutes = item.get("remaining_minutes")
            card.append(
                widgets.muted(
                    "剩余："
                    + (
                        "不限" if remaining_messages is None else f"{remaining_messages} 条"
                    )
                    + " · "
                    + (
                        "不限"
                        if remaining_minutes is None
                        else f"约 {remaining_minutes} 分钟"
                    )
                )
            )
            self.windows_box.append(card)

    def _remove_row(self, row: dict[str, Any]) -> None:
        self.rows_box.remove(row["widget"])
        if row in self._row_widgets:
            self._row_widgets.remove(row)
        self._mark_dirty()

    def _save(self) -> None:
        if self.api is None or self._saving:
            return
        if not self._loaded:
            self.toast("规则尚未成功读取；为避免覆盖服务端配置，请先刷新")
            return
        groups = []
        seen: set[int] = set()
        for row in self._row_widgets:
            entry = row["group_id"]
            raw = entry.get_text().strip()
            try:
                group_id = int(raw or 0)
            except ValueError:
                self.toast("群号必须是数字；空行请移除后再保存")
                entry.grab_focus()
                return
            if group_id <= 0:
                self.toast("群号必须是正整数；空行请移除后再保存")
                entry.grab_focus()
                return
            if group_id in seen:
                self.toast(f"群 {group_id} 已经在触发名单中")
                entry.grab_focus()
                return
            seen.add(group_id)
            groups.append(
                {
                    "group_id": group_id,
                    "max_messages": int(row["max_messages"].get_value()),
                    "window_minutes": int(row["window_minutes"].get_value()),
                    "cache_messages": int(row["cache_messages"].get_value()),
                }
            )
        payload = {"enabled": self.enable_switch.get_active(), "groups": groups}

        def _do() -> dict[str, Any]:
            return self.api.put(
                "/api/settings/group-triggers", payload, timeout=60
            )

        self._saving = True
        self.save_button.set_sensitive(False)

        def _done(result: dict[str, Any]) -> None:
            self._saving = False
            self.save_button.set_sensitive(True)
            self.toast(str(result.get("message") or "已保存"))
            self._render(result)

        def _failed(exc: BaseException) -> None:
            self._saving = False
            self.save_button.set_sensitive(True)
            self.toast(f"保存失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)
