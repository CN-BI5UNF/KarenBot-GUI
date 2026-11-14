"""GTK 启动器：在导入 gi 之前选择渲染器，并在崩溃时自动回退。

GTK/GSK 的环境变量必须在 ``gi`` 被导入之前设置，所以不能把逻辑放进
``gui.app``。这里只依赖标准库；真正的应用由子进程启动，启动器根据退出
码决定是否用软件渲染再试一次。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_STAGE_ENV = "KAREN_GUI_RENDER_STAGE"
_USER_RENDERER_ENV = "KAREN_GUI_RENDERER"
_CHILD_FLAG = "--karen-gui-child"
_MAX_STAGE = 2
_EARLY_EXIT_SECONDS = 20.0


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _log_path() -> Path:
    try:
        from .paths import default_data_root

        root = default_data_root(_project_root())
        path = Path(root) / "logs" / "gui-launcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:  # noqa: BLE001
        return Path("/tmp/karen-gui-launcher.log")


def _log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        with _log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    sys.stderr.write(line)
    sys.stderr.flush()


def _fontconfig_file() -> Path | None:
    data_home = Path(
        os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    )
    root = data_home / "KarenBot" / "fonts"
    path = root / "fonts.conf"
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "cache").mkdir(parents=True, exist_ok=True)
        content = (
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            "<fontconfig>\n"
            '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
            f"  <dir>{root}</dir>\n"
            f"  <cachedir>{root / 'cache'}</cachedir>\n"
            "</fontconfig>\n"
        )
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        return path
    except OSError:
        return None


def _stage_environment(stage: int, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    if not env.get("FONTCONFIG_FILE"):
        fontconfig = _fontconfig_file()
        if fontconfig is not None:
            env["FONTCONFIG_FILE"] = str(fontconfig)
    env[_STAGE_ENV] = str(stage)
    if stage >= 1:
        # Cairo 是最保守的软件渲染路径；GDK_DEBUG 只是额外提示，
        # 不支持该值的 GTK 版本会忽略它。
        env["GSK_RENDERER"] = "cairo"
        env["GDK_DEBUG"] = "gl-disable"
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    if stage >= 2:
        if sys.platform.startswith("win"):
            env["GDK_BACKEND"] = "win32"
        elif base.get("DISPLAY"):
            env["GDK_BACKEND"] = "x11"
    return env


def _child_command(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, _CHILD_FLAG, *args]
    return [sys.executable, "-m", "gui._run", *args]


def _run_child(stage: int, args: list[str]) -> tuple[int, float]:
    env = _stage_environment(stage, os.environ)
    command = _child_command(args)
    started = time.monotonic()
    _log(f"启动 GUI stage={stage} command={' '.join(command)}")
    try:
        process = subprocess.Popen(command, env=env, cwd=str(_project_root()))
    except OSError as exc:
        _log(f"启动子进程失败: {exc}")
        return 127, 0.0
    try:
        code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130, time.monotonic() - started
    return int(code or 0), time.monotonic() - started


def _requested_mode(args: list[str]) -> str:
    override = os.environ.get(_USER_RENDERER_ENV, "").strip().lower()
    if override in {"cairo", "software"}:
        return "cairo"
    if override in {"gl", "hardware"}:
        return "gl"
    for index, value in enumerate(args):
        if value == "--renderer" and index + 1 < len(args):
            return args[index + 1].strip().lower()
        if value.startswith("--renderer="):
            return value.split("=", 1)[1].strip().lower()
    return "auto"


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv)
    if _CHILD_FLAG in raw:
        raw = [item for item in raw if item != _CHILD_FLAG]
        from .app import main as app_main

        return app_main(raw)

    args = list(raw[1:])
    mode = _requested_mode(args)
    if mode == "gl":
        return _run_child(0, args)[0]
    start_stage = 1 if mode == "cairo" else 0
    stage = start_stage
    while stage <= _MAX_STAGE:
        code, elapsed = _run_child(stage, args)
        if code == 0:
            return 0
        if stage >= _MAX_STAGE:
            _log(f"GUI 在最高回退 stage={stage} 仍退出 code={code}")
            return code
        if elapsed > _EARLY_EXIT_SECONDS:
            _log(f"GUI 正常运行后退出 code={code}，不再降级")
            return code
        _log(f"GUI 提前退出 code={code}（{elapsed:.1f}s），回退到 stage={stage + 1}")
        stage += 1
    return 1


__all__ = ["main"]
