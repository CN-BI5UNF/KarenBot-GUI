"""Declarative settings editor and runtime diagnostics."""

from __future__ import annotations

import json
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402
from .settings_panels import (  # noqa: E402
    BackupSettingsPanel,
    SearchSettingsPanel,
    TokenBudgetSettingsPanel,
    UpdateSettingsPanel,
    VisionSettingsPanel,
)

_SPECIAL_PATHS = {
    "features.vision.main_model_images",
    "features.vision.enabled",
    "features.vision.provider",
    "features.vision.model",
    "features.vision.base_url",
    "features.vision.api_key_id",
    "features.vision.gif_mode",
    "features.vision.main_model_videos",
    "features.vision.video_token_reserve",
    "features.vision.video_limits.max_videos_per_request",
    "features.vision.image_token_reserve",
    "features.vision.image_limits.max_images_per_request",
    "features.web_search.enabled",
    "features.web_search.free_enabled",
    "features.web_search.provider",
    "features.web_search.searxng_base_url",
    "features.web_search.max_results",
    "features.web_search.timeout_seconds",
    "features.web_search.official.enabled",
    "features.web_search.official.provider",
    "features.web_search.official.model",
    "features.web_search.official.timeout_seconds",
    "update.mirror",
}


class SettingsPage(Page):
    page_id = "settings"
    page_title = "设置"
    page_subtitle = "运行参数、模型与路径诊断。改动即时写入 config.yaml；需要重启的会给出提示。"
    page_icon = "emblem-system-symbolic"

    def build(self) -> None:
        # The settings page owns two independent scroll areas (group nav and
        # group body), so the outer page scroller must not steal the wheel.
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.body.set_vexpand(True)
        self._data: dict[str, Any] = {}
        self._groups: list[dict[str, Any]] = []
        self._group_pages: dict[str, Gtk.Widget] = {}
        self._group_panels: dict[str, list[Any]] = {}
        self._specs: dict[str, dict[str, Any]] = {}
        self._providers: list[dict[str, Any]] = []
        self._presets: list[dict[str, Any]] = []
        self._agents: dict[str, Any] = {}
        self._provider_error = ""
        self._selected_group = ""
        self._pending_section = ""

        self.body.append(self.header())
        self.restart_hint = widgets.card()
        self.restart_hint.set_visible(False)
        self.body.append(self.restart_hint)
        # 分组导航与字段区可拖动分隔条调整占比；默认只占 156px，
        # 给右侧正文留更多宽度（WebUI 的设置导航也是窄栏）。
        split = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        split.add_css_class("settings-split")
        split.set_wide_handle(True)
        split.set_position(156)
        split.set_resize_start_child(True)
        split.set_resize_end_child(True)
        split.set_shrink_start_child(True)
        split.set_shrink_end_child(False)
        split.set_vexpand(True)
        split.set_hexpand(True)
        self.group_list = Gtk.ListBox()
        self.group_list.set_size_request(120, -1)
        self.group_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.group_list.add_css_class("navigation-sidebar")
        self.group_list.add_css_class("settings-nav")
        self.group_list.connect("row-selected", self._on_group_selected)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.append(widgets.label("分组", css="section-title"))
        nav_scroller = Gtk.ScrolledWindow()
        nav_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nav_scroller.set_overlay_scrolling(False)
        nav_scroller.set_vexpand(True)
        nav_scroller.set_child(self.group_list)
        left.append(nav_scroller)
        split.set_start_child(left)
        self.split_paned = split
        self.group_stack = Gtk.Stack()
        self.group_stack.set_hexpand(True)
        self.group_stack.set_vexpand(True)
        self.group_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.group_stack.set_transition_duration(100)
        self.group_stack.set_margin_start(14)
        split.set_end_child(self.group_stack)
        self.body.append(split)
        self.group_stack.add_named(self.busy("正在读取设置…"), "loading")
        self.group_stack.set_visible_child_name("loading")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            from concurrent.futures import ThreadPoolExecutor

            api = self.api
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {
                    "settings": pool.submit(
                        api.get, "/api/settings", timeout=60
                    ),
                    "providers": pool.submit(
                        api.get, "/api/providers", timeout=60
                    ),
                    "presets": pool.submit(
                        api.get, "/api/providers/presets", timeout=60
                    ),
                }
                data: dict[str, Any] = {}
                for key, future in futures.items():
                    try:
                        data[key] = future.result()
                    except BaseException as exc:  # noqa: BLE001
                        data[key] = {"error": str(exc)}
            return data

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.group_list)
        widgets.clear(self.group_stack)
        self.group_stack.add_named(widgets.muted(f"读取设置失败：{exc}"), "error")
        self.group_stack.set_visible_child_name("error")

    def _render(self, data: dict[str, Any]) -> None:
        payload = data.get("settings") or {}
        self._data = payload
        self._groups = list(payload.get("groups") or [])
        self._specs = {}
        for group in self._groups:
            for spec in group.get("fields") or []:
                path = str(spec.get("path") or "")
                if path:
                    self._specs[path] = spec
        provider_payload = data.get("providers") or {}
        self._provider_error = str(provider_payload.get("error") or "")
        self._providers = list(provider_payload.get("providers") or [])
        self._agents = dict(provider_payload.get("agents") or {})
        preset_payload = data.get("presets") or {}
        if not self._provider_error and preset_payload.get("error"):
            self._provider_error = str(preset_payload.get("error"))
        self._presets = list(preset_payload.get("presets") or [])
        self._group_pages = {}
        self._group_panels = {}
        widgets.clear(self.group_list)
        while self.group_stack.get_first_child() is not None:
            self.group_stack.remove(self.group_stack.get_first_child())
        previous = self._pending_section or self._selected_group
        self._pending_section = ""
        for group in self._groups:
            row = Gtk.ListBoxRow()
            row.group_key = str(group.get("key") or "")  # type: ignore[attr-defined]
            row.add_css_class("nav-row")
            row.set_child(widgets.label(str(group.get("title") or group.get("key") or "")))
            self.group_list.append(row)
        paths_row = Gtk.ListBoxRow()
        paths_row.group_key = "__paths__"  # type: ignore[attr-defined]
        paths_row.add_css_class("nav-row")
        paths_row.set_child(widgets.label("路径与诊断"))
        self.group_list.append(paths_row)
        target = self._row_for_group(previous)
        if target is None and previous == "__paths__":
            target = paths_row
        if target is None:
            target = self.group_list.get_row_at_index(0)
        if target is not None:
            self.group_list.select_row(target)
        GLib.idle_add(self._apply_pending_selection)

    def _apply_pending_selection(self) -> bool:
        key = self._pending_section
        if not key:
            return False
        row = self._row_for_group(key)
        if row is not None:
            if self.group_list.get_selected_row() is not row:
                self.group_list.select_row(row)
            if self.group_list.get_selected_row() is row:
                self._pending_section = ""
        return False

    def _row_for_group(self, key: str) -> Gtk.ListBoxRow | None:
        index = 0
        row = self.group_list.get_row_at_index(index)
        while row is not None:
            if str(getattr(row, "group_key", "")) == key:
                return row
            index += 1
            row = self.group_list.get_row_at_index(index)
        return None

    # ------------------------------------------------------------------
    # Group rendering
    # ------------------------------------------------------------------
    def _on_group_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        key = str(getattr(row, "group_key", ""))
        self._selected_group = key
        if key == "__paths__":
            page = self._paths_page()
            if page.get_parent() is not self.group_stack:
                self.group_stack.add_named(page, "__paths__")
        else:
            page = self._group_pages.get(key)
            if page is None:
                group = next((g for g in self._groups if str(g.get("key")) == key), None)
                if group is None:
                    return
                page = self._build_group(group)
                self._group_pages[key] = page
                self.group_stack.add_named(page, key)
        self.group_stack.set_visible_child(page)
        for panel in self._group_panels.get(key, []):
            on_show = getattr(panel, "on_show", None)
            if callable(on_show):
                on_show()

    def _build_group(self, group: dict[str, Any]) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_propagate_natural_height(False)
        scroller.set_min_content_height(420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_end(4)
        box.set_margin_bottom(18)
        box.append(
            widgets.section_header(
                str(group.get("title") or ""), str(group.get("desc") or "")
            )
        )
        key = str(group.get("key") or "")
        fields = [
            spec
            for spec in (group.get("fields") or [])
            if not spec.get("hidden") and str(spec.get("path") or "") not in _SPECIAL_PATHS
        ]
        if fields:
            card = widgets.card(spacing=4, padding=14)
            for index, spec in enumerate(fields):
                if index:
                    card.append(widgets.separator())
                card.append(self._field_row(spec))
            box.append(card)
        elif group.get("fields"):
            box.append(self.empty("这个分页的选项由下方专用面板设置。"))
        else:
            box.append(
                self.empty(
                    "这个分页没有可视化字段；路径、密钥与运行时操作见「路径与诊断」。"
                )
            )

        panels: list[Any] = []
        if key == "features":
            vision = VisionSettingsPanel(self, group)
            search = SearchSettingsPanel(self, group)
            box.append(vision)
            box.append(search)
            panels.extend([vision, search])
        elif key == "update":
            update_panel = UpdateSettingsPanel(self, group)
            box.append(update_panel)
            panels.append(update_panel)
        elif key == "backup":
            backup = BackupSettingsPanel(self)
            box.append(backup)
            panels.append(backup)
        elif key == "token_budget":
            budget = TokenBudgetSettingsPanel(self)
            box.append(budget)
            panels.append(budget)
        self._group_panels[key] = panels
        scroller.set_child(box)
        return scroller

    def spec_for(self, path: str) -> dict[str, Any]:
        return self._specs.get(path) or {}

    def spec_value(self, path: str, default: Any = None) -> Any:
        spec = self.spec_for(path)
        return spec.get("value", spec.get("default", default))

    def update_spec_value(self, path: str, value: Any) -> None:
        spec = self._specs.get(path)
        if spec is not None:
            spec["value"] = value

    def provider_payload(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        return self._providers, self._presets, self._provider_error

    # ------------------------------------------------------------------
    # Generic controls
    # ------------------------------------------------------------------
    def _field_row(self, field: dict[str, Any]) -> Gtk.Widget:
        kind = str(field.get("type") or "str")
        value = field.get("value", field.get("default"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        label_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label_row.append(
            widgets.label(str(field.get("label") or field.get("path")), css="field-label")
        )
        if field.get("needs_restart"):
            label_row.append(widgets.badge("需重启"))
        label_row.set_hexpand(True)
        box.append(label_row)
        help_text = str(field.get("help") or "")
        if kind == "secret_ref":
            help_text = (help_text + " " if help_text else "") + (
                "密钥只写入加密的 secrets.enc，不落 config.yaml。"
            )
        help_label = widgets.muted(help_text)
        help_label.set_visible(bool(help_text))
        box.append(help_label)

        if kind == "bool":
            control = widgets.switch(bool(value))
            previous = bool(value)

            def _toggle(w: Gtk.Switch, _pspec: Any = None, f=field, old=previous) -> None:
                self._save(
                    f,
                    bool(w.get_active()),
                    on_error=lambda _exc, sw=w, prev=old: _restore_switch(sw, prev),
                )

            control.connect("notify::active", _toggle)
            box.append(control)
        elif kind == "enum":
            options = [(str(v), str(label)) for v, label in (field.get("options") or [])]
            control = widgets.dropdown(options, str(value or ""))
            previous = str(value or "")
            option_help = field.get("option_help") or {}

            def _refresh_hint(*_args: Any) -> None:
                selected = widgets.dropdown_value(control)
                text = str(option_help.get(selected) or help_text or "")
                help_label.set_text(text)
                help_label.set_visible(bool(text))

            def _changed(w: Gtk.DropDown, _pspec: Any = None, f=field, old=previous) -> None:
                _refresh_hint()
                selected = widgets.dropdown_value(w)
                self._save(
                    f,
                    selected,
                    on_error=lambda _exc, dd=w, prev=old: _select_dropdown(dd, prev),
                )

            control.connect("notify::selected", _changed)
            _refresh_hint()
            box.append(control)
        elif kind == "secret_ref":
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry = Gtk.Entry()
            entry.set_visibility(False)
            entry.set_hexpand(True)
            key_id = str(value or "")
            entry.set_placeholder_text(
                f"已保存（ID: {key_id}，留空不修改）" if key_id else "未设置"
            )
            save = widgets.button("保存密钥")
            save.connect(
                "clicked",
                lambda _b, f=field, e=entry: self._save_secret(f, e),
            )
            row.append(entry)
            row.append(save)
            box.append(row)
        elif kind == "list_str":
            area = widgets.text_view("\n".join(str(x) for x in (value or [])), height=64)
            self._bind_text_commit(field, area, help_label)
            box.append(area)
            save = widgets.button("保存")
            save.connect(
                "clicked",
                lambda _b, f=field, a=area: self._commit_text_view(f, a),
            )
            box.append(save)
        elif kind == "json":
            area = widgets.text_view(
                json.dumps(value, ensure_ascii=False, indent=2) if value is not None else "",
                height=110,
                monospace=True,
            )
            self._bind_text_commit(field, area, help_label)
            box.append(area)
            save = widgets.button("保存 JSON")
            save.connect(
                "clicked",
                lambda _b, f=field, a=area: self._commit_text_view(f, a),
            )
            box.append(save)
        elif kind == "list_int":
            entry = Gtk.Entry()
            entry.set_text(
                ", ".join(str(x) for x in (value or []))
                if isinstance(value, list)
                else str(value or "")
            )
            self._bind_entry_commit(field, entry, kind, help_label)
            box.append(entry)
        elif kind in {"int", "float", "int_or_none"} and _bounded(field):
            low = int(field.get("min", 0))
            high = int(field.get("max", 1_000_000_000))
            control = Gtk.SpinButton.new_with_range(low, high, 1)
            control.set_numeric(True)
            control.set_halign(Gtk.Align.START)
            try:
                control.set_value(int(value if value is not None else low))
            except (TypeError, ValueError):
                control.set_value(low)
            last = [int(control.get_value())]

            def _spin_commit(w: Gtk.SpinButton, f=field, state=last) -> None:
                current = int(w.get_value())
                if current == state[0]:
                    return
                self._save(
                    f,
                    current,
                    on_success=lambda _r, val=current, old_state=state: old_state.__setitem__(0, val),
                    on_error=lambda _exc, spin=w, prev=state[0]: spin.set_value(prev),
                )

            focus = Gtk.EventControllerFocus()
            focus.connect("leave", lambda _c, w=control: _spin_commit(w))
            control.add_controller(focus)
            control.connect("activate", lambda w: _spin_commit(w))
            box.append(control)
        else:
            entry = Gtk.Entry()
            if kind in {"int", "float", "int_or_none"}:
                entry.set_placeholder_text("留空 = 自动" if kind == "int_or_none" else "")
            entry.set_text("" if value is None else str(value))
            self._bind_entry_commit(field, entry, kind, help_label)
            if str(field.get("path") or "") == "backup.directory":
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                entry.set_hexpand(True)
                pick = widgets.button("选择…")
                pick.connect(
                    "clicked",
                    lambda _b, e=entry: self._pick_backup_dir(field, e),
                )
                row.append(entry)
                row.append(pick)
                box.append(row)
            else:
                box.append(entry)
        return box

    def _bind_entry_commit(
        self,
        field: dict[str, Any],
        entry: Gtk.Entry,
        kind: str,
        help_label: Gtk.Label,
    ) -> None:
        last = {"raw": entry.get_text()}

        def _commit() -> None:
            raw = entry.get_text().strip()
            if raw == last["raw"]:
                return
            try:
                value, display = _parse_scalar(kind, raw)
            except ValueError as exc:
                help_label.set_text(str(exc))
                help_label.set_visible(True)
                self.toast(str(exc))
                entry.set_text(last["raw"])
                return
            help_label.set_visible(False)

            def _done(_result: Any) -> None:
                last["raw"] = display
                entry.set_text(display)

            def _failed(_exc: BaseException) -> None:
                entry.set_text(last["raw"])

            self._save(field, value, on_success=_done, on_error=_failed)

        entry.connect("activate", lambda _e: _commit())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: _commit())
        entry.add_controller(focus)

    def _bind_text_commit(
        self,
        field: dict[str, Any],
        area: Gtk.ScrolledWindow,
        help_label: Gtk.Label,
    ) -> None:
        view: Gtk.TextView = area.text_view  # type: ignore[attr-defined]

        def _commit() -> None:
            text = widgets.text_value(area)
            current = field.get("value", field.get("default"))
            if str(field.get("type")) == "list_str":
                value = _parse_list_str(text)
                if value == list(current or []):
                    return
            else:
                try:
                    value = json.loads(text) if text.strip() else None
                except json.JSONDecodeError as exc:
                    help_label.set_text(f"JSON 解析失败：第 {exc.lineno} 行，{exc.msg}")
                    help_label.set_visible(True)
                    return
                if value == current:
                    return
            help_label.set_visible(False)
            self._save(field, value)

        key = Gtk.EventControllerKey()
        key.connect(
            "key-pressed",
            lambda _c, keyval, _code, state: _hotkey_commit(keyval, state, _commit),
        )
        view.add_controller(key)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: _commit())
        view.add_controller(focus)

    def _commit_text_view(self, field: dict[str, Any], area: Gtk.ScrolledWindow) -> None:
        kind = str(field.get("type") or "")
        text = widgets.text_value(area)
        if kind == "list_str":
            value = _parse_list_str(text)
        else:
            try:
                value = json.loads(text) if text.strip() else None
            except json.JSONDecodeError as exc:
                self.toast(f"JSON 解析失败：第 {exc.lineno} 行，{exc.msg}")
                return
        self._save(field, value)

    def _pick_backup_dir(self, field: dict[str, Any], entry: Gtk.Entry) -> None:
        path = widgets.path_picker(
            self.app.window, title_text="选择备份目录", folders=True
        )
        if not path:
            return
        entry.set_text(path)
        self._save(field, path)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    def _save(
        self,
        field: dict[str, Any],
        value: Any,
        *,
        on_success: Any = None,
        on_error: Any = None,
    ) -> None:
        if self.api is None:
            return
        path = str(field.get("path") or "")
        if not path:
            return
        current = field.get("value", field.get("default"))
        if value == current:
            if callable(on_success):
                on_success({"ok": True, "value": value, "needs_restart": False})
            return

        def _do() -> dict[str, Any]:
            return self.api.patch("/api/settings", {"path": path, "value": value}, timeout=60)

        def _done(result: dict[str, Any]) -> None:
            stored = result.get("value", value)
            field["value"] = stored
            self.update_spec_value(path, stored)
            if result.get("needs_restart"):
                self.mark_restart()
                self.toast(
                    f"{field.get('label')}："
                    f"{result.get('message') or '已保存；需要重启 Runtime 后生效'}"
                )
            else:
                self.toast(
                    f"{field.get('label')}："
                    f"{result.get('message') or '已保存并立即生效'}"
                )
            if callable(on_success):
                on_success(result)

        def _failed(exc: BaseException) -> None:
            self.toast(f"保存失败：{exc}")
            if callable(on_error):
                on_error(exc)

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _save_secret(self, field: dict[str, Any], entry: Gtk.Entry) -> None:
        if self.api is None:
            return
        key_id = str(field.get("secret_id") or "")
        value = entry.get_text().strip()
        if not key_id:
            return
        if not value:
            widgets.ConfirmDialog(
                self.app.window,
                heading="清空这个密钥？",
                body=key_id,
                confirm_label="清空",
                destructive=True,
                on_confirm=lambda: self._put_secret(field, key_id, "", entry),
            )
            return
        self._put_secret(field, key_id, value, entry)

    def _put_secret(
        self,
        field: dict[str, Any],
        key_id: str,
        value: str,
        entry: Gtk.Entry,
    ) -> None:
        if self.api is None:
            return
        ref_path = str(field.get("path") or "")

        def _do() -> dict[str, Any]:
            secret = self.api.put(
                "/api/settings/secrets", {"key_id": key_id, "value": value}, timeout=30
            )
            ref_error = ""
            if value and ref_path:
                try:
                    self.api.patch(
                        "/api/settings",
                        {"path": ref_path, "value": key_id},
                        timeout=60,
                    )
                except BaseException as exc:  # noqa: BLE001
                    ref_error = str(exc)
            return {"secret": secret, "ref_error": ref_error}

        def _done(result: dict[str, Any]) -> None:
            entry.set_text("")
            if value:
                entry.set_placeholder_text(f"已保存（ID: {key_id}，留空不修改）")
                field["value"] = key_id
                self.update_spec_value(ref_path, key_id)
                if result.get("ref_error"):
                    self.toast(
                        f"密钥已保存，但更新配置引用失败：{result['ref_error']}"
                    )
                else:
                    self.toast("密钥已保存")
                self.mark_restart()
            else:
                entry.set_placeholder_text("未设置")
                field["value"] = ""
                self.toast("密钥已清空")

        widgets.run_async(_do, on_success=_done, on_error=lambda exc: self.toast(str(exc)))

    def mark_restart(self) -> None:
        if self.restart_hint.get_visible():
            return
        widgets.clear(self.restart_hint)
        self.restart_hint.set_visible(True)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(
            widgets.label(
                "有配置需要重启 Runtime（后端）才能生效；不需要重启或刷新前端。"
            )
        )
        row.set_hexpand(True)
        restart = widgets.button("立即重启 Runtime", css="suggested-action")
        restart.connect("clicked", lambda _b: self._restart())
        row.append(restart)
        self.restart_hint.append(row)

    def _restart(self) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post("/api/system/restart", {}, timeout=180)

        def _done(_r: Any) -> None:
            self.restart_hint.set_visible(False)
            self.toast("Runtime 已重启")

        widgets.run_async(_do, on_success=_done, on_error=lambda exc: self.toast(f"重启失败：{exc}"))

    # ------------------------------------------------------------------
    # Paths and diagnostics
    # ------------------------------------------------------------------
    def _paths_page(self) -> Gtk.Widget:
        page = self._group_pages.get("__paths__")
        if page is not None:
            return page
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_propagate_natural_height(False)
        scroller.set_min_content_height(420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_end(4)
        box.set_margin_bottom(18)
        box.append(widgets.section_header("路径与诊断", "配置、数据目录与已保存的密钥 ID"))
        paths = self._data.get("paths") or {}
        path_card = widgets.card(spacing=4)
        for key, value in paths.items():
            path_card.append(widgets.property_row(str(key), str(value), wrap=True))
        box.append(path_card)
        secrets = self._data.get("secrets_index") or []
        secret_card = widgets.card(spacing=4)
        secret_card.append(widgets.label("已保存的密钥 ID", css="section-title"))
        if secrets:
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(8)
            flow.set_column_spacing(6)
            flow.set_row_spacing(6)
            for key_id in secrets:
                flow.append(widgets.badge(str(key_id)))
            secret_card.append(flow)
        else:
            secret_card.append(widgets.muted("还没有保存密钥。"))
        box.append(secret_card)
        controls = widgets.card(spacing=8)
        controls.append(widgets.label("运行时操作", css="section-title"))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, path in (
            ("启动 Runtime", "/api/system/start"),
            ("停止 Runtime", "/api/system/stop"),
            ("重启 Runtime", "/api/system/restart"),
        ):
            btn = widgets.button(label)
            btn.connect(
                "clicked",
                lambda _b, endpoint=path, name=label: self._runtime_action(endpoint, name),
            )
            row.append(btn)
        controls.append(row)
        box.append(controls)
        scroller.set_child(box)
        self._group_pages["__paths__"] = scroller
        return scroller

    def _runtime_action(self, path: str, label: str) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post(path, {}, timeout=120)

        widgets.run_async(
            _do,
            on_success=lambda _r: self.toast(f"{label}完成"),
            on_error=lambda exc: self.toast(f"{label}失败：{exc}"),
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def select_group(self, key: str) -> None:
        if not self._groups:
            self._pending_section = key
            return
        row = self._row_for_group(key)
        if row is None:
            self._pending_section = key
            GLib.idle_add(self._apply_pending_selection)
            return
        self.group_list.select_row(row)
        selected = self.group_list.get_selected_row()
        if selected is not row:
            self._pending_section = key
            GLib.idle_add(self._apply_pending_selection)


def _bounded(field: dict[str, Any]) -> bool:
    return field.get("min") is not None and field.get("max") is not None


def _parse_scalar(kind: str, raw: str) -> tuple[Any, str]:
    if kind in {"int", "int_or_none"}:
        if raw == "" and kind == "int_or_none":
            return None, ""
        try:
            value = int(raw)
        except ValueError:
            raise ValueError("需要整数") from None
        return value, str(value)
    if kind == "float":
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("需要数字") from None
        return value, str(value)
    if kind == "list_int":
        parts = _split_list(raw)
        try:
            values = [int(item) for item in parts]
        except ValueError:
            raise ValueError("需要逗号分隔的整数") from None
        return values, ", ".join(str(item) for item in values)
    return raw, raw


def _parse_list_str(text: str) -> list[str]:
    return _split_list(text)


def _split_list(text: str) -> list[str]:
    import re

    return [
        item.strip()
        for item in re.split(r"[\n,，]+", str(text or ""))
        if item.strip()
    ]


def _restore_switch(switch: Gtk.Switch, value: bool) -> None:
    if bool(switch.get_active()) != bool(value):
        switch.set_active(bool(value))


def _select_dropdown(dropdown: Gtk.DropDown, value: str) -> None:
    values = getattr(dropdown, "_values", [])
    if value in values:
        dropdown.set_selected(values.index(value))


def _hotkey_commit(keyval: int, state: Any, commit: Any) -> bool:
    if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.CONTROL_MASK:
        commit()
        return True
    return False
