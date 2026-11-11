"""Persona mind dashboard matching the WebUI tabs and wake modal."""

from __future__ import annotations

import json
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

TABS = [
    ("effects", "短期影响"),
    ("cues", "线索"),
    ("todos", "待办"),
    ("profiles", "用户画像"),
    ("monologues", "内心独白"),
    ("trajectories", "整理轨迹"),
    ("state_logs", "状态日志"),
    ("sleep", "睡眠记录"),
    ("eat", "进食记录"),
    ("arc", "人格弧光"),
]


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class MindPage(Page):
    refresh_on_activate = True
    page_id = "mind"
    page_title = "人格后台"
    page_subtitle = "人格的内心状态与决策轨迹。需要「设置 → 人格与生理 → 启用人格后台」才会产生数据。"
    page_icon = "emblem-favorite-symbolic"

    def build(self) -> None:
        self._state: dict[str, Any] = {}
        self._state_busy = False
        self._wake_busy = False
        self._last_poll = 0.0
        self._tab_loaded: set[str] = set()
        self._tab_busy: set[str] = set()
        self._tab_hosts: dict[str, Gtk.Box] = {}

        header = self.header()
        self.wake_button = widgets.button("唤醒", css="suggested-action")
        self.wake_button.set_sensitive(False)
        self.wake_button.set_tooltip_text("只有睡眠/昏睡中的人格才能被唤醒")
        self.wake_button.connect("clicked", lambda _b: self._open_wake_dialog())
        header.append(self.wake_button)
        self.body.append(header)

        self.banner = widgets.card()
        self.banner.set_visible(False)
        self.body.append(self.banner)

        self.state_grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        self.state_grid.set_column_homogeneous(True)
        self.body.append(self.state_grid)

        self.monologue_card = widgets.card(spacing=4)
        self.monologue_card.set_visible(False)
        self.body.append(self.monologue_card)

        self.reply_box = widgets.card()
        self.reply_box.set_visible(False)
        self.body.append(self.reply_box)

        self.tabs_card = widgets.card(spacing=8)
        tab_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tab_head.append(widgets.section_header("轨迹", "人格数据库中的只读视图"))
        tab_head.set_hexpand(True)
        self.tabs_card.append(tab_head)

        self.tab_stack = Gtk.Stack()
        self.tab_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.tab_stack.set_transition_duration(120)
        self.tab_switch = Gtk.StackSwitcher()
        self.tab_switch.set_stack(self.tab_stack)
        self.tab_switch.set_halign(Gtk.Align.START)
        switch_scroll = Gtk.ScrolledWindow()
        switch_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        switch_scroll.set_child(self.tab_switch)
        switch_scroll.set_min_content_height(44)
        switch_scroll.add_css_class("tab-switcher-scroll")
        self.tabs_card.append(switch_scroll)
        for key, title in TABS:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            page.append(widgets.muted("打开标签页后加载…"))
            self.tab_stack.add_titled(page, key, title)
            self._tab_hosts[key] = page
        self.tab_stack.connect("notify::visible-child", self._tab_changed)
        self.tabs_card.append(self.tab_stack)
        self.body.append(self.tabs_card)

        self.banner.set_visible(False)
        self._render_disabled("正在读取人格状态…")
        GLib.timeout_add_seconds(3, self._poll)

    # ------------------------------------------------------------------
    # State polling
    # ------------------------------------------------------------------
    def refresh(self, *, load_tab: bool = True) -> None:
        if self.api is None or self._state_busy:
            return
        self._state_busy = True
        if load_tab:
            self._tab_loaded.clear()

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/mind/state", timeout=30)

        def _done(data: dict[str, Any]) -> None:
            self._state_busy = False
            self._render_state(data)

        def _failed(exc: BaseException) -> None:
            self._state_busy = False
            self._error(exc)

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def _poll(self) -> bool:
        if not self.get_mapped() or self._wake_busy:
            return True
        self.refresh(load_tab=False)
        return True

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.state_grid)
        self._render_disabled(f"读取人格状态失败：{exc}")

    def _render_disabled(self, message: str) -> None:
        widgets.clear(self.banner)
        self.banner.append(widgets.muted(message))
        self.banner.set_visible(True)
        widgets.clear(self.state_grid)
        self.monologue_card.set_visible(False)
        self.wake_button.set_sensitive(False)
        self.tabs_card.set_sensitive(False)

    def _render_state(self, data: dict[str, Any]) -> None:
        self._state = data
        if not data.get("available"):
            self._render_disabled(
                str(data.get("reason") or "人格后台未启用。")
            )
            return
        self.banner.set_visible(False)
        self.tabs_card.set_sensitive(True)
        state = data.get("state") or {}
        activity = data.get("activity") or {}
        physiology = data.get("physiology") or {}
        action = str(state.get("current_action") or "awake")
        action_labels = {
            "awake": "清醒",
            "sleeping": "睡眠中",
            "eating": "进食中",
            "collapsing": "体力崩溃",
            "working": "专注工作中",
        }
        sleeping = action in {"sleeping", "collapsing"}
        self.wake_button.set_sensitive(sleeping and not self._wake_busy)
        self.wake_button.set_tooltip_text(
            "像被人叫醒一样唤醒人格"
            if sleeping
            else "只有睡眠/昏睡中的人格才能被唤醒"
        )

        widgets.clear(self.state_grid)
        age = data.get("age")
        if isinstance(age, dict):
            age = age.get("effective")
        tiles = [
            ("当前心情", self._num(state.get("mood"), 2)),
            ("社交需求", self._num(state.get("social_need"), 2)),
            ("当前动作", action_labels.get(action, action)),
            ("年龄", _display_value(age)),
        ]
        if not physiology or physiology.get("energy_mode") != "off":
            tiles.append(("能量", self._num(state.get("energy"), 1)))
        if not physiology or physiology.get("satiety_mode") != "off":
            tiles.append(("饱食度", self._num(state.get("satiety"), 1)))
        tiles.append(
            ("上次心跳", widgets.short_time(state.get("last_tick_at")) or "—")
        )
        for index, (label_text, value_text) in enumerate(tiles):
            tile = widgets.card(spacing=3, padding=10)
            tile.set_hexpand(True)
            tile.append(widgets.label(label_text, css="stat-label"))
            tile.append(widgets.label(value_text, css="stat-value"))
            self.state_grid.attach(tile, index % 4, index // 4, 1, 1)

        monologue = str(state.get("latest_monologue") or "").strip()
        widgets.clear(self.monologue_card)
        if monologue:
            self.monologue_card.append(
                widgets.label("最近一次内心独白", css="field-label")
            )
            self.monologue_card.append(
                widgets.label(monologue, wrap=True, selectable=True)
            )
            self.monologue_card.set_visible(True)
        else:
            self.monologue_card.set_visible(False)

        activity_text = str(activity.get("text") or "")
        widgets.clear(self.banner)
        if activity_text:
            self.banner.append(widgets.muted(activity_text))
            self.banner.set_visible(True)
        else:
            self.banner.set_visible(False)
        current = self._current_tab()
        if current and current not in self._tab_loaded:
            self._load_tab(current)

    @staticmethod
    def _num(value: Any, digits: int) -> str:
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _current_tab(self) -> str:
        child = self.tab_stack.get_visible_child()
        if child is None:
            return TABS[0][0]
        for key, host in self._tab_hosts.items():
            if host is child:
                return key
        return TABS[0][0]

    def _tab_changed(self, *_args: Any) -> None:
        key = self._current_tab()
        if key and key not in self._tab_loaded and self._state.get("available"):
            self._load_tab(key)

    def _load_tab(self, key: str) -> None:
        if self.api is None or not self._state.get("available"):
            return
        if key in self._tab_busy:
            return
        host = self._tab_hosts.get(key)
        if host is None:
            return
        self._tab_busy.add(key)
        widgets.clear(host)
        host.append(self.busy("正在读取…"))

        def _fetch() -> dict[str, Any]:
            return self.api.get(f"/api/mind/tab/{key}?limit=60", timeout=30)

        def _done(data: dict[str, Any]) -> None:
            self._tab_busy.discard(key)
            self._tab_loaded.add(key)
            self._render_tab(key, data)

        def _failed(exc: BaseException) -> None:
            self._tab_busy.discard(key)
            widgets.clear(host)
            host.append(widgets.muted(f"读取失败：{exc}"))

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def _render_tab(self, key: str, data: dict[str, Any]) -> None:
        host = self._tab_hosts[key]
        widgets.clear(host)
        items = (
            data.get("items")
            or data.get("entries")
            or data.get("records")
            or data.get("data")
        )
        if items is None:
            items = data.get("rows")
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or not items:
            host.append(
                widgets.muted(str(data.get("message") or "暂无数据。"))
            )
            return
        headers: list[str] = []
        for item in items:
            if isinstance(item, dict):
                for name in item:
                    if name not in headers:
                        headers.append(str(name))
                    if len(headers) >= 6:
                        break
            if len(headers) >= 6:
                break
        if not headers:
            for item in items[:100]:
                card = widgets.card(spacing=4)
                card.append(
                    widgets.label(str(item), wrap=True, selectable=True)
                )
                host.append(card)
            return
        rows = [
            [
                _display_value((item or {}).get(name))
                if isinstance(item, dict)
                else "—"
                for name in headers
            ]
            for item in items[:60]
        ]
        host.append(
            widgets.table(
                headers,
                rows,
                weights=[1.0] * len(headers),
            )
        )

    # ------------------------------------------------------------------
    # Wake modal
    # ------------------------------------------------------------------
    def _open_wake_dialog(self) -> None:
        if self.api is None or self._wake_busy:
            return
        action = str((self._state.get("state") or {}).get("current_action") or "")
        if action not in {"sleeping", "collapsing"}:
            self.toast("只有睡眠/昏睡中的人格才能被唤醒")
            return
        window = widgets.FormWindow(
            self.app.window,
            "唤醒人格",
            width=560,
            height=420,
            submit_label="叫醒",
            on_submit=lambda: _submit(window),
        )
        window.body_box.append(
            widgets.muted(
                "像被人叫醒一样，人格会回一句自然的话。回复只显示在本地，"
                "不会自动发送到 QQ。"
            )
        )
        message_view = widgets.text_view("", height=120)
        window.add_row("叫醒留言（可选）", message_view)
        window.body_box.append(
            widgets.muted("留空只表示叫醒；最多 2000 字。")
        )
        error = widgets.muted("")
        window.body_box.append(error)
        window.present()

        def _submit(dialog: Gtk.Window) -> None:
            if self._wake_busy:
                return
            message = widgets.text_value(message_view).strip()[:2000]
            self._wake_busy = True
            self.wake_button.set_sensitive(False)

            def _do() -> dict[str, Any]:
                return self.api.post(
                    "/api/mind/wake",
                    {"message": message, "reason": "admin_gui"},
                    timeout=150,
                )

            def _done(result: dict[str, Any]) -> None:
                self._wake_busy = False
                dialog.close()
                self._render_wake_reply(result)
                self.refresh()

            def _failed(exc: BaseException) -> None:
                self._wake_busy = False
                self.wake_button.set_sensitive(True)
                error.set_text(f"唤醒失败：{exc}")

            widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _render_wake_reply(self, result: dict[str, Any]) -> None:
        widgets.clear(self.reply_box)
        reply = str(result.get("reply") or "")
        message_text = str(result.get("message") or "已唤醒")
        self.reply_box.append(
            widgets.label("唤醒对话", css="card-title")
        )
        self.reply_box.append(
            widgets.muted("以下对白只显示在人格后台，不会自动发送到 QQ。")
        )
        if reply:
            self.reply_box.append(
                widgets.label(reply, css="chat-text", wrap=True, selectable=True)
            )
        else:
            self.reply_box.append(widgets.muted("（没有生成对白）"))
        error = str(result.get("reply_error") or "")
        if error:
            self.reply_box.append(widgets.muted(f"对白生成失败：{error}"))
        self.reply_box.set_visible(True)
        self.toast(message_text)
