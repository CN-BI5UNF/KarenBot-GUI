"""Reusable GTK widgets and thread-to-GTK helpers."""

from __future__ import annotations

import html
import queue
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="karen-gui-http")

# Worker threads queue deliveries here; a GLib timeout owned by the main thread
# drains it.  Relying on GLib.idle_add from a worker was unreliable on the ARM
# GTK build used here, and a queue makes delivery ordering explicit.
_CALLBACKS: queue.Queue[tuple[Callable[[Any], None] | None, Any]] = queue.Queue()
_PUMP_INSTALLED = False
_PUMP_BUSY = False


def _drain_callbacks() -> bool:
    global _PUMP_BUSY
    if _PUMP_BUSY:
        return True
    _PUMP_BUSY = True
    try:
        while True:
            try:
                callback, value = _CALLBACKS.get_nowait()
            except queue.Empty:
                break
            if callback is None:
                continue
            try:
                callback(value)
            except Exception:  # noqa: BLE001 - never take down GTK
                traceback.print_exc()
    finally:
        _PUMP_BUSY = False
    return True


def install_callback_pump() -> None:
    global _PUMP_INSTALLED
    if _PUMP_INSTALLED:
        return
    _PUMP_INSTALLED = True
    GLib.timeout_add(25, _drain_callbacks)


def run_async(
    fn: Callable[..., Any],
    *,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run a blocking API call without freezing the GTK main loop."""
    install_callback_pump()
    future = _EXECUTOR.submit(fn, **kwargs)

    def _done(completed: Any) -> None:
        try:
            result = completed.result()
        except BaseException as exc:  # noqa: BLE001
            if on_error is not None:
                _CALLBACKS.put((on_error, exc))
            else:
                traceback.print_exception(type(exc), exc, exc.__traceback__)
            return
        if on_success is not None:
            _CALLBACKS.put((on_success, result))

    future.add_done_callback(_done)


def clear(box: Gtk.Box) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def add_css(widget: Gtk.Widget, css: str) -> None:
    """Add one or more space-separated CSS classes.

    GTK's add_css_class takes a single class; several call sites in the GUI
    pass strings such as ``"badge badge-green"``.  Splitting here keeps those
    calls working and lets the warm WebUI palette apply consistently.
    """
    for name in str(css or "").split():
        if name:
            widget.add_css_class(name)


def label(
    text: str = "",
    *,
    css: str = "",
    wrap: bool = False,
    selectable: bool = False,
    xalign: float = 0.0,
    ellipsize: bool = False,
) -> Gtk.Label:
    widget = Gtk.Label(label=text or "")
    widget.set_xalign(xalign)
    widget.set_wrap(wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_selectable(selectable)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    add_css(widget, css)
    return widget


def title(text: str, *, level: int = 2) -> Gtk.Label:
    widget = label(text, css="page-title", wrap=True)
    if level == 1:
        widget.add_css_class("page-title-xl")
    return widget


def muted(text: str, *, wrap: bool = True) -> Gtk.Label:
    return label(text, css="muted", wrap=wrap)


def section_header(name: str, subtitle: str = "") -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.append(label(name, css="section-title"))
    if subtitle:
        box.append(muted(subtitle))
    return box


def card(*, spacing: int = 8, padding: int = 20) -> Gtk.Box:
    """A WebUI-style card.

    Inner padding belongs to the card background (CSS), not to outer margins,
    so cards stretch to the content column like the browser console.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.add_css_class("card")
    if padding <= 10:
        box.add_css_class("card-tight")
    return box


def card_row(**kwargs: Any) -> Gtk.Box:
    box = card(**kwargs)
    box.set_orientation(Gtk.Orientation.HORIZONTAL)
    return box


def button(text: str, *, css: str = "", icon: str | None = None) -> Gtk.Button:
    widget = Gtk.Button()
    if icon:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(label(text))
        widget.set_child(content)
    else:
        widget.set_label(text)
    widget.set_halign(Gtk.Align.START)
    widget.set_valign(Gtk.Align.CENTER)
    add_css(widget, css)
    return widget


def icon_button(icon: str, tooltip: str = "", *, css: str = "flat") -> Gtk.Button:
    widget = Gtk.Button.new_from_icon_name(icon)
    # 顶栏是 36px 的图标按钮；默认 flat 保持 WebUI 的无边框观感。
    add_css(widget, css)
    widget.add_css_class("icon-button")
    if tooltip:
        widget.set_tooltip_text(tooltip)
    return widget


def badge(text: str, *, css: str = "badge") -> Gtk.Label:
    widget = label(text, css=css)
    widget.set_halign(Gtk.Align.START)
    return widget


def stat_box(label_text: str, value_text: str, *, small: bool = False) -> Gtk.Box:
    """A stat tile without its own card chrome (WebUI ``statCard``)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    box.add_css_class("stat")
    name = label(label_text, css="stat-label", wrap=True)
    box.append(name)
    value = label(value_text, css="stat-value-small" if small else "stat-value")
    box.append(value)
    return box


def table(
    headers: list[str],
    rows: list[list[Any]],
    *,
    weights: list[float] | None = None,
    empty_text: str = "暂无数据",
) -> Gtk.Box:
    """A lightweight, WebUI-like data table for GTK 4.

    Rows are regular horizontal boxes with equal stretch weights, which keeps
    column widths aligned without the overhead of a ColumnView/model for the
    small tables in the control panel.
    """
    columns = max(1, len(headers))
    if weights is None or len(weights) != columns:
        weights = [1.0] * columns
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    outer.add_css_class("data-table")

    head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    head.add_css_class("table-head")
    for text, weight in zip(headers, weights, strict=False):
        cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        cell.set_hexpand(True)
        cell.set_size_request(max(48, int(weight * 64)), -1)
        cell.append(label(text, css="table-head-label", wrap=True))
        head.append(cell)
    outer.append(head)

    if not rows:
        empty = label(empty_text, css="empty-state", wrap=True, xalign=0.5)
        empty.set_hexpand(True)
        outer.append(empty)
        return outer

    for values in rows:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-row")
        for index in range(columns):
            value = values[index] if index < len(values) else ""
            cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            cell.add_css_class("table-cell")
            cell.set_hexpand(True)
            cell.set_valign(Gtk.Align.CENTER)
            cell.set_size_request(max(48, int(weights[index] * 64)), -1)
            if isinstance(value, Gtk.Widget):
                cell.append(value)
            else:
                cell.append(label(str(value if value is not None else "—"), wrap=True, xalign=0.0))
            row.append(cell)
        outer.append(row)
    return outer


def status_dot(ok: bool | None = None) -> Gtk.DrawingArea:
    widget = Gtk.DrawingArea()
    widget.set_content_width(10)
    widget.set_content_height(10)
    widget.set_valign(Gtk.Align.CENTER)

    def draw(area: Gtk.DrawingArea, cr: Any, width: int, height: int) -> bool:
        if ok is True:
            cr.set_source_rgb(0.22, 0.75, 0.42)
        elif ok is False:
            cr.set_source_rgb(0.9, 0.31, 0.31)
        else:
            cr.set_source_rgb(0.55, 0.55, 0.55)
        cr.arc(width / 2, height / 2, min(width, height) / 2, 0, 6.28318)
        cr.fill()
        return False

    widget.set_draw_func(draw)
    return widget


def flow_row(*children: Gtk.Widget, spacing: int = 8) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    box.set_valign(Gtk.Align.CENTER)
    for child in children:
        box.append(child)
    return box


def separator(*, margin_top: int = 6, margin_bottom: int = 6) -> Gtk.Separator:
    widget = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    widget.set_margin_top(margin_top)
    widget.set_margin_bottom(margin_bottom)
    return widget


def format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_timestamp(value: Any) -> str:
    try:
        stamp = float(value or 0)
    except (TypeError, ValueError):
        return str(value or "")
    if stamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return str(value or "")


def property_row(name: str, value: str, *, wrap: bool = True) -> Gtk.Box:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.append(label(name, css="property-name", xalign=0.0))
    val = label(value, css="property-value", wrap=wrap, selectable=True)
    val.set_hexpand(True)
    row.append(val)
    return row


def format_uptime(seconds: float | int | None) -> str:
    try:
        value = int(float(seconds or 0))
    except (TypeError, ValueError):
        value = 0
    value = max(0, value)
    if value < 60:
        return f"{value} 秒"
    days, rem = divmod(value, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分 {seconds} 秒"


def short_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if isinstance(value, (int, float)) or text.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(value)).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%m-%d %H:%M:%S")
    except ValueError:
        return text[:19]


def escape_markup(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def toast(window: Any, message: str) -> None:
    overlay = getattr(window, "toast_overlay", None)
    if overlay is not None:
        overlay.add_toast(Adw.Toast.new(str(message)))
        return
    print(message)


class ConfirmDialog:
    """Small Adw.MessageDialog wrapper that calls a callback on confirm."""

    def __init__(
        self,
        window: Gtk.Window,
        *,
        heading: str,
        body: str = "",
        confirm_label: str = "确认",
        destructive: bool = False,
        on_confirm: Callable[[], None],
    ) -> None:
        dialog = Adw.MessageDialog(
            transient_for=window,
            modal=True,
            heading=heading,
            body=body,
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("ok", confirm_label)
        dialog.set_response_appearance(
            "ok",
            Adw.ResponseAppearance.DESTRUCTIVE
            if destructive
            else Adw.ResponseAppearance.SUGGESTED,
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def _response(_dialog: Adw.MessageDialog, response: str) -> None:
            if response == "ok":
                on_confirm()

        dialog.connect("response", _response)
        dialog.present()
        self.dialog = dialog


class FormWindow(Gtk.Window):
    """Modal form window with a header bar, scroll body and action footer."""

    def __init__(
        self,
        parent: Gtk.Window,
        title_text: str,
        *,
        width: int = 620,
        height: int = 620,
        submit_label: str = "保存",
        on_submit: Callable[[], None],
    ) -> None:
        super().__init__()
        self.set_title(title_text)
        self.set_default_size(width, height)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.on_submit = on_submit
        self.set_titlebar(Adw.HeaderBar())
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.body_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.body_box.set_margin_top(16)
        self.body_box.set_margin_bottom(16)
        self.body_box.set_margin_start(18)
        self.body_box.set_margin_end(18)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.body_box)
        outer.append(scroller)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(8)
        footer.set_margin_bottom(12)
        footer.set_margin_start(18)
        footer.set_margin_end(18)
        footer.set_halign(Gtk.Align.END)
        cancel = button("取消")
        cancel.connect("clicked", lambda _b: self.close())
        submit = button(submit_label, css="suggested-action")
        submit.connect("clicked", lambda _b: self.on_submit())
        self.submit_button = submit
        self.cancel_button = cancel
        footer.append(cancel)
        footer.append(submit)
        outer.append(footer)
        self.set_child(outer)

    def add_row(self, name: str, widget: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.append(label(name, css="field-label"))
        row.append(widget)
        self.body_box.append(row)
        return row


def entry(text: str = "", *, placeholder: str = "") -> Gtk.Entry:
    widget = Gtk.Entry()
    widget.set_text(text or "")
    if placeholder:
        widget.set_placeholder_text(placeholder)
    return widget


def text_view(text: str = "", *, height: int = 180, monospace: bool = False) -> Gtk.ScrolledWindow:
    view = Gtk.TextView()
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.get_buffer().set_text(text or "")
    if monospace:
        view.add_css_class("monospace")
    scroller = Gtk.ScrolledWindow()
    scroller.set_min_content_height(height)
    scroller.set_child(view)
    scroller.add_css_class("text-area")
    scroller.text_view = view  # type: ignore[attr-defined]
    return scroller


def text_value(widget: Gtk.ScrolledWindow) -> str:
    view: Gtk.TextView = widget.text_view  # type: ignore[attr-defined]
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)


def dropdown(options: list[tuple[str, str]], selected: str = "") -> Gtk.DropDown:
    labels = Gtk.StringList.new([name for _value, name in options])
    widget = Gtk.DropDown(model=labels)
    for index, (value, _name) in enumerate(options):
        if value == selected:
            widget.set_selected(index)
            break
    widget._values = [value for value, _name in options]  # type: ignore[attr-defined]
    return widget


def dropdown_value(widget: Gtk.DropDown) -> str:
    index = int(widget.get_selected())
    values = getattr(widget, "_values", [])
    if 0 <= index < len(values):
        return values[index]
    return ""


def switch(active: bool = False) -> Gtk.Switch:
    widget = Gtk.Switch()
    widget.set_active(bool(active))
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_halign(Gtk.Align.START)
    return widget


def path_picker(
    parent: Gtk.Window,
    *,
    title_text: str = "选择文件",
    folders: bool = False,
    patterns: list[str] | None = None,
) -> str:
    paths = files_picker(
        parent,
        title_text=title_text,
        folders=folders,
        patterns=patterns,
    )
    return paths[0] if paths else ""


def files_picker(
    parent: Gtk.Window,
    *,
    title_text: str = "选择文件",
    folders: bool = False,
    patterns: list[str] | None = None,
) -> list[str]:
    dialog = Gtk.FileChooserNative(
        title=title_text,
        transient_for=parent,
        action=Gtk.FileChooserAction.SELECT_FOLDER
        if folders
        else Gtk.FileChooserAction.OPEN,
        accept_label="选择",
        cancel_label="取消",
    )
    dialog.set_select_multiple(not folders)
    if patterns and not folders:
        file_filter = Gtk.FileFilter()
        file_filter.set_name("支持的文件")
        for pattern in patterns:
            file_filter.add_pattern(pattern)
        dialog.add_filter(file_filter)
    result: list[str] = []
    loop = GLib.MainLoop()

    def _done(_dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            files = dialog.get_files()
            for index in range(files.get_n_items()):
                item = files.get_item(index)
                path = item.get_path() if item is not None else None
                if path:
                    result.append(path)
        loop.quit()

    dialog.connect("response", _done)
    dialog.show()
    loop.run()
    return result


def save_path_picker(
    parent: Gtk.Window,
    *,
    title_text: str = "保存文件",
    initial_name: str = "",
) -> str:
    dialog = Gtk.FileChooserNative(
        title=title_text,
        transient_for=parent,
        action=Gtk.FileChooserAction.SAVE,
        accept_label="保存",
        cancel_label="取消",
    )
    if initial_name:
        dialog.set_current_name(Path(initial_name).name)
    result: dict[str, str] = {}
    loop = GLib.MainLoop()

    def _done(_dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            if selected is not None:
                result["path"] = selected.get_path() or ""
        loop.quit()

    dialog.connect("response", _done)
    dialog.show()
    loop.run()
    return result.get("path", "")


class ChipList(Gtk.Box):
    """Numeric ID editor with removable chips (WebUI whitelist/blacklist)."""

    def __init__(
        self,
        title: str,
        placeholder: str,
        *,
        on_changed: Callable[[list[int]], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self._values: list[int] = []
        self._on_changed = on_changed
        self.append(label(title, css="field-label"))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text(placeholder)
        self.entry.connect("activate", lambda _e: self._add_from_entry())
        row.append(self.entry)
        add = button("添加", css="compact-button")
        add.connect("clicked", lambda _b: self._add_from_entry())
        row.append(add)
        self.append(row)
        self.chip_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(self.chip_host)

    def get_values(self) -> list[int]:
        return list(self._values)

    def set_values(self, values: Any, *, notify: bool = False) -> None:
        parsed: set[int] = set()
        for raw in values or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                parsed.add(value)
        self._values = sorted(parsed)
        self._render()
        if notify and self._on_changed is not None:
            self._on_changed(self.get_values())

    @staticmethod
    def _parse(text: str) -> list[int]:
        result: set[int] = set()
        for chunk in str(text or "").replace("，", ",").replace("、", ",").replace(";", ",").replace("；", ",").split():
            for piece in chunk.split(","):
                piece = piece.strip()
                if not piece:
                    continue
                try:
                    value = int(piece)
                except ValueError:
                    continue
                if value > 0:
                    result.add(value)
        return sorted(result)

    def _add_from_entry(self) -> None:
        values = self._parse(self.entry.get_text())
        if not values:
            return
        self.entry.set_text("")
        merged = sorted(set(self._values) | set(values))
        if merged == self._values:
            return
        self._values = merged
        self._render()
        if self._on_changed is not None:
            self._on_changed(self.get_values())

    def _remove(self, value: int) -> None:
        if value not in self._values:
            return
        self._values = [item for item in self._values if item != value]
        self._render()
        if self._on_changed is not None:
            self._on_changed(self.get_values())

    def _render(self) -> None:
        clear(self.chip_host)
        if not self._values:
            self.chip_host.append(label("名单为空", css="field-help"))
            return
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(10)
        flow.set_min_children_per_line(1)
        flow.set_row_spacing(4)
        flow.set_column_spacing(4)
        for value in self._values:
            chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            chip.add_css_class("chip")
            chip.append(label(str(value), css="chip-label"))
            remove = Gtk.Button(label="×")
            remove.add_css_class("chip-remove")
            remove.set_tooltip_text("移出名单")
            remove.connect("clicked", lambda _b, v=value: self._remove(v))
            chip.append(remove)
            flow.append(chip)
        self.chip_host.append(flow)


__all__ = [
    "ChipList",
    "ConfirmDialog",
    "FormWindow",
    "badge",
    "button",
    "card",
    "card_row",
    "clear",
    "dropdown",
    "dropdown_value",
    "entry",
    "files_picker",
    "format_bytes",
    "format_timestamp",
    "escape_markup",
    "flow_row",
    "format_uptime",
    "icon_button",
    "label",
    "muted",
    "path_picker",
    "property_row",
    "save_path_picker",
    "separator",
    "run_async",
    "section_header",
    "short_time",
    "status_dot",
    "switch",
    "text_value",
    "text_view",
    "title",
    "toast",
]
