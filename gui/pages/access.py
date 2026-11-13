"""Whitelist / blacklist control page with chip editors."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402


def _access_status_text(
    mode: str,
    white_qq: int,
    white_group: int,
    black_enabled: bool,
    black_qq: int,
    black_group: int,
) -> tuple[str, bool]:
    white_label = {
        "open": "白名单未限制入站",
        "verify": "陌生人由管理员审核",
        "whitelist": "仅白名单内可触发回复",
    }.get(mode, mode)
    black_state = (
        f"黑名单生效中（{black_qq} 个 QQ、{black_group} 个群）"
        if black_enabled
        else f"黑名单已关闭（保留 {black_qq + black_group} 项，不拦截）"
    )
    empty_whitelist = (
        mode == "whitelist" and white_qq + white_group == 0
    )
    warning = (
        " 当前白名单为空，保存后所有入站消息都会被拦截。"
        if empty_whitelist
        else ""
    )
    return (
        f"{white_label}；白名单 {white_qq + white_group} 项；"
        f"{black_state}。保存后立即生效，无需重启。{warning}",
        empty_whitelist,
    )


class AccessListsPage(Page):
    refresh_on_activate = True
    page_id = "access"
    page_title = "黑白名单"
    page_subtitle = "统一管理入站策略、白名单和黑名单。黑名单优先于白名单与管理员审核；保存后立即生效。"
    page_icon = "system-users-symbolic"

    def build(self) -> None:
        self._loading = False
        self._dirty = False
        self._saving = False
        # 在服务端名单成功读取之前，绝不允许保存：否则一次读取失败后的
        # 空表单会把服务端整份名单覆盖成空名单。
        self._loaded = False
        self._loading_remote = False
        header_row = self.header()
        self.dirty_badge = widgets.badge("未保存", css="badge badge-orange")
        self.dirty_badge.set_visible(False)
        header_row.append(self.dirty_badge)
        self.save_button = widgets.button(
            "保存并立即生效", css="suggested-action"
        )
        self.save_button.set_sensitive(False)
        self.save_button.connect("clicked", lambda _b: self._save())
        header_row.append(self.save_button)
        self.body.append(header_row)

        self.wl_card = widgets.card(spacing=8)
        self.wl_card.set_sensitive(False)
        self.wl_card.append(
            widgets.section_header(
                "白名单",
                "限制哪些 QQ 号或群可以触发回复；仅在 mode=whitelist 时严格生效。",
            )
        )
        self.wl_mode = widgets.dropdown(
            [
                ("open", "open（对所有人开放，注意 API 费用）"),
                ("verify", "verify（陌生人走管理员审核）"),
                ("whitelist", "whitelist（仅名单内可用）"),
            ],
            "verify",
        )
        self.wl_mode.connect("notify::selected", lambda *_: self._mark_dirty())
        self.wl_card.append(self._field("入站策略", self.wl_mode))
        self.wl_qq = widgets.ChipList(
            "白名单 QQ 号",
            "输入 QQ 号后回车，可一次粘贴多个",
            on_changed=lambda _v: self._mark_dirty(),
        )
        self.wl_group = widgets.ChipList(
            "白名单群号",
            "输入群号后回车，可一次粘贴多个",
            on_changed=lambda _v: self._mark_dirty(),
        )
        self.wl_card.append(self.wl_qq)
        self.wl_card.append(self.wl_group)
        self.wl_card.append(
            widgets.muted("仅在 whitelist 模式下严格限制私聊和群聊。")
        )
        self.body.append(self.wl_card)

        self.bl_card = widgets.card(spacing=8)
        self.bl_card.set_sensitive(False)
        self.bl_card.append(
            widgets.section_header(
                "黑名单",
                "命中后消息在入站处直接丢弃——不回复、不入库、不消耗 API 费用。",
            )
        )
        enabled_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.bl_enabled = widgets.switch(True)
        self.bl_enabled.connect(
            "notify::active", lambda *_: self._mark_dirty()
        )
        enabled_row.append(self.bl_enabled)
        enabled_row.append(widgets.label("启用黑名单（关闭时名单保留但不拦截）"))
        self.bl_card.append(enabled_row)
        self.bl_qq = widgets.ChipList(
            "拉黑的 QQ 号",
            "输入 QQ 号后回车，可一次粘贴多个",
            on_changed=lambda _v: self._mark_dirty(),
        )
        self.bl_group = widgets.ChipList(
            "拉黑的群",
            "输入群号后回车，可一次粘贴多个",
            on_changed=lambda _v: self._mark_dirty(),
        )
        self.bl_card.append(self.bl_qq)
        self.bl_card.append(self.bl_group)
        self.body.append(self.bl_card)

        priority = widgets.card(spacing=5)
        priority.append(widgets.label("优先级", css="card-title"))
        priority.append(
            widgets.muted(
                "黑名单优先级最高：先查黑名单，命中即丢弃，不再看白名单或审核。\n"
                "白名单模式为 open 时对所有人开放，黑名单仍能拦住被拉黑的对象。\n"
                "白名单为空且 mode=whitelist 时，所有入站消息都会被拦截。"
            )
        )
        self.body.append(priority)

        self.status_label = widgets.muted("")
        self.body.append(self.status_label)

    def _field(self, name: str, widget: Gtk.Widget) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(widgets.label(name, css="field-label"))
        box.append(widget)
        return box

    def _mark_dirty(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self.dirty_badge.set_visible(True)
        self._update_status()

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def discard_unsaved_changes(self) -> None:
        self._dirty = False
        self.dirty_badge.set_visible(False)

    def refresh(self) -> None:
        if self.api is None or self.has_unsaved_changes():
            return
        self._loading_remote = True
        self.save_button.set_sensitive(False)

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/settings/lists", timeout=30)

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        self._loading_remote = False
        self._loaded = False
        self.save_button.set_sensitive(False)
        self.wl_card.set_sensitive(False)
        self.bl_card.set_sensitive(False)
        self.status_label.set_text(f"读取名单失败：{exc}。请点击右上角刷新重试。")
        self.status_label.add_css_class("danger-text")

    def _render(self, data: dict[str, Any]) -> None:
        self._loading = True
        whitelist = data.get("whitelist") or {}
        blacklist = data.get("blacklist") or {}
        values = [value for value, _label in _dropdown_values(self.wl_mode)]
        mode = str(whitelist.get("mode") or "verify")
        if mode in values:
            self.wl_mode.set_selected(values.index(mode))
        self.wl_qq.set_values(whitelist.get("qq_ids") or [])
        self.wl_group.set_values(whitelist.get("group_ids") or [])
        self.bl_enabled.set_active(bool(blacklist.get("enabled", True)))
        self.bl_qq.set_values(blacklist.get("qq_ids") or [])
        self.bl_group.set_values(blacklist.get("group_ids") or [])
        self._loading = False
        self._loading_remote = False
        self._loaded = True
        self._update_status()
        self._dirty = False
        self.dirty_badge.set_visible(False)
        self.wl_card.set_sensitive(True)
        self.bl_card.set_sensitive(True)
        if not self._saving:
            self.save_button.set_sensitive(True)

    def _update_status(self) -> None:
        text, warning = _access_status_text(
            widgets.dropdown_value(self.wl_mode),
            len(self.wl_qq.get_values()),
            len(self.wl_group.get_values()),
            bool(self.bl_enabled.get_active()),
            len(self.bl_qq.get_values()),
            len(self.bl_group.get_values()),
        )
        self.status_label.set_text(text)
        if warning:
            self.status_label.add_css_class("danger-text")
        else:
            self.status_label.remove_css_class("danger-text")

    def _payload(self) -> dict[str, Any]:
        return {
            "whitelist": {
                "mode": widgets.dropdown_value(self.wl_mode),
                "qq_ids": self.wl_qq.get_values(),
                "group_ids": self.wl_group.get_values(),
            },
            "blacklist": {
                "enabled": self.bl_enabled.get_active(),
                "qq_ids": self.bl_qq.get_values(),
                "group_ids": self.bl_group.get_values(),
            },
        }

    def _save(self) -> None:
        if self.api is None or self._saving:
            return
        if not self._loaded:
            self.toast("名单尚未成功读取；为避免覆盖服务端配置，请先刷新")
            return
        payload = self._payload()
        whitelist = payload["whitelist"]
        if (
            whitelist["mode"] == "whitelist"
            and not whitelist["qq_ids"]
            and not whitelist["group_ids"]
        ):
            widgets.ConfirmDialog(
                self.app.window,
                heading="白名单为空，确定保存？",
                body="当前入站策略是 whitelist，且白名单里没有任何 QQ 或群。"
                "保存后所有入站消息都会被拦截。",
                confirm_label="仍然保存",
                destructive=True,
                on_confirm=lambda: self._commit(payload),
            )
            return
        self._commit(payload)

    def _commit(self, payload: dict[str, Any]) -> None:
        if self.api is None or self._saving:
            return
        if not self._loaded:
            self.toast("名单尚未成功读取；为避免覆盖服务端配置，请先刷新")
            return

        def _do() -> dict[str, Any]:
            return self.api.put("/api/settings/lists", payload, timeout=60)

        self._saving = True
        self.save_button.set_sensitive(False)

        def _done(result: dict[str, Any]) -> None:
            self._saving = False
            self.save_button.set_sensitive(True)
            self.toast(str(result.get("message") or "名单已保存"))
            self._render(result)

        def _failed(exc: BaseException) -> None:
            self._saving = False
            self.save_button.set_sensitive(True)
            self.toast(f"保存失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)


def _dropdown_values(dropdown: Gtk.DropDown) -> list[tuple[str, str]]:
    values = getattr(dropdown, "_values", [])
    return [(str(value), str(value)) for value in values]
