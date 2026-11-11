"""Karen Desktop — native GTK4 application entry point."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, widgets  # noqa: E402
from .api import ApiClient  # noqa: E402
from .identity import application_id  # noqa: E402
from .local_server import LocalControlServer  # noqa: E402

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# WebUI 的导航顺序与标题。第四列保留给旧的元组解包代码，不再显示分组标题。
NAV_ITEMS = [
    ("overview", "总览", "speedometer-symbolic", "", "overview", "OverviewPage"),
    ("chats", "对话", "mail-unread-symbolic", "", "chats", "ChatsPage"),
    ("memory", "记忆", "user-bookmarks-symbolic", "", "memory", "MemoryPage"),
    ("mind", "人格后台", "emblem-favorite-symbolic", "", "mind", "MindPage"),
    ("logs", "日志", "utilities-terminal-symbolic", "", "logs", "LogsPage"),
    ("personas", "人格", "avatar-default-symbolic", "", "personas", "PersonasPage"),
    ("slang", "黑话", "chat-message-new-symbolic", "", "slang", "SlangPage"),
    ("knowledge", "知识", "accessories-dictionary-symbolic", "", "knowledge", "KnowledgePage"),
    ("models", "模型管理", "applications-science-symbolic", "", "models", "ModelsPage"),
    ("emoji", "表情包", "face-smile-symbolic", "", "emoji", "EmojiPage"),
    ("container", "容器", "package-x-generic-symbolic", "", "container", "ContainerPage"),
    ("storage", "存储与数据", "drive-harddisk-symbolic", "", "storage", "StoragePage"),
    ("access", "黑白名单", "system-users-symbolic", "", "access", "AccessListsPage"),
    ("triggers", "群聊触发", "preferences-system-notifications-symbolic", "", "triggers", "TriggersPage"),
    ("settings", "设置", "emblem-system-symbolic", "", "settings", "SettingsPage"),
]

# WebUI 通过总览页的更新提示和设置页打开更新面板，导航栏里没有单独的“更新”。
# 原生 GUI 保留这个页面，但不占用侧栏位置。
HIDDEN_PAGES = [
    ("updates", "更新", "software-update-available-symbolic", "", "updates", "UpdatesPage"),
]

SIDEBAR_WIDTH = 200
SIDEBAR_COLLAPSED_WIDTH = 64


_CSS_PROVIDER: Gtk.CssProvider | None = None

_LIGHT_PALETTE = """
/* 与 webui/static/app.css 的暖米色 / 青瓷青设计令牌保持一致。 */
@define-color karen_bg #F8F5EE;
@define-color karen_fg #2B2622;
@define-color karen_text_secondary #6B635A;
@define-color karen_text_disabled #B5AC9F;
@define-color karen_sidebar_bg #FCFAF4;
@define-color karen_sidebar_fg #2B2622;
@define-color karen_card_bg #FCFAF4;
@define-color karen_card_fg #2B2622;
@define-color karen_hover #F0E8D6;
@define-color karen_border #E8E1CE;
@define-color karen_accent_bg #6FA39A;
@define-color karen_accent_fg #4F7F76;
@define-color karen_accent_soft rgba(111, 163, 154, 0.11);
@define-color karen_success #7A9B6E;
@define-color karen_warning #D9A85F;
@define-color karen_error #C0584F;
@define-color karen_success_bg #7A9B6E;
@define-color karen_success_fg #FFFFFF;
@define-color karen_warning_bg #D9A85F;
@define-color karen_warning_fg #FFFFFF;
@define-color karen_error_bg #C0584F;
@define-color karen_error_fg #FFFFFF;
@define-color accent_color #4F7F76;
@define-color accent_bg_color #6FA39A;
@define-color accent_fg_color #FFFFFF;
@define-color window_bg_color @karen_bg;
@define-color window_fg_color @karen_fg;
@define-color view_bg_color @karen_card_bg;
@define-color view_fg_color @karen_card_fg;
@define-color headerbar_bg_color @karen_bg;
@define-color headerbar_fg_color @karen_fg;
@define-color card_bg_color @karen_card_bg;
@define-color card_fg_color @karen_card_fg;
@define-color popover_bg_color @karen_card_bg;
@define-color popover_fg_color @karen_card_fg;
"""

_DARK_PALETTE = """
@define-color karen_bg #1A1817;
@define-color karen_fg #E8E2D4;
@define-color karen_text_secondary #9B9286;
@define-color karen_text_disabled #5C544A;
@define-color karen_sidebar_bg #232120;
@define-color karen_sidebar_fg #E8E2D4;
@define-color karen_card_bg #232120;
@define-color karen_card_fg #E8E2D4;
@define-color karen_hover #2E2B28;
@define-color karen_border #3A3633;
@define-color karen_accent_bg #6FA39A;
@define-color karen_accent_fg #9AC8BE;
@define-color karen_accent_soft rgba(111, 163, 154, 0.15);
@define-color karen_success #7A9B6E;
@define-color karen_warning #D9A85F;
@define-color karen_error #C0584F;
@define-color karen_success_bg #7A9B6E;
@define-color karen_success_fg #FFFFFF;
@define-color karen_warning_bg #D9A85F;
@define-color karen_warning_fg #FFFFFF;
@define-color karen_error_bg #C0584F;
@define-color karen_error_fg #FFFFFF;
@define-color accent_color #9AC8BE;
@define-color accent_bg_color #6FA39A;
@define-color accent_fg_color #FFFFFF;
@define-color window_bg_color @karen_bg;
@define-color window_fg_color @karen_fg;
@define-color view_bg_color @karen_card_bg;
@define-color view_fg_color @karen_card_fg;
@define-color headerbar_bg_color @karen_bg;
@define-color headerbar_fg_color @karen_fg;
@define-color card_bg_color @karen_card_bg;
@define-color card_fg_color @karen_card_fg;
@define-color popover_bg_color @karen_card_bg;
@define-color popover_fg_color @karen_card_fg;
"""


def _theme_preference_path() -> Path:
    return Path(GLib.get_user_config_dir()) / "karen-gui" / "theme"


def _read_theme_preference() -> str:
    try:
        value = _theme_preference_path().read_text(encoding="utf-8").strip()
        return value if value in _COLOR_SCHEMES else "auto"
    except OSError:
        return "auto"


def _write_theme_preference(value: str) -> None:
    try:
        path = _theme_preference_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        logger.debug("保存外观偏好失败", exc_info=True)


def _sidebar_preference_path() -> Path:
    return Path(GLib.get_user_config_dir()) / "karen-gui" / "sidebar"


def _read_sidebar_collapsed() -> bool:
    try:
        return _sidebar_preference_path().read_text(encoding="utf-8").strip() == "collapsed"
    except OSError:
        return False


def _write_sidebar_collapsed(collapsed: bool) -> None:
    try:
        path = _sidebar_preference_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("collapsed" if collapsed else "expanded", encoding="utf-8")
    except OSError:
        logger.debug("保存侧栏偏好失败", exc_info=True)


def _dark_preferred() -> bool:
    try:
        manager = Adw.StyleManager.get_default()
        if manager.get_dark():
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        settings = Gtk.Settings.get_default()
        return bool(
            settings is not None
            and settings.get_property("gtk-application-prefer-dark-theme")
        )
    except Exception:  # noqa: BLE001
        return False


def load_css(dark: bool | None = None) -> None:
    global _CSS_PROVIDER
    if dark is None:
        dark = _dark_preferred()
    css_path = Path(__file__).with_name("style.css")
    try:
        rules = css_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("读取 GUI 样式失败", exc_info=True)
        return
    provider = Gtk.CssProvider()
    try:
        provider.load_from_string(
            (_DARK_PALETTE if dark else _LIGHT_PALETTE) + "\n" + rules
        )
    except Exception:  # noqa: BLE001
        logger.warning("加载 GUI 样式失败", exc_info=True)
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _CSS_PROVIDER is not None:
        try:
            Gtk.StyleContext.remove_provider_for_display(display, _CSS_PROVIDER)
        except Exception:  # noqa: BLE001
            pass
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _CSS_PROVIDER = provider


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Karen")
        self.set_default_size(1240, 840)
        self.set_size_request(960, 640)
        self.app = application
        self.api: ApiClient | None = None
        self.backend: LocalControlServer | None = None
        self.pages: dict[str, Any] = {}
        self.nav_rows: dict[str, Gtk.ListBoxRow] = {}
        self.current_page_id = ""
        self.status: dict[str, Any] = {}
        self._status_poll_busy = False
        self._last_setup_hint = False
        self._last_runtime_state = ""
        self._nav_guard = False
        self._unsaved_dialog: Adw.MessageDialog | None = None
        self._force_close = False
        widgets.install_callback_pump()
        self._build_shell()
        self._show_loading("正在启动本地控制服务…（首次启动约需 20 秒）")
        self._start_backend()

    @property
    def window(self) -> MainWindow:
        """Pages receive the window as their app; this keeps dialog code simple."""
        return self

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------
    def _build_shell(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        # 用 Paned 固定侧栏宽度：普通 Gtk.Box 在内容页最小宽度较小时
        # 会把多余空间分给侧栏，导致 200px 侧栏被撑宽。
        root = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        root.add_css_class("shell-paned")
        root.set_wide_handle(False)
        root.set_resize_start_child(False)
        root.set_resize_end_child(True)
        root.set_shrink_start_child(False)
        root.set_shrink_end_child(False)
        self.shell_paned = root
        self.toast_overlay.set_child(root)
        self.set_content(self.toast_overlay)
        self._sidebar_collapsed = _read_sidebar_collapsed()
        self._nav_labels: list[Gtk.Label] = []
        self._nav_contents: list[Gtk.Box] = []
        self.page_specs = {
            item[0]: item for item in [*NAV_ITEMS, *HIDDEN_PAGES]
        }

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sidebar.set_size_request(SIDEBAR_WIDTH, -1)
        self.sidebar.add_css_class("sidebar")

        self.brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.brand.add_css_class("sidebar-brand")
        self.brand.set_size_request(-1, 56)
        self.brand_text = widgets.label("KarenBot", css="app-name")
        self.brand_text.set_hexpand(True)
        self.brand.append(self.brand_text)
        self.sidebar_toggle = widgets.icon_button(
            "sidebar-show-symbolic", "折叠侧栏", css="flat sidebar-toggle"
        )
        self.sidebar_toggle.connect("clicked", lambda _b: self.toggle_sidebar())
        self.brand.append(self.sidebar_toggle)
        self.sidebar.append(self.brand)

        self.nav_list = Gtk.ListBox()
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class("navigation-sidebar")
        self.nav_list.connect("row-selected", self._on_nav_selected)
        self._build_nav()

        nav_scroller = Gtk.ScrolledWindow()
        nav_scroller.set_vexpand(True)
        nav_scroller.set_child(self.nav_list)
        nav_scroller.add_css_class("sidebar-scroll")
        self.sidebar.append(nav_scroller)

        self.sidebar_foot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.sidebar_foot.add_css_class("sidebar-foot")
        self.runtime_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.runtime_dot = widgets.status_dot(None)
        self.runtime_label = widgets.label("连接中…", css="conn-text")
        self.runtime_label.set_hexpand(True)
        self.runtime_box.append(self.runtime_dot)
        self.runtime_box.append(self.runtime_label)
        self.sidebar_foot.append(self.runtime_box)
        self.version_label = widgets.label(
            f"Karen Desktop {__version__}", css="app-version"
        )
        self.version_label.set_tooltip_text("原生 GTK4 桌面控制台（独立数据目录）")
        self.sidebar_foot.append(self.version_label)
        self.sidebar.append(self.sidebar_foot)
        self._apply_sidebar_state(self._sidebar_collapsed, persist=False)
        root.set_start_child(self.sidebar)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right.set_hexpand(True)
        header = Adw.HeaderBar()
        header.add_css_class("app-topbar")
        header.set_show_start_title_buttons(False)
        # WebUI 顶栏没有居中窗口标题；用空 title widget 覆盖 Adw 默认绑定。
        header.set_title_widget(Gtk.Box())
        self.adapter_badge = widgets.label(
            "启动中", css="badge badge-idle topbar-badge"
        )
        self.persona_label = widgets.label(
            "当前人格：—", css="persona-label"
        )
        header.pack_start(self.adapter_badge)
        header.pack_start(self.persona_label)
        self.restart_button = widgets.icon_button(
            "system-reboot-symbolic", "重启 Runtime（不重新加载代码）"
        )
        self.restart_button.connect("clicked", lambda _b: self._restart_runtime())
        header.pack_end(self.restart_button)
        self.theme_button = self._theme_button()
        header.pack_end(self.theme_button)
        self.fullscreen_button = widgets.icon_button(
            "view-fullscreen-symbolic", "全屏"
        )
        self.fullscreen_button.connect(
            "clicked", lambda _b: self._toggle_fullscreen()
        )
        self.connect(
            "notify::fullscreened",
            lambda *_args: self._update_fullscreen_button(),
        )
        header.pack_end(self.fullscreen_button)
        right.append(header)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(160)
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)
        right.append(self.stack)
        root.set_end_child(right)
        root.set_position(
            SIDEBAR_COLLAPSED_WIDTH if self._sidebar_collapsed else SIDEBAR_WIDTH
        )
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)
        self._update_theme_button()

    # ------------------------------------------------------------------
    # Chrome (WebUI 风格的顶栏 / 可折叠侧栏)
    # ------------------------------------------------------------------
    def _theme_button(self) -> Gtk.Button:
        button = widgets.icon_button(
            "display-brightness-symbolic", "切换外观（跟随系统 → 浅色 → 深色）"
        )
        button.connect("clicked", lambda _b: self._cycle_theme())
        return button

    def _cycle_theme(self) -> None:
        order = ["auto", "light", "dark"]
        current = getattr(self.app, "theme", "auto")
        index = order.index(current) if current in order else 0
        self.app.set_theme(order[(index + 1) % len(order)])

    def _update_theme_button(self) -> None:
        button = getattr(self, "theme_button", None)
        if button is None:
            return
        theme = getattr(self.app, "theme", "auto")
        icons = {
            "auto": "display-brightness-symbolic",
            "light": "weather-clear-symbolic",
            "dark": "weather-clear-night-symbolic",
        }
        labels = {
            "auto": "外观：跟随系统（点击切换浅色）",
            "light": "外观：浅色（点击切换深色）",
            "dark": "外观：深色（点击切换跟随系统）",
        }
        button.set_icon_name(icons.get(theme, icons["auto"]))
        button.set_tooltip_text(labels.get(theme, labels["auto"]))

    def toggle_sidebar(self) -> None:
        self._apply_sidebar_state(not self._sidebar_collapsed, persist=True)

    def _apply_sidebar_state(self, collapsed: bool, *, persist: bool) -> None:
        self._sidebar_collapsed = bool(collapsed)
        width = SIDEBAR_COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH
        self.sidebar.set_size_request(width, -1)
        paned = getattr(self, "shell_paned", None)
        if paned is not None:
            paned.set_position(width)
        if collapsed:
            self.sidebar.add_css_class("collapsed")
        else:
            self.sidebar.remove_css_class("collapsed")
        brand = getattr(self, "brand", None)
        if brand is not None:
            brand.set_halign(Gtk.Align.CENTER if collapsed else Gtk.Align.FILL)
        self.brand_text.set_visible(not collapsed)
        self.sidebar_toggle.set_tooltip_text("展开侧栏" if collapsed else "折叠侧栏")
        self.version_label.set_visible(not collapsed)
        self.runtime_label.set_visible(not collapsed)
        for label in getattr(self, "_nav_labels", []):
            label.set_visible(not collapsed)
        for content in getattr(self, "_nav_contents", []):
            content.set_halign(Gtk.Align.CENTER if collapsed else Gtk.Align.FILL)
        if persist:
            _write_sidebar_collapsed(collapsed)

    def _toggle_fullscreen(self) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _update_fullscreen_button(self) -> None:
        button = getattr(self, "fullscreen_button", None)
        if button is None:
            return
        fullscreen = self.is_fullscreen()
        button.set_icon_name(
            "view-restore-symbolic" if fullscreen else "view-fullscreen-symbolic"
        )
        button.set_tooltip_text("退出全屏" if fullscreen else "全屏")

    def _restart_runtime(self) -> None:
        if self.api is None:
            self.toast("Runtime 尚未就绪")
            return

        def _do() -> Any:
            return self.api.post("/api/system/restart", {}, timeout=180)

        def _confirm() -> None:
            widgets.run_async(
                _do,
                on_success=lambda _r: (
                    self.toast("Runtime 已重启"),
                    self._poll_status(),
                    self.refresh_current(),
                ),
                on_error=lambda exc: self.toast(f"重启失败：{exc}"),
            )

        widgets.ConfirmDialog(
            self,
            heading="重启 Runtime？",
            body="正在处理的对话会被中断。只重建运行时，不会重新加载 Python 代码。",
            confirm_label="重启",
            on_confirm=_confirm,
        )

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_F5:
            self.refresh_current()
            return True
        if keyval == Gdk.KEY_F11:
            self._toggle_fullscreen()
            return True
        if not (state & Gdk.ModifierType.CONTROL_MASK):
            return False
        if keyval == Gdk.KEY_r:
            self.refresh_current()
            return True
        if keyval == Gdk.KEY_q:
            self.close()
            return True
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9:
            index = keyval - Gdk.KEY_1
            if index < len(NAV_ITEMS):
                self.show_page(NAV_ITEMS[index][0])
                return True
        return False

    def _build_nav(self) -> None:
        for page_id, title_text, icon, _section, _module, _attr in NAV_ITEMS:
            row = Gtk.ListBoxRow()
            row.add_css_class("nav-row")
            row.page_id = page_id  # type: ignore[attr-defined]
            row.set_tooltip_text(title_text)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            content.add_css_class("nav-content")
            content.set_halign(Gtk.Align.FILL)
            icon_widget = Gtk.Image.new_from_icon_name(icon)
            icon_widget.set_pixel_size(16)
            icon_widget.add_css_class("nav-icon")
            content.append(icon_widget)
            nav_label = widgets.label(title_text, css="nav-label")
            content.append(nav_label)
            row.set_child(content)
            self.nav_list.append(row)
            self.nav_rows[page_id] = row
            self._nav_labels.append(nav_label)
            self._nav_contents.append(content)

    def _show_loading(self, message: str) -> None:
        page = getattr(self, "_loading_page", None)
        if page is None:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            page.set_valign(Gtk.Align.CENTER)
            page.set_halign(Gtk.Align.CENTER)
            page.set_vexpand(True)
            spinner = Gtk.Spinner()
            spinner.set_size_request(32, 32)
            spinner.start()
            page.append(spinner)
            page.append(widgets.label(message, css="muted", xalign=0.5))
            self._loading_page = page
            self.stack.add_named(page, "loading")
        else:
            last = page.get_last_child()
            if isinstance(last, Gtk.Label):
                last.set_text(message)
        self.stack.set_visible_child_name("loading")

    # ------------------------------------------------------------------
    # Backend lifecycle
    # ------------------------------------------------------------------
    def _start_backend(self) -> None:
        def _start() -> str:
            self.backend = LocalControlServer(
                PROJECT_ROOT,
                data_root=getattr(self.app, "data_root", None),
            )
            return self.backend.start()

        widgets.run_async(
            _start,
            on_success=self._on_backend_ready,
            on_error=self._on_backend_error,
        )

    def _on_backend_ready(self, base_url: str) -> None:
        logger.info("GUI 已连接控制服务 %s", base_url)
        self.api = ApiClient(base_url, token=getattr(self.backend, "auth_token", ""))
        GLib.timeout_add(250, self._first_status_poll)

    def _on_backend_error(self, exc: BaseException) -> None:
        self.runtime_label.set_text("后端启动失败")
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_valign(Gtk.Align.CENTER)
        page.set_halign(Gtk.Align.CENTER)
        page.set_vexpand(True)
        page.append(widgets.title("本地控制服务启动失败", level=1))
        page.append(widgets.muted(str(exc)))
        retry = widgets.button("重试启动", css="suggested-action")
        retry.connect("clicked", lambda _b: self._retry_backend())
        page.append(retry)
        self.stack.add_named(page, "backend-error")
        self.stack.set_visible_child_name("backend-error")
        self.toast(f"本地控制服务启动失败：{exc}")

    def _retry_backend(self) -> None:
        if self.backend is not None:
            self.backend.stop()
        self.backend = None
        self.api = None
        self._show_loading("正在重试本地控制服务…")
        self._start_backend()

    def _first_status_poll(self) -> bool:
        self._poll_status()
        GLib.timeout_add_seconds(2, self._status_timer)
        return False

    def _status_timer(self) -> bool:
        if self.api is None:
            return True
        if not self._status_poll_busy:
            self._poll_status()
        return True

    def _poll_status(self) -> None:
        if self.api is None or self._status_poll_busy:
            return
        self._status_poll_busy = True
        api = self.api

        def _fetch() -> dict[str, Any]:
            return api.get("/api/status", timeout=10)

        widgets.run_async(
            _fetch,
            on_success=self._on_status,
            on_error=self._on_status_error,
        )

    def _set_badge(self, label: Gtk.Label, text: str, tone: str) -> None:
        label.set_text(text)
        for css in ("badge-ok", "badge-warn", "badge-bad", "badge-idle"):
            label.remove_css_class(css)
        label.add_css_class(tone)

    def _on_status(self, status: dict[str, Any]) -> None:
        self._status_poll_busy = False
        self.status = status if isinstance(status, dict) else {}
        state = str(self.status.get("state") or "unknown")
        previous_state = self._last_runtime_state
        self._last_runtime_state = state
        setup_required = bool(self.status.get("setup_required"))
        persona = str(self.status.get("persona") or self.status.get("persona_id") or "—")
        connected = bool(self.status.get("adapter_connected"))
        adapter = self.status.get("adapter") or {}

        if state != "running":
            failed = state == "error"
            self._set_badge(
                self.adapter_badge,
                "启动失败" if failed else ("待配置" if setup_required else "未运行"),
                "badge-bad" if failed else "badge-idle",
            )
        elif not adapter:
            self._set_badge(self.adapter_badge, "未配置渠道", "badge-warn")
        elif connected:
            self._set_badge(
                self.adapter_badge,
                f"已就位 · {adapter.get('mode', '')}://{adapter.get('host', '')}:{adapter.get('port', '')}",
                "badge-ok",
            )
        else:
            self._set_badge(self.adapter_badge, "渠道未连接", "badge-idle")
        self.persona_label.set_text(f"当前人格：{persona}")

        if state == "running":
            uptime = widgets.format_uptime(self.status.get("uptime_seconds"))
            self.runtime_label.set_text(f"运行中 · {uptime}" if uptime else "运行中")
            self._set_runtime_dot(True)
        elif state == "error":
            self.runtime_label.set_text("启动失败")
            self._set_runtime_dot(False)
        elif setup_required:
            self.runtime_label.set_text("等待首次配置")
            self._set_runtime_dot(None)
        else:
            self.runtime_label.set_text("Runtime 未运行")
            self._set_runtime_dot(None)
        data_dir = str(self.status.get("data_dir") or "")
        if data_dir:
            self.version_label.set_tooltip_text(f"数据目录：{data_dir}")
        if setup_required:
            self.nav_list.set_sensitive(False)
            if not self._last_setup_hint:
                self._last_setup_hint = True
                self.show_page("setup")
            return
        self.nav_list.set_sensitive(True)
        if self._last_setup_hint:
            self._last_setup_hint = False
            self.show_page("overview")
        if state == "running" and previous_state != "running":
            page = self.pages.get(self.current_page_id)
            if page is not None and page.loaded:
                page.refresh()
        if not self.current_page_id:
            self.show_page("overview")
        elif self.current_page_id == "overview":
            page = self.pages.get("overview")
            if page is not None and page.loaded:
                page.apply_status(self.status)

    def _on_status_error(self, exc: BaseException) -> None:
        self._status_poll_busy = False
        self._set_runtime_dot(False)
        self.runtime_label.set_text("连接中…")
        self._set_badge(self.adapter_badge, "渠道未连接", "badge-idle")
        self.persona_label.set_text("当前人格：—")

    def _set_runtime_dot(self, ok: bool | None) -> None:
        parent = self.runtime_dot.get_parent()
        if parent is None:
            return
        new_dot = widgets.status_dot(ok)
        parent.remove(self.runtime_dot)
        self.runtime_dot = new_dot
        parent.prepend(new_dot)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _on_nav_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None or self._nav_guard:
            return
        page_id = getattr(row, "page_id", "")
        if page_id:
            self.show_page(page_id)

    def _page_has_unsaved(self, page_id: str) -> bool:
        page = self.pages.get(page_id)
        if page is None:
            return False
        check = getattr(page, "has_unsaved_changes", None)
        try:
            return bool(check()) if callable(check) else False
        except Exception:  # noqa: BLE001
            logger.exception("检查页面未保存状态失败：%s", page_id)
            return False

    def _restore_nav_selection(self) -> None:
        row = self.nav_rows.get(self.current_page_id)
        if row is None:
            return
        self._nav_guard = True
        try:
            self.nav_list.select_row(row)
        finally:
            self._nav_guard = False

    def _discard_current_unsaved(self) -> None:
        page = self.pages.get(self.current_page_id)
        discard = getattr(page, "discard_unsaved_changes", None)
        if callable(discard):
            discard()

    def _confirm_unsaved(
        self,
        *,
        heading: str,
        body: str,
        on_discard: Any,
    ) -> None:
        if self._unsaved_dialog is not None:
            self._unsaved_dialog.present()
            return
        dialog = Adw.MessageDialog.new(self, heading, body)
        dialog.add_response("cancel", "取消")
        dialog.add_response("discard", "放弃修改")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        self._unsaved_dialog = dialog

        def _response(widget: Adw.MessageDialog, response: str) -> None:
            self._unsaved_dialog = None
            widget.close()
            if response != "discard":
                return
            self._discard_current_unsaved()
            on_discard()

        dialog.connect("response", _response)
        dialog.present()

    def _pending_navigation(self, page_id: str, section: str) -> Any:
        def _discard() -> None:
            self.show_page(page_id, section=section)

        return _discard

    def show_page(self, page_id: str, *, section: str = "") -> None:
        if page_id == self.current_page_id and not section:
            return
        if (
            self.current_page_id
            and page_id != self.current_page_id
            and self._page_has_unsaved(self.current_page_id)
        ):
            page = self.pages.get(self.current_page_id)
            title = getattr(page, "page_title", self.current_page_id)
            self._restore_nav_selection()
            self._confirm_unsaved(
                heading="未保存的更改",
                body=f"「{title}」有尚未保存的修改。离开将丢失这些修改。",
                on_discard=self._pending_navigation(page_id, section),
            )
            return
        if page_id == "setup":
            page = self._setup_page()
        elif page_id in self.page_specs:
            page = self._ensure_page(page_id)
        else:
            return
        if page is None:
            return
        self.current_page_id = page_id
        self.stack.set_visible_child(page)
        row = self.nav_rows.get(page_id)
        if row is not None and self.nav_list.get_selected_row() is not row:
            self.nav_list.select_row(row)
        self.set_title(f"{page.page_title or 'Karen'} · KarenBot")
        page.activate()
        if section:
            select_group = getattr(page, "select_group", None)
            if callable(select_group):
                select_group(section)

    def refresh_current(self) -> None:
        page = self.pages.get(self.current_page_id)
        if page is not None:
            page.refresh()

    def _ensure_page(self, page_id: str) -> Any:
        page = self.pages.get(page_id)
        if page is not None:
            return page
        if self.api is None:
            return None
        spec = self.page_specs.get(page_id)
        if spec is None:
            return None
        module_name, attr = spec[4], spec[5]
        try:
            module = importlib.import_module(f"gui.pages.{module_name}")
            page_cls = getattr(module, attr)
            page = page_cls(self)
        except Exception as exc:  # noqa: BLE001
            logger.exception("加载页面失败：%s", page_id)
            page = widgets.card()
            page.append(widgets.title("页面加载失败"))
            page.append(widgets.muted(str(exc)))
        self.pages[page_id] = page
        self.stack.add_named(page, page_id)
        return page

    def _setup_page(self) -> Any:
        page = self.pages.get("setup")
        if page is not None:
            return page
        if self.api is None:
            return None
        from .pages.setup import SetupPage

        page = SetupPage(self)
        self.pages["setup"] = page
        self.stack.add_named(page, "setup")
        return page

    def on_setup_finished(self) -> None:
        self._last_setup_hint = False
        self.nav_list.set_sensitive(True)
        if "overview" in self.pages:
            self.pages["overview"].loaded = False
        self.show_page("overview")
        self._poll_status()

    def toast(self, message: str) -> None:
        widgets.toast(self, message)

    def confirm_close(self) -> bool:
        """Return True when the window may close; otherwise show a guard."""
        if self._force_close:
            return True
        if not self._page_has_unsaved(self.current_page_id):
            return True
        page = self.pages.get(self.current_page_id)
        title = getattr(page, "page_title", self.current_page_id)
        self._confirm_unsaved(
            heading="退出前有未保存的更改",
            body=f"「{title}」有尚未保存的修改。退出将丢失这些修改。",
            on_discard=self._force_close_window,
        )
        return False

    def _force_close_window(self) -> None:
        self._force_close = True
        self.close()

    def close_request(self) -> bool:
        if self.backend is not None:
            self.backend.stop()
        return False


_COLOR_SCHEMES = {
    "auto": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


class KarenApplication(Adw.Application):
    def __init__(
        self,
        *,
        data_root: Path | None = None,
        theme: str = "auto",
    ) -> None:
        super().__init__(
            application_id=application_id(data_root),
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.data_root = data_root
        chosen = theme if theme in _COLOR_SCHEMES else "auto"
        if chosen == "auto":
            chosen = _read_theme_preference()
        self.theme = chosen
        self.window: MainWindow | None = None
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def set_theme(self, theme: str) -> None:
        value = theme if theme in _COLOR_SCHEMES else "auto"
        self.theme = value
        _write_theme_preference(value)
        Adw.StyleManager.get_default().set_color_scheme(
            _COLOR_SCHEMES[value]
        )
        self._apply_theme()
        if self.window is not None:
            self.window._update_theme_button()

    def _apply_theme(self) -> None:
        load_css(_dark_preferred())

    def _on_activate(self, _app: Gio.Application) -> None:
        if self.window is not None:
            self.window.present()
            return
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(_COLOR_SCHEMES[self.theme])
        self._apply_theme()
        style_manager.connect("notify::dark", lambda *_: self._apply_theme())
        self.window = MainWindow(self)
        self.window.connect("close-request", self._on_close_request)
        self.window.present()

    def _on_close_request(self, window: Gtk.Window) -> bool:
        if self.window is not None and not self.window.confirm_close():
            return True
        if self.window is not None and self.window.backend is not None:
            self.window.backend.stop()
        return False

    def _on_shutdown(self, _app: Gio.Application) -> None:
        if self.window is not None and self.window.backend is not None:
            self.window.backend.stop()


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv)
    parser = argparse.ArgumentParser(
        prog="karen-gui",
        description="KarenBot 原生 GTK4 桌面控制台",
        add_help=True,
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="使用指定的数据目录；默认使用本 GUI 目录下的 data/（完全隔离）",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="打印 GUI 版本后退出",
    )
    parser.add_argument(
        "--theme",
        choices=("auto", "light", "dark"),
        default="auto",
        help="外观：跟随系统（auto，默认）、浅色或深色",
    )
    args, remaining = parser.parse_known_args(raw[1:])
    if args.version:
        from . import __version__

        print(__version__)
        return 0
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    data_root = Path(args.data_dir).expanduser() if args.data_dir else None
    app = KarenApplication(data_root=data_root, theme=args.theme)
    return app.run([raw[0], *remaining] if raw else ["karen-gui", *remaining])


__all__ = ["KarenApplication", "MainWindow", "main"]
