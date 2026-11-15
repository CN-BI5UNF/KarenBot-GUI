"""GUI 外观皮肤：Karen 内置样式、系统 Adwaita、外部 GTK4 主题。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from gi.repository import GLib

logger = logging.getLogger(__name__)

KAREN_SKIN = "karen"
SYSTEM_SKIN = "system"
THEME_PREFIX = "theme:"

FONT_SCALE_DEFAULT = 1.0
FONT_SCALE_MIN = 0.8
FONT_SCALE_MAX = 1.6
_FONT_SIZE_PX = re.compile(r"(font-size\s*:\s*)([0-9]+(?:\.[0-9]+)?)px")


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


def _font_scale_path() -> Path:
    return _config_dir() / "font-scale"


def read_font_scale() -> float:
    try:
        value = float(_font_scale_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return FONT_SCALE_DEFAULT
    return max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, value))


def write_font_scale(value: float) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        scale = FONT_SCALE_DEFAULT
    scale = round(max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale)), 2)
    path = _font_scale_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{scale:g}", encoding="utf-8")
    except OSError:
        logger.warning("保存 GUI 字体大小失败", exc_info=True)
    return scale


def scale_font_sizes(css: str, scale: float | None = None) -> str:
    """Scale every absolute font-size in a CSS document.

    The bundled style sheet uses px sizes for headings and labels; changing
    only ``window`` would leave those fixed.  Scaling the declarations keeps
    the original hierarchy while respecting the user's preference.
    """
    factor = read_font_scale() if scale is None else float(scale)
    if abs(factor - 1.0) < 0.001:
        return css

    def _replace(match: re.Match[str]) -> str:
        size = max(6.0, round(float(match.group(2)) * factor, 1))
        return f"{match.group(1)}{size:g}px"

    return _FONT_SIZE_PX.sub(_replace, css)


def base_font_css(scale: float | None = None) -> str:
    factor = read_font_scale() if scale is None else float(scale)
    return f"window {{ font-size: {14 * factor:g}px; }}"


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
    "FONT_SCALE_DEFAULT",
    "FONT_SCALE_MAX",
    "FONT_SCALE_MIN",
    "KAREN_SKIN",
    "SYSTEM_SKIN",
    "THEME_PREFIX",
    "base_font_css",
    "discover_gtk4_themes",
    "external_theme_css",
    "read_font_scale",
    "read_skin",
    "scale_font_sizes",
    "skin_options",
    "theme_roots",
    "write_font_scale",
    "write_skin",
]
