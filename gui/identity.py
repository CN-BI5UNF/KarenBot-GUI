"""GApplication identity helpers (no GTK imports)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

APP_ID = "io.github.cnbi5unf.KarenBot.Gui"


def application_id(data_root: Path | None) -> str:
    """Keep isolated GUI data roots in separate GApplication instances.

    GApplication forwards a second process with the same application ID to the
    already-running window.  That is desirable for one data root, but wrong for
    QA/portable installs using ``--data-dir``.  A stable suffix derived from
    the data root lets both instances coexist without touching each other.
    """
    override = os.environ.get("KAREN_GUI_APP_ID", "").strip()
    if override:
        return override
    if data_root is None:
        return APP_ID
    try:
        resolved = Path(data_root).expanduser().resolve()
    except OSError:
        resolved = Path(data_root).expanduser()
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:12]
    return f"{APP_ID}.p{digest}"


__all__ = ["APP_ID", "application_id"]
