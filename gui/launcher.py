"""GTK 启动器：在导入 gi 之前选择渲染器，并在崩溃时自动回退。

GTK/GSK 的环境变量必须在 ``gi`` 被导入之前设置，所以不能把逻辑放进
``gui.app``。这里只依赖标准库；真正的应用由子进程启动，启动器根据退出
码决定是否用软件渲染再试一次。

``pythonw.exe`` 启动时没有控制台，``sys.stdin/stdout/stderr`` 都是 ``None``。
启动器和子进程都必须先经过 :func:`ensure_standard_streams`，否则任何一次
``print()`` / ``logging`` / ``sys.stderr.write`` 都会让 GUI 静默退出。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_STAGE_ENV = "KAREN_GUI_RENDER_STAGE"
_USER_RENDERER_ENV = "KAREN_GUI_RENDERER"
_CHILD_FLAG = "--karen-gui-child"
_MAX_STAGE = 2
_EARLY_EXIT_SECONDS = 20.0
_CHILD_LOG_NAME = "gui-child.log"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    from .paths import default_data_root

    return Path(default_data_root(_project_root()))


def _log_path() -> Path:
    try:
        path = _data_root() / "logs" / "gui-launcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:  # noqa: BLE001
        return Path(tempfile.gettempdir()) / "karen-gui-launcher.log"


def _child_log_path() -> Path:
    path = _data_root() / "logs" / _CHILD_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _rotate_child_log() -> None:
    """Keep one previous child log so repeated launches cannot grow forever."""
    try:
        path = _child_log_path()
        if path.is_file() and path.stat().st_size > 0:
            os.replace(path, path.with_name(path.name + ".1"))
    except Exception:  # noqa: BLE001 - logging must never block startup
        pass


def ensure_standard_streams() -> None:
    """Replace ``None`` standard streams (pythonw.exe) with the null device."""
    for name in ("stdin", "stdout", "stderr"):
        if getattr(sys, name, None) is not None:
            continue
        mode = "r" if name == "stdin" else "w"
        try:
            setattr(sys, name, open(os.devnull, mode, encoding="utf-8"))
        except OSError:
            pass


def _enable_faulthandler() -> None:
    try:
        import faulthandler

        stream = sys.stderr
        if stream is None:
            return
        faulthandler.enable(file=stream)
    except (AttributeError, OSError, RuntimeError, ValueError):
        pass


def prepare_process() -> None:
    """Make a pythonw process safe before any GTK/backend import."""
    ensure_standard_streams()
    _enable_faulthandler()


def _write_stderr(line: str) -> None:
    stream = sys.stderr
    if stream is None:
        # pythonw.exe has no console.  Writing here used to raise
        # AttributeError before Popen(), so the desktop shortcut could never
        # start the GUI.
        return
    try:
        stream.write(line)
        stream.flush()
    except (AttributeError, OSError, ValueError):
        pass


def _log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
    try:
        with _log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    _write_stderr(line)


def _show_error_dialog(title: str, message: str) -> None:
    """Surface a fatal error on pythonw, where stderr is not visible."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:  # noqa: BLE001
        pass


def report_fatal(title: str, message: str) -> None:
    """Log a fatal error and show it to the user when no console exists."""
    _log(f"{title}: {message}")
    _show_error_dialog(title, message)


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
    # 子进程同样可能跑在 pythonw 下；保留故障栈，便于以后抓原生崩溃。
    env.setdefault("PYTHONFAULTHANDLER", "1")
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


def _run_child(
    stage: int,
    args: list[str],
    *,
    windowed: bool = False,
) -> tuple[int, float]:
    env = _stage_environment(stage, os.environ)
    command = _child_command(args)
    started = time.monotonic()
    _log(f"启动 GUI stage={stage} command={' '.join(command)}")
    child_log = None
    child_log_path: Path | None = None
    if windowed:
        # 没有控制台时，子进程的 traceback 只能写进文件；否则任何启动期
        # 崩溃都只会表现为“点了没反应”。
        try:
            child_log_path = _child_log_path()
            child_log = child_log_path.open("a", encoding="utf-8", buffering=1)
            _log(f"子进程输出写入 {child_log_path}")
        except OSError as exc:
            _log(f"无法创建子进程日志，输出将丢弃: {exc}")
    try:
        process = subprocess.Popen(
            command,
            env=env,
            cwd=str(_project_root()),
            stdin=subprocess.DEVNULL if windowed else None,
            stdout=child_log if child_log is not None else None,
            stderr=subprocess.STDOUT if child_log is not None else None,
        )
    except OSError as exc:
        if child_log is not None:
            child_log.close()
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
    finally:
        if child_log is not None:
            child_log.close()
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


def _failure_message(code: int) -> str:
    try:
        launcher_log = str(_log_path())
    except Exception:  # noqa: BLE001
        launcher_log = "（无法确定）"
    try:
        child_log = str(_child_log_path())
    except Exception:  # noqa: BLE001
        child_log = "（无法确定）"
    return (
        f"KarenBot GUI 未能启动（退出码 {code}）。\n\n"
        f"启动器日志：\n{launcher_log}\n\n"
        f"子进程日志：\n{child_log}"
    )


def _run(raw: list[str], *, windowed: bool) -> int:
    if _CHILD_FLAG in raw:
        raw = [item for item in raw if item != _CHILD_FLAG]
        from .app import main as app_main

        return app_main(raw)

    args = list(raw[1:])
    mode = _requested_mode(args)
    if mode == "gl":
        return _run_child(0, args, windowed=windowed)[0]
    start_stage = 1 if mode == "cairo" else 0
    stage = start_stage
    while stage <= _MAX_STAGE:
        code, elapsed = _run_child(stage, args, windowed=windowed)
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


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv)
    # pythonw.exe 没有控制台；必须在替换标准流之前记住这一点。
    windowed = sys.stderr is None or sys.stdout is None
    prepare_process()
    if windowed:
        _rotate_child_log()
    try:
        code = _run(raw, windowed=windowed)
    except SystemExit:
        # --help/--version 在 frozen 入口里走 argparse 的 SystemExit，不能
        # 当成启动失败。
        raise
    except BaseException as exc:  # noqa: BLE001 - last line of defence
        import traceback

        report_fatal(
            "KarenBot GUI 启动失败",
            f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
        )
        return 1
    if code != 0 and windowed:
        _show_error_dialog("KarenBot GUI 启动失败", _failure_message(code))
    return code


__all__ = [
    "ensure_standard_streams",
    "main",
    "prepare_process",
    "report_fatal",
]
