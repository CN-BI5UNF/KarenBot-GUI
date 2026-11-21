"""Data-root resolution shared by the GUI launcher and LocalControlServer.

Development checkouts keep their isolated ``data/`` directory so opening the
GUI cannot touch the data root of a running WebUI service.  Packaged builds
(which do not contain ``.git``) use the normal per-user application data root;
that directory is outside the source tree, so the in-app updater is allowed to
manage the checkout without refusing every operation with
``data_dir_inside_project``.

``KAREN_GUI_DATA_DIR`` overrides both rules for portable installs and tests.
``KAREN_DATA_ROOT`` is the variable written by the Windows installer; the GUI
honours it as well so ``<install>/data`` actually becomes the runtime root.
Older GUI builds ignored it and used the platform data directory, so
:func:`adopt_legacy_data_root` performs a one-time copy for existing installs.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from platformdirs import user_data_dir

ENV_DATA_DIR = "KAREN_GUI_DATA_DIR"
ENV_RUNTIME_DATA_DIR = "KAREN_DATA_ROOT"

_ROOT_MARKER = ".gui-data-root"
_LEGACY_IGNORED = {"logs", "cache", "__pycache__"}


def platform_data_root() -> Path:
    """The per-user data root used by packaged builds without overrides."""
    return Path(user_data_dir("KarenBot", appauthor=False))


def default_data_root(project_root: Path) -> Path:
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser()
    runtime_override = os.environ.get(ENV_RUNTIME_DATA_DIR, "").strip()
    if runtime_override:
        return Path(runtime_override).expanduser()
    root = Path(project_root)
    if (root / ".git").exists():
        return root / "data"
    return platform_data_root()


def _instance_dir(root: Path) -> Path:
    return root / "instances" / "default"


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return left.expanduser() == right.expanduser()


def _ignore_legacy(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _LEGACY_IGNORED}


def _has_instance_data(root: Path) -> bool:
    try:
        return any(_instance_dir(root).iterdir())
    except OSError:
        return False


def _write_root_marker(root: Path, legacy: Path | None) -> None:
    try:
        source = f"adopted_from={legacy}\n" if legacy is not None else ""
        (root / _ROOT_MARKER).write_text(source, encoding="utf-8")
    except OSError:
        pass


def _copy_newer_files(source: Path, destination: Path) -> int:
    """Copy only files in *source* that are newer than their destination.

    Used when the installer already created ``<install>/data`` (from a legacy
    ``app/data``) while older GUI builds kept writing to the platform data
    root.  In that case the platform root is the live one; per-file mtimes keep
    newer data without overwriting anything that is genuinely newer in target.
    """
    copied = 0
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [name for name in dirnames if name not in _LEGACY_IGNORED]
        relative = Path(dirpath).relative_to(source)
        out_dir = destination / relative
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            if name in _LEGACY_IGNORED or name.endswith(".log"):
                continue
            src = Path(dirpath) / name
            dst = out_dir / name
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
            shutil.copy2(src, dst)
            copied += 1
    return copied


def adopt_legacy_data_root(project_root: Path, data_root: Path) -> Path:
    """Copy data from the pre-``KAREN_DATA_ROOT`` location exactly once.

    The Windows installer writes ``KAREN_DATA_ROOT=<install>/data`` and already
    migrates legacy ``app/data`` there.  GUI builds before this fix ignored the
    variable, so existing users have their data only in the platform data
    directory.  Migrating keeps the installer's "program and data are separate"
    promise without showing those users a fresh setup wizard.

    Returns *data_root* on success.  If the copy fails, the legacy root is
    returned instead so the user still sees their data; nothing is deleted.
    """
    target = Path(data_root).expanduser()
    legacy = platform_data_root()
    if _same_path(target, legacy):
        return target
    if (target / _ROOT_MARKER).is_file():
        # 这个数据根已经由修复后的 GUI 接管过，不再重复迁移。
        return target

    legacy_has_data = _has_instance_data(legacy)
    if _has_instance_data(target):
        # 目标已有数据（通常来自安装器的 app/data 迁移），但修复前的 GUI
        # 一直把新数据写在平台目录。把平台目录里更新的文件补进来，避免
        # 用户升级后看到一份旧数据。
        if legacy_has_data:
            try:
                _copy_newer_files(legacy, target)
            except OSError:
                return legacy
        _write_root_marker(target, legacy if legacy_has_data else None)
        return target

    if not legacy_has_data:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            return legacy
        _write_root_marker(target, None)
        return target

    staging = target.parent / f"{target.name}.adopting"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(legacy, staging, symlinks=True, ignore=_ignore_legacy)
        target.mkdir(parents=True, exist_ok=True)
        # Move complete top-level entries instead of merging everything into
        # target: ``instances`` is then either fully present or untouched, so
        # a failed migration cannot leave a half-copied database behind.
        for entry in staging.iterdir():
            destination = target / entry.name
            if destination.exists():
                if destination.is_dir() and entry.is_dir():
                    shutil.copytree(
                        entry, destination, symlinks=True, dirs_exist_ok=True
                    )
                else:
                    shutil.copy2(entry, destination)
            else:
                shutil.move(str(entry), str(destination))
        _write_root_marker(target, legacy)
        shutil.rmtree(staging, ignore_errors=True)
        return target
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return legacy


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
    "ENV_RUNTIME_DATA_DIR",
    "adopt_legacy_data_root",
    "data_dir_inside_project",
    "default_data_root",
    "platform_data_root",
]
