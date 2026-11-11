"""Loopback-only control server used by the native GTK application.

The desktop client is not a browser: it never serves the WebUI static files.
It uses the shared ``backend.app`` control plane, so every backend feature
(runtime, chats, personas, memory, settings, updates, ...) has exactly one
implementation for both frontends.  The server binds to 127.0.0.1 on a random
port and requires a per-process random bearer token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BackendError(RuntimeError):
    pass


class LocalControlServer:
    """Own a private RuntimeHost + FastAPI server in a background thread."""

    def __init__(
        self,
        project_root: Path,
        *,
        data_root: Path | None = None,
        host: str = "127.0.0.1",
    ) -> None:
        self.project_root = Path(project_root)
        # The GUI must never silently attach to the live KarenBot data root.
        # ``AppPaths`` treats this checkout as its default project and would
        # otherwise resolve to the user data directory used by the running
        # service.  Use an isolated data directory unless the caller opts in.
        self.data_root = (
            Path(data_root).expanduser()
            if data_root
            else self.project_root / "data"
        )
        self.host = host
        self.port = 0
        self.base_url = ""
        self.server: Any = None
        self.app: Any = None
        self.runtime_host: Any = None
        self.auth_token = ""
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_error = ""
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, *, wait_seconds: float = 90.0) -> str:
        if self._thread is not None:
            return self.base_url
        if self.data_root is not None:
            self.data_root.mkdir(parents=True, exist_ok=True)
            os.environ["KAREN_DATA_ROOT"] = str(self.data_root)
        self.port = _free_port(self.host)
        self.base_url = f"http://{self.host}:{self.port}"
        self._thread = threading.Thread(
            target=self._thread_main,
            name="karen-gui-backend",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(max(0.5, float(wait_seconds))):
            raise BackendError("本地控制服务启动超时")
        if self.last_error:
            raise BackendError(self.last_error)
        return self.base_url

    def stop(self, *, timeout: float = 15.0) -> None:
        server = self.server
        loop = self.loop
        if server is not None and loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(setattr, server, "should_exit", True)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(max(1.0, float(timeout)))
        self._thread = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except BaseException as exc:  # noqa: BLE001 - surfaced to the GUI
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("本地控制服务异常退出")
        finally:
            self._ready.set()
            self._stopped.set()
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                loop.close()

    def _is_fresh_root(self, runtime_host: Any) -> bool:
        try:
            paths = runtime_host.build_paths()
            data_dir = Path(paths.DATA_DIR)
            if (data_dir / "compatibility_state.json").exists():
                return False
            if (data_dir / "maintenance.sqlite3").exists():
                return False
            if any((data_dir / "memory").rglob("*.db")):
                return False
            if any((data_dir / "vector").rglob("*.db")):
                return False
            return True
        except Exception:  # noqa: BLE001
            logger.warning("检测 GUI 首次运行状态失败", exc_info=True)
            return False

    async def _write_first_run_compat(self, runtime_host: Any) -> None:
        """Create compatibility metadata once a fresh Runtime has initialized.

        Fresh data roots have no compatibility_state.json.  The normal startup
        gate would interpret the post-setup state as "migration required" and
        deadlock before the Runtime can create its databases.  For a truly
        fresh root we bypass that one gate, start the Runtime, then record the
        versions that were actually measured.
        """
        try:
            from core.compat import read_local_state
            from memory.maintenance_store import MaintenanceStore

            paths = runtime_host.build_paths()
            data_dir = Path(paths.DATA_DIR)
            await MaintenanceStore(paths.MAINTENANCE_DB_FILE).initialize()
            measured = read_local_state(
                data_dir, config_path=Path(paths.CONFIG_FILE)
            )
            manifest_path = self.project_root / "compatibility.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            state = {
                "state_format": 1,
                "phase": "idle",
                "generation": 0,
                "data_contract_epoch": int(manifest.get("data_contract_epoch", 0) or 0),
                "migration_set_id": str(manifest.get("migration_set_id") or ""),
                "features": list(manifest.get("required_features") or []),
                "planes": dict(measured.planes),
            }
            state_path = data_dir / "compatibility_state.json"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info("已为 GUI 首次运行写入兼容状态：%s", state)
        except Exception:  # noqa: BLE001
            logger.warning("GUI 首次运行兼容状态写入失败", exc_info=True)

    async def _serve(self) -> None:
        import uvicorn

        from backend.app import create_control_app
        from backend.auth import TokenAuth
        from backend.runtime_host import RuntimeHost

        from . import __version__

        runtime_host = RuntimeHost(self.project_root)
        self.auth_token = secrets.token_urlsafe(32)
        try:
            from main import setup_logging

            paths = runtime_host.build_paths()
            setup_logging(
                "INFO",
                project_root=self.project_root,
                logs_dir=paths.LOGS_DIR,
            )
        except Exception:  # noqa: BLE001
            logger.warning("GUI 文件日志初始化失败，继续使用控制台日志", exc_info=True)
        if self._is_fresh_root(runtime_host):
            fresh_host = runtime_host
            configured_start = runtime_host.start
            configured_gate = runtime_host._runtime_compat_gate
            first_run_state = {"done": False}

            async def _first_run_start(*args: Any, **kwargs: Any) -> bool:
                ok = await configured_start(*args, **kwargs)
                if ok and not first_run_state["done"]:
                    first_run_state["done"] = True
                    await self._write_first_run_compat(fresh_host)
                    fresh_host._runtime_compat_gate = configured_gate
                    fresh_host.start = configured_start  # type: ignore[method-assign]
                return ok

            runtime_host._runtime_compat_gate = lambda: {
                "ok": True,
                "code": "gui_first_run",
                "message": "GUI 首次运行，允许 Runtime 初始化数据",
            }
            runtime_host.start = _first_run_start  # type: ignore[method-assign]
            logger.info("检测到全新的 GUI 数据目录，将执行首次运行初始化")
        auth = TokenAuth(self.auth_token, enabled=True)
        self.runtime_host = runtime_host

        # 与 WebUI 共用 backend.app；GUI 不挂静态前端、不开放文档路由，
        # 但 API 路由、Runtime 生命周期和更新检查完全来自同一个模块。
        app = create_control_app(
            runtime_host,
            auth,
            title="KarenBot GUI Control API",
            description="原生 GTK 客户端使用的本地控制面",
            version=__version__,
            docs=False,
            auth_error_message="未授权：请使用 GUI 生成的本地令牌",
        )
        self.app = app

        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            loop="asyncio",
            lifespan="on",
        )
        server = uvicorn.Server(config)
        self.server = server
        app.state.server = server
        serve_task = asyncio.create_task(server.serve(), name="gui-uvicorn")
        try:
            while not server.started:
                if serve_task.done():
                    exc = serve_task.exception()
                    if exc is not None:
                        raise exc
                    raise RuntimeError("本地控制服务在监听前退出")
                await asyncio.sleep(0.05)
            self._ready.set()
            logger.info("GUI 控制服务监听 %s", self.base_url)
            await serve_task
        finally:
            if not serve_task.done():
                serve_task.cancel()
                try:
                    await serve_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self.server = None


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


__all__ = ["BackendError", "LocalControlServer"]
