"""GUI 外观皮肤：Karen 内置样式、系统 Adwaita、外部 GTK4 主题。"""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import GLib

logger = logging.getLogger(__name__)

KAREN_SKIN = "karen"
SYSTEM_SKIN = "system"
THEME_PREFIX = "theme:"


def _config_dir() -> Path:
    return Path(GLib.get_user_config_dir()) / "karen-gui"


def _preference_path() -> Path:
    return _config_dir() / "skin"


def theme_roots() -> list[Path]:
    return [
        Path(GLib.get_user_data_dir()) / "themes",
        _config_dir() / "themes",
        Path.home() / ".themes",
    ]


def discover_gtk4_themes() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in theme_roots():
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            css = child / "gtk-4.0" / "gtk.css"
            if css.is_file() and child.name not in found:
                found[child.name] = css
    return dict(sorted(found.items(), key=lambda item: item[0].casefold()))


def skin_options() -> list[tuple[str, str]]:
    options = [
        (KAREN_SKIN, "Karen 暖色（推荐，最接近 Linux 目标机）"),
        (SYSTEM_SKIN, "系统 Adwaita（跟随桌面）"),
    ]
    options.extend(
        (f"{THEME_PREFIX}{name}", f"{name}（GTK4 主题）")
        for name in discover_gtk4_themes()
    )
    return options


def read_skin() -> str:
    try:
        value = _preference_path().read_text(encoding="utf-8").strip()
    except OSError:
        return KAREN_SKIN
    if value in {KAREN_SKIN, SYSTEM_SKIN}:
        return value
    if value.startswith(THEME_PREFIX):
        name = value[len(THEME_PREFIX) :]
        if name in discover_gtk4_themes():
            return value
    return KAREN_SKIN


def write_skin(value: str) -> None:
    path = _preference_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value or KAREN_SKIN, encoding="utf-8")
    except OSError:
        logger.warning("保存 GUI 皮肤选择失败", exc_info=True)


def external_theme_css() -> str:
    skin = read_skin()
    if not skin.startswith(THEME_PREFIX):
        return ""
    name = skin[len(THEME_PREFIX) :]
    css_path = discover_gtk4_themes().get(name)
    if css_path is None:
        logger.warning("GTK4 主题不存在或缺少 gtk-4.0/gtk.css: %s", name)
        return ""
    try:
        return css_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("读取 GTK4 主题失败: %s", css_path, exc_info=True)
        return ""


__all__ = [
    "KAREN_SKIN",
    "SYSTEM_SKIN",
    "THEME_PREFIX",
    "discover_gtk4_themes",
    "external_theme_css",
    "read_skin",
    "skin_options",
    "theme_roots",
    "write_skin",
]
