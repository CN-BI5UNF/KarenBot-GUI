"""Guarded destructive-data dialogs shared by personas and storage pages.

The browser frontend uses the same preview → confirmation phrase → job contract
from ``backend/api/admin.py``.  Nothing here deletes files directly: the GUI
only renders the server's impact preview, collects the explicit confirmation,
and polls the background job.  Optional backups stay off by default.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402

ADMIN_HEADERS = {"X-Karen-Admin": "1"}

PHASE_LABELS = {
    "queued": "排队中",
    "preflight": "检查目标",
    "backing_up": "创建备份",
    "writing_cleanup_marker": "写入清理标记",
    "updating_knowledge": "更新知识库",
    "deleting_memory": "删除聊天与记忆",
    "deleting_vector": "删除 RAG 向量库",
    "creating_empty_database": "创建空数据库",
    "completed": "完成",
    "partial": "部分完成",
    "failed": "失败",
    "cancelled": "已取消",
    "interrupted": "已中断",
    "scheduled": "已调度",
}

TERMINAL_STATES = {"completed", "partial", "failed", "cancelled", "interrupted"}


def admin_get(page: Any, path: str, *, timeout: float = 60) -> Any:
    return page.api.get(path, headers=ADMIN_HEADERS, timeout=timeout)


def admin_post(
    page: Any,
    path: str,
    body: Any = None,
    *,
    timeout: float = 120,
) -> Any:
    return page.api.post(
        path, body, headers=ADMIN_HEADERS, timeout=timeout
    )


def _warning_card(lines: list[str]) -> Gtk.Box:
    card = widgets.card(spacing=5, padding=12)
    card.add_css_class("danger-card")
    for index, line in enumerate(lines):
        card.append(
            widgets.label(
                line,
                css="danger-text" if index == 0 else "muted",
                wrap=True,
            )
        )
    return card


def _impact_table(rows: list[list[str]]) -> Gtk.Widget:
    return widgets.table(
        ["项目", "影响"], rows, weights=[0.8, 2.2], empty_text="没有可预览的影响"
    )


def _affected_sentence(stats: dict[str, Any]) -> str:
    return (
        f"{widgets.format_bytes(stats.get('bytes'))} · "
        f"{int(stats.get('files') or 0)} 个文件"
    )


def open_persona_cleanup(
    page: Any,
    persona: str,
    *,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Preview and execute one persona's runtime-data cleanup."""

    def _fetch() -> dict[str, Any]:
        return admin_post(
            page,
            f"/api/admin/personas/{_quote(persona)}/cleanup/preview",
            None,
            timeout=120,
        )

    widgets.run_async(
        _fetch,
        on_success=lambda preview: _show_preview(page, persona, preview, on_done),
        on_error=lambda exc: page.toast(f"读取清理预览失败：{exc}"),
    )


def open_uninstall(
    page: Any,
    *,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Preview and request the local uninstall helper."""

    def _fetch() -> dict[str, Any]:
        return admin_post(page, "/api/admin/uninstall/preview", None, timeout=120)

    widgets.run_async(
        _fetch,
        on_success=lambda preview: _show_uninstall_preview(page, preview, on_done),
        on_error=lambda exc: page.toast(f"读取卸载预览失败：{exc}"),
    )


def _show_preview(
    page: Any,
    persona: str,
    preview: dict[str, Any],
    on_done: Callable[[], None] | None,
) -> None:
    phrase = str(preview.get("confirmation_phrase") or "")
    memory = preview.get("memory") or {}
    vector = preview.get("vector") or {}
    knowledge = preview.get("knowledge") or {}
    window = widgets.FormWindow(
        page.app.window,
        f"清理「{persona}」的运行数据",
        width=760,
        height=780,
        submit_label="确认清理",
        on_submit=lambda: _execute(),
    )
    window.submit_button.add_css_class("destructive-action")
    window.submit_button.set_sensitive(False)
    warning = _warning_card(
        [
            "此操作不可撤销；执行时会短暂停止 Runtime，删除完成后自动恢复。",
            "不会删除：人格定义、其他人格、workspace、日志、表情包、"
            "全局配置/密钥、备份库、共享黑话和共享知识。",
        ]
    )
    window.body_box.append(warning)
    window.body_box.append(
        _impact_table(
            [
                ["聊天 / 记忆数据库", _affected_sentence(memory)],
                ["RAG 向量库", _affected_sentence(vector)],
                ["私有知识条目", f"{int(knowledge.get('private_entries') or 0)} 条"],
                ["共享知识 / 其他人格", "保留"],
                ["预计释放", widgets.format_bytes(preview.get("expected_bytes"))],
            ]
        )
    )
    active = "当前人格" if preview.get("active") else "非当前人格"
    mode = (
        "暂停并自动恢复 Runtime"
        if preview.get("requires_runtime_restart")
        else "离线执行"
    )
    window.body_box.append(
        widgets.muted(
            f"{active} · 执行方式：{mode} · 预览过期时间："
            f"{preview.get('expires_at') or '—'}"
        )
    )
    protected = [
        str(item.get("key") or item.get("path") or item)
        if isinstance(item, dict)
        else str(item)
        for item in (preview.get("protected") or [])
    ]
    if protected:
        window.body_box.append(
            widgets.muted("受保护项：" + "、".join(protected))
        )
    for warning_text in preview.get("warnings") or []:
        window.body_box.append(widgets.muted(str(warning_text)))

    backup_row, backup_switch = _check_row(
        "删除前创建该人格的完整备份（默认关闭；备份包含聊天与记忆）"
    )
    acknowledge_row, acknowledge_switch = _check_row(
        "我明白此操作不可撤销，且未勾选备份时不会保留副本"
    )
    window.body_box.append(backup_row)
    window.body_box.append(acknowledge_row)

    phrase_entry = Gtk.Entry()
    phrase_entry.set_placeholder_text(phrase)
    window.add_row("输入确认短语", phrase_entry)
    window.body_box.append(widgets.muted(phrase))
    error = widgets.label("", css="danger-text", wrap=True)
    window.body_box.append(error)
    busy = {"value": False, "job": None}

    def _sync(*_args: Any) -> None:
        ready = (
            acknowledge_switch.get_active()
            and phrase_entry.get_text().strip() == phrase
        )
        window.submit_button.set_sensitive(bool(ready) and not busy["value"])

    acknowledge_switch.connect("notify::active", _sync)
    phrase_entry.connect("changed", _sync)
    window.present()

    def _execute() -> None:
        if busy["value"]:
            return
        if not acknowledge_switch.get_active():
            error.set_text("请先勾选不可撤销确认。")
            return
        if phrase_entry.get_text().strip() != phrase:
            error.set_text("确认短语不匹配。")
            return
        busy["value"] = True
        window.submit_button.set_sensitive(False)
        error.set_text("正在提交清理任务…")
        payload = {
            "preview_id": preview.get("preview_id"),
            "confirmation_token": preview.get("confirmation_token"),
            "expected_generation": preview.get("generation"),
            "idempotency_key": f"gui-{uuid.uuid4()}",
            "typed_confirmation": phrase_entry.get_text().strip(),
            "acknowledge_destructive": True,
            "create_backup": bool(backup_switch.get_active()),
        }

        def _do() -> dict[str, Any]:
            return admin_post(
                page,
                f"/api/admin/personas/{_quote(persona)}/cleanup/execute",
                payload,
                timeout=120,
            )

        def _done(job: dict[str, Any]) -> None:
            window.close()
            page.toast("清理任务已提交")
            _show_job_progress(
                page,
                title=f"正在清理「{persona}」",
                subtitle="服务端任务已提交；关闭进度窗口不会中止已开始的删除。",
                job=job,
                audit_path=str(preview.get("audit_path") or ""),
                on_done=on_done,
            )

        def _failed(exc: BaseException) -> None:
            busy["value"] = False
            error.set_text(f"清理失败：{exc}")
            _sync()

        widgets.run_async(_do, on_success=_done, on_error=_failed)


def _show_uninstall_preview(
    page: Any,
    preview: dict[str, Any],
    on_done: Callable[[], None] | None,
) -> None:
    if not preview.get("supported"):
        window = widgets.FormWindow(
            page.app.window,
            "当前环境不支持自动卸载",
            width=640,
            height=520,
            submit_label="关闭",
            on_submit=lambda: None,
        )
        window.on_submit = window.close
        window.body_box.append(
            widgets.muted(str(preview.get("unsupported_reason") or "请按文档手动卸载。"))
        )
        window.body_box.append(
            widgets.label(
                str(preview.get("manual_steps") or ""),
                css="monospace",
                wrap=True,
                selectable=True,
            )
        )
        window.present()
        return

    phrase = str(preview.get("confirmation_phrase") or "")
    targets = preview.get("targets") or []
    optional_backup = preview.get("optional_backup") or {}
    backup_available = bool(optional_backup.get("available"))
    window = widgets.FormWindow(
        page.app.window,
        "永久卸载 KarenBot",
        width=800,
        height=820,
        submit_label="永久卸载",
        on_submit=lambda: _execute(),
    )
    window.submit_button.add_css_class("destructive-action")
    window.submit_button.set_sensitive(False)
    window.body_box.append(
        _warning_card(
            [
                "点击确认后本地控制服务会退出；删除完成后无法再从本窗口确认结果。",
                "未勾选备份时，本机不会保留任何数据副本；GitHub 远端不会被修改。",
            ]
        )
    )
    window.body_box.append(
        _impact_table(
            [
                [
                    str(target.get("kind") or "目标"),
                    _affected_sentence(target),
                ]
                for target in targets
            ]
        )
    )
    paths = "\n".join(str(target.get("path") or "") for target in targets)
    if paths:
        window.body_box.append(
            widgets.label(paths, css="monospace", wrap=True, selectable=True)
        )
    retained = [
        str(item.get("kind") or item.get("path") or item)
        if isinstance(item, dict)
        else str(item)
        for item in (preview.get("retained") or [])
    ]
    if retained:
        window.body_box.append(widgets.muted("保留：" + "、".join(retained)))
    backup_row, backup_switch = _check_row(
        "删除前创建完整备份（用户数据 + 源码归档，默认关闭）"
        if backup_available
        else "当前 Runtime 未运行，无法创建可选备份"
    )
    backup_switch.set_sensitive(backup_available)
    acknowledge_row, acknowledge_switch = _check_row(
        "我确认已理解并接受永久删除，且知道 GitHub 远端不会改变"
    )
    window.body_box.append(backup_row)
    window.body_box.append(acknowledge_row)
    phrase_entry = Gtk.Entry()
    phrase_entry.set_placeholder_text(phrase)
    window.add_row("输入确认短语", phrase_entry)
    window.body_box.append(widgets.muted(phrase))
    error = widgets.label("", css="danger-text", wrap=True)
    window.body_box.append(error)
    busy = {"value": False}

    def _sync(*_args: Any) -> None:
        ready = (
            acknowledge_switch.get_active()
            and phrase_entry.get_text().strip() == phrase
            and (not backup_switch.get_active() or backup_available)
        )
        window.submit_button.set_sensitive(bool(ready) and not busy["value"])

    acknowledge_switch.connect("notify::active", _sync)
    backup_switch.connect("notify::active", _sync)
    phrase_entry.connect("changed", _sync)
    window.present()

    def _execute() -> None:
        if busy["value"]:
            return
        if not acknowledge_switch.get_active():
            error.set_text("请先勾选永久删除确认。")
            return
        if phrase_entry.get_text().strip() != phrase:
            error.set_text("确认短语不匹配。")
            return
        busy["value"] = True
        window.submit_button.set_sensitive(False)
        error.set_text("正在提交卸载任务…")
        payload = {
            "preview_id": preview.get("preview_id"),
            "confirmation_token": preview.get("confirmation_token"),
            "expected_generation": preview.get("generation"),
            "idempotency_key": f"gui-{uuid.uuid4()}",
            "typed_confirmation": phrase_entry.get_text().strip(),
            "acknowledge_destructive": True,
            "create_backup": bool(backup_switch.get_active()),
        }

        def _do() -> dict[str, Any]:
            return admin_post(
                page, "/api/admin/uninstall/execute", payload, timeout=120
            )

        def _done(job: dict[str, Any]) -> None:
            window.close()
            page.toast("卸载任务已调度；本地服务即将退出")
            _show_job_progress(
                page,
                title="正在准备卸载",
                subtitle=(
                    "服务即将退出；独立删除助手会在后端退出后继续。"
                    "请保存审计路径以便之后确认结果。"
                ),
                job=job,
                audit_path=str(preview.get("audit_path") or ""),
                on_done=on_done,
                allow_disconnect=True,
            )

        def _failed(exc: BaseException) -> None:
            busy["value"] = False
            error.set_text(f"卸载未能启动：{exc}")
            _sync()

        widgets.run_async(_do, on_success=_done, on_error=_failed)


def _check_row(text: str) -> tuple[Gtk.Box, Gtk.CheckButton]:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    check = Gtk.CheckButton()
    row.append(check)
    row.append(widgets.label(text, wrap=True))
    return row, check


def _show_job_progress(
    page: Any,
    *,
    title: str,
    subtitle: str,
    job: dict[str, Any],
    on_done: Callable[[], None] | None,
    allow_disconnect: bool = False,
    audit_path: str = "",
) -> None:
    job_id = str(job.get("job_id") or "")
    # execute 返回的 public job 顶层没有 audit_path；它通常来自 preview，
    # 任务完成后才出现在 result.audit_path。先把 preview 提供的路径显示出来，
    # 终态时再用 result 补充。
    audit_path = str(job.get("audit_path") or audit_path or "")
    window = Gtk.Window()
    window.set_title(title)
    window.set_default_size(620, 400)
    window.set_transient_for(page.app.window)
    window.set_modal(True)
    window.set_titlebar(Adw.HeaderBar())
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(20)
    box.set_margin_end(20)
    box.append(_warning_card([subtitle]))
    phase = widgets.label("正在读取任务状态…", css="section-title", wrap=True)
    detail = widgets.muted("")
    result = widgets.muted("")
    close = widgets.button("关闭")
    close.set_halign(Gtk.Align.END)
    close.set_sensitive(False)
    close.connect("clicked", lambda _b: window.close())
    box.append(phase)
    box.append(detail)
    box.append(result)
    box.append(widgets.muted(f"任务：{job_id or '—'}"))
    audit_label = widgets.muted(f"审计：{audit_path}" if audit_path else "审计：任务结束后显示")
    box.append(audit_label)
    box.append(close)
    scroller = Gtk.ScrolledWindow()
    scroller.set_vexpand(True)
    scroller.set_child(box)
    window.set_child(scroller)

    state = {"stopped": False, "errors": 0, "attempts": 0}

    def _closed(*_args: Any) -> bool:
        state["stopped"] = True
        return False

    window.connect("close-request", _closed)
    window.present()

    def _finish(text: str, *, terminal: bool = True) -> None:
        state["stopped"] = True
        phase.set_text(text)
        close.set_sensitive(True)
        if terminal and callable(on_done):
            on_done()

    def _tick() -> bool:
        if state["stopped"]:
            return False
        state["attempts"] += 1

        def _do() -> dict[str, Any]:
            return admin_get(page, f"/api/admin/jobs/{_quote(job_id)}", timeout=30)

        def _done(data: dict[str, Any]) -> None:
            state["errors"] = 0
            job_state = str(data.get("state") or "")
            phase_name = str(data.get("phase") or job_state)
            phase.set_text(
                f"阶段：{PHASE_LABELS.get(phase_name, phase_name or '处理中')}"
            )
            progress = data.get("progress") or {}
            if progress.get("bytes_total"):
                detail.set_text(
                    f"{widgets.format_bytes(progress.get('bytes_done'))} / "
                    f"{widgets.format_bytes(progress.get('bytes_total'))}"
                )
            else:
                detail.set_text(f"状态：{job_state or '未知'}")
            if job_state in {"scheduled"}:
                result.set_text(
                    "卸载已调度：后端退出后，独立助手会继续删除。"
                )
                _finish("任务已调度", terminal=False)
                return
            if job_state in TERMINAL_STATES:
                payload = data.get("result") or {}
                summary = (
                    f"已释放 {widgets.format_bytes(payload.get('bytes_freed'))}；"
                    f"Runtime："
                    + (
                        "已恢复"
                        if (payload.get("runtime") or {}).get("restarted")
                        else "未运行/恢复失败"
                    )
                )
                backup = payload.get("backup") or {}
                backup_path = str(
                    backup.get("path") if isinstance(backup, dict) else backup or ""
                )
                if backup_path:
                    summary += f"\n备份：{backup_path}"
                result.set_text(summary)
                terminal_audit = str(
                    data.get("audit_path")
                    or payload.get("audit_path")
                    or audit_path
                    or ""
                )
                if terminal_audit:
                    audit_label.set_text(f"审计：{terminal_audit}")
                if job_state == "completed":
                    page.toast("清理完成")
                elif job_state == "cancelled":
                    page.toast("任务已取消（可能已有部分内容被删除）")
                else:
                    page.toast(
                        f"清理{PHASE_LABELS.get(job_state, job_state)}："
                        f"{data.get('error_message') or payload.get('error') or '请查看结果'}"
                    )
                _finish("任务已结束")
                return
            GLib.timeout_add(1000, _tick)

        def _failed(exc: BaseException) -> None:
            state["errors"] += 1
            if allow_disconnect and state["errors"] >= 3:
                result.set_text(f"无法读取任务状态：{exc}")
                _finish("本地服务已退出或连接中断", terminal=False)
                return
            if state["errors"] < 20:
                detail.set_text(f"读取任务状态失败：{exc}；继续重试…")
                GLib.timeout_add(1200, _tick)
            else:
                _finish("读取任务状态失败；请检查日志和审计记录。")

        widgets.run_async(_do, on_success=_done, on_error=_failed)
        return False

    GLib.timeout_add(400, _tick)


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = ["open_persona_cleanup", "open_uninstall", "admin_get"]
