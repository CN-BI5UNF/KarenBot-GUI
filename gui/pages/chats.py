"""Conversation browser page."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

_EMOJI_LABEL_RE = re.compile(r"\[表情包\s*[:：]\s*([^\]]+?)\s*\]")


class ChatsPage(Page):
    refresh_on_activate = True
    page_id = "chats"
    page_title = "对话"
    page_subtitle = "与 QQ 完全一致的收发记录。底部输入框可在不接 NapCat 的情况下直接试跑人格。"
    page_icon = "chat-bubbles-symbolic"

    def build(self) -> None:
        # 对话页是固定布局：会话/记录区吃满剩余高度，底部试跑框始终可见。
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.body.set_vexpand(True)
        self._selected_key = ""
        self._disposed = False
        self._load_serial = 0
        self._display_limit = 300
        self._last_signature: tuple[Any, ...] | None = None
        self._conversations: list[dict[str, Any]] = []
        self._conversations_signature: tuple[Any, ...] | None = None
        self._load_busy = False
        self._conversations_busy = False
        self._pending_display_reload = False
        self._last_conversations_at = 0.0
        self._search_timer = 0
        self._expanded_ids: set[str] = set()
        self._collapsed_ids: set[str] = set()
        self._last_display_data: dict[str, Any] | None = None
        self._building_display = False
        self._emoji_names: dict[str, str] = {}
        self._emoji_names_loaded = False
        self._emoji_names_busy = False
        self._emoji_textures: dict[str, Gdk.Texture] = {}
        self._emoji_texture_busy: set[str] = set()
        self._emoji_texture_waiters: dict[
            str, list[tuple[Gtk.Picture, Gtk.Label]]
        ] = {}
        header_row = self.header()
        inject = widgets.button("注入测试消息", icon="list-add-symbolic")
        inject.connect("clicked", lambda _b: self._inject_dialog())
        header_row.append(inject)
        self.body.append(header_row)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("搜索会话内容…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda _e: self._schedule_search())
        self.show_chat = Gtk.CheckButton(label="聊天")
        self.show_chat.set_active(True)
        self.show_system = Gtk.CheckButton(label="系统")
        self.show_system.set_active(True)
        self.show_tools = Gtk.CheckButton(label="工具")
        self.show_tools.set_active(True)
        self.show_reasoning = Gtk.CheckButton(label="思考")
        self.show_reasoning.set_active(True)
        self.media_only = Gtk.CheckButton(label="只看媒体")
        self.auto_refresh = Gtk.CheckButton(label="实时刷新")
        self.auto_refresh.set_active(True)
        for check in (
            self.show_chat,
            self.show_system,
            self.show_tools,
            self.show_reasoning,
            self.media_only,
        ):
            check.connect("toggled", lambda _c: self._reset_and_load())
        toolbar.append(self.search_entry)
        toolbar.append(self.show_chat)
        toolbar.append(self.show_system)
        toolbar.append(self.show_tools)
        toolbar.append(self.show_reasoning)
        toolbar.append(self.media_only)
        toolbar.append(self.auto_refresh)
        self.body.append(toolbar)

        # WebUI 的「默认展开」开关：只影响当前显示，不重新请求后端。
        expand_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        expand_row.add_css_class("toolbar")
        expand_row.append(widgets.label("默认展开", css="field-help"))
        self.expand_reasoning = Gtk.CheckButton(label="展开思考")
        self.expand_system = Gtk.CheckButton(label="展开系统")
        self.expand_tool_call = Gtk.CheckButton(label="展开工具调用")
        self.expand_tool_result = Gtk.CheckButton(label="展开工具返回/结果")
        for check in (
            self.expand_reasoning,
            self.expand_system,
            self.expand_tool_call,
            self.expand_tool_result,
        ):
            check.connect("toggled", lambda _c: self._rerender_display())
            expand_row.append(check)
        self.body.append(expand_row)

        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_position(310)
        paned.set_vexpand(True)
        paned.set_hexpand(True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left.set_size_request(280, -1)
        left.append(widgets.label("会话", css="section-title"))
        self.conversation_search = Gtk.SearchEntry()
        self.conversation_search.set_placeholder_text("搜索会话名或预览…")
        self.conversation_search.set_margin_top(6)
        self.conversation_search.set_margin_bottom(6)
        self.conversation_search.connect(
            "search-changed", lambda _e: self._render_conversations()
        )
        left.append(self.conversation_search)
        self.conversation_list = Gtk.ListBox()
        self.conversation_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.conversation_list.connect("row-selected", self._on_conversation)
        left_scroller = Gtk.ScrolledWindow()
        left_scroller.set_min_content_height(260)
        left_scroller.set_vexpand(True)
        left_scroller.set_child(self.conversation_list)
        self.conversation_scroller = left_scroller
        left.append(left_scroller)
        paned.set_start_child(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_margin_start(12)
        right_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.conversation_title = widgets.label("选择左侧会话", css="section-title")
        self.conversation_title.set_hexpand(True)
        self.more_button = widgets.button("加载更早")
        self.more_button.set_visible(False)
        self.more_button.connect("clicked", lambda _b: self._load_more())
        self.all_button = widgets.button("显示全部")
        self.all_button.set_visible(False)
        self.all_button.connect("clicked", lambda _b: self._show_all())
        self.reload_display_button = widgets.icon_button(
            "view-refresh-symbolic", "重新加载当前会话记录"
        )
        self.reload_display_button.connect(
            "clicked", lambda _b: self._manual_reload_display()
        )
        right_head.append(self.conversation_title)
        right_head.append(self.reload_display_button)
        right_head.append(self.more_button)
        right_head.append(self.all_button)
        right.append(right_head)
        self.display_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.display_scroller = Gtk.ScrolledWindow()
        self.display_scroller.set_min_content_height(260)
        self.display_scroller.set_vexpand(True)
        self.display_scroller.set_child(self.display_box)
        right.append(self.display_scroller)
        paned.set_end_child(right)
        self.body.append(paned)

        composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        composer.add_css_class("chat-composer")
        sender_label = widgets.label("发送者", css="field-label")
        composer.append(sender_label)
        self.composer_qq = Gtk.Entry()
        self.composer_qq.set_width_chars(8)
        self.composer_qq.set_text("10001")
        self.composer_qq.set_tooltip_text("发送者 QQ 号")
        composer.append(self.composer_qq)
        composer_input = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2
        )
        composer_input.set_hexpand(True)
        self.composer_entry = widgets.text_view("", height=48)
        self.composer_entry.set_hexpand(True)
        composer_view: Gtk.TextView = self.composer_entry.text_view  # type: ignore[attr-defined]
        composer_view.set_tooltip_text(
            "输入一条模拟消息：Enter 发送，Shift+Enter 换行"
        )
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._composer_key)
        composer_view.add_controller(key_controller)
        composer_input.append(self.composer_entry)
        composer_input.append(
            widgets.muted("Enter 发送 · Shift+Enter 换行")
        )
        composer.append(composer_input)
        send = widgets.button("发送", icon="mail-send-symbolic", css="suggested-action")
        send.connect("clicked", lambda _b: self._send_composer())
        composer.append(send)
        advanced = widgets.button("高级")
        advanced.set_tooltip_text("发送群聊消息或自定义昵称")
        advanced.connect("clicked", lambda _b: self._inject_dialog())
        composer.append(advanced)
        self.composer_send = send
        self.body.append(composer)
        GLib.timeout_add_seconds(5, self._poll)

    def _composer_key(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (
            state & Gdk.ModifierType.SHIFT_MASK
        ):
            self._send_composer()
            return True
        return False

    def _send_composer(self) -> None:
        text = widgets.text_value(self.composer_entry).strip()
        if not text or self.api is None:
            return
        user_id = self.composer_qq.get_text().strip() or "10001"
        payload = {
            "text": text,
            "user_id": user_id,
            "nickname": "测试用户",
            "scope": "private",
            "group_id": None,
        }
        self.composer_send.set_sensitive(False)

        def _do() -> dict[str, Any]:
            return self.api.post("/api/chats/inject", payload, timeout=30)

        def _done(result: dict[str, Any]) -> None:
            self.composer_send.set_sensitive(True)
            self.composer_entry.text_view.get_buffer().set_text("")  # type: ignore[attr-defined]
            conversation_id = str(result.get("conversation_id") or "")
            self.toast(str(result.get("message") or "消息已注入"))
            if result.get("blacklisted"):
                # The backend dropped the message, so there is no conversation
                # to select; keep the user where they were.
                self.refresh(load_display=False)
                return
            if conversation_id:
                self._selected_key = conversation_id
                self._last_signature = None
                self._last_display_data = None
                self._expanded_ids.clear()
                self._collapsed_ids.clear()
                self._display_limit = 300
                self._load_selected(scroll="bottom")
            self.refresh(load_display=False)

        def _failed(exc: BaseException) -> None:
            self.composer_send.set_sensitive(True)
            self.toast(f"发送失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    # ------------------------------------------------------------------
    def activate(self) -> None:
        super().activate()
        # The emoji library can change while this page is not visible. A
        # small names index is enough; image bytes are fetched only for labels
        # that actually occur in the visible records.
        self._load_emoji_names(force=True)

    def _load_emoji_names(self, *, force: bool = False) -> None:
        if self.api is None or self._emoji_names_busy:
            return
        if self._emoji_names_loaded and not force:
            return
        self._emoji_names_busy = True
        api = self.api

        def _fetch() -> dict[str, Any]:
            return api.get("/api/emoji/names", timeout=20)

        def _done(data: dict[str, Any]) -> None:
            self._emoji_names_busy = False
            self._emoji_names_loaded = True
            names = {
                str(item.get("name") or "").casefold(): str(
                    item.get("file") or ""
                )
                for item in data.get("items") or []
                if item.get("name") and item.get("file")
            }
            if names != self._emoji_names:
                self._emoji_names = names
                if self._last_display_data is not None:
                    self._rerender_display()

        def _failed(_exc: BaseException) -> None:
            self._emoji_names_busy = False
            self._emoji_names_loaded = True

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def _rich_text_widget(self, text: str) -> Gtk.Widget:
        """Chat bubble body with ``[表情包: name]`` replaced by thumbnails.

        The message text is never used to build a filesystem path: only the
        server-provided mapping is consulted, exactly like the WebUI.
        """
        source = str(text or "")
        if "[表情包" not in source or not self._emoji_names:
            return widgets.label(
                source, css="chat-text", wrap=True, selectable=True
            )
        segments: list[tuple[str, Any]] = []
        cursor = 0
        has_image = False
        for match in _EMOJI_LABEL_RE.finditer(source):
            if match.start() > cursor:
                segments.append(("text", source[cursor:match.start()]))
            name = match.group(1).strip()
            filename = self._emoji_names.get(name.casefold())
            if filename:
                segments.append(("emoji", (name, filename)))
                has_image = True
            else:
                segments.append(("text", match.group(0)))
            cursor = match.end()
        if cursor < len(source):
            segments.append(("text", source[cursor:]))
        if not has_image:
            return widgets.label(
                source, css="chat-text", wrap=True, selectable=True
            )
        # Merge adjacent text runs so that prose around an emoji stays one
        # wrapping label instead of one widget per fragment.
        merged: list[tuple[str, Any]] = []
        for kind, value in segments:
            if (
                kind == "text"
                and merged
                and merged[-1][0] == "text"
            ):
                merged[-1] = ("text", str(merged[-1][1]) + str(value))
            else:
                merged.append((kind, value))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("chat-rich-text")
        for kind, value in merged:
            if kind == "text":
                if str(value):
                    box.append(
                        widgets.label(
                            str(value),
                            css="chat-text",
                            wrap=True,
                            selectable=True,
                        )
                    )
                continue
            name, filename = value
            holder = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=4
            )
            placeholder = widgets.muted(f"[表情包: {name}]")
            picture = Gtk.Picture()
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_size_request(44, 44)
            picture.set_visible(False)
            picture.set_tooltip_text(name)
            holder.append(placeholder)
            holder.append(picture)
            box.append(holder)
            self._attach_emoji_texture(filename, picture, placeholder)
        return box

    def _attach_emoji_texture(
        self,
        filename: str,
        picture: Gtk.Picture,
        placeholder: Gtk.Label,
    ) -> None:
        cached = self._emoji_textures.get(filename)
        if cached is not None:
            picture.set_paintable(cached)
            picture.set_visible(True)
            placeholder.set_visible(False)
            return
        waiters = self._emoji_texture_waiters.setdefault(filename, [])
        waiters.append((picture, placeholder))
        if filename in self._emoji_texture_busy or self.api is None:
            return
        self._emoji_texture_busy.add(filename)
        api = self.api
        path = f"/api/emoji/file/{quote(filename, safe='')}"

        def _fetch() -> bytes:
            return api.raw(path, timeout=20)

        def _done(data: bytes) -> None:
            self._emoji_texture_busy.discard(filename)
            texture: Gdk.Texture | None
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except Exception:  # noqa: BLE001
                texture = None
            if texture is not None:
                self._emoji_textures[filename] = texture
            for pic, label in self._emoji_texture_waiters.pop(filename, []):
                if texture is not None:
                    pic.set_paintable(texture)
                    pic.set_visible(True)
                    label.set_visible(False)
                else:
                    label.set_text(label.get_text() + "（预览失败）")

        def _failed(_exc: BaseException) -> None:
            self._emoji_texture_busy.discard(filename)
            for _pic, label in self._emoji_texture_waiters.pop(filename, []):
                label.set_text(label.get_text() + "（加载失败）")

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def refresh(self, *, load_display: bool = True) -> None:
        if self.api is None:
            return
        if self._conversations_busy:
            self._pending_display_reload = (
                self._pending_display_reload or load_display
            )
            return
        self._conversations_busy = True
        self._last_conversations_at = time.monotonic()

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/chats/conversations", timeout=90)

        def _done(data: dict[str, Any]) -> None:
            self._conversations_busy = False
            previous = self._selected_key
            self._render_conversations(data)
            reload_display = load_display or self._pending_display_reload
            self._pending_display_reload = False
            if (
                reload_display
                and self._selected_key
                and self._selected_key == previous
            ):
                self._load_selected(scroll="preserve")

        def _failed(exc: BaseException) -> None:
            self._conversations_busy = False
            self._error(exc)

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)


    def _inject_dialog(self) -> None:
        window = widgets.FormWindow(
            self.app.window,
            "注入一条测试消息",
            width=560,
            height=520,
            submit_label="注入",
            on_submit=lambda: _send(),
        )
        text = widgets.text_view("", height=110)
        user_id = Gtk.Entry()
        user_id.set_text("10001")
        nickname = Gtk.Entry()
        nickname.set_text("测试用户")
        scope = widgets.dropdown([("private", "私聊"), ("group", "群聊")], "private")
        group_id = Gtk.Entry()
        group_id.set_placeholder_text("群聊时必填，例如 123456")
        window.add_row("消息正文", text)
        window.add_row("发送者 QQ", user_id)
        window.add_row("昵称", nickname)
        window.add_row("会话类型", scope)
        window.add_row("群号", group_id)
        error = widgets.muted("")
        window.body_box.append(error)

        def _send() -> None:
            if self.api is None:
                return
            payload = {
                "text": widgets.text_value(text).strip(),
                "user_id": user_id.get_text().strip() or "10001",
                "nickname": nickname.get_text().strip() or "测试用户",
                "scope": widgets.dropdown_value(scope) or "private",
                "group_id": group_id.get_text().strip() or None,
            }
            if not payload["text"]:
                error.set_text("消息正文不能为空。")
                return
            if payload["scope"] == "group" and not payload["group_id"]:
                error.set_text("群聊消息必须填写群号。")
                return

            def _do() -> dict[str, Any]:
                return self.api.post("/api/chats/inject", payload, timeout=30)

            def _done(result: dict[str, Any]) -> None:
                window.close()
                conversation_id = str(result.get("conversation_id") or "")
                if conversation_id:
                    self._selected_key = conversation_id
                    self._last_signature = None
                    self._last_display_data = None
                    self._expanded_ids.clear()
                    self._collapsed_ids.clear()
                    self._display_limit = 300
                self.toast(str(result.get("message") or "消息已注入"))
                if conversation_id:
                    self._load_selected(scroll="bottom")
                self.refresh(load_display=False)

            widgets.run_async(_do, on_success=_done, on_error=lambda exc: error.set_text(str(exc)))

        window.present()

    def _error(self, exc: BaseException) -> None:
        # Force the next successful poll to rebuild the list instead of
        # short-circuiting on the previous unchanged signature.
        self._conversations_signature = None
        widgets.clear(self.conversation_list)
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_child(widgets.muted(f"读取对话失败：{exc}"))
        self.conversation_list.append(row)

    def _render_conversations(self, data: dict[str, Any] | None = None) -> None:
        adjustment = self.conversation_scroller.get_vadjustment()
        old_value = adjustment.get_value()
        if data is not None:
            conversations = list(data.get("conversations") or [])
            signature = tuple(
                (
                    conv.get("key"),
                    conv.get("label"),
                    conv.get("preview"),
                    conv.get("record_count"),
                    conv.get("last_timestamp"),
                )
                for conv in conversations
            )
            if (
                signature == self._conversations_signature
                and self._conversations
            ):
                return
            self._conversations = conversations
            self._conversations_signature = signature
        widgets.clear(self.conversation_list)
        needle = self.conversation_search.get_text().strip().casefold()
        conversations = [
            conv
            for conv in self._conversations
            if not needle
            or needle
            in (
                str(conv.get("label") or "")
                + " "
                + str(conv.get("key") or "")
                + " "
                + str(conv.get("preview") or "")
            ).casefold()
        ]
        if not conversations:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.set_child(
                widgets.muted(
                    "没有匹配的会话。"
                    if self._conversations
                    else "暂无对话记录；收到消息后会出现在这里。"
                )
            )
            self.conversation_list.append(row)
            return
        selected_row: Gtk.ListBoxRow | None = None
        first_normal: Gtk.ListBoxRow | None = None
        for conv in conversations:
            row = Gtk.ListBoxRow()
            row.conversation_key = str(conv.get("key") or "")  # type: ignore[attr-defined]
            row.add_css_class("conversation-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            title = widgets.label(
                str(conv.get("label") or conv.get("key") or ""),
                css="conversation-title",
                ellipsize=True,
            )
            title.set_hexpand(True)
            head.append(title)
            count = conv.get("record_count")
            if count is not None:
                head.append(widgets.badge(f"{count} 条"))
            box.append(head)
            preview = str(conv.get("preview") or "")
            if preview:
                box.append(
                    widgets.label(
                        preview, css="conversation-preview", ellipsize=True
                    )
                )
            stamp = widgets.short_time(conv.get("last_timestamp"))
            if stamp:
                box.append(widgets.label(stamp, css="conversation-preview"))
            row.set_child(box)
            self.conversation_list.append(row)
            if row.conversation_key == self._selected_key:  # type: ignore[attr-defined]
                selected_row = row
            if (
                first_normal is None
                and not str(row.conversation_key).startswith("system:")
            ):
                first_normal = row
        if selected_row is not None:
            self.conversation_list.select_row(selected_row)
        elif not self._selected_key and first_normal is not None:
            self.conversation_list.select_row(first_normal)
        if old_value > 0:
            GLib.idle_add(
                lambda: (adjustment.set_value(old_value), False)[1]
            )

    def _on_conversation(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        key = getattr(row, "conversation_key", "")
        if not key:
            return
        if key != self._selected_key:
            self._selected_key = key
            self._display_limit = 300
            self._last_signature = None
            self._last_display_data = None
            self._expanded_ids.clear()
            self._collapsed_ids.clear()
            self.more_button.set_visible(False)
            self.all_button.set_visible(False)
            widgets.clear(self.display_box)
            self.display_box.append(widgets.muted("正在准备这个会话…"))
            self._load_selected(scroll="bottom")

    def _manual_reload_display(self) -> None:
        if not self._selected_key:
            return
        self._last_signature = None
        self._load_selected(scroll="preserve")

    def _schedule_search(self) -> None:
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(350, self._search_fired)

    def _search_fired(self) -> bool:
        self._search_timer = 0
        self._display_limit = 300
        self._load_selected(scroll="bottom")
        return False

    def _reset_and_load(self) -> None:
        self._display_limit = 300
        self._last_signature = None
        self._load_selected(scroll="bottom")

    def _load_more(self) -> None:
        if self._display_limit <= 0:
            return
        self._display_limit += 300
        self._load_selected(scroll="top")

    def _show_all(self) -> None:
        self._display_limit = 0
        self._load_selected(scroll="top")

    def _load_selected(
        self,
        *,
        silent: bool = False,
        scroll: str = "bottom",
    ) -> None:
        if self.api is None or not self._selected_key:
            return
        self._load_busy = True
        self._load_serial += 1
        serial = self._load_serial
        if not silent:
            self.conversation_title.set_text(f"正在加载 {self._selected_key}…")
        query = [
            f"conversation_id={_quote(self._selected_key)}",
            f"limit={self._display_limit}",
            f"show_chat={'true' if self.show_chat.get_active() else 'false'}",
            f"show_system={'true' if self.show_system.get_active() else 'false'}",
            f"show_tools={'true' if self.show_tools.get_active() else 'false'}",
            f"show_reasoning={'true' if self.show_reasoning.get_active() else 'false'}",
            f"media_only={'true' if self.media_only.get_active() else 'false'}",
        ]
        search = self.search_entry.get_text().strip()
        if search:
            query.append(f"q={_quote(search)}")
        path = "/api/chats/display?" + "&".join(query)

        def _fetch() -> dict[str, Any]:
            return self.api.get(path, timeout=90)

        def _done(data: dict[str, Any]) -> None:
            if serial != self._load_serial:
                return
            self._load_busy = False
            items = data.get("items") or []
            last = items[-1] if items else {}
            signature = (
                data.get("total"),
                data.get("filtered_total"),
                len(items),
                data.get("truncated"),
                last.get("timestamp"),
                str(last.get("text") or last.get("summary") or "")[:120],
            )
            if silent and signature == self._last_signature:
                return
            self._last_signature = signature
            self._render_display(data, scroll=scroll)

        def _failed(exc: BaseException) -> None:
            if serial != self._load_serial:
                return
            self._load_busy = False
            self._display_error(exc)

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def dispose(self) -> None:
        self._disposed = True
        self._load_serial += 1
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = 0
        self._emoji_texture_waiters.clear()
        self._emoji_texture_busy.clear()

    def _poll(self) -> bool:
        if self._disposed:
            return False
        if not self.get_mapped():
            return True
        if self.auto_refresh is None or not self.auto_refresh.get_active():
            return True
        now = time.monotonic()
        if (
            not self._conversations_busy
            and now - self._last_conversations_at >= 5
        ):
            self.refresh(load_display=False)
        if self._selected_key and not self._load_busy:
            self._load_selected(silent=True, scroll="preserve")
        return True

    def _display_error(self, exc: BaseException) -> None:
        self._last_display_data = None
        # 下一次轮询即使拿到与上次相同的数据也必须重新渲染，否则错误文本
        # 会永久留在页面上。
        self._last_signature = None
        self.conversation_title.set_text("加载失败")
        widgets.clear(self.display_box)
        self.display_box.append(widgets.muted(f"无法读取会话：{exc}"))

    def _render_display(self, data: dict[str, Any], *, scroll: str = "bottom") -> None:
        self._last_display_data = data
        adjustment = self.display_scroller.get_vadjustment()
        old_value = adjustment.get_value()
        at_bottom = (
            adjustment.get_upper() <= 0
            or old_value + adjustment.get_page_size()
            >= adjustment.get_upper() - 40
        )
        widgets.clear(self.display_box)
        conv = data.get("conversation") or {}
        title = str(conv.get("label") or self._selected_key)
        total = data.get("total")
        filtered = data.get("filtered_total")
        shown = filtered if filtered is not None else len(data.get("items") or [])
        self.conversation_title.set_text(
            f"{title} · {shown} 项"
            + (f" / {total} 条记录" if total else "")
        )
        items = data.get("items") or []
        total_count = int(total or 0)
        filtered_count = int(filtered or 0)
        hidden = max(0, filtered_count - len(items))
        self.more_button.set_visible(hidden > 0 and self._display_limit > 0)
        self.more_button.set_label(f"加载更早（{min(hidden, 300)}）")
        self.all_button.set_visible(hidden > 0)
        self._building_display = True
        try:
            if not items:
                if total_count > 0 and filtered_count == 0:
                    self.display_box.append(
                        widgets.muted(
                            "当前过滤条件下没有内容。试试勾上「聊天」或「系统」，"
                            "或清空搜索词。"
                        )
                    )
                else:
                    self.display_box.append(
                        widgets.muted("这个会话还没有可显示的记录。")
                    )
            for item in items:
                self.display_box.append(self._display_row(item))
            if hidden > 0:
                self.display_box.append(
                    widgets.muted(
                        f"还有 {hidden} 条更早的记录未显示；可点上方"
                        "「加载更早」或「显示全部」。"
                    )
                )
            elif data.get("truncated"):
                self.display_box.append(widgets.muted("已显示全部记录。"))
        finally:
            self._building_display = False
        mode = scroll
        if mode == "preserve" and at_bottom:
            mode = "bottom"
        GLib.timeout_add(
            60,
            lambda: self._restore_scroll(mode, old_value),
        )

    def _restore_scroll(self, mode: str, old_value: float) -> bool:
        adjustment = self.display_scroller.get_vadjustment()
        if mode == "bottom":
            adjustment.set_value(max(0.0, adjustment.get_upper() - adjustment.get_page_size()))
        elif mode == "top":
            adjustment.set_value(0.0)
        else:
            adjustment.set_value(old_value)
        return False

    def _rerender_display(self) -> None:
        """Apply the default-expand switches without another backend request."""
        if self._last_display_data is None:
            return
        self._render_display(self._last_display_data, scroll="preserve")

    def _is_expanded(self, item: dict[str, Any]) -> bool:
        """Per-item user action wins over the four default-expand switches."""
        item_id = _item_id(item)
        if item_id in self._expanded_ids:
            return True
        if item_id in self._collapsed_ids:
            return False
        kind = str(item.get("kind") or "")
        if kind == "reasoning":
            return self.expand_reasoning.get_active()
        if kind in {"system_event", "runtime_receipt", "assistant_note"}:
            return self.expand_system.get_active()
        if kind == "tool_call":
            return self.expand_tool_call.get_active()
        if kind == "tool_result":
            return self.expand_tool_result.get_active()
        return False

    def _remember_expanded(self, item: dict[str, Any], expanded: bool) -> None:
        if self._building_display:
            return
        item_id = _item_id(item)
        if expanded:
            self._collapsed_ids.discard(item_id)
            self._expanded_ids.add(item_id)
        else:
            self._expanded_ids.discard(item_id)
            self._collapsed_ids.add(item_id)

    def _collapsible_row(
        self,
        item: dict[str, Any],
        *,
        extra_class: str = "",
        nested: bool = False,
    ) -> Gtk.Widget:
        """Summary header plus expandable full text, matching WebUI behavior."""
        kind = str(item.get("kind") or "")
        label = _KIND_LABELS.get(kind, kind or "记录")
        speaker = str(item.get("speaker_label") or item.get("role_label") or "")
        stamp = widgets.short_time(item.get("timestamp"))
        summary = " ".join(str(item.get("summary") or "").split())[:160]
        severity = str(item.get("severity") or "normal")
        prefix = "警告 · " if severity == "warning" else "错误 · " if severity == "error" else ""
        bits = [prefix + label]
        if speaker and speaker != label:
            bits.append(speaker)
        if stamp:
            bits.append(stamp)
        if summary:
            bits.append(summary)
        expander = Gtk.Expander(label=" · ".join(bits))
        expander.add_css_class("chat-expander")
        expander.set_expanded(self._is_expanded(item))
        full_text = str(item.get("text") or "")
        truncated = kind == "tool_result" and len(full_text) > 4000
        text = full_text[:4000] if truncated else full_text
        if text:
            wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            wrapper.set_margin_start(16)
            wrapper.append(self._rich_text_widget(text))
            if truncated:
                wrapper.append(
                    widgets.muted(
                        f"工具结果较长（{len(full_text)} 字符），此处仅显示前 4000 字符。"
                    )
                )
                show_full = widgets.button("查看完整结果")
                show_full.connect(
                    "clicked",
                    lambda _b, value=full_text: self._show_full_text(
                        "工具结果", value
                    ),
                )
                wrapper.append(show_full)
            expander.set_child(wrapper)
        expander.connect(
            "notify::expanded",
            lambda widget, _param, current=item: self._remember_expanded(
                current, widget.get_expanded()
            ),
        )
        if not nested:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            row.add_css_class("chat-row")
            if extra_class:
                row.add_css_class(extra_class)
            row.append(expander)
            return row
        return expander

    def _show_full_text(self, title: str, text: str) -> None:
        window = widgets.FormWindow(
            self.app.window,
            title,
            width=820,
            height=640,
            submit_label="关闭",
            on_submit=lambda: window.close(),
        )
        window.cancel_button.set_visible(False)
        area = widgets.text_view(text, height=520, monospace=True)
        window.add_row("完整内容（可选中复制）", area)
        window.present()

    def _display_row(self, item: dict[str, Any]) -> Gtk.Widget:
        kind = str(item.get("kind") or "chat")
        if kind == "tool_call":
            # 对应 WebUI 的结构：工具调用本身可折叠，返回项永远挂在下面，
            # 每个返回项仍按自己的默认展开开关/单条操作独立折叠。
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            row.add_css_class("chat-row")
            row.add_css_class("chat-tool")
            row.append(self._collapsible_row(item, nested=True))
            results = item.get("tool_results") or []
            if results:
                result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                result_box.add_css_class("tool-results")
                for result in results:
                    result_box.append(
                        self._collapsible_row(result, extra_class="chat-tool", nested=True)
                    )
                row.append(result_box)
            return row
        if kind in {
            "reasoning",
            "assistant_note",
            "system_event",
            "runtime_receipt",
            "tool_result",
        }:
            return self._collapsible_row(
                item,
                extra_class=f"chat-{kind}",
            )

        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        row.add_css_class("chat-row")
        row.add_css_class(f"chat-{kind}")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        speaker = str(item.get("speaker_label") or item.get("role_label") or kind)
        head.append(widgets.label(speaker, css="chat-speaker"))
        stamp = widgets.short_time(item.get("timestamp"))
        if stamp:
            head.append(widgets.label(stamp, css="muted"))
        summary = str(item.get("summary") or "").strip()
        if summary:
            head.append(
                widgets.label(summary, css="muted", ellipsize=True)
            )
        severity = str(item.get("severity") or "normal")
        if severity in {"error", "warning"}:
            head.append(
                widgets.label(
                    severity,
                    css="badge badge-red" if severity == "error" else "badge-orange",
                )
            )
        head.set_hexpand(True)
        row.append(head)
        text = str(item.get("text") or "")
        if text:
            row.append(self._rich_text_widget(text))
        elif kind in {"inbound_message", "outbound_message"}:
            row.append(widgets.muted("（空）"))
        return row


_KIND_LABELS = {
    "reasoning": "思考",
    "tool_call": "工具调用",
    "tool_result": "工具结果",
    "system_event": "系统",
    "runtime_receipt": "回执",
    "assistant_note": "备注",
}


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or f"{item.get('kind')}:{item.get('timestamp')}:{item.get('summary')}")


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
