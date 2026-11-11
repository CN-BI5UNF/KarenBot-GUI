"""Group-slang management page."""

from __future__ import annotations

import json
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

STATUS_LABEL = {"candidate": "待确认", "confirmed": "已确认", "rejected": "已拒绝"}


class SlangPage(Page):
    refresh_on_activate = True
    page_id = "slang"
    page_title = "群聊黑话"
    page_subtitle = "知识库按群隔离、同群所有人格共享；候选词条需要人工补充释义并确认，只有已确认词条能被模型查询。"
    page_icon = "chat-message-new-symbolic"

    def build(self) -> None:
        self._search_timer = 0
        self._conv_sync = False
        header_row = self.header()
        settings_button = widgets.button("学习设置")
        settings_button.connect(
            "clicked", lambda _b: self.app.show_page("settings", section="features")
        )
        header_row.append(settings_button)
        self.add_button = widgets.button(
            "手动添加", icon="list-add-symbolic", css="suggested-action"
        )
        self.add_button.connect("clicked", lambda _b: self._editor(None))
        header_row.append(self.add_button)
        self.body.append(header_row)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.conversation_entry = Gtk.Entry()
        self.conversation_entry.set_placeholder_text("group:123456（可留空看全部群）")
        self.conversation_entry.set_width_chars(24)
        self.conversation_picker = widgets.dropdown([("", "全部群聊")], "")
        self.conversation_picker.connect(
            "notify::selected", self._conversation_selected
        )
        self.conversation_entry.connect("activate", lambda _e: self.refresh())
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("搜索词条、释义、用法…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda _e: self._schedule_search())
        self.status_filter = widgets.dropdown(
            [("", "全部状态"), ("candidate", "待确认"), ("confirmed", "已确认"), ("rejected", "已拒绝")],
            "",
        )
        self.status_filter.connect("notify::selected", lambda *_: self.refresh())
        self.learn_button = widgets.button("从当前缓存学习")
        self.learn_button.connect("clicked", lambda _b: self._learn())
        toolbar.append(self.conversation_entry)
        toolbar.append(self.conversation_picker)
        toolbar.append(self.search_entry)
        toolbar.append(self.status_filter)
        toolbar.append(self.learn_button)
        self.body.append(toolbar)
        self.stats_label = widgets.muted("")
        self.body.append(self.stats_label)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.list_box)

    def _schedule_search(self) -> None:
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(300, self._search_fired)

    def _search_fired(self) -> bool:
        self._search_timer = 0
        self.refresh()
        return False

    def _conversation_selected(self, *_args: Any) -> None:
        if self._conv_sync:
            return
        value = widgets.dropdown_value(self.conversation_picker)
        self.conversation_entry.set_text(value)
        self.refresh()

    def refresh(self) -> None:
        if self.api is None:
            return
        from urllib.parse import quote

        params = []
        conv = self.conversation_entry.get_text().strip()
        query = self.search_entry.get_text().strip()
        status = widgets.dropdown_value(self.status_filter)
        if conv:
            params.append(f"conversation_id={quote(conv, safe='')}")
        if query:
            params.append(f"q={quote(query, safe='')}")
        if status:
            params.append(f"status={status}")
        path = "/api/slang" + (("?" + "&".join(params)) if params else "")

        def _fetch() -> dict[str, Any]:
            return self.api.get(path, timeout=30)

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.list_box)
        self.list_box.append(widgets.muted(f"读取黑话失败：{exc}"))

    def _render(self, data: dict[str, Any]) -> None:
        widgets.clear(self.list_box)
        stats = data.get("stats") or {}
        counts = stats.get("counts") or {}
        settings = data.get("settings") or {}
        writable = data.get("writable") is not False
        self.add_button.set_sensitive(writable)
        self.learn_button.set_sensitive(writable)
        conversations = list(data.get("conversations") or [])
        current_conv = self.conversation_entry.get_text().strip()
        if current_conv and current_conv not in conversations:
            conversations.append(current_conv)
        options = [("", "全部群聊")] + [(item, item) for item in conversations]
        self._conv_sync = True
        self.conversation_picker.set_model(
            Gtk.StringList.new([label for _value, label in options])
        )
        self.conversation_picker._values = [value for value, _label in options]  # type: ignore[attr-defined]
        values = getattr(self.conversation_picker, "_values", [])
        if current_conv in values:
            self.conversation_picker.set_selected(values.index(current_conv))
        else:
            self.conversation_picker.set_selected(0)
        self._conv_sync = False
        buffers = data.get("buffers") or {}
        buffered = buffers.get(current_conv, 0) if current_conv else 0
        bits = [
            f"共 {stats.get('total', 0)} 条",
            f"待确认 {counts.get('candidate', 0)}",
            f"已确认 {counts.get('confirmed', 0)}",
            f"已拒绝 {counts.get('rejected', 0)}",
        ]
        if data.get("matched") is not None and (
            self.search_entry.get_text().strip()
            or widgets.dropdown_value(self.status_filter)
        ):
            bits.append(f"匹配 {data.get('matched')} 条")
        if current_conv:
            bits.append(f"当前群缓存 {buffered} 条")
            bits.append(
                f"自动提取阈值 {settings.get('extract_min_messages', '—')} 条"
            )
        bits.append("同群人格共享")
        if not writable:
            bits.append("黑话库只读：上次读取失败")
        self.stats_label.set_text(" · ".join(bits))
        entries = data.get("entries") or []
        if not entries:
            self.list_box.append(self.empty("当前条件下没有词条。"))
            return
        for entry in entries:
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(str(entry.get("content") or ""), css="section-title"))
            status = str(entry.get("status") or "candidate")
            css = "badge badge-green" if status == "confirmed" else (
                "badge badge-red" if status == "rejected" else "badge badge-orange"
            )
            head.append(widgets.badge(STATUS_LABEL.get(status, status), css=css))
            head.append(widgets.muted(str(entry.get("conversation_id") or "")))
            head.set_hexpand(True)
            edit = widgets.button("编辑")
            edit.connect("clicked", lambda _b, e=entry: self._editor(e))
            head.append(edit)
            delete = widgets.button("删除", css="destructive-action")
            delete.connect("clicked", lambda _b, e=entry: self._delete(e))
            head.append(delete)
            card.append(head)
            meaning = str(entry.get("meaning") or "（未填写含义）")
            card.append(widgets.label("含义：" + meaning, wrap=True, selectable=True))
            extra = []
            if entry.get("usage"):
                extra.append("用法：" + str(entry["usage"]))
            if entry.get("example"):
                extra.append("示例：" + str(entry["example"]))
            if entry.get("risk"):
                extra.append("风险：" + str(entry["risk"]))
            if entry.get("count") is not None:
                extra.append(f"出现 {entry['count']} 次")
            if entry.get("persona_id"):
                extra.append("来源人格：" + str(entry["persona_id"]))
            if entry.get("source"):
                extra.append("来源：" + str(entry["source"]))
            if entry.get("rejection_reason"):
                extra.append("自动拒绝：" + str(entry["rejection_reason"]))
            if extra:
                card.append(widgets.muted(" · ".join(extra)))
            self.list_box.append(card)

    def _editor(self, entry: dict[str, Any] | None) -> None:
        window = widgets.FormWindow(
            self.app.window,
            "编辑黑话" if entry else "添加黑话",
            on_submit=lambda: _save(),
        )
        conv = Gtk.Entry()
        conv.set_text(str((entry or {}).get("conversation_id") or self.conversation_entry.get_text().strip()))
        conv.set_sensitive(entry is None)
        content = Gtk.Entry()
        content.set_text(str((entry or {}).get("content") or ""))
        meaning = widgets.text_view(str((entry or {}).get("meaning") or ""), height=90)
        usage = Gtk.Entry()
        usage.set_text(str((entry or {}).get("usage") or ""))
        example = Gtk.Entry()
        example.set_text(str((entry or {}).get("example") or ""))
        risk = Gtk.Entry()
        risk.set_text(str((entry or {}).get("risk") or ""))
        status = widgets.dropdown(
            [("candidate", "待确认"), ("confirmed", "已确认"), ("rejected", "已拒绝")],
            str((entry or {}).get("status") or "confirmed"),
        )
        window.add_row("群聊 ID", conv)
        window.add_row("词条", content)
        window.add_row("含义", meaning)
        window.add_row("使用场景", usage)
        window.add_row("示例", example)
        window.add_row("风险提示", risk)
        window.add_row("状态", status)
        if entry and entry.get("rejection_reason"):
            window.body_box.append(
                widgets.label(
                    "自动拒绝记录：" + str(entry["rejection_reason"]),
                    css="danger-text",
                    wrap=True,
                )
            )
        evidence = (entry or {}).get("evidence") or (entry or {}).get("sources") or []
        if evidence:
            window.body_box.append(widgets.label("证据", css="field-label"))
            window.body_box.append(
                widgets.label(
                    json.dumps(evidence, ensure_ascii=False, indent=2)
                    if isinstance(evidence, (dict, list))
                    else str(evidence),
                    css="monospace",
                    wrap=True,
                    selectable=True,
                )
            )
        error = widgets.muted("")
        window.body_box.append(error)

        def _save() -> None:
            if self.api is None:
                return
            payload = {
                "conversation_id": conv.get_text().strip(),
                "content": content.get_text().strip(),
                "meaning": widgets.text_value(meaning).strip(),
                "usage": usage.get_text().strip(),
                "example": example.get_text().strip(),
                "risk": risk.get_text().strip(),
                "status": widgets.dropdown_value(status),
            }
            if not payload["content"] or not payload["conversation_id"]:
                error.set_text("群聊 ID 和词条不能为空。")
                return
            if payload["status"] == "confirmed" and not payload["meaning"]:
                error.set_text("确认词条前必须填写含义。")
                return
            path = "/api/slang" if entry is None else f"/api/slang/{_quote(entry.get('id'))}"
            method = "post" if entry is None else "patch"

            def _do() -> Any:
                return getattr(self.api, method)(path, payload, timeout=30)

            def _done(_r: Any) -> None:
                window.close()
                self.toast("词条已保存")
                self.refresh()

            widgets.run_async(_do, on_success=_done, on_error=lambda exc: error.set_text(str(exc)))

        window.present()

    def _delete(self, entry: dict[str, Any]) -> None:
        def _do_delete() -> None:
            if self.api is None:
                return

            def _do() -> Any:
                return self.api.delete(f"/api/slang/{_quote(entry.get('id'))}", timeout=30)

            widgets.run_async(
                _do,
                on_success=lambda _r: (self.toast("已删除"), self.refresh()),
                on_error=lambda exc: self.toast(str(exc)),
            )

        widgets.ConfirmDialog(
            self.app.window,
            heading=f"删除「{entry.get('content') or '词条'}」？",
            body="不会影响聊天记录。",
            confirm_label="删除",
            destructive=True,
            on_confirm=_do_delete,
        )

    def _learn(self) -> None:
        conv = self.conversation_entry.get_text().strip()
        if not conv or self.api is None:
            self.toast("请先填写 group:<群号>")
            return

        def _do() -> Any:
            return self.api.post("/api/slang/learn", {"conversation_id": conv}, timeout=180)

        widgets.run_async(
            _do,
            on_success=lambda result: (self.toast(str(result.get("message") or "学习完成")), self.refresh()),
            on_error=lambda exc: self.toast(f"学习失败：{exc}"),
        )


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")
