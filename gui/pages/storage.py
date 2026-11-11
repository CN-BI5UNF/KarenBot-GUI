"""Storage inventory, safe cache cleanup, context budget and jobs."""

from __future__ import annotations

import uuid
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402
from .destructive_admin import ADMIN_HEADERS, admin_get, open_uninstall  # noqa: E402


class StoragePage(Page):
    refresh_on_activate = True
    page_id = "storage"
    page_title = "存储与数据"
    page_subtitle = "查看存储占用、清理可重建缓存、检查上下文预算，以及预览并执行人格运行数据清理和本地完全卸载。原始聊天、用户文件与备份受保护。"
    page_icon = "drive-harddisk-symbolic"

    def build(self) -> None:
        self.body.append(self.header())
        self.summary_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.summary_box.set_homogeneous(True)
        self.body.append(self.summary_box)
        self.warning_box = widgets.card()
        self.warning_box.set_visible(False)
        self.body.append(self.warning_box)
        self.body.append(widgets.section_header("占用分类", "原始聊天、用户文件与备份受保护"))
        self.categories_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.body.append(self.categories_box)
        cleanup_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.preview_button = widgets.button("预览选中缓存清理")
        self.preview_button.connect("clicked", lambda _b: self._preview())
        cleanup_row.append(self.preview_button)
        self.body.append(cleanup_row)
        self.body.append(widgets.section_header("上下文预算", "滚动摘要与压缩状态"))
        self.context_box = widgets.card()
        self.body.append(self.context_box)
        self.body.append(widgets.section_header("清理任务", "最近的后台清理结果"))
        self.jobs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.body.append(self.jobs_box)
        self.body.append(
            widgets.section_header(
                "危险数据操作",
                "所有危险操作都需要预览影响、输入确认短语并勾选确认；可选备份默认关闭。",
            )
        )
        self.admin_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.admin_box)
        self._categories: list[dict[str, Any]] = []
        self._checks: dict[str, Gtk.CheckButton] = {}
        self._preview: dict[str, Any] | None = None
        self._jobs: list[dict[str, Any]] = []
        self._job_poll_source = 0
        self._job_poll_id = ""
        self.status_label = widgets.muted("")
        self.body.append(self.status_label)

    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, path, timeout in (
                ("usage", "/api/storage/usage", 90),
                ("context", "/api/context/status", 30),
                ("jobs", "/api/storage/jobs?limit=15", 30),
            ):
                try:
                    result[key] = self.api.get(path, timeout=timeout)
                except BaseException as exc:  # noqa: BLE001
                    result[key] = {"error": str(exc)}
            try:
                result["admin_jobs"] = admin_get(
                    self, "/api/admin/jobs?limit=20", timeout=30
                )
            except BaseException as exc:  # noqa: BLE001
                result["admin_jobs"] = {"error": str(exc)}
            return result

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.categories_box)
        self.categories_box.append(widgets.muted(f"读取存储信息失败：{exc}"))

    def _render(self, data: dict[str, Any]) -> None:
        usage = data.get("usage") or {}
        if usage.get("error"):
            self.status_label.set_text(f"读取存储占用失败：{usage['error']}")
        else:
            self.status_label.set_text("")
            self._render_summary(usage)
            self._render_categories(usage)
        self._render_context(data.get("context") or {})
        self._render_jobs(data.get("jobs") or {})
        self._render_admin(data.get("admin_jobs") or {})

    def _render_admin(self, data: dict[str, Any]) -> None:
        widgets.clear(self.admin_box)
        uninstall = widgets.card(spacing=6)
        uninstall.append(
            widgets.label("卸载 KarenBot", css="card-title")
        )
        uninstall.append(
            widgets.muted(
                "停止服务并删除本机源码、虚拟环境、数据目录和程序备份；"
                "不会修改 GitHub、NapCat、Docker、系统 keyring，也不会删除"
                " ~/Debata_BeiFen 或 ~/debata-backups。"
            )
        )
        uninstall_button = widgets.button(
            "检查影响并卸载", css="destructive-action"
        )
        uninstall_button.connect(
            "clicked",
            lambda _b: open_uninstall(self, on_done=self.refresh),
        )
        uninstall.append(uninstall_button)
        self.admin_box.append(uninstall)

        persona_card = widgets.card(spacing=6)
        persona_card.append(
            widgets.label("人格运行数据", css="card-title")
        )
        persona_card.append(
            widgets.muted(
                "在人格页对指定人格执行「清理运行数据」：删除聊天/记忆/RAG/"
                "私有知识，保留人格定义、角色形象、共享知识、黑话与 workspace。"
            )
        )
        persona_button = widgets.button("打开人格页")
        persona_button.connect(
            "clicked", lambda _b: self.app.show_page("personas")
        )
        persona_card.append(persona_button)
        self.admin_box.append(persona_card)

        jobs_card = widgets.card(spacing=6)
        jobs_card.append(
            widgets.label("最近的数据管理任务", css="card-title")
        )
        error = str(data.get("error") or "")
        jobs = list(data.get("jobs") or [])
        if error:
            jobs_card.append(widgets.muted(f"读取危险操作记录失败：{error}"))
        elif not jobs:
            jobs_card.append(widgets.muted("还没有危险操作记录。"))
        else:
            rows: list[list[Any]] = []
            for job in jobs:
                job_id = str(job.get("job_id") or "")
                job_state = str(job.get("state") or "")
                action = (
                    "卸载"
                    if str(job.get("action") or "") == "uninstall"
                    else "人格清理"
                )
                phase = str(job.get("phase") or job_state or "—")
                result = job.get("result") or {}
                outcome = (
                    widgets.format_bytes(result.get("bytes_freed"))
                    if result.get("bytes_freed")
                    else str(job.get("error_message") or "—")
                )
                cells: list[Any] = [
                    widgets.short_time(job.get("created_at")),
                    action,
                    str(job.get("subject") or "—"),
                    _admin_state_label(job_state),
                    phase,
                    outcome,
                ]
                if job_state in {"queued", "running", "cancelling"}:
                    cancel = widgets.button(
                        "取消", css="compact-button"
                    )
                    cancel.connect(
                        "clicked",
                        lambda _b, jid=job_id: self._cancel_admin_job(jid),
                    )
                    cells.append(cancel)
                else:
                    cells.append("")
                rows.append(cells)
            jobs_card.append(
                widgets.table(
                    ["时间", "操作", "对象", "状态", "阶段", "结果", "操作"],
                    rows,
                    weights=[1.1, 0.8, 1.0, 0.8, 0.9, 1.2, 0.6],
                )
            )
        self.admin_box.append(jobs_card)

    def _cancel_admin_job(self, job_id: str) -> None:
        if self.api is None:
            return

        def _do() -> dict[str, Any]:
            return self.api.post(
                f"/api/admin/jobs/{job_id}/cancel",
                {},
                headers=ADMIN_HEADERS,
                timeout=30,
            )

        widgets.run_async(
            _do,
            on_success=lambda result: (
                self.toast(str(result.get("message") or "已请求取消")),
                self.refresh(),
            ),
            on_error=lambda exc: self.toast(f"取消失败：{exc}"),
        )

    def _render_summary(self, usage: dict[str, Any]) -> None:
        widgets.clear(self.summary_box)
        disk = usage.get("disk") or {}
        metrics = [
            ("磁盘可用", _bytes(disk.get("free")), f"已用 {disk.get('percent', 0)}%"),
            ("可回收缓存", _bytes(usage.get("reclaimable_bytes")), "内存缓存 + 过期临时文件"),
            ("受保护数据", _bytes(usage.get("protected_bytes")), "聊天 / 用户文件 / 日志 / 备份"),
        ]
        for name, value, hint in metrics:
            card = widgets.card(spacing=2)
            card.append(widgets.label(value, css="metric-value"))
            card.append(widgets.label(name, css="metric-label"))
            card.append(widgets.muted(hint))
            self.summary_box.append(card)
        low = usage.get("low_disk") or {}
        widgets.clear(self.warning_box)
        if low.get("warning"):
            self.warning_box.set_visible(True)
            self.warning_box.append(
                widgets.label(
                    f"磁盘空间预警：可用 {_bytes(low.get('free_bytes'))}"
                    f"（{low.get('free_percent')}%）。系统不会自动删除聊天或唯一附件。",
                    css="danger-text",
                    wrap=True,
                )
            )
        else:
            self.warning_box.set_visible(False)

    def _render_categories(self, usage: dict[str, Any]) -> None:
        widgets.clear(self.categories_box)
        self._checks = {}
        self._categories = list(usage.get("categories") or [])
        if not self._categories:
            self.categories_box.append(widgets.muted("没有可显示的存储分类。"))
            return
        for category in self._categories:
            card = widgets.card(spacing=4)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            reclaimable = bool(category.get("reclaimable"))
            check = Gtk.CheckButton()
            check.set_active(reclaimable and int(category.get("bytes") or 0) > 0)
            check.set_sensitive(reclaimable)
            self._checks[str(category.get("key"))] = check
            head.append(check)
            head.append(widgets.label(str(category.get("label") or category.get("key")), css="section-title"))
            head.append(
                widgets.badge(
                    "受保护" if category.get("protected") else ("可清理" if reclaimable else "不可清理"),
                    css="badge" if category.get("protected") else "badge badge-green",
                )
            )
            head.append(widgets.label(_bytes(category.get("bytes")), css="metric-label"))
            card.append(head)
            card.append(widgets.muted(str(category.get("description") or "")))
            self.categories_box.append(card)

    def _render_context(self, data: dict[str, Any]) -> None:
        widgets.clear(self.context_box)
        if data.get("error"):
            self.context_box.append(widgets.muted(f"读取上下文状态失败：{data['error']}"))
            return
        if not data:
            self.context_box.append(widgets.muted("暂无上下文状态。"))
            return
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = str(value)
            self.context_box.append(widgets.property_row(str(key), str(value)))
        compact = widgets.button("立即压缩上下文")
        compact.connect("clicked", lambda _b: self._compact())
        self.context_box.append(compact)

    def _render_jobs(self, data: dict[str, Any]) -> None:
        widgets.clear(self.jobs_box)
        jobs = list(data.get("jobs") or [])
        self._jobs = jobs
        if not jobs:
            self.jobs_box.append(widgets.muted("还没有清理任务。"))
            return
        for job in jobs:
            card = widgets.card(spacing=4)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(str(job.get("job_id") or ""), css="section-title"))
            state = str(job.get("state") or "")
            head.append(widgets.badge(state))
            head.append(widgets.muted(str(job.get("created_at") or "")))
            head.set_hexpand(True)
            if state in {"queued", "running", "cancelling", "scheduled"}:
                cancel = widgets.button("取消")
                cancel.connect("clicked", lambda _b, j=job: self._cancel(j))
                head.append(cancel)
            card.append(head)
            cats = job.get("categories") or []
            if cats:
                card.append(widgets.muted("类别：" + "、".join(str(x) for x in cats)))
            result = job.get("result") or {}
            if isinstance(result, dict) and result:
                parts = []
                if result.get("bytes_freed") is not None:
                    parts.append(_bytes(result.get("bytes_freed")))
                if result.get("entries_freed") is not None:
                    parts.append(f"{result.get('entries_freed')} 项")
                if result.get("skipped"):
                    parts.append(f"跳过 {result.get('skipped')}")
                if parts:
                    card.append(widgets.muted("释放：" + " · ".join(parts)))
                for error in (result.get("errors") or [])[:3]:
                    card.append(
                        widgets.muted(
                            f"错误：{error.get('category') or '—'} {error.get('code') or ''}"
                        )
                    )
            if job.get("error_message"):
                card.append(
                    widgets.label(
                        str(job["error_message"]), css="danger-text", wrap=True
                    )
                )
            self.jobs_box.append(card)

    # ------------------------------------------------------------------
    def _preview(self) -> None:
        categories = [key for key, check in self._checks.items() if check.get_active()]
        if not categories or self.api is None:
            self.toast("请先勾选要清理的类别")
            return

        def _do() -> dict[str, Any]:
            return self.api.post(
                "/api/storage/cleanup/preview", {"categories": categories}, timeout=120
            )

        def _done(preview: dict[str, Any]) -> None:
            self._preview = preview
            counts = preview.get("category_counts") or {}
            lines = [
                f"{key}: {_bytes(value.get('bytes'))} / {value.get('items', 0)} 项"
                for key, value in counts.items()
            ]
            body = "\n".join(lines) + f"\n预计回收 {_bytes(preview.get('expected_bytes'))}"
            widgets.ConfirmDialog(
                self.app.window,
                heading="确认清理这些缓存？",
                body=body,
                confirm_label="执行清理",
                destructive=True,
                on_confirm=self._execute_preview,
            )

        widgets.run_async(_do, on_success=_done, on_error=lambda exc: self.toast(f"预览失败：{exc}"))

    def _execute_preview(self) -> None:
        preview = self._preview
        if not preview or self.api is None:
            return
        payload = {
            "preview_id": preview.get("preview_id"),
            "confirmation_token": preview.get("confirmation_token"),
            "idempotency_key": uuid.uuid4().hex,
            "expected_generation": preview.get("generation"),
        }

        def _do() -> Any:
            return self.api.post("/api/storage/cleanup/execute", payload, timeout=120)

        def _done(result: Any) -> None:
            self.toast("清理任务已提交")
            if isinstance(result, dict) and result.get("job_id"):
                self._start_job_poll(str(result["job_id"]))
            self.refresh()

        widgets.run_async(_do, on_success=_done, on_error=lambda exc: self.toast(f"清理失败：{exc}"))

    def _start_job_poll(self, job_id: str) -> None:
        self._job_poll_id = job_id
        if self._job_poll_source:
            GLib.source_remove(self._job_poll_source)
        self._job_poll_source = GLib.timeout_add_seconds(1, self._poll_job)

    def _poll_job(self) -> bool:
        self._job_poll_source = 0
        if self.api is None or not self._job_poll_id:
            return False
        if not self.get_mapped():
            return False
        job_id = self._job_poll_id

        def _do() -> dict[str, Any]:
            return self.api.get(
                f"/api/storage/jobs/{_quote(job_id)}", timeout=30
            )

        def _done(job: dict[str, Any]) -> None:
            self._jobs = [
                item for item in self._jobs if item.get("job_id") != job_id
            ]
            self._jobs.insert(0, job)
            self._render_jobs({"jobs": self._jobs})
            self.status_label.set_text(f"清理任务 {job.get('state') or '进行中'}")
            if str(job.get("state") or "") in {
                "queued",
                "running",
                "cancelling",
                "scheduled",
            }:
                self._job_poll_source = GLib.timeout_add_seconds(1, self._poll_job)
            else:
                self._job_poll_id = ""
                self.refresh()

        def _failed(exc: BaseException) -> None:
            self.status_label.set_text(f"读取清理任务失败：{exc}")
            self._job_poll_id = ""

        widgets.run_async(_do, on_success=_done, on_error=_failed)
        return False

    def _cancel(self, job: dict[str, Any]) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post(f"/api/storage/jobs/{_quote(job.get('job_id'))}/cancel", {}, timeout=30)

        widgets.run_async(
            _do,
            on_success=lambda _r: (self.toast("已请求取消"), self.refresh()),
            on_error=lambda exc: self.toast(str(exc)),
        )

    def _compact(self) -> None:
        if self.api is None:
            return
        self.toast("正在压缩上下文…")

        def _do() -> Any:
            return self.api.post("/api/context/compact", {}, timeout=180)

        widgets.run_async(
            _do,
            on_success=lambda _r: (self.toast("压缩完成"), self.refresh()),
            on_error=lambda exc: self.toast(f"压缩失败：{exc}"),
        )


def _admin_state_label(state: str) -> str:
    return {
        "queued": "排队中",
        "running": "执行中",
        "cancelling": "取消中",
        "scheduled": "已调度",
        "completed": "完成",
        "partial": "部分完成",
        "failed": "失败",
        "cancelled": "已取消",
        "interrupted": "已中断",
    }.get(state, state or "—")


def _bytes(value: Any) -> str:
    try:
        number = max(0, float(value or 0))
    except (TypeError, ValueError):
        number = 0
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1
    return f"{number:.1f} {units[index]}" if index else f"{int(number)} B"


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")
