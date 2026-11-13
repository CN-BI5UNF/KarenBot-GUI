"""Data-root resolution shared by the GUI launcher and LocalControlServer.

Development checkouts keep their isolated ``data/`` directory so opening the
GUI cannot touch the data root of a running WebUI service.  Packaged builds
(which do not contain ``.git``) use the normal per-user application data root;
that directory is outside the source tree, so the in-app updater is allowed to
manage the checkout without refusing every operation with
``data_dir_inside_project``.

``KAREN_GUI_DATA_DIR`` overrides both rules for portable installs and tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

ENV_DATA_DIR = "KAREN_GUI_DATA_DIR"


def default_data_root(project_root: Path) -> Path:
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser()
    root = Path(project_root)
    if (root / ".git").exists():
        return root / "data"
    return Path(user_data_dir("KarenBot", appauthor=False))


def data_dir_inside_project(project_root: Path, data_root: Path) -> bool:
    """Return whether *data_root* is the checkout or a descendant of it."""
    try:
        root = Path(project_root).expanduser().resolve()
        target = Path(data_root).expanduser().resolve()
    except OSError:
        root = Path(project_root).expanduser()
        target = Path(data_root).expanduser()
    return target == root or root in target.parents


__all__ = [
    "ENV_DATA_DIR",
    "data_dir_inside_project",
    "default_data_root",
]
