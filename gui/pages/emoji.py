"""Emoji library with thumbnails."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class EmojiPage(Page):
    refresh_on_activate = True
    page_id = "emoji"
    page_title = "表情包"
    page_subtitle = "人格在聊天中可以发送这些图片。名称就是 AI 调用时用的名字，别用太生僻的字。"
    page_icon = "face-smile-symbolic"

    def build(self) -> None:
        self._supported: list[str] = [".png", ".jpg", ".jpeg", ".gif"]
        self._max_bytes = 5 * 1024 * 1024
        header_row = self.header()
        upload = widgets.button("添加表情包", icon="list-add-symbolic", css="suggested-action")
        upload.connect("clicked", lambda _b: self._upload())
        header_row.append(upload)
        self.body.append(header_row)
        self.info = widgets.muted("")
        self.body.append(self.info)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("按名称筛选…")
        self.search_entry.connect("search-changed", lambda _e: self._render_grid())
        self.body.append(self.search_entry)
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(7)
        self.flow.set_min_children_per_line(2)
        self.flow.set_row_spacing(10)
        self.flow.set_column_spacing(10)
        self.flow.set_homogeneous(True)
        self.body.append(self.flow)
        self._items: list[dict[str, Any]] = []

    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/emoji", timeout=30)

        widgets.run_async(_fetch, on_success=self._on_data, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.flow)
        self.flow.append(widgets.muted(f"读取表情包失败：{exc}"))

    def _on_data(self, data: dict[str, Any]) -> None:
        self._items = list(data.get("items") or [])
        self._supported = list(data.get("supported_exts") or self._supported)
        try:
            self._max_bytes = int(data.get("max_upload_bytes") or self._max_bytes)
        except (TypeError, ValueError):
            pass
        ext_text = " ".join(ext.lstrip(".").upper() for ext in self._supported)
        self.info.set_text(
            f"共 {len(self._items)} 个表情包 · {data.get('dir', '')} · "
            f"支持 {ext_text} · 单文件 ≤ {widgets.format_bytes(self._max_bytes)}"
        )
        self._render_grid()

    def _render_grid(self) -> None:
        widgets.clear(self.flow)
        query = self.search_entry.get_text().strip().lower()
        items = [item for item in self._items if not query or query in str(item.get("name") or "").lower()]
        if not items:
            self.flow.append(widgets.muted("没有匹配的表情包。"))
            return
        for item in items:
            self.flow.append(self._tile(item))

    def _tile(self, item: dict[str, Any]) -> Gtk.Widget:
        name = str(item.get("name") or "")
        filename = str(item.get("file") or "")
        box = widgets.card(spacing=5, padding=8)
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_size_request(96, 96)
        box.append(picture)
        self._load_thumbnail(filename, picture)
        title = widgets.label(name, wrap=False, ellipsize=True)
        title.set_halign(Gtk.Align.CENTER)
        title.set_tooltip_text(name)
        box.append(title)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        rename = widgets.button("改名")
        rename.connect("clicked", lambda _b: self._rename(item))
        delete = widgets.button("删除")
        delete.add_css_class("destructive-action")
        delete.connect("clicked", lambda _b: self._delete(item))
        actions.append(rename)
        actions.append(delete)
        actions.set_halign(Gtk.Align.CENTER)
        box.append(actions)
        return box

    def _load_thumbnail(self, filename: str, picture: Gtk.Picture) -> None:
        if self.api is None or not filename:
            return
        from urllib.parse import quote

        path = f"/api/emoji/file/{quote(filename, safe='')}"

        def _fetch() -> bytes:
            return self.api.raw(path, timeout=20)

        def _show(data: bytes) -> None:
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                picture.set_paintable(texture)
            except Exception:  # noqa: BLE001
                picture.set_tooltip_text("图片预览失败")

        widgets.run_async(_fetch, on_success=_show, on_error=lambda _e: None)

    def _upload(self) -> None:
        if self.api is None:
            return
        window = Gtk.Window()
        window.set_title("添加表情包")
        window.set_default_size(680, 620)
        window.set_transient_for(self.app.window)
        window.set_modal(True)
        window.set_titlebar(Gtk.HeaderBar())
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(14)
        body.set_margin_bottom(14)
        body.set_margin_start(18)
        body.set_margin_end(18)
        body.append(
            widgets.muted(
                "可以一次选择多张图片，并为每个文件改一个名字；AI 发送表情包时使用这个名字。"
                f"支持 {' '.join(ext.lstrip('.').upper() for ext in self._supported)}，"
                f"单个不超过 {widgets.format_bytes(self._max_bytes)}。"
            )
        )
        add_button = widgets.button("选择图片", icon="list-add-symbolic")
        body.append(add_button)
        staging = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_min_content_height(300)
        scroller.set_child(staging)
        body.append(scroller)
        status = widgets.muted("还没有选择文件。")
        body.append(status)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(8)
        footer.set_margin_bottom(12)
        footer.set_margin_start(18)
        footer.set_margin_end(18)
        footer.append(status)
        status.set_hexpand(True)
        cancel = widgets.button("取消")
        cancel.connect("clicked", lambda _b: window.close())
        submit = widgets.button("添加", css="suggested-action")
        footer.append(cancel)
        footer.append(submit)
        outer.append(body)
        outer.append(footer)
        window.set_child(outer)
        window.present()
        staged: list[dict[str, Any]] = []

        def refresh_staging() -> None:
            widgets.clear(staging)
            if not staged:
                staging.append(widgets.muted("还没有选择文件。"))
                status.set_text("还没有选择文件。")
                return
            for entry in staged:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                picture = Gtk.Picture()
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_size_request(44, 44)
                try:
                    texture = Gdk.Texture.new_from_filename(str(entry["path"]))
                    picture.set_paintable(texture)
                except Exception:  # noqa: BLE001
                    pass
                row.append(picture)
                name_entry = entry["name"]
                name_entry.set_hexpand(True)
                remove = widgets.button("移除")
                remove.connect(
                    "clicked",
                    lambda _b, item=entry: (
                        staged.remove(item),
                        refresh_staging(),
                    ),
                )
                row.append(name_entry)
                row.append(remove)
                card = widgets.card(spacing=4, padding=8)
                card.append(row)
                card.append(widgets.muted(str(entry["path"])))
                staging.append(card)
            status.set_text(f"已选择 {len(staged)} 个文件。")

        def add_files() -> None:
            patterns = ["*" + ext for ext in self._supported]
            paths = widgets.files_picker(
                self.app.window,
                title_text="选择表情包图片（可多选）",
                patterns=patterns,
            )
            known = {str(entry["path"]) for entry in staged}
            for path in paths:
                if path in known:
                    continue
                source = Path(path)
                if source.suffix.lower() not in self._supported:
                    self.toast(f"{source.name}：不支持的格式")
                    continue
                try:
                    size = source.stat().st_size
                except OSError as exc:
                    self.toast(f"{source.name}：{exc}")
                    continue
                if size > self._max_bytes:
                    self.toast(
                        f"{source.name} 超过 {widgets.format_bytes(self._max_bytes)} 上限"
                    )
                    continue
                staged.append(
                    {
                        "path": path,
                        "name": widgets.entry(source.stem),
                    }
                )
            refresh_staging()

        def submit_files() -> None:
            if not staged:
                status.set_text("还没有选择文件。")
                return
            submit.set_sensitive(False)
            status.set_text("正在添加…")
            files: list[tuple[str, str, bytes, str]] = []
            rename: dict[str, str] = {}
            for entry in staged:
                source = Path(entry["path"])
                try:
                    data = source.read_bytes()
                except OSError as exc:
                    status.set_text(f"读取 {source.name} 失败：{exc}")
                    submit.set_sensitive(True)
                    return
                files.append(("files", source.name, data, _mime(source)))
                rename[source.name] = entry["name"].get_text().strip() or source.stem

            def _do() -> dict[str, Any]:
                return self.api.upload(
                    "/api/emoji/upload",
                    fields={"rename": json.dumps(rename, ensure_ascii=False)},
                    files=files,
                    timeout=180,
                )

            def _done(result: dict[str, Any]) -> None:
                added = int(result.get("count") or 0)
                skipped = result.get("skipped") or []
                deduped = result.get("deduped") or []
                self.toast(f"已添加 {added} 个表情包")
                for item in skipped[:3]:
                    self.toast(
                        f"{item.get('file') or '文件'}：{item.get('reason') or '已跳过'}"
                    )
                for item in deduped[:3]:
                    self.toast(
                        f"{item.get('name') or '表情包'} 重名，已存为 {item.get('file')}"
                    )
                window.close()
                self.refresh()

            def _failed(exc: BaseException) -> None:
                status.set_text(f"上传失败：{exc}")
                submit.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        add_button.connect("clicked", lambda _b: add_files())
        submit.connect("clicked", lambda _b: submit_files())
        refresh_staging()

    def _rename(self, item: dict[str, Any]) -> None:
        if self.api is None:
            return
        window = widgets.FormWindow(
            self.app.window,
            "重命名表情包",
            width=420,
            height=240,
            on_submit=lambda: _save(),
        )
        entry = Gtk.Entry()
        entry.set_text(str(item.get("name") or ""))
        window.add_row("新名称", entry)
        error = widgets.muted("")
        window.body_box.append(error)

        def _save() -> None:
            name = str(item.get("name") or "")
            new_name = entry.get_text().strip()
            if not new_name:
                error.set_text("名称不能为空。")
                return

            def _do() -> Any:
                return self.api.patch(f"/api/emoji/{_quote(name)}", {"new_name": new_name}, timeout=30)

            def _done(result: dict[str, Any]) -> None:
                window.close()
                self.toast(f"已改名为 {result.get('to') or new_name}")
                self.refresh()

            widgets.run_async(_do, on_success=_done, on_error=lambda exc: error.set_text(str(exc)))

        window.present()

    def _delete(self, item: dict[str, Any]) -> None:
        def _do_delete() -> None:
            if self.api is None:
                return

            def _do() -> Any:
                return self.api.delete(f"/api/emoji/{_quote(item.get('name'))}", timeout=30)

            widgets.run_async(
                _do,
                on_success=lambda _r: (self.toast("已删除"), self.refresh()),
                on_error=lambda exc: self.toast(str(exc)),
            )

        widgets.ConfirmDialog(
            self.app.window,
            heading=f"删除「{item.get('name')}」？",
            body="此操作不可撤销。",
            confirm_label="删除",
            destructive=True,
            on_confirm=_do_delete,
        )


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")


def _mime(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
