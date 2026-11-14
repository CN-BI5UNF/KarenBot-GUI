"""可选中文字体：检测、fontconfig 配置与安装状态。"""

from __future__ import annotations

import os
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from gi.repository import GLib

FONT_FILENAMES = (
    "NotoSansSC-VF.otf",
    "NotoSerifSC-VF.otf",
)


def font_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / "KarenBot" / "fonts"


def fontconfig_path() -> Path:
    return font_dir() / "fonts.conf"


def missing_fonts() -> list[str]:
    root = font_dir()
    return [name for name in FONT_FILENAMES if not (root / name).is_file()]


def ensure_fontconfig() -> Path | None:
    """生成只追加 app 字体目录的 fontconfig 配置；不覆盖系统字体。"""
    root = font_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = fontconfig_path()
    cache = root / "cache"
    if os.name == "nt":
        windows_root = str(
            os.environ.get("WINDIR") or r"C:\Windows"
        ).replace("\\", "/")
        windows_fonts = Path(windows_root) / "Fonts"
        include = f"  <dir>{xml_escape(windows_fonts.as_posix())}</dir>\n"
    else:
        include = (
            '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
        )
    content = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        "<fontconfig>\n"
        f"{include}"
        f"  <dir>{xml_escape(root.as_posix())}</dir>\n"
        f"  <cachedir>{xml_escape(cache.as_posix())}</cachedir>\n"
        "</fontconfig>\n"
    )
    try:
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return path


__all__ = [
    "FONT_FILENAMES",
    "ensure_fontconfig",
    "font_dir",
    "fontconfig_path",
    "missing_fonts",
]
