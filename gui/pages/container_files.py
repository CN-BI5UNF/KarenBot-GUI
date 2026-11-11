"""Read-only host and container workspace file browser (WebUI layout)."""

from __future__ import annotations

import posixpath
import time
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from ..api import q  # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
CACHE_TTL_SECONDS = 15

MODES = {
    "host": {
        "label": "本机工作区",
        "root": "/",
        "root_label": "本机工作区",
        "list": "/api/workspace/files",
        "content": "/api/workspace/files/content",
        "raw": "/api/workspace/files/raw",
        "note": "本机 AI 工作区（模型文件工具使用的目录）",
    },
    "container": {
        "label": "容器工作区",
        "root": "/workspace",
        "root_label": "容器工作区",
        "list": "/api/container/files",
        "content": "/api/container/files/content",
        "raw": "/api/container/files/raw",
        "note": "容器 /workspace（Docker 持久存储）",
    },
}

TYPE_TEXT = {
    "dir": "文件夹",
    "file": "文件",
    "symlink": "符号链接",
    "other": "其他",
}
TYPE_ICON = {
    "dir": "folder-symbolic",
    "file": "text-x-generic-symbolic",
    "symlink": "insert-link-symbolic",
    "other": "dialog-question-symbolic",
}


class WorkspaceBrowser(Gtk.Box):
    def __init__(self, page: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.page = page
        self.mode = "host"
        self.entries: list[dict[str, Any]] = []
        self._seq = 0
        self._loading = False
        self._container_running: bool | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._states = {
            "host": {"path": "/", "data": None, "loaded": False, "error": ""},
            "container": {
                "path": "/workspace",
                "data": None,
                "loaded": False,
                "error": "",
            },
        }
        self._filters = {"host": "", "container": ""}
        self.add_css_class("card")

        self.append(widgets.label("文件管理", css="card-title"))
        self.append(
            widgets.label(
                "只读浏览两个互相独立的工作区：本机 AI 工作区"
                "（AppPaths.WORKSPACE_DIR）和容器 /workspace。支持目录导航、"
                "文本预览和常见图片打开；符号链接不跟随。",
                css="card-sub",
                wrap=True,
            )
        )

        modes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.host_button = widgets.button(
            "本机工作区", icon="folder-symbolic", css="compact-button"
        )
        self.host_button.set_tooltip_text("本机 AI 工作区（模型文件工具使用的目录）")
        self.host_button.connect("clicked", lambda _b: self._switch_mode("host"))
        self.container_button = widgets.button(
            "容器工作区", icon="package-x-generic-symbolic", css="compact-button"
        )
        self.container_button.set_tooltip_text("容器 /workspace（Docker 持久工作区）")
        self.container_button.connect(
            "clicked", lambda _b: self._switch_mode("container")
        )
        modes.append(self.host_button)
        modes.append(self.container_button)
        self.mode_note = widgets.muted(MODES["host"]["note"])
        self.mode_note.set_hexpand(True)
        modes.append(self.mode_note)
        self.append(modes)

        path_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.up_button = widgets.button(
            "上级", icon="go-up-symbolic", css="compact-button"
        )
        self.up_button.set_tooltip_text("回到上一级目录")
        self.up_button.connect("clicked", lambda _b: self._up())
        path_row.append(self.up_button)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_hexpand(True)
        self.path_entry.set_text("/")
        self.path_entry.set_placeholder_text("/")
        self.path_entry.set_tooltip_text("输入路径后按 Enter 或点「打开路径」")
        self.path_entry.connect("activate", lambda _e: self._open_path())
        path_row.append(self.path_entry)
        open_button = widgets.button("打开路径", css="compact-button")
        open_button.connect("clicked", lambda _b: self._open_path())
        path_row.append(open_button)
        refresh_button = widgets.button(
            "刷新", icon="view-refresh-symbolic", css="compact-button"
        )
        refresh_button.set_tooltip_text("刷新当前目录（绕过 15 秒缓存）")
        refresh_button.connect("clicked", lambda _b: self.load(force=True))
        path_row.append(refresh_button)
        self.open_button = open_button
        self.refresh_button = refresh_button
        filter_label = widgets.label("筛选", css="field-label")
        path_row.append(filter_label)
        self.filter_entry = Gtk.Entry()
        self.filter_entry.set_placeholder_text("筛选当前目录")
        self.filter_entry.set_tooltip_text("只筛选当前目录中已加载的条目")
        self.filter_entry.set_size_request(180, -1)
        self.filter_entry.connect("changed", lambda _e: self._on_filter_changed())
        path_row.append(self.filter_entry)
        self.append(path_row)

        self.breadcrumb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.append(self.breadcrumb)
        self.status = widgets.muted("正在读取…")
        self.append(self.status)
        self.list_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.append(self.list_host)
        self._render_modes()
        self.load()

    # ------------------------------------------------------------------
    # State / loading
    # ------------------------------------------------------------------
    def _state(self) -> dict[str, Any]:
        return self._states[self.mode]

    def set_container_running(self, running: bool | None) -> None:
        self._container_running = running
        if self.mode == "container":
            self._render_status()

    def _switch_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self._filters[self.mode] = self.filter_entry.get_text()
        self.mode = mode
        self.filter_entry.set_text(self._filters[mode])
        self._render_modes()
        self.load()

    def _render_modes(self) -> None:
        for mode, button in (
            ("host", self.host_button),
            ("container", self.container_button),
        ):
            if mode == self.mode:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")
        self.mode_note.set_text(MODES[self.mode]["note"])
        self.path_entry.set_placeholder_text(MODES[self.mode]["root"])

    def _normalize(self, path: str) -> str:
        text = str(path or "").strip()
        if self.mode == "host":
            if not text:
                return "/"
            return text if text.startswith("/") else f"/{text}"
        if not text:
            return "/workspace"
        if not text.startswith("/"):
            return f"/workspace/{text}"
        if text != "/workspace" and not text.startswith("/workspace/"):
            return "/workspace"
        return text

    def _open_path(self) -> None:
        self.load(self.path_entry.get_text().strip())

    def _up(self) -> None:
        current = self._normalize(self.path_entry.get_text())
        parent = posixpath.dirname(current)
        if self.mode == "host":
            target = parent or "/"
        else:
            target = parent if parent.startswith("/workspace") else "/workspace"
        self.load(target)

    def _cache_key(self, path: str) -> str:
        return f"{self.mode}:{path}"

    def load(
        self,
        path: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        if self.page.api is None:
            return
        state = self._state()
        target = self._normalize(
            path if path is not None else state.get("path") or MODES[self.mode]["root"]
        )
        state["path"] = target
        state["error"] = ""
        key = self._cache_key(target)
        hit = self._cache.get(key)
        if hit is not None and not force and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            state["data"] = hit[1]
            state["loaded"] = True
            self._loading = False
            self._render()
            return

        self._seq += 1
        token = self._seq
        self._loading = True
        state["loaded"] = False
        self._render()
        api = self.page.api
        list_path = MODES[self.mode]["list"]
        mode = self.mode

        def _do() -> dict[str, Any]:
            return api.get(f"{list_path}?path={q(target)}", timeout=120)

        def _done(data: dict[str, Any]) -> None:
            if token != self._seq or mode != self.mode:
                return
            state["data"] = data
            state["path"] = str(data.get("path") or target)
            state["loaded"] = True
            state["error"] = ""
            self._cache[key] = (time.monotonic(), data)
            if mode == "container":
                self._container_running = True
            self._loading = False
            self._render()

        def _failed(exc: BaseException) -> None:
            if token != self._seq or mode != self.mode:
                return
            state["data"] = None
            state["loaded"] = False
            state["error"] = str(exc)
            if mode == "container":
                self._container_running = False
            self._loading = False
            self._render()

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def reset(self) -> None:
        self._seq += 1
        self._cache.clear()
        for mode in self._states:
            self._states[mode] = {
                "path": MODES[mode]["root"],
                "data": None,
                "loaded": False,
                "error": "",
            }
            self._filters[mode] = ""
        self.filter_entry.set_text("")
        self._loading = False
        self._render()
        self.load(force=True)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _on_filter_changed(self) -> None:
        self._filters[self.mode] = self.filter_entry.get_text()
        self._render_status()
        self._render_list()

    def _filtered(self) -> list[dict[str, Any]]:
        data = self._state().get("data") or {}
        entries = list(data.get("entries") or [])
        needle = self.filter_entry.get_text().strip().casefold()
        if not needle:
            return entries
        return [
            entry
            for entry in entries
            if needle in str(entry.get("name") or "").casefold()
        ]

    def _render(self) -> None:
        state = self._state()
        self.path_entry.set_text(str(state.get("path") or MODES[self.mode]["root"]))
        self.up_button.set_sensitive(
            not self._loading
            and state.get("path") not in (None, "", MODES[self.mode]["root"])
        )
        self.open_button.set_sensitive(not self._loading)
        self.refresh_button.set_sensitive(not self._loading)
        self._render_modes()
        self._render_breadcrumb()
        self._render_status()
        self._render_list()

    def _render_breadcrumb(self) -> None:
        widgets.clear(self.breadcrumb)
        state = self._state()
        current = str(state.get("path") or MODES[self.mode]["root"])
        root = MODES[self.mode]["root"]
        parts: list[str] = []
        if self.mode == "host":
            parts = [part for part in current.strip("/").split("/") if part]
        elif current.startswith("/workspace/"):
            parts = [
                part
                for part in current[len("/workspace/") :].split("/")
                if part
            ]
        root_text = MODES[self.mode]["root_label"]
        root_button = widgets.button(root_text, css="compact-button")
        root_button.set_tooltip_text(f"回到{MODES[self.mode]['label']}根目录")
        root_button.connect("clicked", lambda _b: self.load(root, force=True))
        self.breadcrumb.append(root_button)
        accumulated = root
        for part in parts:
            accumulated = f"{accumulated.rstrip('/')}/{part}"
            target = accumulated
            self.breadcrumb.append(widgets.label("›", css="muted"))
            crumb = widgets.button(part, css="compact-button")
            crumb.set_tooltip_text(f"打开 {target}")
            crumb.connect("clicked", lambda _b, path=target: self.load(path))
            self.breadcrumb.append(crumb)

    def _render_status(self) -> None:
        state = self._state()
        if self._loading:
            self.status.set_text(f"正在读取 {state.get('path') or ''}…")
            return
        if state.get("error"):
            self.status.set_text(f"读取失败：{state['error']}")
            return
        if not state.get("loaded"):
            if self.mode == "container" and self._container_running is False:
                self.status.set_text(
                    "容器未运行；点「刷新」会尝试启动容器并读取 /workspace。"
                )
            else:
                self.status.set_text("正在等待目录列表…")
            return
        data = state.get("data") or {}
        shown = len(self._filtered())
        total = int(data.get("count") or 0)
        filter_text = self.filter_entry.get_text().strip()
        suffix = f"（筛选后 {shown}/{total}）" if filter_text else ""
        root_prefix = (
            f"根目录：{data.get('root')} · "
            if self.mode == "host" and data.get("root")
            else ("容器 /workspace · " if self.mode == "container" else "")
        )
        text = f"{root_prefix}{total} 项{suffix}"
        if data.get("truncated"):
            text += (
                f"；目录超过 {data.get('max_entries') or 1000} 项，"
                "仅显示部分内容"
            )
        self.status.set_text(text)

    def _render_list(self) -> None:
        widgets.clear(self.list_host)
        state = self._state()
        if self._loading:
            self.list_host.append(widgets.muted("正在读取目录…", wrap=True))
            return
        if state.get("error"):
            self.list_host.append(
                widgets.muted(
                    f"无法读取目录：{state['error']}\n"
                    + (
                        "确认 Docker 容器和 C 存储已启动；也可以点「刷新」重试。"
                        if self.mode == "container"
                        else "确认本机工作区目录存在；也可以点「刷新」重试。"
                    ),
                    wrap=True,
                )
            )
            return
        if not state.get("loaded"):
            self.list_host.append(widgets.muted("尚未加载文件列表"))
            return
        entries = self._filtered()
        if not entries:
            self.list_host.append(
                widgets.muted(
                    "当前目录没有匹配项"
                    if self.filter_entry.get_text().strip()
                    else "目录为空",
                    wrap=True,
                )
            )
            return
        rows: list[list[Any]] = []
        for entry in entries:
            kind = str(entry.get("type") or "file")
            name = str(entry.get("name") or "")
            action: Any
            if kind == "dir":
                action = widgets.button("打开", css="compact-button")
                target = str(entry.get("path") or "")
                action.connect(
                    "clicked",
                    lambda _b, path=target: self.load(path),
                )
            elif kind == "file":
                ext = posixpath.splitext(name)[1].lower()
                action = widgets.button(
                    "查看图片" if ext in IMAGE_EXTS else "查看",
                    css="compact-button",
                )
                action.connect(
                    "clicked", lambda _b, item=entry: self._open_file(item)
                )
            else:
                action = widgets.label(
                    "不跟随" if kind == "symlink" else "—", css="field-help"
                )
            name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon = Gtk.Image.new_from_icon_name(
                TYPE_ICON.get(kind, "text-x-generic-symbolic")
            )
            icon.set_pixel_size(16)
            name_box.append(icon)
            strong = widgets.label(name, css="table-name", wrap=True)
            strong.set_hexpand(True)
            name_box.append(strong)
            if kind == "symlink" and entry.get("target"):
                name_box.append(
                    widgets.label(
                        f"→ {entry.get('target')}", css="muted monospace"
                    )
                )
            rows.append(
                [
                    name_box,
                    TYPE_TEXT.get(kind, kind),
                    "—" if kind == "dir" else widgets.format_bytes(entry.get("size")),
                    widgets.format_timestamp(entry.get("mtime")) or "—",
                    str(entry.get("mode") or "—"),
                    action,
                ]
            )
        self.list_host.append(
            widgets.table(
                ["名称", "类型", "大小", "修改时间", "权限", "操作"],
                rows,
                weights=[3.4, 1.1, 1.1, 1.8, 1.2, 1.4],
            )
        )

    # ------------------------------------------------------------------
    # Preview windows
    # ------------------------------------------------------------------
    def _base_window(self, title_text: str, subtitle: str) -> Gtk.Window:
        window = Gtk.Window()
        window.set_title(title_text)
        window.set_default_size(860, 660)
        window.set_transient_for(self.page.app.window)
        header = Adw.HeaderBar()
        window.set_titlebar(header)
        self._preview_window = window
        self._preview_subtitle = subtitle
        return window

    def _preview_image(self, path: str, title_text: str, entry: dict[str, Any]) -> None:
        if self.page.api is None:
            return
        subtitle = (
            "本机工作区图片预览"
            if self.mode == "host"
            else "容器工作区图片预览"
        )
        window = self._base_window(title_text, subtitle)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_top(10)
        body.set_margin_bottom(10)
        body.set_margin_start(10)
        body.set_margin_end(10)
        body.append(widgets.label(path, css="field-help monospace", wrap=True))
        body.append(
            widgets.muted(
                f"{widgets.format_bytes(entry.get('size'))} · "
                f"{widgets.format_timestamp(entry.get('mtime')) or '—'}"
                + (f" · {entry.get('mode')}" if entry.get("mode") else "")
            )
        )
        spinner = Gtk.Spinner()
        spinner.start()
        body.append(spinner)
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_hexpand(True)
        picture.set_vexpand(True)
        body.append(picture)
        window.set_child(body)
        window.present()
        raw_path = MODES[self.mode]["raw"]
        api = self.page.api

        def _do() -> bytes:
            return api.raw(f"{raw_path}?path={q(path)}", timeout=120)

        def _done(data: bytes) -> None:
            spinner.stop()
            spinner.set_visible(False)
            try:
                picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
            except Exception as exc:  # noqa: BLE001
                body.append(widgets.muted(f"图片解码失败：{exc}"))

        def _failed(exc: BaseException) -> None:
            spinner.stop()
            spinner.set_visible(False)
            body.append(widgets.muted(f"读取图片失败：{exc}"))

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _preview_text(self, path: str, title_text: str) -> None:
        if self.page.api is None:
            return
        window = self._base_window(
            title_text,
            "本机工作区文件预览"
            if self.mode == "host"
            else "容器工作区文件预览",
        )
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_top(10)
        body.set_margin_bottom(10)
        body.set_margin_start(10)
        body.set_margin_end(10)
        body.append(widgets.label(path, css="field-help monospace", wrap=True))
        status = widgets.muted("正在读取…")
        body.append(status)
        window.set_child(body)
        window.present()
        content_path = MODES[self.mode]["content"]
        api = self.page.api

        def _do() -> dict[str, Any]:
            return api.get(f"{content_path}?path={q(path)}", timeout=120)

        def _done(data: dict[str, Any]) -> None:
            widgets.clear(body)
            body.append(widgets.label(path, css="field-help monospace", wrap=True))
            body.append(
                widgets.muted(
                    f"{widgets.format_bytes(data.get('size'))} · "
                    f"{widgets.format_timestamp(data.get('mtime')) or '—'}"
                    + (f" · {data.get('mode')}" if data.get("mode") else "")
                )
            )
            if data.get("binary"):
                body.append(widgets.muted("二进制文件，不提供文本预览。"))
            else:
                area = widgets.text_view(
                    str(data.get("content") or ""), height=540, monospace=True
                )
                area.set_vexpand(True)
                body.append(area)
            if data.get("truncated"):
                body.append(
                    widgets.muted(
                        f"文件较大，仅预览前 "
                        f"{widgets.format_bytes(data.get('preview_bytes') or 0)}。"
                    )
                )

        def _failed(exc: BaseException) -> None:
            widgets.clear(body)
            body.append(widgets.muted(f"读取文件失败：{exc}"))

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _open_file(self, entry: dict[str, Any]) -> None:
        name = str(entry.get("name") or "")
        path = str(entry.get("path") or "")
        if posixpath.splitext(name)[1].lower() in IMAGE_EXTS:
            self._preview_image(path, name or path, entry)
        else:
            self._preview_text(path, name or path)
