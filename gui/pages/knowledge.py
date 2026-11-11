"""Knowledge notebook: search, CRUD and manual web research."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

KINDS = [("meme", "梗"), ("fact", "资料"), ("note", "笔记")]


class KnowledgePage(Page):
    refresh_on_activate = True
    page_id = "knowledge"
    page_title = "知识 / 热梗"
    page_subtitle = "LLM 联网考究产生的笔记；只有启用条目能被模型按需查询，可选共享给其他人格只读引用。"
    page_icon = "accessories-dictionary-symbolic"

    def build(self) -> None:
        self._persona_id = ""
        self._search_timer = 0
        header_row = self.header()
        settings_button = widgets.button("考究设置")
        settings_button.connect(
            "clicked", lambda _b: self.app.show_page("settings", section="features")
        )
        header_row.append(settings_button)
        self.add_button = widgets.button(
            "手动添加", icon="list-add-symbolic", css="suggested-action"
        )
        self.add_button.connect("clicked", lambda _b: self._editor(None))
        header_row.append(self.add_button)
        self.trend_button = widgets.button("获取当前热梗")
        self.trend_button.connect("clicked", lambda _b: self._trends())
        header_row.append(self.trend_button)
        self.body.append(header_row)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("搜索标题 / 内容 / 标签…")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda _e: self._schedule_search())
        self.kind_filter = widgets.dropdown([("", "全部类型")] + KINDS, "")
        self.kind_filter.connect("notify::selected", lambda *_: self.refresh())
        self.status_filter = widgets.dropdown(
            [("", "全部状态"), ("active", "启用"), ("archived", "归档")], ""
        )
        self.status_filter.connect("notify::selected", lambda *_: self.refresh())
        toolbar.append(self.search_entry)
        toolbar.append(self.kind_filter)
        toolbar.append(self.status_filter)
        self.body.append(toolbar)
        self.stats_label = widgets.muted("")
        self.body.append(self.stats_label)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.list_box)

        research = widgets.card(spacing=8)
        research.append(widgets.section_header("联网考究", "让后台模型搜索并整理成短笔记"))
        research_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.research_entry = Gtk.Entry()
        self.research_entry.set_placeholder_text("例如：本周网络热梗 / 某版本发布时间")
        self.research_entry.set_hexpand(True)
        self.research_kind = widgets.dropdown(KINDS, "meme")
        research_row.append(self.research_entry)
        research_row.append(self.research_kind)
        self.research_button = widgets.button("执行考究", css="suggested-action")
        self.research_button.connect("clicked", lambda _b: self._research())
        research_row.append(self.research_button)
        research.append(research_row)
        self.body.append(research)

    def _schedule_search(self) -> None:
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(300, self._search_fired)

    def _search_fired(self) -> bool:
        self._search_timer = 0
        self.refresh()
        return False

    def refresh(self) -> None:
        if self.api is None:
            return
        from urllib.parse import quote

        params = []
        query = self.search_entry.get_text().strip()
        kind = widgets.dropdown_value(self.kind_filter)
        status = widgets.dropdown_value(self.status_filter)
        if query:
            params.append(f"query={quote(query, safe='')}")
        if kind:
            params.append(f"kind={kind}")
        if status:
            params.append(f"status={status}")
        path = "/api/knowledge" + (("?" + "&".join(params)) if params else "")

        def _fetch() -> dict[str, Any]:
            return self.api.get(path, timeout=30)

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.list_box)
        self.list_box.append(widgets.muted(f"读取知识库失败：{exc}"))

    def _render(self, data: dict[str, Any]) -> None:
        widgets.clear(self.list_box)
        entries = data.get("entries") or []
        stats = data.get("stats") or {}
        kinds = stats.get("kinds") or {}
        settings = data.get("settings") or {}
        state = data.get("state") or {}
        self._persona_id = str(data.get("persona_id") or "")
        writable = data.get("writable") is not False
        self.add_button.set_sensitive(writable)
        self.research_button.set_sensitive(writable)
        self.trend_button.set_sensitive(writable)
        bits = [
            f"共 {stats.get('total', len(entries))} 条",
            f"梗 {kinds.get('meme', 0)}",
            f"资料 {kinds.get('fact', 0)}",
            f"笔记 {kinds.get('note', 0)}",
        ]
        if stats.get("shared"):
            bits.append(f"共享 {stats['shared']} 条")
        bits.append(
            f"查询返回上限 {settings.get('inject_max', '—')} 条 / "
            f"{settings.get('max_prompt_chars', '—')} 字符"
        )
        bits.append(
            "后台考究"
            + (
                f"每 {settings.get('research_interval_hours', '—')} 小时"
                if settings.get("auto_research_enabled")
                else "已关闭"
            )
        )
        if state.get("last_trend_run_at"):
            bits.append(f"上次热梗考究：{widgets.short_time(state['last_trend_run_at'])}")
        if not writable:
            bits.append("知识库只读：上次读取失败")
        self.stats_label.set_text(" · ".join(bits))
        if not entries:
            self.list_box.append(self.empty("知识库还是空的。"))
            return
        for entry in entries:
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            kind = str(entry.get("kind") or "note")
            head.append(widgets.badge(dict(KINDS).get(kind, kind)))
            foreign_shared = bool(
                entry.get("shared")
                and entry.get("persona_id")
                and self._persona_id
                and str(entry.get("persona_id")) != self._persona_id
            )
            if entry.get("shared"):
                head.append(widgets.badge("共享"))
            if foreign_shared:
                head.append(widgets.badge("只读", css="badge badge-orange"))
            if entry.get("status") == "archived":
                head.append(widgets.badge("归档", css="badge badge-orange"))
            title_label = widgets.label(
                str(entry.get("title") or "无标题"), css="section-title", wrap=True
            )
            title_label.set_hexpand(True)
            head.append(title_label)
            editable = writable and not foreign_shared
            if editable:
                edit = widgets.button("编辑")
                edit.connect("clicked", lambda _b, e=entry: self._editor(e))
                head.append(edit)
                delete = widgets.button("删除", css="destructive-action")
                delete.connect("clicked", lambda _b, e=entry: self._delete(e))
                head.append(delete)
            card.append(head)
            content = str(entry.get("content") or "")
            card.append(widgets.label(content, wrap=True, selectable=True))
            meta = []
            tags = entry.get("tags") or []
            if tags:
                meta.append("标签：" + "、".join(str(x) for x in tags))
            if entry.get("usage"):
                meta.append("语境：" + str(entry.get("usage")))
            sources = entry.get("sources") or []
            if sources:
                meta.append("来源：" + "、".join(str(x) for x in sources[:3]))
            if entry.get("confidence") is not None:
                try:
                    meta.append(f"置信度 {float(entry['confidence']):.2f}")
                except (TypeError, ValueError):
                    pass
            stamp = widgets.short_time(entry.get("updated_at"))
            if stamp:
                meta.append(stamp)
            if meta:
                card.append(widgets.muted(" · ".join(meta)))
            self.list_box.append(card)

    def _editor(self, entry: dict[str, Any] | None) -> None:
        window = widgets.FormWindow(
            self.app.window,
            "编辑知识笔记" if entry else "添加知识笔记",
            submit_label="保存",
            on_submit=lambda: _save(),
        )
        kind = widgets.dropdown(KINDS, str((entry or {}).get("kind") or "note"))
        title = Gtk.Entry()
        title.set_text(str((entry or {}).get("title") or ""))
        content = widgets.text_view(str((entry or {}).get("content") or ""), height=160)
        usage = Gtk.Entry()
        usage.set_text(str((entry or {}).get("usage") or ""))
        tags = Gtk.Entry()
        tags.set_text(", ".join(str(x) for x in ((entry or {}).get("tags") or [])))
        sources = Gtk.Entry()
        sources.set_text(", ".join(str(x) for x in ((entry or {}).get("sources") or [])))
        status = widgets.dropdown(
            [("active", "启用"), ("archived", "归档")],
            str((entry or {}).get("status") or "active"),
        )
        shared = widgets.switch(bool((entry or {}).get("shared")))
        confidence = Gtk.SpinButton.new_with_range(0, 1, 0.05)
        confidence.set_digits(2)
        try:
            confidence.set_value(float((entry or {}).get("confidence") or 1.0))
        except (TypeError, ValueError):
            confidence.set_value(1.0)
        window.add_row("类型", kind)
        window.add_row("标题", title)
        window.add_row("内容", content)
        window.add_row("使用语境", usage)
        window.add_row("标签（逗号分隔）", tags)
        window.add_row("来源（逗号分隔）", sources)
        window.add_row("状态", status)
        shared_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        shared_row.append(shared)
        shared_row.append(widgets.muted("允许其他人格只读引用"))
        window.add_row("共享", shared_row)
        window.add_row("置信度", confidence)
        error = widgets.muted("")
        window.body_box.append(error)

        def _split(value: str) -> list[str]:
            return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]

        def _save() -> None:
            if self.api is None:
                return
            payload = {
                "kind": widgets.dropdown_value(kind),
                "title": title.get_text().strip(),
                "content": widgets.text_value(content).strip(),
                "usage": usage.get_text().strip(),
                "tags": _split(tags.get_text()),
                "sources": _split(sources.get_text()),
                "status": widgets.dropdown_value(status),
                "shared": shared.get_active(),
                "confidence": float(confidence.get_value()),
            }
            if not payload["title"] or not payload["content"]:
                error.set_text("标题和内容不能为空。")
                return
            path = "/api/knowledge" if entry is None else f"/api/knowledge/{_quote(entry.get('id'))}"
            method = "post" if entry is None else "patch"

            def _do() -> Any:
                return getattr(self.api, method)(path, payload, timeout=60)

            def _finish() -> None:
                window.close()
                self.toast("知识笔记已保存")
                self.refresh()

            def _done(result: Any) -> None:
                confidence_value = float(confidence.get_value())
                if (
                    entry is None
                    and abs(confidence_value - 1.0) > 1e-9
                    and isinstance(result, dict)
                ):
                    new_id = (result.get("entry") or {}).get("id")
                    if new_id:
                        def _patch() -> Any:
                            return self.api.patch(
                                f"/api/knowledge/{_quote(new_id)}",
                                {"confidence": confidence_value},
                                timeout=60,
                            )

                        def _patched(_r: Any) -> None:
                            _finish()

                        def _patch_failed(exc: BaseException) -> None:
                            error.set_text(
                                f"笔记已创建，但写入置信度失败：{exc}"
                            )

                        widgets.run_async(
                            _patch,
                            on_success=_patched,
                            on_error=_patch_failed,
                        )
                        return
                _finish()

            def _failed(exc: BaseException) -> None:
                error.set_text(str(exc))

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        window.present()

    def _delete(self, entry: dict[str, Any]) -> None:
        def _delete_now() -> None:
            if self.api is None:
                return

            def _do() -> Any:
                return self.api.delete(f"/api/knowledge/{_quote(entry.get('id'))}", timeout=30)

            widgets.run_async(
                _do,
                on_success=lambda _r: (self.toast("已删除"), self.refresh()),
                on_error=lambda exc: self.toast(str(exc)),
            )

        widgets.ConfirmDialog(
            self.app.window,
            heading=f"删除「{entry.get('title') or '这条笔记'}」？",
            body="删除后模型将查询不到这条知识。",
            confirm_label="删除",
            destructive=True,
            on_confirm=_delete_now,
        )

    def _trends(self) -> None:
        if self.api is None:
            return

        def _do() -> None:
            self.trend_button.set_sensitive(False)
            self.toast("正在刷新当前热梗，可能需要一段时间…")

            def _request() -> dict[str, Any]:
                return self.api.post("/api/knowledge/trends", {}, timeout=300)

            def _done(result: dict[str, Any]) -> None:
                self.trend_button.set_sensitive(True)
                if result.get("skipped"):
                    self.toast(str(result.get("reason") or "热梗考究已跳过"))
                else:
                    self.toast(
                        f"热梗考究完成：保存 {result.get('saved', 0)} 条"
                        + (
                            f"，跳过 {result.get('duplicates', 0)} 条"
                            if result.get("duplicates")
                            else ""
                        )
                    )
                self.refresh()

            def _failed(exc: BaseException) -> None:
                self.trend_button.set_sensitive(True)
                self.toast(f"热梗考究失败：{exc}")

            widgets.run_async(_request, on_success=_done, on_error=_failed)

        widgets.ConfirmDialog(
            self.app.window,
            heading="刷新当前网络热梗？",
            body="会调用搜索与模型，并按设置保存新笔记；可能产生 API 费用。",
            confirm_label="开始考究",
            on_confirm=_do,
        )

    def _research(self) -> None:
        query = self.research_entry.get_text().strip()
        if not query or self.api is None:
            self.toast("请先填写考究主题")
            return
        payload = {
            "query": query,
            "kind": widgets.dropdown_value(self.research_kind),
            "max_notes": 8,
            "save": True,
        }
        self.toast("正在联网考究，可能需要一段时间…")

        def _do() -> Any:
            return self.api.post("/api/knowledge/research", payload, timeout=180)

        widgets.run_async(
            _do,
            on_success=lambda _r: (self.toast("考究完成"), self.refresh()),
            on_error=lambda exc: self.toast(f"考究失败：{exc}"),
        )


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")
