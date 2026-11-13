"""Release status, changelog browser and guarded source updates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from ..paths import data_dir_inside_project  # noqa: E402
from .base import Page  # noqa: E402

MODULE_REPO_TEXT = {
    "backend": "backend",
    "gui": "gui",
    "webui": "webui",
}

RELATION_TEXT = {
    "current": "当前版本",
    "newer": "可更新",
    "older": "可回退",
    "diverged": "另一条历史",
}

REASON_TEXT = {
    "up_to_date": "当前已经是最新版本",
    "dependency_change_requires_install": "目标版本修改了依赖文件；自动安装已关闭，需要手动安装依赖",
    "dependency_install_failed": "依赖安装失败，源码已回滚",
    "dependency_install_failed_rollback_failed": "依赖安装失败，且源码回滚失败；请检查工作树",
    "dependency_install_timeout": "依赖安装超时，源码已回滚",
    "worktree_dirty": "工作树有未提交改动",
    "data_dir_inside_project": "用户数据目录位于代码工作树内",
    "git_timeout": "连接远端超时",
    "git_failed": "git 拉取失败",
    "git_missing": "找不到 git",
    "release_not_found": "远端找不到这个版本",
    "rollback_not_confirmed": "回退/切换操作需要确认",
    "legacy_unknown": "目标版本没有兼容声明，不能自动应用",
    "migration_required": "目标版本需要数据迁移，自动更新已阻止",
    "downgrade_required": "目标版本不能安全读取当前数据版本",
    "data_contract_too_new": "目标版本不认识当前较新的数据契约",
    "unsupported_data_contract": "目标版本不支持当前数据版本",
    "feature_missing": "目标版本需要本地尚不支持的数据能力",
    "data_unreadable": "本地数据版本不可读",
    "launcher_protocol_too_old": "启动保护协议过旧",
    "data_state_changed": "检查后本地数据已变化，请重新检查",
    "compat_manifest_changed": "目标兼容声明已变化，请重新检查",
    "manifest_invalid": "目标兼容声明无效",
    "unsupported_manifest_format": "目标兼容声明格式不受支持",
    "unknown_plane": "目标兼容声明包含未知数据平面",
    "check_expired": "更新检查已过期，请重新检查",
    "target_changed": "目标提交已变化，请重新检查",
    "head_changed": "代码 HEAD 已变化，请重新检查",
    "confirmation_token_invalid": "确认令牌不匹配，请重新检查",
    "no_check": "请先检查更新",
}


def _reason_text(reason: Any) -> str:
    text = str(reason or "").strip()
    return REASON_TEXT.get(text, text or "未知原因")


def _relation_text(release: dict[str, Any]) -> str:
    if release.get("is_current"):
        return RELATION_TEXT["current"]
    relation = str(release.get("relation") or "")
    return RELATION_TEXT.get(relation, relation)


def _action_label(release: dict[str, Any]) -> str:
    if release.get("prerelease"):
        return "安装 Pre-release"
    if release.get("relation") == "older":
        return "回退到此版本"
    if release.get("relation") == "diverged":
        return "切换到此版本"
    return "更新到此版本"


def _release_tag(release: dict[str, Any]) -> str:
    return str(release.get("release_tag") or release.get("tag") or "")


def _component_text(release: dict[str, Any]) -> str:
    return str(release.get("component_label") or release.get("component") or "")


class UpdatesPage(Page):
    refresh_on_activate = True
    page_id = "updates"
    page_title = "更新"
    page_subtitle = "版本状态、远端发布与更新日志；源码更新需要干净工作树并重启后端"
    page_icon = "software-update-available-symbolic"

    def build(self) -> None:
        self._releases_loaded = False
        self._releases_busy = False
        self._check_busy = False
        self._applying = False
        self._release_buttons: list[Gtk.Button] = []
        self._check_apply_button: Gtk.Button | None = None
        self._check_result: dict[str, Any] | None = None

        header_row = self.header()
        self.check_button = widgets.button("检查更新")
        self.check_button.connect("clicked", lambda _b: self._check())
        header_row.append(self.check_button)
        restart = widgets.button(
            "重启后端", icon="system-reboot-symbolic"
        )
        restart.set_tooltip_text(
            "停止并重新启动 GUI 自己的本地后端，重新加载磁盘上的 Python 代码"
        )
        restart.connect(
            "clicked", lambda _b: self._confirm_restart_backend()
        )
        header_row.append(restart)
        self.body.append(header_row)
        self.data_dir_warning = widgets.label(
            "当前数据目录位于代码仓库内，后端更新器会拒绝检查/应用更新。"
            "开发检出请用 --data-dir 指向仓库外目录；打包安装版默认使用用户数据目录。",
            css="danger-text",
            wrap=True,
        )
        self.data_dir_warning.set_visible(False)
        self.body.append(self.data_dir_warning)

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
                "更新只替换 backend/ 与当前 GUI 前端模块，不改写用户数据目录；"
                "应用前会备份当前模块。后端更新后重启本地后端即可；"
                "GUI 前端更新后必须完全退出并重新打开应用。"
            )
        )
        self.body.append(note)

        self.status_label = widgets.muted("")
        self.body.append(self.status_label)

        self.check_card = widgets.card(spacing=5)
        self.check_card.set_visible(False)
        self.body.append(self.check_card)

        self.available_card = widgets.card(spacing=5)
        self.body.append(self.available_card)

        self.body.append(
            widgets.section_header(
                "远端版本", "标注了当前、可更新、可回退与兼容状态"
            )
        )
        self.releases_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8
        )
        self.body.append(self.releases_box)
        self.load_button = widgets.button(
            "加载远端版本列表", icon="view-refresh-symbolic"
        )
        self.load_button.connect(
            "clicked", lambda _b: self._load_releases(force=True)
        )
        self.body.append(self.load_button)

    def refresh(self) -> None:
        if self.api is None:
            return
        self._check_data_root()

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

        widgets.run_async(
            _fetch, on_success=self._render_info, on_error=self._error
        )

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.info_card)
        self.info_card.append(widgets.muted(f"读取版本信息失败：{exc}"))

    def _render_info(self, data: dict[str, Any]) -> None:
        widgets.clear(self.info_card)
        version = data.get("version") or {}
        status = data.get("status") or {}
        available = data.get("available") or {}
        self.info_card.append(widgets.label("当前版本", css="section-title"))
        if status.get("mode") == "module":
            self.info_card.append(
                widgets.property_row(
                    "前端类型",
                    str(status.get("frontend_label") or status.get("frontend") or ""),
                )
            )
            for key, component in (status.get("components") or {}).items():
                installed = component.get("installed") or {}
                self.info_card.append(
                    widgets.property_row(
                        str(component.get("label") or key),
                        f"{installed.get('version') or installed.get('tag') or '未记录'} · "
                        f"{MODULE_REPO_TEXT.get(key, component.get('repo') or '')}",
                    )
                )
            self.info_card.append(
                widgets.property_row(
                    "更新仓库",
                    str(status.get("repo") or ""),
                )
            )
            if status.get("worktree_dirty"):
                self.info_card.append(
                    widgets.label(
                        "当前是包含未提交改动的开发工作树；可以检查版本，但不能应用模块更新。",
                        css="danger-text",
                        wrap=True,
                    )
                )
            for name, value in (
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
                if value:
                    self.info_card.append(
                        widgets.property_row(name, str(value))
                    )
            self._notify_guard = True
            self.notify_switch.set_active(not bool(available.get("suppressed")))
            self._notify_guard = False
            widgets.clear(self.available_card)
            release = available.get("release") or {}
            if release:
                self.available_card.append(
                    widgets.label("自动提示的 Latest 更新", css="section-title")
                )
                self.available_card.append(
                    widgets.property_row(
                        "组件",
                        _component_text(release),
                    )
                )
                self.available_card.append(
                    widgets.property_row("版本", _release_tag(release))
                )
            else:
                self.available_card.append(
                    widgets.muted(
                        "当前没有可自动提示的 Latest 更新。"
                        "Pre-release 不会自动提示，但可以在下方版本列表手动选择。"
                    )
                )
            if not self._releases_loaded and not self._releases_busy:
                self._load_releases(force=False)
            return
        for name, value in (
            ("版本标签", version.get("version_label")),
            ("提交", version.get("commit_short") or version.get("commit")),
        ):
            if value:
                self.info_card.append(widgets.property_row(name, str(value)))
        if status.get("error"):
            self.info_card.append(
                widgets.muted(f"更新状态：{status['error']}")
            )
        else:
            for name, value in (
                ("分支", status.get("current_branch")),
                (
                    "工作树",
                    "有未提交改动" if status.get("worktree_dirty") else "干净",
                ),
                (
                    "更新目标",
                    status.get("target_branch") or status.get("target_ref"),
                ),
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
                    self.info_card.append(
                        widgets.property_row(name, str(value))
                    )
        self._notify_guard = True
        self.notify_switch.set_active(not bool(available.get("suppressed")))
        self._notify_guard = False
        widgets.clear(self.available_card)
        release = available.get("release") or {}
        if release:
            self.available_card.append(
                widgets.label("远端可用版本", css="section-title")
            )
            self.available_card.append(
                widgets.property_row(
                    "版本",
                    str(release.get("name") or release.get("tag") or ""),
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
                        "发布时间",
                        widgets.short_time(release.get("published_at")),
                    )
                )
        else:
            self.available_card.append(
                widgets.muted(
                    "当前没有缓存中的远端版本；点「检查更新」或下方"
                    "「加载远端版本列表」读取 Releases。"
                    + (
                        f"（{available.get('last_error')}）"
                        if available.get("last_error")
                        else ""
                    )
                )
            )
        if not self._releases_loaded and not self._releases_busy:
            self._load_releases(force=False)

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
        if self.api is None or self._check_busy or self._applying:
            return
        self._check_busy = True
        self.check_button.set_sensitive(False)
        self.status_label.set_text("正在检查远端版本…")

        def _do() -> dict[str, Any]:
            return self.api.post("/api/update/check", {}, timeout=330)

        def _done(result: dict[str, Any]) -> None:
            self._check_busy = False
            self.check_button.set_sensitive(True)
            self._check_result = result
            self._render_check(result)
            if result.get("can_apply"):
                message = (
                    "发现可更新版本："
                    + str(
                        result.get("target_tag")
                        or result.get("target_commit_short")
                        or "目标版本"
                    )
                )
            else:
                errors = result.get("errors") or {}
                message = (
                    "；".join(f"{key}: {value}" for key, value in errors.items())
                    or _reason_text(result.get("reason") or result.get("reason_text"))
                )
            self.status_label.set_text(message)
            self.toast(message)
            # The cached availability snapshot may have changed.
            self.refresh()

        def _failed(exc: BaseException) -> None:
            self._check_busy = False
            self.check_button.set_sensitive(True)
            self.status_label.set_text(f"检查更新失败：{exc}")
            self.toast(f"检查失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _render_check(self, result: dict[str, Any]) -> None:
        widgets.clear(self.check_card)
        self._check_apply_button = None
        target_name = str(
            result.get("target_name")
            or result.get("target_label")
            or result.get("target_tag")
            or result.get("target_commit_short")
            or "目标版本"
        )
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.append(widgets.label("目标版本检查", css="section-title"))
        relation = str(result.get("target_relation") or "")
        if relation:
            head.append(
                widgets.badge(RELATION_TEXT.get(relation, relation))
            )
        if not result.get("can_apply"):
            head.append(widgets.badge("不可应用", css="badge badge-red"))
        head.set_hexpand(True)
        self.check_card.append(head)
        self.check_card.append(
            widgets.property_row("目标", target_name)
        )
        updates = [item for item in result.get("updates") or [] if isinstance(item, dict)]
        for item in updates:
            self.check_card.append(
                widgets.property_row(
                    _component_text(item) or "组件",
                    _release_tag(item)
                    + ("（Pre-release，极不稳定）" if item.get("prerelease") else ""),
                )
            )
        commit = str(
            result.get("target_commit_short")
            or result.get("target_commit")
            or ""
        )
        if commit:
            self.check_card.append(widgets.property_row("提交", commit))
        reason = str(result.get("reason") or "")
        if reason:
            self.check_card.append(
                widgets.property_row("结果", _reason_text(reason))
            )
        dependencies = [
            str(item) for item in result.get("dependency_changes") or []
        ]
        if dependencies:
            auto = bool(result.get("auto_install_dependencies", True))
            self.check_card.append(
                widgets.muted(
                    "依赖文件变化（"
                    + (
                        "应用更新后自动安装，失败会回滚源码"
                        if auto
                        else "需手动安装，禁止自动应用"
                    )
                    + "）："
                    + "、".join(dependencies)
                )
            )
        for component, error in (result.get("errors") or {}).items():
            self.check_card.append(
                widgets.label(
                    f"{component} 仓库读取失败：{error}",
                    css="danger-text",
                    wrap=True,
                )
            )
        for warning in result.get("warnings") or []:
            self.check_card.append(
                widgets.label(
                    "警告：" + str(warning),
                    css="danger-text" if not result.get("can_apply") else "muted",
                    wrap=True,
                )
            )
        commits = [str(item) for item in result.get("commits") or []]
        if commits:
            expander = Gtk.Expander(label=f"将包含 {len(commits)} 个提交")
            text_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=2
            )
            text_box.set_margin_top(6)
            for line in commits[:20]:
                text_box.append(
                    widgets.label(line, css="monospace", wrap=True, selectable=True)
                )
            expander.set_child(text_box)
            self.check_card.append(expander)
        if result.get("can_apply"):
            apply_button = widgets.button(
                "应用此版本", css="suggested-action"
            )
            apply_button.connect(
                "clicked", lambda _b, checked=result: self._confirm_apply(checked)
            )
            self._check_apply_button = apply_button
            self.check_card.append(apply_button)
        self.check_card.set_visible(True)

    def _check_data_root(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        data_dir = str((getattr(self.app, "status", {}) or {}).get("data_dir") or "")
        if not data_dir:
            self.data_dir_warning.set_visible(False)
            return
        self.data_dir_warning.set_visible(
            data_dir_inside_project(project_root, Path(data_dir))
        )

    def _load_releases(self, *, force: bool) -> None:
        if self.api is None or self._releases_busy:
            return
        self._releases_busy = True
        self.load_button.set_sensitive(False)
        path = "/api/update/releases" + ("?force=true" if force else "")
        if not self._releases_loaded:
            widgets.clear(self.releases_box)
            self.releases_box.append(self.busy("正在读取远端版本…"))

        def _do() -> dict[str, Any]:
            return self.api.get(path, timeout=330)

        def _done(data: dict[str, Any]) -> None:
            self._releases_busy = False
            self.load_button.set_sensitive(True)
            self._releases_loaded = True
            self._render_releases(data)

        def _failed(exc: BaseException) -> None:
            self._releases_busy = False
            self.load_button.set_sensitive(True)
            if self._releases_loaded:
                self.toast(f"刷新远端版本失败：{exc}")
                return
            widgets.clear(self.releases_box)
            self.releases_box.append(
                widgets.muted(f"加载远端版本失败：{exc}")
            )
            retry = widgets.button("重试")
            retry.connect(
                "clicked", lambda _b: self._load_releases(force=False)
            )
            self.releases_box.append(retry)

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _render_releases(self, data: dict[str, Any]) -> None:
        widgets.clear(self.releases_box)
        self._release_buttons = []
        errors = data.get("errors") or {}
        if errors:
            self.releases_box.append(
                widgets.label(
                    "部分仓库读取失败："
                    + "；".join(f"{key}: {value}" for key, value in errors.items()),
                    css="danger-text",
                    wrap=True,
                )
            )
        releases = data.get("releases") or []
        if not releases:
            self.releases_box.append(widgets.muted("远端没有可用版本。"))
            return
        for release in releases:
            self.releases_box.append(self._release_card(release))

    def _release_card(self, release: dict[str, Any]) -> Gtk.Widget:
        card = widgets.card(spacing=5)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.append(
            widgets.label(
                str(release.get("name") or _release_tag(release) or ""),
                css="section-title",
            )
        )
        component_text = _component_text(release)
        if component_text:
            head.append(widgets.badge(component_text, css="badge badge-idle"))
        if release.get("prerelease"):
            head.append(widgets.badge("Pre-release", css="badge badge-red"))
        if release.get("is_current"):
            head.append(widgets.badge("当前版本", css="badge badge-green"))
        elif release.get("relation"):
            head.append(widgets.badge(_relation_text(release)))
        compat = release.get("compat") or {}
        blocked = (
            not release.get("is_current")
            and compat.get("compatible") is False
        )
        if blocked:
            badge = widgets.badge("兼容性未通过", css="badge badge-red")
            if compat.get("message"):
                badge.set_tooltip_text(str(compat["message"]))
            head.append(badge)
        elif compat.get("compatible") is True:
            head.append(widgets.badge("兼容", css="badge badge-green"))
        head.append(widgets.muted(_release_tag(release)))
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
                widgets.muted("发布时间：" + widgets.short_time(published))
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
        if release.get("is_current"):
            card.append(widgets.badge("正在使用", css="badge"))
            return card
        action = widgets.button(
            "不可自动应用" if blocked else _action_label(release),
            css="suggested-action" if not blocked else "",
        )
        action.set_sensitive(not blocked and not self._applying)
        if blocked:
            action.set_tooltip_text(
                str(compat.get("message") or "目标版本与当前数据不兼容")
            )
        action.connect(
            "clicked",
            lambda _b, target=release: self._begin_apply(target),
        )
        if not blocked:
            self._release_buttons.append(action)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(action)
        card.append(row)
        return card

    def _set_apply_busy(self, busy: bool) -> None:
        self._applying = busy
        self.check_button.set_sensitive(not busy)
        self.load_button.set_sensitive(not busy)
        for button in self._release_buttons:
            button.set_sensitive(not busy)
        if self._check_apply_button is not None:
            self._check_apply_button.set_sensitive(not busy)

    def _begin_apply(self, release: dict[str, Any]) -> None:
        if self.api is None or self._applying or self._check_busy:
            return
        compat = release.get("compat") or {}
        if compat.get("compatible") is False:
            self.status_label.set_text(
                "不可自动应用：" + str(compat.get("message") or compat.get("code") or "")
            )
            return
        tag = str(release.get("tag") or "").strip()
        if not tag:
            self.toast("这个版本没有可用的 tag")
            return
        self._set_apply_busy(True)
        self.status_label.set_text(f"正在检查目标版本 {tag}…")

        def _do() -> dict[str, Any]:
            return self.api.post(
                "/api/update/check", {"target_tag": tag}, timeout=330
            )

        def _done(checked: dict[str, Any]) -> None:
            self._set_apply_busy(False)
            self._check_result = checked
            self._render_check(checked)
            if not checked.get("can_apply"):
                message = _reason_text(
                    checked.get("reason") or checked.get("reason_text")
                )
                self.status_label.set_text(message)
                self.toast(message)
                return
            self.status_label.set_text("已检查目标版本，等待确认。")
            self._confirm_apply(checked)

        def _failed(exc: BaseException) -> None:
            self._set_apply_busy(False)
            self.status_label.set_text(f"检查目标版本失败：{exc}")
            self.toast(f"检查失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _confirm_apply(self, checked: dict[str, Any]) -> None:
        if self._applying:
            return
        name = str(
            checked.get("target_name")
            or checked.get("target_label")
            or checked.get("target_tag")
            or "目标版本"
        )
        rollback = bool(
            checked.get("is_rollback") or checked.get("is_diverged")
        )
        kind = "回退" if checked.get("is_rollback") else (
            "切换" if checked.get("is_diverged") else "更新"
        )
        module_mode = str(checked.get("mode") or "") == "module"
        lines = []
        if module_mode:
            for item in checked.get("updates") or []:
                if isinstance(item, dict):
                    lines.append(
                        f"{_component_text(item) or '组件'}："
                        f"{_release_tag(item)}"
                        + ("（Pre-release，极不稳定）" if item.get("prerelease") else "")
                    )
        else:
            lines.append(
                f"目标提交：{str(checked.get('target_commit') or '')[:12]}"
            )
        dependencies = [
            str(item) for item in checked.get("dependency_changes") or []
        ]
        if dependencies:
            auto = bool(checked.get("auto_install_dependencies", True))
            lines.append(
                "依赖文件变化（"
                + (
                    "应用更新后自动安装，失败会回滚源码"
                    if auto
                    else "需手动安装，禁止自动应用"
                )
                + "）："
                + "、".join(dependencies)
            )
        warnings = [str(item) for item in checked.get("warnings") or []]
        if warnings:
            lines.append("\n警告：\n" + "\n".join("• " + item for item in warnings))
        commits = [str(item) for item in checked.get("commits") or []]
        if commits:
            lines.append(
                "\n将包含的提交：\n"
                + "\n".join(commits[:12])
            )
        if module_mode:
            lines.append(
                "\n只会替换 backend/ 与 gui/ 模块目录；用户数据目录不会被覆盖，"
                "当前模块会先备份到数据目录的 module_backups/。"
            )
            lines.append(
                "\n后端更新后需要重启本地后端；GUI 前端更新后必须完全退出并重新打开应用。"
            )
        else:
            lines.append(
                "\n更新会修改当前代码工作树；用户数据目录不会被覆盖，"
                "旧 HEAD 会先创建备份引用。"
            )
            lines.append(
                "\n更新完成后需要重启 GUI 本地后端以加载新代码；"
                "如果目标版本也修改了 GUI 界面代码，需要重新打开应用。"
            )
        if rollback:
            lines.append(
                "\n这是回退/切换操作：当前分支会被移动到目标提交。"
            )
        widgets.ConfirmDialog(
            self.app.window,
            heading=f"确认{kind}到「{name}」？",
            body="\n".join(lines),
            confirm_label=f"确认{kind}",
            destructive=rollback,
            on_confirm=lambda: self._apply(checked),
        )

    def _apply(self, checked: dict[str, Any]) -> None:
        if self.api is None or self._applying:
            return
        token = str(checked.get("confirmation_token") or "")
        module_mode = str(checked.get("mode") or "") == "module"
        target_sha = str(checked.get("target_commit") or "")
        if not token or (not module_mode and not target_sha):
            self.toast("检查结果缺少确认令牌或目标提交，请重新检查")
            return
        rollback = bool(
            checked.get("is_rollback") or checked.get("is_diverged")
        )
        payload = {
            "confirmation_token": token,
            "target_sha": target_sha,
            "confirm_branch_switch": True,
            "confirm_rollback": rollback,
            "defer_restart": True,
            "acknowledge_prerelease": any(
                item.get("prerelease")
                for item in checked.get("updates") or []
                if isinstance(item, dict)
            ),
        }
        self._set_apply_busy(True)
        self.status_label.set_text("正在应用更新…")

        def _do() -> dict[str, Any]:
            return self.api.post(
                "/api/update/apply", payload, timeout=900
            )

        def _done(result: dict[str, Any]) -> None:
            self._set_apply_busy(False)
            self._releases_loaded = False
            message = str(result.get("message") or "更新完成")
            self.status_label.set_text(message)
            self.toast(message)
            if result.get("requires_app_restart"):
                widgets.ConfirmDialog(
                    self.app.window,
                    heading="更新完成，需要重新打开应用",
                    body=message
                    + "\n\nGUI 前端代码已替换；当前窗口仍运行旧界面。"
                    "请完全退出 KarenBot 后重新启动，新的界面和后端才会一起加载。",
                    confirm_label="知道了",
                    on_confirm=self.refresh,
                )
            elif result.get("restart_scheduled") or result.get("restart_required"):
                widgets.ConfirmDialog(
                    self.app.window,
                    heading="更新完成，需要重启后端",
                    body=message
                    + "\n\nGUI 会停止并重新启动自己的本地后端，"
                    "期间界面短暂显示加载页。",
                    confirm_label="立即重启后端",
                    on_confirm=self._restart_backend,
                )
            else:
                self.refresh()

        def _failed(exc: BaseException) -> None:
            self._set_apply_busy(False)
            self.status_label.set_text(f"应用更新失败：{exc}")
            self.toast(f"更新失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _confirm_restart_backend(self) -> None:
        if self._applying:
            return
        widgets.ConfirmDialog(
            self.app.window,
            heading="重启 GUI 本地后端？",
            body="当前正在进行的请求会被中断，界面会短暂显示加载页。"
            "这会重新启动 GUI 自己的后端进程内服务并重新加载磁盘上的 Python "
            "代码；不会加载当前进程中已导入的 GUI 界面代码。",
            confirm_label="重启后端",
            on_confirm=self._restart_backend,
        )

    def _restart_backend(self) -> None:
        restart = getattr(self.app, "restart_backend", None)
        if not callable(restart):
            self.toast("当前窗口不支持重启后端")
            return
        self.status_label.set_text("正在重启本地后端…")
        restart()
