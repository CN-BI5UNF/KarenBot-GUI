"""Important-memory CRUD and RAG index browser."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class MemoryPage(Page):
    refresh_on_activate = True
    page_id = "memory"
    page_title = "记忆"
    page_subtitle = "跨会话长期保留的事实。置顶的记忆每次都进上下文。"
    page_icon = "user-bookmarks-symbolic"

    def build(self) -> None:
        header_row = self.header()
        self.mode_badge = widgets.badge("模式：—")
        header_row.append(self.mode_badge)
        self.body.append(header_row)
        add_card = widgets.card(spacing=8)
        add_card.append(widgets.section_header("新增记忆", "重复内容不会被重复保存"))
        self.new_entry = widgets.text_view("", height=70)
        add_card.append(self.new_entry)
        add_card.append(widgets.muted("支持多行；重复内容不会被重复保存。"))
        add_button = widgets.button("记下来", css="suggested-action")
        add_button.connect("clicked", lambda _b: self._add())
        add_card.append(add_button)
        self.body.append(add_card)

        switch = Gtk.StackSwitcher()
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switch.set_stack(self.stack)
        self.body.append(switch)
        important_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.stack.add_titled(important_box, "important", "重要记忆")
        self.important_box = important_box
        rag_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.stack.add_titled(rag_box, "rag", "RAG 历史索引")
        self.rag_box = rag_box
        self.stack.connect("notify::visible-child", lambda *_: self._tab_changed())
        self.body.append(self.stack)

    def refresh(self) -> None:
        if self.api is None:
            return
        if self.stack.get_visible_child_name() == "rag":
            self._load_rag()
        else:
            self._load_important()

    def _tab_changed(self) -> None:
        if self.stack.get_visible_child_name() == "rag":
            self._load_rag()
        else:
            self._load_important()

    def _load_important(self) -> None:
        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/memory", timeout=30)

        widgets.run_async(_fetch, on_success=self._render_important, on_error=self._error)

    def _load_rag(self) -> None:
        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/memory/rag?limit=300", timeout=30)

        widgets.run_async(_fetch, on_success=self._render_rag, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        box = self.rag_box if self.stack.get_visible_child_name() == "rag" else self.important_box
        widgets.clear(box)
        box.append(widgets.muted(f"读取失败：{exc}"))

    def _render_important(self, data: dict[str, Any]) -> None:
        widgets.clear(self.important_box)
        mode = str(data.get("mode") or "file")
        self.mode_badge.set_text(f"模式：{mode}")
        items = data.get("items") or []
        if not items:
            self.important_box.append(self.empty("还没有保存任何重要记忆。"))
            return
        for item in items:
            row = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            scope = str(item.get("scope") or "全局")
            head.append(widgets.badge(scope))
            stamp = widgets.short_time(item.get("timestamp"))
            if stamp:
                head.append(widgets.muted(stamp))
            head.set_hexpand(True)
            item_id = item.get("id")
            pin = Gtk.CheckButton(label="置顶")
            pin.set_active(bool(item.get("pinned")))
            pin.connect(
                "toggled",
                lambda w, i=item_id: self._set_pinned(i, w.get_active()),
            )
            head.append(pin)
            delete = widgets.button("删除")
            delete.add_css_class("destructive-action")
            delete.connect("clicked", lambda _b, i=item_id: self._delete(i))
            head.append(delete)
            row.append(head)
            row.append(widgets.label(str(item.get("content") or ""), wrap=True, selectable=True))
            self.important_box.append(row)

    def _render_rag(self, data: dict[str, Any]) -> None:
        widgets.clear(self.rag_box)
        if not data.get("available"):
            self.rag_box.append(
                self.empty(
                    str(data.get("error") or "RAG 未启用。请在设置 → 记忆里切换到 rag 模式并重启 Runtime。")
                )
            )
            return
        self.rag_box.append(
            widgets.muted(
                f"共 {data.get('count', 0)} 条；向量服务"
                f"{'已就绪' if data.get('embedding_ready') else '未就绪'}。"
            )
        )
        entries = data.get("entries") or []
        if not entries:
            self.rag_box.append(self.empty("RAG 索引里还没有条目。"))
            return
        for entry in entries:
            row = widgets.card(spacing=4)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(str(entry.get("conversation_id") or "—"), css="monospace"))
            head.append(widgets.muted(str(entry.get("timestamp") or "")))
            row.append(head)
            row.append(widgets.label(str(entry.get("content") or ""), wrap=True, selectable=True))
            self.rag_box.append(row)

    def _add(self) -> None:
        content = widgets.text_value(self.new_entry).strip()
        if not content or self.api is None:
            return
        buffer = self.new_entry.text_view.get_buffer()  # type: ignore[attr-defined]
        buffer.set_text("")

        def _do() -> dict[str, Any]:
            return self.api.post("/api/memory", {"content": content, "pinned": False}, timeout=30)

        def _done(result: dict[str, Any]) -> None:
            self.toast(str(result.get("message") or "已保存"))
            self._load_important()

        widgets.run_async(_do, on_success=_done, on_error=lambda exc: self.toast(str(exc)))

    def _set_pinned(self, item_id: Any, pinned: bool) -> None:
        if self.api is None or not item_id:
            return

        def _do() -> Any:
            return self.api.patch(f"/api/memory/{_quote(item_id)}", {"pinned": pinned}, timeout=30)

        widgets.run_async(
            _do,
            on_success=lambda _r: self.toast("已更新"),
            on_error=lambda exc: (self.toast(str(exc)), self._load_important()),
        )

    def _delete(self, item_id: Any) -> None:
        if self.api is None or not item_id:
            return

        def _do() -> Any:
            return self.api.delete(f"/api/memory/{_quote(item_id)}", timeout=30)

        widgets.ConfirmDialog(
            self.app.window,
            heading="删除这条重要记忆？",
            body="删除后模型将无法再查询到它。",
            confirm_label="删除",
            destructive=True,
            on_confirm=lambda: widgets.run_async(
                _do,
                on_success=lambda _r: (
                    self.toast("已删除"),
                    self._load_important(),
                ),
                on_error=lambda exc: self.toast(str(exc)),
            ),
        )


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")
