"""Special settings panels that mirror the WebUI's dedicated controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from ..api import q  # noqa: E402


def _spec_map(group: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(spec.get("path") or ""): spec
        for spec in group.get("fields") or []
        if spec.get("path")
    }


def _value(spec: dict[str, Any], default: Any = None) -> Any:
    return spec.get("value", spec.get("default", default))


def _options(spec: dict[str, Any]) -> list[tuple[str, str]]:
    return [(str(value), str(label)) for value, label in (spec.get("options") or [])]


def _field_block(label_text: str, control: Gtk.Widget, help_text: str = "") -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(widgets.label(label_text, css="field-label"))
    if help_text:
        box.append(widgets.muted(help_text))
    box.append(control)
    return box


def _labeled_switch(text: str, active: bool) -> tuple[Gtk.Box, Gtk.Switch]:
    switch = widgets.switch(active)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.append(switch)
    row.append(widgets.label(text))
    return row, switch


def _spin(spec: dict[str, Any], low: int, high: int) -> Gtk.SpinButton:
    control = Gtk.SpinButton.new_with_range(low, high, 1)
    control.set_numeric(True)
    control.set_halign(Gtk.Align.START)
    try:
        control.set_value(int(_value(spec, low) or low))
    except (TypeError, ValueError):
        control.set_value(low)
    return control


def _card(title: str, description: str, *children: Gtk.Widget | None) -> Gtk.Box:
    card = widgets.card(spacing=9, padding=14)
    card.append(widgets.section_header(title, description))
    for child in children:
        if child is not None:
            card.append(child)
    return card


def _provider_preset(
    provider: dict[str, Any], presets: list[dict[str, Any]]
) -> dict[str, Any] | None:
    preset_id = str(provider.get("preset") or "").lower()
    return next((item for item in presets if str(item.get("id")) == preset_id), None)


def _model_candidates(
    presets: list[dict[str, Any]],
    provider: dict[str, Any] | None,
    capability: str | None = None,
) -> list[tuple[str, str]]:
    preset_id = ""
    if provider:
        preset_id = str(provider.get("preset") or "").lower()
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for preset in presets:
        if preset_id and str(preset.get("id") or "").lower() != preset_id:
            continue
        for model in preset.get("models") or []:
            caps = model.get("capabilities") or []
            if capability and capability not in caps:
                continue
            model_id = str(model.get("id") or "")
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            result.append((model_id, str(model.get("display_name") or model_id)))
    return result


class _ModelSuggestMenu(Gtk.MenuButton):
    def __init__(self, entry: Gtk.Entry) -> None:
        super().__init__(icon_name="view-list-symbolic")
        self.entry = entry
        self.set_tooltip_text("从预设模型中选择")
        self.add_css_class("flat")
        self.set_valign(Gtk.Align.CENTER)
        self._popover = Gtk.Popover()
        self._scroller = Gtk.ScrolledWindow()
        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.connect("row-activated", self._picked)
        self._scroller.set_child(self._listbox)
        self._popover.set_child(self._scroller)
        self.set_popover(self._popover)
        self.set_visible(False)

    def set_candidates(self, candidates: list[tuple[str, str]]) -> None:
        child = self._listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._listbox.remove(child)
            child = nxt
        for model_id, label in candidates:
            row = Gtk.ListBoxRow()
            row.model_value = model_id  # type: ignore[attr-defined]
            row.set_child(widgets.label(f"{label}  ·  {model_id}", wrap=False))
            self._listbox.append(row)
        self._scroller.set_size_request(320, min(320, max(80, 34 * len(candidates))))
        self.set_visible(bool(candidates))

    def _picked(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self.entry.set_text(str(getattr(row, "model_value", "")))
        self._popover.popdown()


def _chat_model_hint(page: Any) -> tuple[str, bool, bool]:
    """Return (label, supports_vision, supports_video) for the chat model."""
    providers = page._providers
    presets = page._presets
    chat = (page._agents or {}).get("chat") or {}
    if not chat:
        return "", False, False
    provider_id = str(chat.get("provider") or "")
    model_id = str(chat.get("model") or "")
    provider = next((item for item in providers if item.get("id") == provider_id), None)
    preset = _provider_preset(provider, presets) if provider else None
    label = f"{provider_id} / {model_id}" if provider_id or model_id else ""
    if preset is None:
        return label, False, False
    model = next(
        (item for item in (preset.get("models") or []) if item.get("id") == model_id),
        None,
    )
    caps = set(model.get("capabilities") or []) if model else set()
    return label, "vision" in caps, "video" in caps


class VisionSettingsPanel(Gtk.Box):
    def __init__(self, page: Any, group: dict[str, Any]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.page = page
        self.specs = _spec_map(group)
        self._build()

    def _build(self) -> None:
        specs = self.specs
        native = specs.get("features.vision.main_model_images")
        enabled_spec = specs.get("features.vision.enabled")
        if native is None or enabled_spec is None:
            self.append(widgets.muted("视觉设置字段不完整，无法渲染专用面板。"))
            return

        label, supports_vision, supports_video = _chat_model_hint(self.page)
        native_hint = widgets.muted("")
        native_select = widgets.dropdown(_options(native), str(_value(native, "auto")))
        native_select.connect(
            "notify::selected",
            lambda w, *_args: self._save_immediate(
                native, widgets.dropdown_value(w), native_hint, label, supports_vision, supports_video
            ),
        )

        def refresh_native_hint(*_args: Any) -> None:
            mode = widgets.dropdown_value(native_select)
            if mode == "off":
                text = "不向主模型附图；独立视觉仍可按需使用。"
            elif mode == "on":
                text = "明确声明主模型可接收图片；仍需协议支持图片转换，否则不会附图。"
            elif not label:
                text = "还没有配置聊天模型，auto 无法判断视觉能力。"
            elif supports_vision:
                text = f"当前聊天模型 {label} 在预设中标记了 vision，auto 会附图。"
            else:
                text = (
                    f"当前聊天模型 {label} 未被预设标记为 vision，auto 不会附图；"
                    "可以改成“开启”，或使用下方独立视觉。"
                )
            native_hint.set_text(text)

        native_select.connect("notify::selected", lambda *_: refresh_native_hint())
        refresh_native_hint()
        self.append(
            _card(
                "主模型原生图片输入",
                "让聊天模型直接接收用户图片；这条路径不需要独立视觉 provider。",
                _field_block(
                    "图片输入策略",
                    native_select,
                    "auto：仅预设标记 vision 的聊天模型；on：显式开启；off：不向主模型附图。",
                ),
                native_hint,
                self._immediate_spec_control("features.vision.image_token_reserve", 1, 1_000_000),
                self._immediate_spec_control(
                    "features.vision.image_limits.max_images_per_request", 1, 100
                ),
                self._immediate_spec_control("features.vision.gif_mode", options=True),
            )
        )

        video = specs.get("features.vision.main_model_videos")
        if video is not None:
            video_hint = widgets.muted("")
            video_select = widgets.dropdown(_options(video), str(_value(video, "auto")))

            def refresh_video_hint(*_args: Any) -> None:
                mode = widgets.dropdown_value(video_select)
                if mode == "off":
                    text = "不向主模型发送视频；仍会保留“未发送”占位。"
                elif mode == "on":
                    text = "明确声明主模型可接收完整 video_url；协议不支持时不会发送。"
                elif not label:
                    text = "还没有配置聊天模型，auto 无法判断视频能力。"
                elif supports_video:
                    text = f"当前聊天模型 {label} 在预设中标记了 video，auto 会发送完整视频。"
                else:
                    text = (
                        f"当前聊天模型 {label} 未被预设标记为 video，auto 不会发送；"
                        "可改成“开启”或换用支持视频的模型。"
                    )
                video_hint.set_text(text)

            video_select.connect(
                "notify::selected",
                lambda w, *_args: self._save_immediate(
                    video,
                    widgets.dropdown_value(w),
                    video_hint,
                    label,
                    supports_vision,
                    supports_video,
                ),
            )
            video_select.connect("notify::selected", lambda *_: refresh_video_hint())
            refresh_video_hint()
            self.append(
                _card(
                    "主模型原生视频输入",
                    "把完整视频作为 video_url 发给聊天模型；不支持时只保留占位，不抽帧。",
                    _field_block("视频输入策略", video_select),
                    video_hint,
                    self._immediate_spec_control("features.vision.video_token_reserve", 1, 1_000_000),
                    self._immediate_spec_control(
                        "features.vision.video_limits.max_videos_per_request", 1, 20
                    ),
                )
            )

        self.append(self._independent_card())
    def _immediate_spec_control(
        self, path: str, low: int = 0, high: int = 0, *, options: bool = False
    ) -> Gtk.Widget | None:
        spec = self.specs.get(path)
        if spec is None:
            return None
        label = str(spec.get("label") or path)
        help_text = str(spec.get("help") or "")
        if options:
            control = widgets.dropdown(_options(spec), str(_value(spec, "")))
            control.connect(
                "notify::selected",
                lambda w, _pspec, s=spec: self.page._save(
                    s, widgets.dropdown_value(w)
                ),
            )
        else:
            control = _spin(spec, low, high)
            last = [int(control.get_value())]

            def _changed(w: Gtk.SpinButton, s=spec, state=last) -> None:
                value = int(w.get_value())
                if value == state[0]:
                    return
                self.page._save(
                    s,
                    value,
                    on_success=lambda _r, v=value, st=state: st.__setitem__(0, v),
                    on_error=lambda _e, spin=w, old=state[0]: spin.set_value(old),
                )

            control.connect("value-changed", _changed)
        return _field_block(label, control, help_text)

    def _save_immediate(
        self,
        spec: dict[str, Any],
        value: Any,
        hint: Gtk.Label,
        label: str,
        supports_vision: bool,
        supports_video: bool,
    ) -> None:
        self.page._save(spec, value)
        if str(spec.get("path", "")).endswith("main_model_images"):
            _set_native_hint(hint, value, label, supports_vision)
        else:
            _set_video_hint(hint, value, label, supports_video)

    def _independent_card(self) -> Gtk.Box:
        specs = self.specs
        enabled_spec = specs.get("features.vision.enabled")
        if enabled_spec is None:
            return _card("独立视觉识别（可选）", "", widgets.muted("字段缺失"))
        providers, presets, provider_error = self.page.provider_payload()
        current_provider = str(_value(specs.get("features.vision.provider"), "") or "")
        model_spec = specs.get("features.vision.model") or {}
        base_spec = specs.get("features.vision.base_url") or {}
        key_spec = specs.get("features.vision.api_key_id") or {}
        key_state = {"id": str(_value(key_spec, "") or "")}

        enabled_row, enabled_switch = _labeled_switch(
            "启用独立视觉识别（describe_image）", bool(_value(enabled_spec, False))
        )
        enabled_switch.set_active(bool(_value(enabled_spec, False)))
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        provider_options = [("", "自定义 OpenAI 兼容端点")]
        for provider in providers:
            preset = _provider_preset(provider, presets)
            label = f"{provider.get('display_name') or provider.get('id')} ({provider.get('id')})"
            if preset:
                label += f" · 预设 {preset.get('display_name') or preset.get('id')}"
            provider_options.append((str(provider.get("id")), label))
        if current_provider and not any(value == current_provider for value, _ in provider_options):
            provider_options.append(
                (current_provider, f"当前配置：{current_provider}（不在 provider 列表）")
            )
        provider_select = widgets.dropdown(provider_options, current_provider)
        provider_select.set_hexpand(True)

        model_entry = Gtk.Entry()
        model_entry.set_text(str(_value(model_spec, "") or ""))
        model_entry.set_placeholder_text("例如 glm-4v / qwen-vl-max")
        current_provider_data = next(
            (item for item in providers if str(item.get("id")) == current_provider), None
        )
        suggestion = _ModelSuggestMenu(model_entry)
        suggestion.set_candidates(
            _model_candidates(presets, current_provider_data, "vision")
        )
        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_row.append(model_entry)
        model_row.append(suggestion)

        override_row, override_switch = _labeled_switch(
            "覆盖该 provider 的地址/密钥（高级）", False
        )
        base_entry = Gtk.Entry()
        base_entry.set_text(str(_value(base_spec, "") or ""))
        base_entry.set_placeholder_text("https://api.example.com/v1")
        base_row = _field_block(
            "视觉独立 base_url",
            base_entry,
            "自定义端点必填；选择已有 provider 时留空即可复用其地址。",
        )
        key_entry = Gtk.Entry()
        key_entry.set_visibility(False)
        key_entry.set_placeholder_text(
            f"已配置 {key_state['id']}（留空不修改）" if key_state["id"] else "未设置"
        )
        key_row = _field_block(
            "视觉独立 API Key",
            key_entry,
            "自定义端点必填；选择已有 provider 时留空即可复用其密钥。",
        )
        warning = widgets.muted(provider_error)
        warning.set_visible(bool(provider_error))
        custom_note = widgets.muted("")
        save_status = widgets.muted("")
        save_button = widgets.button("保存视觉设置", css="suggested-action")
        save_button.set_halign(Gtk.Align.END)
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_row.append(widgets.muted(""))
        action_row.get_first_child().set_hexpand(True)
        action_row.append(save_button)

        def sync_visibility(*_args: Any) -> None:
            details.set_visible(bool(enabled_switch.get_active()))
            is_custom = not widgets.dropdown_value(provider_select)
            show_override = is_custom or override_switch.get_active()
            override_row.set_visible(not is_custom)
            base_row.set_visible(show_override)
            key_row.set_visible(show_override)
            if is_custom:
                custom_note.set_text(
                    "未选择已有 provider：需要填写 base_url 和 API Key，按 OpenAI 兼容协议连接。"
                )
            else:
                custom_note.set_text(
                    "复用该 provider 的协议、地址与密钥；只有视觉端点不同时才勾选“覆盖”。"
                )
            if not providers:
                warning.set_text(
                    "还没有添加 provider。可以到「模型与提供商」添加，或使用自定义端点。"
                )
                warning.set_visible(True)

        def provider_changed(*_args: Any) -> None:
            override_switch.set_active(False)
            base_entry.set_text("")
            key_entry.set_text("")
            provider_id = widgets.dropdown_value(provider_select)
            provider_data = next(
                (item for item in providers if str(item.get("id")) == provider_id), None
            )
            suggestion.set_candidates(
                _model_candidates(presets, provider_data, "vision")
            )
            sync_visibility()

        provider_select.connect("notify::selected", provider_changed)
        override_switch.connect("notify::active", sync_visibility)
        enabled_switch.connect("notify::active", sync_visibility)
        save_button.connect("clicked", lambda _b: save())

        def save() -> None:
            want_enabled = bool(enabled_switch.get_active())
            provider_value = widgets.dropdown_value(provider_select).strip()
            model_value = model_entry.get_text().strip()
            is_custom = not provider_value
            use_override = is_custom or bool(override_switch.get_active())
            base_value = base_entry.get_text().strip() if use_override else ""
            key_value = key_entry.get_text().strip() if use_override else ""
            if want_enabled:
                if not model_value:
                    save_status.set_text("请填写视觉模型 ID。")
                    return
                if is_custom and not base_value:
                    save_status.set_text("自定义视觉端点需要填写 base_url。")
                    return
                if is_custom and not key_value and not key_state["id"]:
                    save_status.set_text("自定义视觉端点需要填写 API Key。")
                    return
            payload: dict[str, Any] = {"enabled": want_enabled}
            if want_enabled:
                payload.update(
                    {
                        "provider": provider_value,
                        "model": model_value,
                        "base_url": base_value,
                        "api_key_id": key_state["id"] if use_override else "",
                    }
                )
                if key_value:
                    payload["api_key"] = key_value
            save_button.set_sensitive(False)
            save_status.set_text("正在保存…")

            def _do() -> dict[str, Any]:
                return self.page.api.patch("/api/settings/vision", payload, timeout=60)

            def _done(result: dict[str, Any]) -> None:
                saved = result.get("value") or {}
                self.page.update_spec_value("features.vision.enabled", bool(saved.get("enabled")))
                self.page.update_spec_value(
                    "features.vision.provider", saved.get("provider") or ""
                )
                self.page.update_spec_value("features.vision.model", saved.get("model") or "")
                self.page.update_spec_value(
                    "features.vision.base_url", saved.get("base_url") or ""
                )
                self.page.update_spec_value(
                    "features.vision.api_key_id", saved.get("api_key_id") or ""
                )
                if result.get("api_key_saved"):
                    key_entry.set_text("")
                key_id = str(saved.get("api_key_id") or "")
                key_state["id"] = key_id
                key_entry.set_placeholder_text(
                    f"已配置 {key_id}（留空不修改）" if key_id else "未设置"
                )
                if result.get("needs_restart"):
                    save_status.set_text(
                        str(
                            result.get("message")
                            or "视觉设置已保存；需要重启 Runtime 后生效"
                        )
                    )
                    self.page.mark_restart()
                else:
                    save_status.set_text(
                        str(result.get("message") or "视觉设置已保存并立即生效")
                    )
                self.page.toast(str(result.get("message") or "视觉设置已保存"))
                save_button.set_sensitive(True)

            def _failed(exc: BaseException) -> None:
                save_status.set_text(f"保存失败：{exc}")
                save_button.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        details.append(warning)
        details.append(custom_note)
        details.append(_field_block("视觉 provider", provider_select))
        details.append(_field_block("视觉模型", model_row))
        details.append(override_row)
        details.append(base_row)
        details.append(key_row)
        sync_visibility()
        card = _card(
            "独立视觉识别（可选）",
            "主模型不能看图，或想把看图交给另一个模型时使用；开启后只提供 describe_image 工具。",
            enabled_row,
            details,
            action_row,
            save_status,
        )
        return card

class SearchSettingsPanel(Gtk.Box):
    def __init__(self, page: Any, group: dict[str, Any]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.page = page
        self.specs = _spec_map(group)
        self._build()

    def _build(self) -> None:
        specs = self.specs
        if "features.web_search.enabled" not in specs:
            self.append(widgets.muted("联网搜索设置字段不完整。"))
            return
        providers, presets, provider_error = self.page.provider_payload()
        master_row, master_switch = _labeled_switch(
            "启用联网搜索 web_search",
            bool(_value(specs["features.web_search.enabled"], True)),
        )
        free_row, free_switch = _labeled_switch(
            "启用免费搜索（优先）",
            bool(_value(specs["features.web_search.free_enabled"], True)),
        )
        official_row, official_switch = _labeled_switch(
            "启用官方搜索（仅在免费搜索不可用时回退）",
            bool(_value(specs.get("features.web_search.official.enabled"), False)),
        )
        engine_spec = specs.get("features.web_search.provider") or {}
        engine_select = widgets.dropdown(
            _options(engine_spec), str(_value(engine_spec, "bing_rss"))
        )
        searxng_spec = specs.get("features.web_search.searxng_base_url") or {}
        searxng_entry = Gtk.Entry()
        searxng_entry.set_text(str(_value(searxng_spec, "") or ""))
        searxng_entry.set_placeholder_text("https://searx.example.com")
        searxng_row = _field_block("SearXNG 地址", searxng_entry)
        max_spec = specs.get("features.web_search.max_results") or {}
        timeout_spec = specs.get("features.web_search.timeout_seconds") or {}
        max_spin = _spin(max_spec, 1, 20)
        timeout_spin = _spin(timeout_spec, 1, 60)
        official_timeout_spec = specs.get("features.web_search.official.timeout_seconds") or {}
        official_timeout_spin = _spin(official_timeout_spec, 5, 180)
        probe_status = widgets.muted("")
        probe_button = widgets.button("测速免费搜索")
        free_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        free_details.append(_field_block("免费搜索后端", engine_select))
        free_details.append(searxng_row)
        free_details.append(_field_block("最多结果数", max_spin, "1–20，建议 5。"))
        free_details.append(
            _field_block("免费搜索超时（秒）", timeout_spin, "测速和单次请求都会受此限制。")
        )
        free_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        free_actions.append(probe_button)
        free_details.append(free_actions)
        free_details.append(probe_status)
        free_details.append(
            widgets.muted(
                "Bing RSS 受 Microsoft 的 RSS 个人非商业使用条款约束；"
                "商业部署建议自建 SearXNG、使用官方搜索 API 或取得授权。"
            )
        )

        official_options: list[tuple[str, str]] = [("", "未选择官方搜索通道")]
        current_provider = str(_value(specs.get("features.web_search.official.provider"), "") or "")
        current_model = str(_value(specs.get("features.web_search.official.model"), "") or "")
        current_channel = f"{current_provider}::{current_model}" if current_provider else ""
        known_channels: set[str] = set()
        for provider in providers:
            preset = _provider_preset(provider, presets)
            if not preset:
                continue
            pname = str(provider.get("display_name") or provider.get("id"))
            if preset.get("search_channel"):
                value = f"{provider.get('id')}::"
                known_channels.add(value)
                official_options.append(
                    (
                        value,
                        f"{pname} · {preset.get('search_label') or '官方搜索'}（provider 级）",
                    )
                )
            for model in preset.get("models") or []:
                if not model.get("search_channel"):
                    continue
                if "web_search" not in (model.get("capabilities") or []):
                    continue
                value = f"{provider.get('id')}::{model.get('id')}"
                known_channels.add(value)
                official_options.append(
                    (
                        value,
                        f"{pname} / {model.get('display_name') or model.get('id')}",
                    )
                )
        if current_channel and current_channel not in known_channels:
            official_options.append(
                (current_channel, f"当前配置：{current_channel}（不在预设搜索列表）")
            )
        channel_select = widgets.dropdown(official_options, current_channel)
        official_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        official_details.append(
            _field_block(
                "官方搜索通道",
                channel_select,
                "只列出预设中已确认存在官方搜索 API 的 provider / 模型。",
            )
        )
        official_details.append(
            _field_block("官方搜索超时（秒）", official_timeout_spin)
        )
        if provider_error:
            official_details.append(widgets.muted(f"读取 provider/预设失败：{provider_error}"))
        elif not known_channels:
            official_details.append(
                widgets.muted("当前已添加的 provider 没有已确认的官方搜索通道。")
            )
        official_details.append(
            widgets.muted(
                "官方搜索会调用模型或搜索 API，可能产生额外费用；"
                "两者都开时免费搜索优先，只有免费通道失败才回退到官方。"
            )
        )

        save_status = widgets.muted("")
        save_button = widgets.button("保存搜索设置", css="suggested-action")
        save_button.set_halign(Gtk.Align.END)

        def sync_visibility(*_args: Any) -> None:
            enabled = bool(master_switch.get_active())
            free_switch.set_sensitive(enabled)
            official_switch.set_sensitive(enabled)
            free_details.set_visible(enabled and bool(free_switch.get_active()))
            official_details.set_visible(enabled and bool(official_switch.get_active()))
            searxng_row.set_visible(widgets.dropdown_value(engine_select) == "searxng")
            probe_button.set_sensitive(bool(free_switch.get_active()) and enabled)

        engine_select.connect("notify::selected", sync_visibility)
        free_switch.connect("notify::active", sync_visibility)
        official_switch.connect("notify::active", sync_visibility)
        master_switch.connect("notify::active", sync_visibility)
        sync_visibility()

        probe_button.connect("clicked", lambda _b: probe())
        save_button.connect("clicked", lambda _b: save())

        def probe() -> None:
            provider = widgets.dropdown_value(engine_select)
            searxng = searxng_entry.get_text().strip()
            if provider == "searxng" and not searxng:
                probe_status.set_text("请先填写 SearXNG 地址。")
                return
            probe_button.set_sensitive(False)
            probe_status.set_text("测速中…")

            def _do() -> dict[str, Any]:
                return self.page.api.post(
                    "/api/settings/web-search/probe",
                    {
                        "provider": provider,
                        "searxng_base_url": searxng,
                        "timeout_seconds": float(timeout_spin.get_value()) or 10.0,
                    },
                    timeout=30,
                )

            def _done(result: dict[str, Any]) -> None:
                if result.get("ok"):
                    probe_status.set_text(
                        f"可用：{result.get('latency_ms', 0)} ms（{result.get('engine') or provider}）"
                    )
                else:
                    error = result.get("error") or result.get("error_code") or "未知错误"
                    probe_status.set_text(
                        f"不可用：{error}（{result.get('latency_ms', 0)} ms）"
                    )
                probe_button.set_sensitive(True)

            def _failed(exc: BaseException) -> None:
                probe_status.set_text(f"测速失败：{exc}")
                probe_button.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        def save() -> None:
            enabled = bool(master_switch.get_active())
            free_enabled = bool(free_switch.get_active())
            official_enabled = bool(official_switch.get_active())
            provider = widgets.dropdown_value(engine_select)
            searxng = searxng_entry.get_text().strip()
            if enabled and not free_enabled and not official_enabled:
                save_status.set_text("至少开启免费搜索或官方搜索。")
                return
            if enabled and free_enabled and provider == "searxng" and not searxng:
                save_status.set_text("选择 SearXNG 时需要填写实例地址。")
                return
            channel = widgets.dropdown_value(channel_select)
            if enabled and official_enabled and not channel:
                save_status.set_text("开启官方搜索前请选择一个官方搜索通道。")
                return
            official_provider, official_model = (
                (channel.split("::", 1) + [""])[:2] if channel else ("", "")
            )
            payload = {
                "enabled": enabled,
                "free_enabled": free_enabled,
                "provider": provider,
                "searxng_base_url": searxng,
                "max_results": int(max_spin.get_value()) or 5,
                "timeout_seconds": float(timeout_spin.get_value()) or 10.0,
                "official_enabled": official_enabled,
                "official_provider": official_provider,
                "official_model": official_model,
                "official_timeout_seconds": float(official_timeout_spin.get_value()) or 45.0,
            }
            save_button.set_sensitive(False)
            save_status.set_text("正在保存…")

            def _do() -> dict[str, Any]:
                return self.page.api.patch("/api/settings/web-search", payload, timeout=60)

            def _done(result: dict[str, Any]) -> None:
                saved = result.get("value") or {}
                self.page.update_spec_value("features.web_search.enabled", saved.get("enabled"))
                self.page.update_spec_value(
                    "features.web_search.free_enabled", saved.get("free_enabled")
                )
                self.page.update_spec_value(
                    "features.web_search.provider", saved.get("provider")
                )
                self.page.update_spec_value(
                    "features.web_search.searxng_base_url",
                    saved.get("searxng_base_url") or "",
                )
                self.page.update_spec_value(
                    "features.web_search.max_results", saved.get("max_results")
                )
                self.page.update_spec_value(
                    "features.web_search.timeout_seconds", saved.get("timeout_seconds")
                )
                self.page.update_spec_value(
                    "features.web_search.official.enabled", saved.get("official_enabled")
                )
                self.page.update_spec_value(
                    "features.web_search.official.provider",
                    saved.get("official_provider") or "",
                )
                self.page.update_spec_value(
                    "features.web_search.official.model", saved.get("official_model") or ""
                )
                self.page.update_spec_value(
                    "features.web_search.official.timeout_seconds",
                    saved.get("official_timeout_seconds"),
                )
                if result.get("needs_restart"):
                    save_status.set_text(
                        str(
                            result.get("message")
                            or "搜索设置已保存；需要重启 Runtime 后生效"
                        )
                    )
                    self.page.mark_restart()
                else:
                    save_status.set_text(
                        str(result.get("message") or "搜索设置已保存并立即生效")
                    )
                self.page.toast(str(result.get("message") or "搜索设置已保存"))
                save_button.set_sensitive(True)

            def _failed(exc: BaseException) -> None:
                save_status.set_text(f"保存失败：{exc}")
                save_button.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        self.append(
            _card(
                "联网搜索",
                "免费搜索优先；官方搜索只在免费通道失败时回退，且需要显式开启。",
                master_row,
                free_row,
                free_details,
            )
        )
        self.append(
            _card(
                "官方搜索（可选）",
                "调用模型或搜索服务的官方 API，可能产生额外费用。",
                official_row,
                official_details,
                save_button,
                save_status,
            )
        )


class BackupSettingsPanel(Gtk.Box):
    def __init__(self, page: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.page = page
        self._active_job = ""
        self._poll_source = 0
        self._bump = 0
        self._build()
        self.connect("notify::mapped", self._on_mapped)

    def _build(self) -> None:
        self.status_card = _card(
            "备份状态",
            "备份包含配置、加密密钥库、聊天、RAG、工作区与人格；文件未加密。",
        )
        self.summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.status_card.append(self.summary_box)
        warning = widgets.label(
            "安全提示：备份 ZIP 可能包含 RSA 私钥与加密密钥库，请保存在可信位置，"
            "不要上传或公开分享。",
            css="danger-text",
            wrap=True,
        )
        self.status_card.append(warning)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.start_button = widgets.button("创建备份", css="suggested-action")
        self.start_button.connect("clicked", lambda _b: self._start())
        self.cancel_button = widgets.button("取消当前备份", css="destructive-action")
        self.cancel_button.set_visible(False)
        self.cancel_button.connect("clicked", lambda _b: self._cancel())
        refresh = widgets.button("刷新")
        refresh.connect("clicked", lambda _b: self.refresh())
        actions.append(self.start_button)
        actions.append(self.cancel_button)
        actions.append(refresh)
        self.status_card.append(actions)
        self.status_label = widgets.muted("正在读取备份状态…")
        self.status_card.append(self.status_label)
        self.append(self.status_card)

        self.append(widgets.section_header("备份任务", "最近 10 个任务；运行中的任务可取消"))
        self.jobs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.jobs_box)

        self.append(widgets.section_header("备份文件", "可离线校验或下载到本机"))
        self.files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.files_box)

    def _on_mapped(self, *_args: Any) -> None:
        if self.get_mapped():
            self.refresh()

    def on_show(self) -> None:
        if self.get_mapped():
            self.refresh()

    def refresh(self) -> None:
        if self.page.api is None:
            return
        self._bump += 1
        token = self._bump

        def _do() -> dict[str, Any]:
            return self.page.api.get("/api/backup/status", timeout=60)

        def _done(data: dict[str, Any]) -> None:
            if token != self._bump:
                return
            self._render(data)

        def _failed(exc: BaseException) -> None:
            self.status_label.set_text(f"读取备份状态失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _render(self, data: dict[str, Any]) -> None:
        widgets.clear(self.summary_box)
        directory = str(data.get("directory") or "—")
        self.summary_box.append(widgets.property_row("备份目录", directory, wrap=True))
        self.summary_box.append(
            widgets.property_row(
                "包含入站媒体",
                "是" if data.get("include_media") else "否",
            )
        )
        files = data.get("files") or []
        if files:
            newest = files[0]
            self.summary_box.append(
                widgets.property_row(
                    "最近备份",
                    f"{newest.get('filename')} ({widgets.format_bytes(newest.get('size'))})",
                    wrap=True,
                )
            )
        else:
            self.summary_box.append(widgets.property_row("最近备份", "还没有备份"))
        running = bool(data.get("running"))
        self._active_job = str(data.get("active_job_id") or "")
        self.start_button.set_sensitive(not running)
        self.cancel_button.set_visible(running)
        if running:
            self.status_label.set_text("备份进行中…")
            self._schedule_poll()
        else:
            self._stop_poll()
            jobs = data.get("jobs") or []
            if jobs:
                latest = jobs[0]
                state = str(latest.get("state") or "")
                if state in {"done", "completed", "success"}:
                    self.status_label.set_text(
                        f"最近任务完成：{widgets.format_bytes(latest.get('processed_bytes'))}"
                    )
                elif state:
                    self.status_label.set_text(f"最近任务：{state}")
                else:
                    self.status_label.set_text("目前没有运行中的备份。")
            else:
                self.status_label.set_text("目前没有运行中的备份。")
        self._render_jobs(data.get("jobs") or [])
        self._render_files(files)

    def _render_jobs(self, jobs: list[dict[str, Any]]) -> None:
        widgets.clear(self.jobs_box)
        if not jobs:
            self.jobs_box.append(self.page.empty("还没有备份任务。"))
            return
        for job in jobs[:10]:
            card = widgets.card(spacing=5, padding=10)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            state = str(job.get("state") or "unknown")
            head.append(widgets.label(str(job.get("id") or "")[:12], css="monospace"))
            head.append(_state_badge(state))
            stage = str(job.get("stage") or "")
            if stage:
                head.append(widgets.muted(stage))
            head.set_hexpand(True)
            card.append(head)
            total = int(job.get("total_bytes") or 0)
            processed = int(job.get("processed_bytes") or 0)
            if total > 0 and state not in {"done", "completed", "failed", "cancelled"}:
                progress = Gtk.ProgressBar()
                progress.set_fraction(min(1.0, processed / total))
                progress.set_show_text(False)
                card.append(progress)
            card.append(
                widgets.muted(
                    f"{widgets.format_bytes(processed)} / {widgets.format_bytes(total)}"
                    + (f" · {job.get('current')}" if job.get("current") else "")
                )
            )
            error = job.get("error")
            if isinstance(error, dict) and error.get("message"):
                card.append(widgets.label(str(error["message"]), css="danger-text", wrap=True))
            for warning in job.get("warnings") or []:
                card.append(widgets.muted(f"警告：{warning}"))
            started = widgets.format_timestamp(job.get("started_at"))
            finished = widgets.format_timestamp(job.get("finished_at"))
            stamps = " · ".join(x for x in (started, finished) if x)
            if stamps:
                card.append(widgets.muted(stamps))
            self.jobs_box.append(card)

    def _render_files(self, files: list[dict[str, Any]]) -> None:
        widgets.clear(self.files_box)
        if not files:
            self.files_box.append(self.page.empty("备份目录里还没有文件。"))
            return
        for item in files[:20]:
            filename = str(item.get("filename") or "")
            card = widgets.card(spacing=4, padding=10)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(filename, css="section-title", ellipsize=True))
            head.set_hexpand(True)
            if item.get("includes_keys"):
                head.append(widgets.badge("含密钥", css="badge badge-red"))
            if item.get("partial"):
                head.append(widgets.badge("不完整", css="badge badge-orange"))
            card.append(head)
            meta = [
                widgets.format_bytes(item.get("size")),
                widgets.format_timestamp(item.get("created_at")),
            ]
            file_count = item.get("file_count")
            if file_count:
                meta.append(f"{file_count} 个文件")
            card.append(widgets.muted(" · ".join(str(x) for x in meta if x)))
            if item.get("warnings"):
                card.append(widgets.muted("警告：" + "；".join(map(str, item["warnings"]))))
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            verify = widgets.button("离线校验")
            verify.connect("clicked", lambda _b, name=filename: self._verify(name))
            download = widgets.button("下载")
            download.connect("clicked", lambda _b, name=filename: self._download(name))
            actions.append(verify)
            actions.append(download)
            card.append(actions)
            self.files_box.append(card)

    def _start(self) -> None:
        if self.page.api is None:
            return
        self.start_button.set_sensitive(False)
        self.status_label.set_text("正在启动备份…")

        def _do() -> dict[str, Any]:
            return self.page.api.post("/api/backup", {}, timeout=60)

        def _done(result: dict[str, Any]) -> None:
            self.page.toast(str(result.get("message") or "备份已开始"))
            self.refresh()

        def _failed(exc: BaseException) -> None:
            self.start_button.set_sensitive(True)
            self.status_label.set_text(f"备份启动失败：{exc}")
            self.page.toast(f"备份启动失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _cancel(self) -> None:
        if self.page.api is None or not self._active_job:
            return
        job_id = self._active_job

        def _do() -> dict[str, Any]:
            return self.page.api.post(f"/api/backup/jobs/{q(job_id)}/cancel", {}, timeout=60)

        def _done(_result: dict[str, Any]) -> None:
            self.status_label.set_text("已请求取消，等待当前写入边界。")
            self.refresh()

        widgets.run_async(
            _do,
            on_success=_done,
            on_error=lambda exc: self.page.toast(f"取消失败：{exc}"),
        )

    def _verify(self, filename: str) -> None:
        if self.page.api is None:
            return
        self.status_label.set_text(f"正在校验 {filename}…")

        def _do() -> dict[str, Any]:
            return self.page.api.post(
                "/api/backup/verify",
                {"filename": filename, "deep_sqlite": True},
                timeout=600,
            )

        def _done(report: dict[str, Any]) -> None:
            if report.get("ok"):
                self.status_label.set_text(
                    f"校验通过：{filename}（{report.get('member_count', 0)} 个成员）"
                )
            else:
                errors = [
                    str(item.get("message") or item.get("code") or "")
                    for item in report.get("errors") or []
                ]
                self.status_label.set_text(
                    "校验失败：" + ("；".join(x for x in errors if x) or "未知原因")
                )
            self.page.toast(self.status_label.get_text())

        def _failed(exc: BaseException) -> None:
            self.status_label.set_text(f"校验失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _download(self, filename: str) -> None:
        if self.page.api is None:
            return
        target = widgets.save_path_picker(
            self.page.app.window, title_text="保存备份", initial_name=filename
        )
        if not target:
            return
        self.status_label.set_text(f"正在下载 {filename}…")

        def _do() -> int:
            data = self.page.api.raw(f"/api/backup/files/{q(filename)}", timeout=600)
            path = Path(target)
            path.write_bytes(data)
            return len(data)

        def _done(size: int) -> None:
            self.status_label.set_text(f"已下载 {filename}（{widgets.format_bytes(size)}）")
            self.page.toast("备份已保存到本机")

        def _failed(exc: BaseException) -> None:
            self.status_label.set_text(f"下载失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _schedule_poll(self) -> None:
        if self._poll_source:
            return
        self._poll_source = GLib.timeout_add_seconds(1, self._poll)

    def _stop_poll(self) -> None:
        if self._poll_source:
            GLib.source_remove(self._poll_source)
            self._poll_source = 0

    def _poll(self) -> bool:
        self._poll_source = 0
        if not self.get_mapped():
            return False
        if self.page.api is None or not self._active_job:
            return False
        job_id = self._active_job

        def _do() -> dict[str, Any]:
            return self.page.api.get(f"/api/backup/jobs/{q(job_id)}", timeout=15)

        def _done(job: dict[str, Any]) -> None:
            state = str(job.get("state") or "")
            processed = widgets.format_bytes(job.get("processed_bytes"))
            total = widgets.format_bytes(job.get("total_bytes"))
            current = str(job.get("current") or job.get("stage") or "")
            self.status_label.set_text(f"备份中：{processed} / {total}" + (f" · {current}" if current else ""))
            if state in {"done", "completed", "success", "failed", "cancelled", "interrupted"}:
                self.refresh()
            else:
                self._schedule_poll()

        def _failed(exc: BaseException) -> None:
            self.status_label.set_text(f"备份进度读取失败：{exc}")
            self._schedule_poll()

        widgets.run_async(_do, on_success=_done, on_error=_failed)
        return False


class UpdateSettingsPanel(Gtk.Box):
    def __init__(self, page: Any, group: dict[str, Any]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.page = page
        self.specs = _spec_map(group)
        self._presets: list[dict[str, str]] = []
        self._build()
        self.connect("notify::mapped", self._on_mapped)

    def _build(self) -> None:
        self.status_label = widgets.muted("正在读取更新状态…")
        self.info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        open_versions = widgets.button(
            "打开版本与更新", icon="software-update-available-symbolic"
        )
        open_versions.connect(
            "clicked", lambda _b: self.page.app.show_page("updates")
        )
        self.info_card = _card(
            "更新状态",
            "只读版本信息；完整的版本列表与更新日志在「版本与更新」页面。",
            self.info_box,
            self.status_label,
            open_versions,
        )
        self.append(self.info_card)

        mirror_spec = self.specs.get("update.mirror") or {}
        self.mirror_spec = mirror_spec
        self.mirror_value = Gtk.Entry()
        self.mirror_value.set_text(str(_value(mirror_spec, "") or ""))
        self.mirror_value.set_placeholder_text("留空使用 GitHub 官方")
        self.mirror_value.set_hexpand(True)
        self.mirror_select = widgets.dropdown([("", "GitHub 官方（直连）")], "")
        self.mirror_select.connect("notify::selected", self._mirror_selected)
        self.probe_status = widgets.muted("")
        save = widgets.button("保存镜像设置", css="suggested-action")
        save.connect("clicked", lambda _b: self._save_mirror())
        probe = widgets.button("测速镜像")
        probe.connect("clicked", lambda _b: self._probe())
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.append(save)
        actions.append(probe)
        mirror_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mirror_row.append(self.mirror_select)
        mirror_row.append(self.mirror_value)
        self.append(
            _card(
                "GitHub 镜像 / 加速源",
                "修改只影响更新检查与拉取，不会自动更新 GUI 源码。",
                _field_block("预设", mirror_row),
                actions,
                self.probe_status,
            )
        )

    def _on_mapped(self, *_args: Any) -> None:
        if self.get_mapped():
            self.refresh()

    def on_show(self) -> None:
        if self.get_mapped():
            self.refresh()

    def refresh(self) -> None:
        if self.page.api is None:
            return
        self.status_label.set_text("正在读取更新状态…")

        def _do() -> dict[str, Any]:
            return self.page.api.get("/api/update/status", timeout=60)

        def _done(data: dict[str, Any]) -> None:
            self._presets = list(data.get("mirror_presets") or [])
            options = [
                (str(item.get("value") or ""), str(item.get("label") or item.get("value") or "官方"))
                for item in self._presets
            ]
            current = str(data.get("mirror") or "")
            if current and not any(value == current for value, _ in options):
                options.append((current, f"当前自定义镜像：{current}"))
            self.mirror_select.set_model(Gtk.StringList.new([label for _v, label in options]))
            self.mirror_select._values = [value for value, _label in options]  # type: ignore[attr-defined]
            index = next((i for i, (value, _label) in enumerate(options) if value == current), 0)
            self.mirror_select.set_selected(index)
            self.mirror_value.set_text(current)
            widgets.clear(self.info_box)
            self.info_box.append(
                widgets.property_row("版本", str(data.get("version_label") or "—"))
            )
            self.info_box.append(
                widgets.property_row(
                    "提交", str(data.get("current_commit_short") or data.get("current_commit") or "—")
                )
            )
            self.info_box.append(
                widgets.property_row("分支", str(data.get("current_branch") or "—"))
            )
            self.info_box.append(
                widgets.property_row(
                    "工作树",
                    "有未提交改动" if data.get("worktree_dirty") else "干净",
                )
            )
            effective = str(data.get("effective_remote") or "")
            if effective:
                self.info_box.append(widgets.property_row("远端", effective, wrap=True))
            if data.get("mirror_error"):
                self.info_box.append(widgets.muted(str(data["mirror_error"])))
            self.status_label.set_text("")

        def _failed(exc: BaseException) -> None:
            self.status_label.set_text(f"读取更新状态失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _mirror_selected(self, *_args: Any) -> None:
        value = widgets.dropdown_value(self.mirror_select)
        self.mirror_value.set_text(value)

    def _save_mirror(self) -> None:
        if not self.mirror_spec:
            return
        value = self.mirror_value.get_text().strip()
        self.page._save(
            self.mirror_spec,
            value,
            on_success=lambda _r: self.refresh(),
        )

    def _probe(self) -> None:
        if self.page.api is None:
            return
        self.probe_status.set_text("正在测速（GitHub 官方与预设镜像）…")
        self.mirror_value.set_text(self.mirror_value.get_text().strip())

        def _do() -> dict[str, Any]:
            return self.page.api.post("/api/update/probe", {}, timeout=120)

        def _done(data: dict[str, Any]) -> None:
            results = data.get("results") or []
            if not results:
                self.probe_status.set_text("没有可测速的镜像。")
                return
            lines = []
            for item in results:
                name = str(item.get("label") or item.get("mirror") or "官方")
                if item.get("ok"):
                    lines.append(f"{name}：{item.get('latency_ms', 0)} ms")
                else:
                    lines.append(f"{name}：失败（{item.get('error') or item.get('error_code') or '未知'}）")
            self.probe_status.set_text("\n".join(lines))

        def _failed(exc: BaseException) -> None:
            self.probe_status.set_text(f"测速失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)


class TokenBudgetSettingsPanel(Gtk.Box):
    def __init__(self, page: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.page = page
        self.snapshot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.status = widgets.muted("")
        compact = widgets.button("立即压缩活跃历史")
        compact.connect("clicked", lambda _b: self._compact())
        self.card = _card(
            "当前预算快照",
            "有效窗口 = min(工作窗口, 模型限制)；净输入预算 = 窗口 - 输出预留 - 安全余量。",
            self.snapshot,
            compact,
            self.status,
        )
        self.append(self.card)
        self.connect("notify::mapped", self._on_mapped)

    def _on_mapped(self, *_args: Any) -> None:
        if self.get_mapped():
            self.refresh()

    def on_show(self) -> None:
        if self.get_mapped():
            self.refresh()

    def refresh(self) -> None:
        if self.page.api is None:
            return
        self.status.set_text("正在读取预算…")

        def _do() -> dict[str, Any]:
            return self.page.api.get("/api/context/status", timeout=60)

        def _done(data: dict[str, Any]) -> None:
            widgets.clear(self.snapshot)
            budget = data.get("budget") or {}
            compaction = data.get("compaction") or {}
            rows = [
                ("Provider / 模型", f"{data.get('provider') or '?'} / {data.get('model') or '?'}"),
                (
                    "工作窗口 / 模型限制",
                    f"{_num(budget.get('window_requested'))} / "
                    f"{_num(budget.get('window_model')) if budget.get('window_model') else '未核实'}",
                ),
                (
                    "输出预留 / 安全余量",
                    f"{_num(budget.get('output_reserve'))} / {_num(budget.get('safety_margin'))}",
                ),
                ("净输入预算", _num(budget.get("input_budget"))),
                (
                    "soft / target / retry / urgent",
                    f"{_num(budget.get('soft_trigger'))} / {_num(budget.get('target_after'))} / "
                    f"{_num(budget.get('retry_target'))} / {_num(budget.get('urgent_trigger'))}",
                ),
                (
                    "固定开销 / 活跃历史预算",
                    f"{_num(data.get('fixed_overhead_tokens'))} / "
                    f"{_num(data.get('working_history_budget'))}",
                ),
                (
                    "压缩状态",
                    f"{compaction.get('last_action') or 'idle'}"
                    + (
                        f"（跳过：{compaction.get('last_skip_reason')}）"
                        if compaction.get("last_skip_reason")
                        else ""
                    )
                    + (
                        f" · 退避剩余 {compaction.get('backoff_seconds_remaining')}s"
                        if compaction.get("backoff_seconds_remaining")
                        else ""
                    ),
                ),
                (
                    "增长预测 / 冷却 / 最少新增",
                    f"{compaction.get('growth_ewma', '—')} / "
                    f"{_num(compaction.get('cooldown_seconds'))}s / "
                    f"{_num(compaction.get('min_new_tokens'))}",
                ),
            ]
            for name, value in rows:
                self.snapshot.append(widgets.property_row(name, value))
            errors = budget.get("errors") or []
            if errors:
                self.status.set_text("预算校验失败：" + "、".join(map(str, errors)))
            else:
                self.status.set_text("")

        def _failed(exc: BaseException) -> None:
            self.status.set_text(f"读取预算失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _compact(self) -> None:
        def _do() -> None:
            if self.page.api is None:
                return

            def _request() -> dict[str, Any]:
                return self.page.api.post("/api/context/compact", {}, timeout=300)

            widgets.run_async(
                _request,
                on_success=self._compacted,
                on_error=lambda exc: self.status.set_text(f"压缩失败：{exc}"),
            )

        widgets.ConfirmDialog(
            self.page.app.window,
            heading="立即压缩活跃历史？",
            body="原文会归档，活跃窗口起点前移。压缩会等待摘要模型完成。",
            confirm_label="压缩",
            on_confirm=_do,
        )

    def _compacted(self, payload: dict[str, Any]) -> None:
        result = payload.get("result") or {}
        if payload.get("ok"):
            self.status.set_text(
                f"压缩完成：归档 {result.get('archived_count', 0)} 条，"
                f"活跃 {result.get('active_records', 0)} 条。"
            )
        else:
            self.status.set_text(
                f"未压缩：{result.get('reason') or result.get('status') or '无可用结果'}"
            )
        self.refresh()


def _set_native_hint(hint: Gtk.Label, mode: str, label: str, supports: bool) -> None:
    if mode == "off":
        hint.set_text("不向主模型附图；独立视觉仍可按需使用。")
    elif mode == "on":
        hint.set_text("明确声明主模型可接收图片；协议不支持时不会附图。")
    elif not label:
        hint.set_text("还没有配置聊天模型，auto 无法判断视觉能力。")
    elif supports:
        hint.set_text(f"当前聊天模型 {label} 在预设中标记了 vision，auto 会附图。")
    else:
        hint.set_text(f"当前聊天模型 {label} 未被标记为 vision，auto 不会附图。")


def _set_video_hint(hint: Gtk.Label, mode: str, label: str, supports: bool) -> None:
    if mode == "off":
        hint.set_text("不向主模型发送视频；仍会保留“未发送”占位。")
    elif mode == "on":
        hint.set_text("明确声明主模型可接收完整 video_url；协议不支持时不会发送。")
    elif not label:
        hint.set_text("还没有配置聊天模型，auto 无法判断视频能力。")
    elif supports:
        hint.set_text(f"当前聊天模型 {label} 在预设中标记了 video，auto 会发送完整视频。")
    else:
        hint.set_text(f"当前聊天模型 {label} 未被标记为 video，auto 不会发送。")


def _state_badge(state: str) -> Gtk.Label:
    mapping = {
        "queued": ("排队中", "badge"),
        "running": ("进行中", "badge badge-orange"),
        "done": ("完成", "badge badge-green"),
        "completed": ("完成", "badge badge-green"),
        "success": ("完成", "badge badge-green"),
        "failed": ("失败", "badge badge-red"),
        "cancelled": ("已取消", "badge badge-orange"),
        "interrupted": ("已中断", "badge badge-red"),
    }
    text, css = mapping.get(state, (state, "badge"))
    return widgets.badge(text, css=css)


def _num(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value or 0)
