"""Release status and changelog browser."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


class UpdatesPage(Page):
    refresh_on_activate = True
    page_id = "updates"
    page_title = "更新"
    page_subtitle = "版本状态、远端发布与更新日志"
    page_icon = "software-update-available-symbolic"

    def build(self) -> None:
        header_row = self.header()
        check = widgets.button("检查更新")
        check.connect("clicked", lambda _b: self._check())
        header_row.append(check)
        self.body.append(header_row)
        self.info_card = widgets.card(spacing=5)
        self.body.append(self.info_card)
        self.notify_card = widgets.card(spacing=5)
        self.notify_switch = widgets.switch(True)
        self._notify_guard = False
        self.notify_switch.connect("notify::active", self._toggle_notify)
        self.notify_card.append(
            widgets.section_header(
                "更新提醒",
                "关闭后仍可手动检查更新；只是不再在总览显示提醒。",
            )
        )
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(self.notify_switch)
        row.append(widgets.label("有可用更新时提醒"))
        self.notify_card.append(row)
        self.body.append(self.notify_card)
        note = widgets.card()
        note.append(
            widgets.muted(
                "这是独立的桌面 GUI 开发树。为保证 GUI 自身代码不被上游版本覆盖，"
                "此页只展示版本与日志，不直接执行源码更新；请使用 git 手动更新 GUI 目录。"
            )
        )
        self.body.append(note)
        self.available_card = widgets.card(spacing=5)
        self.body.append(self.available_card)
        self.body.append(widgets.section_header("远端版本", "标注了当前、可更新、可回退与兼容状态"))
        self.releases_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.releases_box)
        load = widgets.button("加载远端版本列表", icon="view-refresh-symbolic")
        load.connect("clicked", lambda _b: self._load_releases(force=True))
        self.body.append(load)

    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, path in (
                ("version", "/api/update/version"),
                ("status", "/api/update/status"),
                ("available", "/api/update/available"),
            ):
                try:
                    result[key] = self.api.get(path, timeout=30)
                except BaseException as exc:  # noqa: BLE001
                    result[key] = {"error": str(exc)}
            return result

        widgets.run_async(_fetch, on_success=self._render_info, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.info_card)
        self.info_card.append(widgets.muted(f"读取版本信息失败：{exc}"))

    def _render_info(self, data: dict[str, Any]) -> None:
        widgets.clear(self.info_card)
        version = data.get("version") or {}
        status = data.get("status") or {}
        available = data.get("available") or {}
        self.info_card.append(widgets.label("当前版本", css="section-title"))
        for name, value in (
            ("版本标签", version.get("version_label")),
            ("提交", version.get("commit_short") or version.get("commit")),
        ):
            if value:
                self.info_card.append(widgets.property_row(name, str(value)))
        if status.get("error"):
            self.info_card.append(widgets.muted(f"更新状态：{status['error']}"))
        else:
            for name, value in (
                ("分支", status.get("current_branch")),
                (
                    "工作树",
                    "有未提交改动" if status.get("worktree_dirty") else "干净",
                ),
                ("更新目标", status.get("target_branch") or status.get("target_ref")),
                ("远端", status.get("mirror") or "GitHub 官方"),
                ("目标地址", status.get("effective_remote")),
                (
                    "最近检查",
                    widgets.short_time(available.get("last_check_at"))
                    if available.get("last_check_at")
                    else None,
                ),
                (
                    "下次检查",
                    widgets.short_time(available.get("next_check_at"))
                    if available.get("next_check_at")
                    else None,
                ),
            ):
                if value is not None:
                    self.info_card.append(widgets.property_row(name, str(value)))
        self._notify_guard = True
        self.notify_switch.set_active(not bool(available.get("suppressed")))
        self._notify_guard = False
        widgets.clear(self.available_card)
        release = available.get("release") or {}
        if release:
            self.available_card.append(widgets.label("远端可用版本", css="section-title"))
            self.available_card.append(
                widgets.property_row(
                    "版本", str(release.get("name") or release.get("tag") or "")
                )
            )
            self.available_card.append(
                widgets.property_row("Tag", str(release.get("tag") or ""))
            )
            commit = str(
                release.get("commit_short")
                or release.get("commit")
                or release.get("sha")
                or ""
            )
            if commit:
                self.available_card.append(
                    widgets.property_row("提交", commit[:12])
                )
            if release.get("published_at"):
                self.available_card.append(
                    widgets.property_row(
                        "发布时间", widgets.short_time(release.get("published_at"))
                    )
                )
        else:
            self.available_card.append(
                widgets.muted(
                    "当前没有缓存中的远端版本；点「检查更新」或下方「加载远端版本列表」读取 Releases。"
                    + (f"（{available.get('last_error')}）" if available.get("last_error") else "")
                )
            )

    def _toggle_notify(self, switch: Gtk.Switch, *_args: Any) -> None:
        if self._notify_guard or self.api is None:
            return
        active = bool(switch.get_active())
        self._notify_guard = True

        def _do() -> dict[str, Any]:
            return self.api.patch(
                "/api/update/preferences",
                {"suppress_badge": not active},
                timeout=30,
            )

        def _done(_result: dict[str, Any]) -> None:
            self._notify_guard = False
            self.toast("更新提醒设置已保存")

        def _failed(exc: BaseException) -> None:
            self._notify_guard = True
            switch.set_active(not active)
            self._notify_guard = False
            self.toast(f"保存失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _check(self) -> None:
        if self.api is None:
            return
        self.toast("正在检查远端版本…")

        def _do() -> dict[str, Any]:
            return self.api.post("/api/update/check", {}, timeout=300)

        def _done(result: dict[str, Any]) -> None:
            if result.get("can_apply"):
                message = f"发现可更新版本：{result.get('target_tag') or result.get('target_commit_short')}"
            else:
                message = str(result.get("reason_text") or result.get("reason") or "检查完成")
            self.toast(message)
            self.refresh()

        widgets.run_async(_do, on_success=_done, on_error=lambda exc: self.toast(f"检查失败：{exc}"))

    def _load_releases(self, *, force: bool) -> None:
        if self.api is None:
            return
        path = "/api/update/releases" + ("?force=true" if force else "")

        def _do() -> dict[str, Any]:
            return self.api.get(path, timeout=300)

        widgets.run_async(_do, on_success=self._render_releases, on_error=self._releases_error)

    def _releases_error(self, exc: BaseException) -> None:
        widgets.clear(self.releases_box)
        self.releases_box.append(widgets.muted(f"加载远端版本失败：{exc}"))

    def _render_releases(self, data: dict[str, Any]) -> None:
        widgets.clear(self.releases_box)
        releases = data.get("releases") or []
        if not releases:
            self.releases_box.append(widgets.muted("远端没有可用版本。"))
            return
        for release in releases:
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(
                widgets.label(
                    str(release.get("name") or release.get("tag") or ""),
                    css="section-title",
                )
            )
            if release.get("is_current"):
                head.append(widgets.badge("当前版本", css="badge badge-green"))
            elif release.get("relation"):
                head.append(widgets.badge(str(release.get("relation"))))
            compat = release.get("compat") or {}
            if compat.get("compatible") is False:
                head.append(widgets.badge("兼容性未通过", css="badge badge-red"))
            elif compat.get("compatible") is True:
                head.append(widgets.badge("兼容", css="badge badge-green"))
            head.append(widgets.muted(str(release.get("tag") or "")))
            commit = str(
                release.get("commit_short")
                or release.get("commit")
                or release.get("sha")
                or ""
            )
            if commit:
                head.append(widgets.muted(commit[:12]))
            head.set_hexpand(True)
            card.append(head)
            published = release.get("published_at")
            if published:
                card.append(
                    widgets.muted(
                        "发布时间：" + widgets.short_time(published)
                    )
                )
            message = str(compat.get("message") or "")
            if message:
                card.append(widgets.muted(message))
            notes = str(release.get("notes") or "").strip()
            if notes:
                expander = Gtk.Expander(label="更新日志")
                text = widgets.label(notes, wrap=True, selectable=True)
                text.set_margin_top(6)
                expander.set_child(text)
                card.append(expander)
            self.releases_box.append(card)
