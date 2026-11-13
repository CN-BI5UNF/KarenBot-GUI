"""Common page scaffolding."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402


class Page(Gtk.ScrolledWindow):
    page_id = ""
    page_title = ""
    page_subtitle = ""
    page_icon = "applications-system-symbolic"
    refresh_on_activate = False

    def __init__(self, app: Any) -> None:
        super().__init__()
        self.app = app
        self.loaded = False
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.add_css_class("content-area")
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.body.set_margin_top(32)
        self.body.set_margin_bottom(40)
        self.body.set_margin_start(32)
        self.body.set_margin_end(32)
        # WebUI 内容区最大宽度 1100px，窗口拉宽时不把表单摊成整屏。
        clamp = Adw.Clamp()
        clamp.set_maximum_size(1100)
        clamp.set_tightening_threshold(860)
        clamp.set_child(self.body)
        self.set_child(clamp)
        self.build()

    # ------------------------------------------------------------------
    # Subclass API
    # ------------------------------------------------------------------
    def build(self) -> None:
        pass

    def dispose(self) -> None:
        """Stop page-owned timers before the app recreates its backend."""
        pass

    def activate(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.refresh()
        elif self.refresh_on_activate and not self._has_unsaved():
            self.refresh()

    def _has_unsaved(self) -> bool:
        check = getattr(self, "has_unsaved_changes", None)
        try:
            return bool(check()) if callable(check) else False
        except Exception:  # noqa: BLE001
            return False

    def refresh(self) -> None:
        pass

    def refresh_requested(self) -> None:
        """Header refresh button hook; pages may override for a full reload."""
        if self._has_unsaved():
            discard = getattr(self, "discard_unsaved_changes", None)
            if callable(discard):
                confirm = getattr(self.app, "_confirm_unsaved", None)
                if callable(confirm):
                    confirm(
                        heading="未保存的更改",
                        body=f"「{self.page_title}」有尚未保存的修改，"
                        "刷新会丢失这些修改。",
                        on_discard=self.refresh,
                    )
                    return
        self.refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def api(self):
        return self.app.api

    def toast(self, message: str) -> None:
        self.app.toast(message)

    def header(self, *, refresh: bool = True) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        text.append(widgets.title(self.page_title, level=1))
        if self.page_subtitle:
            text.append(
                widgets.label(self.page_subtitle, css="page-desc", wrap=True)
            )
        row.append(text)
        if refresh:
            reload_button = widgets.icon_button(
                "view-refresh-symbolic", "刷新", css="flat"
            )
            reload_button.connect("clicked", lambda _b: self.refresh_requested())
            row.append(reload_button)
        return row

    def show_error(self, exc: BaseException) -> None:
        self.toast(str(exc))

    def empty(self, message: str) -> Gtk.Box:
        box = widgets.card()
        box.add_css_class("empty-state")
        box.set_halign(Gtk.Align.FILL)
        box.append(widgets.muted(message))
        return box

    def busy(self, message: str = "正在加载…") -> Gtk.Box:
        box = widgets.card()
        box.set_orientation(Gtk.Orientation.HORIZONTAL)
        box.set_spacing(10)
        spinner = Gtk.Spinner()
        spinner.start()
        box.append(spinner)
        box.append(widgets.label(message))
        return box


__all__ = ["Page"]
