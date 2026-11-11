"""Persona list, activation, appearance, editing and import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from ..api import q  # noqa: E402
from .base import Page  # noqa: E402
from .destructive_admin import open_persona_cleanup  # noqa: E402
from .persona_dialogs import (  # noqa: E402
    export_persona,
    open_ai_creator,
    open_direct_editor,
    open_refiner,
)

IMAGE_PATTERNS = ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.bmp"]


class PersonasPage(Page):
    refresh_on_activate = True
    page_id = "personas"
    page_title = "人格"
    page_subtitle = "每个人格是 personas/ 下的一个目录；切换人格需要重启 Runtime，角色形象会作为只读知识供模型查看。"
    page_icon = "avatar-default-symbolic"

    def build(self) -> None:
        self.header_row = self.header()
        create_button = widgets.button(
            "AI 新建", icon="list-add-symbolic", css="suggested-action"
        )
        create_button.connect(
            "clicked", lambda _b: open_ai_creator(self, self.refresh)
        )
        self.header_row.append(create_button)
        direct_button = widgets.button("直接写提示词")
        direct_button.connect(
            "clicked", lambda _b: open_direct_editor(self, None, self.refresh)
        )
        self.header_row.append(direct_button)
        import_button = widgets.button("导入角色", icon="document-open-symbolic")
        import_button.connect("clicked", lambda _b: self._import())
        self.header_row.append(import_button)
        self.body.append(self.header_row)
        self.summary = widgets.muted("")
        self.body.append(self.summary)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.list_box)

    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/personas", timeout=30)

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.list_box)
        self.list_box.append(widgets.muted(f"读取角色失败：{exc}"))

    def _render(self, data: dict[str, Any]) -> None:
        widgets.clear(self.list_box)
        personas = data.get("personas") or []
        active = str(data.get("active") or "")
        self.summary.set_text(f"共 {len(personas)} 个角色 · 当前：{active or '—'}")
        for persona in personas:
            name = str(persona.get("name") or persona.get("id") or "")
            count = int(persona.get("appearance_count") or 0)
            box = widgets.card(spacing=6)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            if count:
                content.append(self._list_thumbnail(name))
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            info.set_hexpand(True)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(name, css="section-title"))
            if persona.get("active"):
                head.append(widgets.badge("当前使用", css="badge badge-green"))
            if persona.get("builtin"):
                head.append(widgets.badge("内置"))
            if count:
                head.append(widgets.badge(f"{count} 张形象"))
            head.set_hexpand(True)
            info.append(head)
            description = str(persona.get("description") or "")
            if description:
                info.append(widgets.muted(description))
            content.append(info)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if count:
                gallery = widgets.button(f"形象（{count}）")
                gallery.connect(
                    "clicked", lambda _b, n=name: self._show_appearance(n)
                )
                actions.append(gallery)
            edit = widgets.button("编辑")
            edit.connect(
                "clicked",
                lambda _b, n=name: open_direct_editor(self, n, self.refresh),
            )
            actions.append(edit)
            if not persona.get("active"):
                activate = widgets.button("激活", css="suggested-action")
                activate.connect(
                    "clicked", lambda _b, n=name: self._activate(n)
                )
                actions.append(activate)
            menu_items: list[tuple[str, Any, bool]] = [
                ("查看人设", lambda n=name: self._show_source(n), False),
                ("AI 改写", lambda n=name: open_refiner(self, n, self.refresh), False),
                ("导出", lambda n=name: export_persona(self, n), False),
                ("复制", lambda n=name: self._duplicate_dialog(n), False),
                (
                    "清理运行数据",
                    lambda n=name: open_persona_cleanup(
                        self, n, on_done=self.refresh
                    ),
                    True,
                ),
            ]
            if not persona.get("builtin"):
                menu_items.append(
                    ("删除人格定义", lambda n=name: self._confirm_delete(n), True)
                )
            actions.append(self._more_menu(menu_items))
            content.append(actions)
            box.append(content)
            self.list_box.append(box)

    def _list_thumbnail(self, name: str) -> Gtk.Picture:
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.set_size_request(56, 56)
        picture.set_valign(Gtk.Align.CENTER)
        path = f"/api/personas/{q(name)}/appearance/file"

        def _load() -> bytes:
            return self.api.raw(path, timeout=30)

        def _loaded(data: bytes) -> None:
            try:
                picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
            except Exception:  # noqa: BLE001
                picture.set_visible(False)

        widgets.run_async(
            _load,
            on_success=_loaded,
            on_error=lambda _e: picture.set_visible(False),
        )
        return picture

    def _more_menu(self, items: list[tuple[str, Any, bool]]) -> Gtk.MenuButton:
        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_tooltip_text("更多操作")
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_size_request(150, -1)
        for label, callback, destructive in items:
            item = Gtk.Button(label=label)
            item.set_halign(Gtk.Align.FILL)
            item.add_css_class("flat")
            if destructive:
                item.add_css_class("destructive-action")
            item.connect(
                "clicked",
                lambda _b, cb=callback, pop=popover: (pop.popdown(), cb()),
            )
            box.append(item)
        popover.set_child(box)
        button.set_popover(popover)
        return button

    def _activate(self, name: str) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post(f"/api/personas/{q(name)}/activate", {}, timeout=120)

        def _done(result: dict[str, Any]) -> None:
            self.toast(str(result.get("message") or f"已切换到 {name}"))
            self.refresh()
            if result.get("needs_restart"):
                widgets.ConfirmDialog(
                    self.app.window,
                    heading="切换角色需要重启 Runtime",
                    body="提示词已保存；重启 Runtime 后新角色才会生效。现在重启？",
                    confirm_label="立即重启",
                    on_confirm=self._restart_runtime,
                )

        widgets.run_async(
            _do,
            on_success=_done,
            on_error=lambda exc: self.toast(f"切换角色失败：{exc}"),
        )

    def _restart_runtime(self) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post("/api/system/restart", {}, timeout=180)

        widgets.run_async(
            _do,
            on_success=lambda _r: self.toast("Runtime 已重启"),
            on_error=lambda exc: self.toast(f"重启失败：{exc}"),
        )

    def _show_source(self, name: str) -> None:
        if self.api is None:
            return

        def _do() -> dict[str, Any]:
            return self.api.get(f"/api/personas/{q(name)}/prompt", timeout=30)

        def _done(data: dict[str, Any]) -> None:
            window = Gtk.Window()
            window.set_title(f"{name} · persona_prompt.py")
            window.set_default_size(900, 760)
            window.set_transient_for(self.app.window)
            window.set_modal(True)
            header = Adw.HeaderBar()
            copy = widgets.button("复制源码", icon="edit-copy-symbolic")
            source_text = str(data.get("source") or "")

            def _copy_source() -> None:
                self.get_clipboard().set(GObject.Value(str, source_text))
                self.toast("源码已复制")

            copy.connect("clicked", lambda _b: _copy_source())
            header.pack_start(copy)
            window.set_titlebar(header)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_margin_top(12)
            box.set_margin_bottom(12)
            box.set_margin_start(14)
            box.set_margin_end(14)
            box.append(
                widgets.muted(str(data.get("path") or "persona_prompt.py"))
            )
            view = widgets.text_view(source_text, height=620, monospace=True)
            view.set_vexpand(True)
            view.text_view.set_editable(False)
            view.text_view.set_cursor_visible(False)
            box.append(view)
            window.set_child(box)
            window.present()

        widgets.run_async(
            _do,
            on_success=_done,
            on_error=lambda exc: self.toast(f"读取人设源码失败：{exc}"),
        )

    def _confirm_delete(self, name: str) -> None:
        def _do_delete() -> None:
            if self.api is None:
                return

            def _do() -> Any:
                return self.api.delete(f"/api/personas/{q(name)}", timeout=30)

            widgets.run_async(
                _do,
                on_success=lambda _r: (self.toast(f"已删除 {name}"), self.refresh()),
                on_error=lambda exc: self.toast(f"删除失败：{exc}"),
            )

        widgets.ConfirmDialog(
            self.app.window,
            heading=f"删除角色 {name}？",
            body="人格目录会被删除；已有聊天记录不会被删除。",
            confirm_label="删除",
            destructive=True,
            on_confirm=_do_delete,
        )

    # ------------------------------------------------------------------
    # Appearance
    # ------------------------------------------------------------------
    def _show_appearance(self, name: str) -> None:
        if self.api is None:
            return
        window = Gtk.Window()
        window.set_title(f"{name} · 角色形象")
        window.set_default_size(860, 700)
        window.set_transient_for(self.app.window)
        window.set_modal(True)
        window.set_titlebar(Adw.HeaderBar())
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_top(10)
        toolbar.set_margin_bottom(4)
        toolbar.set_margin_start(14)
        toolbar.set_margin_end(14)
        summary = widgets.muted("正在读取…")
        summary.set_hexpand(True)
        upload = widgets.button("添加形象", icon="list-add-symbolic")
        delete_all = widgets.button("删除全部", css="destructive-action")
        refresh = widgets.icon_button("view-refresh-symbolic", "刷新")
        toolbar.append(summary)
        toolbar.append(upload)
        toolbar.append(delete_all)
        toolbar.append(refresh)
        outer.append(toolbar)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(4)
        flow.set_min_children_per_line(1)
        flow.set_row_spacing(10)
        flow.set_column_spacing(10)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(flow)
        outer.append(scroll)
        window.set_child(outer)
        window.present()

        def reload() -> None:
            widgets.clear(flow)
            summary.set_text("正在读取…")

            def _fetch() -> dict[str, Any]:
                try:
                    return self.api.get(
                        f"/api/personas/{q(name)}/appearance", timeout=30
                    )
                except BaseException as exc:  # noqa: BLE001
                    return {"error": str(exc)}

            def _render(data: dict[str, Any]) -> None:
                widgets.clear(flow)
                if data.get("error"):
                    summary.set_text(f"读取失败：{data['error']}")
                    return
                images = data.get("images") or []
                cover_id = str(data.get("cover_id") or "")
                summary.set_text(f"共 {len(images)} 张 · 预览图已标记")
                delete_all.set_sensitive(bool(images))
                for image in images:
                    flow.append(
                        self._appearance_tile(name, image, cover_id, reload)
                    )

            widgets.run_async(
                _fetch,
                on_success=_render,
                on_error=lambda exc: summary.set_text(str(exc)),
            )

        def add_images() -> None:
            paths = widgets.files_picker(
                self.app.window,
                title_text="选择角色形象（可多选）",
                patterns=IMAGE_PATTERNS,
            )
            if not paths:
                return

            def _do() -> tuple[int, list[str]]:
                added = 0
                errors: list[str] = []
                for path in paths:
                    try:
                        self.api.upload_file(
                            f"/api/personas/{q(name)}/appearance",
                            Path(path),
                            field="file",
                            timeout=120,
                        )
                        added += 1
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(f"{Path(path).name}: {exc}")
                return added, errors

            def _done(result: tuple[int, list[str]]) -> None:
                added, errors = result
                self.toast(
                    f"已添加 {added} 张形象"
                    + (f"，{len(errors)} 张失败" if errors else "")
                )
                if errors:
                    self.toast(errors[0])
                reload()

            widgets.run_async(
                _do, on_success=_done, on_error=lambda exc: self.toast(str(exc))
            )

        def delete_everything() -> None:
            def _do() -> Any:
                return self.api.delete(f"/api/personas/{q(name)}/appearance", timeout=30)

            widgets.run_async(
                _do,
                on_success=lambda _r: (self.toast("角色形象已全部删除"), reload()),
                on_error=lambda exc: self.toast(str(exc)),
            )

        upload.connect("clicked", lambda _b: add_images())
        refresh.connect("clicked", lambda _b: reload())
        delete_all.connect(
            "clicked",
            lambda _b: widgets.ConfirmDialog(
                window,
                heading="删除全部角色形象？",
                body="这会清空该人格的形象画廊；聊天记录不受影响。",
                confirm_label="全部删除",
                destructive=True,
                on_confirm=delete_everything,
            ),
        )
        reload()

    def _appearance_tile(
        self,
        name: str,
        image: dict[str, Any],
        cover_id: str,
        reload: Any,
    ) -> Gtk.Widget:
        card = widgets.card(spacing=5, padding=8)
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_size_request(170, 150)
        card.append(picture)
        image_id = str(image.get("id") or "")
        path = (
            f"/api/personas/{q(name)}/appearance/file?"
            f"image_id={q(image_id)}"
        )

        def _load() -> bytes:
            return self.api.raw(path, timeout=30)

        def _loaded(data: bytes) -> None:
            try:
                picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
            except Exception:  # noqa: BLE001
                picture.set_tooltip_text("预览失败")

        widgets.run_async(_load, on_success=_loaded, on_error=lambda _e: None)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        head.append(widgets.muted(image_id[:8]))
        if image_id == cover_id:
            head.append(widgets.badge("预览图", css="badge badge-green"))
        size = f"{image.get('width') or '?'}×{image.get('height') or '?'}"
        head.append(widgets.muted(size))
        card.append(head)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        if image_id != cover_id:
            cover = widgets.button("设为预览")
            cover.connect(
                "clicked",
                lambda _b: self._appearance_action(
                    "cover", name, image_id, reload
                ),
            )
            actions.append(cover)
        delete = widgets.button("删除", css="destructive-action")
        delete.connect(
            "clicked",
            lambda _b: self._appearance_action("delete", name, image_id, reload),
        )
        actions.append(delete)
        card.append(actions)
        return card

    def _appearance_action(
        self, action: str, name: str, image_id: str, reload: Any
    ) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            if action == "cover":
                return self.api.post(
                    f"/api/personas/{q(name)}/appearance/{q(image_id)}/cover",
                    {},
                    timeout=30,
                )
            return self.api.delete(
                f"/api/personas/{q(name)}/appearance/{q(image_id)}",
                timeout=30,
            )

        widgets.run_async(
            _do,
            on_success=lambda _r: (
                self.toast("已设为预览图" if action == "cover" else "形象已删除"),
                reload(),
            ),
            on_error=lambda exc: self.toast(str(exc)),
        )

    # ------------------------------------------------------------------
    # Copy and import
    # ------------------------------------------------------------------
    def _duplicate_dialog(self, name: str) -> None:
        window = widgets.FormWindow(
            self.app.window,
            f"复制 {name}",
            width=460,
            height=240,
            submit_label="复制",
            on_submit=lambda: _save(),
        )
        new_name = Gtk.Entry()
        new_name.set_text(f"{name}_copy")
        window.add_row("新目录名", new_name)
        error = widgets.muted("")
        window.body_box.append(error)

        def _save() -> None:
            if self.api is None:
                return
            target = new_name.get_text().strip()
            if not target:
                error.set_text("目录名不能为空。")
                return

            def _do() -> dict[str, Any]:
                return self.api.post(
                    f"/api/personas/{q(name)}/duplicate",
                    {"new_name": target},
                    timeout=60,
                )

            def _done(result: dict[str, Any]) -> None:
                window.close()
                self.toast(str(result.get("message") or "已复制"))
                self.refresh()

            widgets.run_async(
                _do, on_success=_done, on_error=lambda exc: error.set_text(str(exc))
            )

        window.present()

    def _import(self) -> None:
        path = widgets.path_picker(
            self.app.window,
            title_text="选择角色 zip 包",
            patterns=["*.zip"],
        )
        if not path:
            return
        if self.api is None:
            return

        def _do() -> dict[str, Any]:
            return self.api.upload_file(
                "/api/personas/import", Path(path), timeout=120
            )

        def _done(result: dict[str, Any]) -> None:
            self.toast(str(result.get("message") or "角色已导入"))
            self.refresh()

        widgets.run_async(
            _do, on_success=_done, on_error=lambda exc: self.toast(f"导入失败：{exc}")
        )
