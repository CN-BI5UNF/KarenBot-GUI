"""Cloud providers, agent bindings and local model plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

REASONING_STYLES = [
    ("", "跟随预设（自定义时不发字段）"),
    ("thinking_extra_body", "thinking_extra_body — DeepSeek / GLM / MiMo 风格"),
    ("qwen_enable_thinking", "qwen_enable_thinking — 通义千问"),
    ("openai_native", "openai_native — OpenAI 官方（不发字段）"),
    ("none", "none — 什么都不发（不认识的中转站用这个）"),
]
REASONING_EFFORT_STYLES = [
    ("", "跟随预设（自定义时不发送）"),
    ("none", "none — 不发送 reasoning_effort"),
    ("openai", "openai — 发送 reasoning_effort（OpenAI / Gemini 反代）"),
    ("deepseek", "deepseek — 发送 reasoning_effort（DeepSeek 风格）"),
]

class _SuggestMenu(Gtk.MenuButton):
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
        self._scroller.set_size_request(340, min(340, max(80, 34 * len(candidates))))
        self.set_visible(bool(candidates))

    def _picked(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self.entry.set_text(str(getattr(row, "model_value", "")))
        self._popover.popdown()


AGENT_LABEL = {
    "chat": "主聊天",
    "proactive": "主动思考",
    "summary": "滚动摘要",
    "persona_gen": "人格生成",
}


class ModelsPage(Page):
    refresh_on_activate = True
    page_id = "models"
    page_title = "模型管理"
    page_subtitle = "配置云端提供商/主模型，以及本地语音合成、向量模型插件。中转站记得选择「上游模型厂商」。"
    page_icon = "applications-science-symbolic"

    def build(self) -> None:
        header_row = self.header()
        scan = widgets.button("重新扫描本地模型")
        scan.connect("clicked", lambda _b: self._load_models(rescan=True))
        header_row.append(scan)
        self.body.append(header_row)
        self.restart_hint = widgets.card()
        self.restart_hint.set_visible(False)
        self.body.append(self.restart_hint)
        self.providers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(
            widgets.section_header(
                "模型提供商",
                "密钥只写不读；保存后会热重建 Provider/Agent，失败时才需要重启 Runtime",
            )
        )
        self.body.append(self.providers_box)
        add = widgets.button("添加提供商", icon="list-add-symbolic", css="suggested-action")
        add.connect("clicked", lambda _b: self._provider_dialog(None))
        self.body.append(add)
        self.agents_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(widgets.section_header("Agent 模型绑定", "主聊天、主动思考、摘要与人格生成"))
        self.body.append(self.agents_box)
        self.body.append(widgets.section_header("本地模型插件", "语音合成与向量模型"))
        self.models_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.models_box)
        self._providers: list[dict[str, Any]] = []
        self._agents: dict[str, Any] = {}
        self._presets: list[dict[str, Any]] = []
        self._vendors: list[dict[str, Any]] = []
        self._models: list[dict[str, Any]] = []

    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            from concurrent.futures import ThreadPoolExecutor

            api = self.api
            with ThreadPoolExecutor(max_workers=3) as pool:
                providers = pool.submit(api.get, "/api/providers", timeout=30)
                presets = pool.submit(
                    api.get, "/api/providers/presets", timeout=30
                )
                models = pool.submit(api.get, "/api/models", timeout=60)
                return {
                    "providers": providers.result(),
                    "presets": presets.result(),
                    "models": models.result(),
                }

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        widgets.clear(self.providers_box)
        self.providers_box.append(widgets.muted(f"读取模型配置失败：{exc}"))

    def _render(self, data: dict[str, Any]) -> None:
        provider_data = data.get("providers") or {}
        self._providers = list(provider_data.get("providers") or [])
        self._agents = dict(provider_data.get("agents") or {})
        presets_payload = data.get("presets") or {}
        self._presets = list(presets_payload.get("presets") or [])
        self._vendors = list(presets_payload.get("vendors") or [])
        self._models = list((data.get("models") or {}).get("models") or [])
        self._render_providers()
        self._render_agents()
        self._render_models()

    def _render_providers(self) -> None:
        widgets.clear(self.providers_box)
        if not self._providers:
            self.providers_box.append(self.empty("还没有配置任何提供商。"))
            return
        for provider in self._providers:
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(str(provider.get("id") or ""), css="section-title"))
            head.append(widgets.label(str(provider.get("display_name") or "")))
            if provider.get("has_key"):
                head.append(widgets.badge("密钥已配置", css="badge badge-green"))
            elif provider.get("api_key_id"):
                head.append(widgets.badge("缺密钥", css="badge badge-orange"))
            health = provider.get("health") or {}
            status = str(health.get("status") or "")
            if status:
                head.append(widgets.badge(health.get("message") or status))
            head.set_hexpand(True)
            test = widgets.button("测试")
            test.connect("clicked", lambda _b, p=provider: self._test_provider(p))
            edit = widgets.button("编辑")
            edit.connect("clicked", lambda _b, p=provider: self._provider_dialog(p))
            delete = widgets.button("删除", css="destructive-action")
            delete.connect("clicked", lambda _b, p=provider: self._delete_provider(p))
            head.append(test)
            head.append(edit)
            head.append(delete)
            card.append(head)
            used = provider.get("used_by") or []
            details = [str(provider.get("base_url") or "—")]
            if provider.get("preset"):
                details.append("预设：" + str(provider["preset"]))
            if provider.get("protocol"):
                details.append("协议：" + str(provider["protocol"]))
            if provider.get("model_vendor"):
                details.append("厂商：" + str(provider["model_vendor"]))
            if provider.get("timeout_seconds") is not None:
                details.append(f"超时：{provider.get('timeout_seconds')}s")
            if used:
                details.append("用于：" + "、".join(str(x) for x in used))
            card.append(widgets.muted(" · ".join(details)))
            self.providers_box.append(card)

    def _render_agents(self) -> None:
        widgets.clear(self.agents_box)
        if not self._agents:
            self.agents_box.append(widgets.muted("没有 Agent 配置。"))
            return
        for name, agent in self._agents.items():
            if not isinstance(agent, dict):
                continue
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(AGENT_LABEL.get(name, name), css="section-title"))
            head.append(
                widgets.muted(
                    f"{agent.get('provider') or '—'} / {agent.get('model') or '—'}"
                )
            )
            head.set_hexpand(True)
            edit = widgets.button("编辑绑定")
            edit.connect("clicked", lambda _b, n=name, a=agent: self._agent_dialog(n, a))
            head.append(edit)
            card.append(head)
            extras = []
            for key, label in (("temperature", "温度"), ("top_p", "top_p"), ("max_tokens", "max tokens")):
                if agent.get(key) is not None:
                    extras.append(f"{label}={agent.get(key)}")
            if agent.get("reasoning"):
                extras.append("思考已启用")
                if agent.get("reasoning_budget"):
                    extras.append(f"强度={agent.get('reasoning_budget')}")
            if agent.get("first_token_timeout_seconds"):
                extras.append(f"首包超时={agent.get('first_token_timeout_seconds')}s")
            if extras:
                card.append(widgets.muted(" · ".join(extras)))
            self.agents_box.append(card)

    def _render_models(self) -> None:
        widgets.clear(self.models_box)
        if not self._models:
            self.models_box.append(self.empty("没有发现本地模型插件。"))
            return
        status_css = {
            "ENABLED": "badge badge-green",
            "INSTALLED": "badge badge-green",
            "NOT_INSTALLED": "badge badge-orange",
            "ERROR": "badge badge-red",
        }
        for model in self._models:
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(str(model.get("display_name") or model.get("name")), css="section-title"))
            head.append(widgets.badge(str(model.get("status_text") or model.get("status")), css=status_css.get(str(model.get("status")), "badge")))
            missing = model.get("missing_deps") or []
            if missing:
                head.append(widgets.badge(f"缺 {len(missing)} 个依赖", css="badge badge-orange"))
            head.set_hexpand(True)
            guide = widgets.button("安装指引")
            guide.connect("clicked", lambda _b, m=model: self._show_guide(m))
            head.append(guide)
            if missing:
                install = widgets.button("安装依赖")
                install.connect("clicked", lambda _b, m=model: self._install_deps(m))
                head.append(install)
            upload = widgets.button("上传 zip")
            upload.connect("clicked", lambda _b, m=model: self._upload_model(m))
            head.append(upload)
            card.append(head)
            description = str(model.get("description") or "")
            if description:
                card.append(widgets.muted(description))
            card.append(widgets.muted(str(model.get("model_dir") or "")))
            self.models_box.append(card)

    # ------------------------------------------------------------------
    # Provider actions
    # ------------------------------------------------------------------
    def _test_provider(self, provider: dict[str, Any]) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post(f"/api/providers/{_quote(provider.get('id'))}/test", {}, timeout=90)

        def _done(result: dict[str, Any]) -> None:
            self.toast(str(result.get("message") or "测试完成"))
            self.refresh()

        widgets.run_async(
            _do,
            on_success=_done,
            on_error=lambda exc: self.toast(f"测试失败：{exc}"),
        )

    def _delete_provider(self, provider: dict[str, Any]) -> None:
        def _do_delete() -> None:
            if self.api is None:
                return

            def _do() -> Any:
                return self.api.delete(
                    f"/api/providers/{_quote(provider.get('id'))}?drop_key=false",
                    timeout=30,
                )

            def _done(result: Any) -> None:
                payload_result = result if isinstance(result, dict) else {}
                self.toast(
                    str(payload_result.get("message") or "已删除提供商")
                )
                if payload_result.get("needs_restart"):
                    self._mark_restart()
                self.refresh()

            widgets.run_async(
                _do,
                on_success=_done,
                on_error=lambda exc: self.toast(str(exc)),
            )

        widgets.ConfirmDialog(
            self.app.window,
            heading=f"删除提供商「{provider.get('id')}」？",
            body="已保存的密钥会保留；仍被 Agent 使用时会被拒绝。",
            confirm_label="删除",
            destructive=True,
            on_confirm=_do_delete,
        )

    def _provider_dialog(self, provider: dict[str, Any] | None) -> None:
        editing = provider is not None
        current = provider or {}
        window = widgets.FormWindow(
            self.app.window,
            "编辑提供商" if editing else "添加提供商",
            width=780,
            height=820,
            submit_label="保存",
            on_submit=lambda: _save(),
        )
        preset_options = [("", "自定义 / 中转站")] + [
            (str(item.get("id")), str(item.get("display_name") or item.get("id")))
            for item in self._presets
        ]
        initial_preset = str(current.get("preset") or "")
        if not editing and not initial_preset:
            initial_preset = "deepseek" if any(
                str(item.get("id")) == "deepseek" for item in self._presets
            ) else ""
        preset = widgets.dropdown(preset_options, initial_preset)
        provider_id = Gtk.Entry()
        provider_id.set_text(str(current.get("id") or ""))
        provider_id.set_sensitive(not editing)
        provider_id.set_placeholder_text("relay01（小写字母开头）")
        display = Gtk.Entry()
        display.set_text(str(current.get("display_name") or ""))
        display.set_placeholder_text("显示名")
        vendor_options = [("", "自动识别（按模型 ID / 预设）")]
        vendor_options.extend(
            (str(item.get("id")), str(item.get("label") or item.get("id")))
            for item in self._vendors
        )
        current_vendor = str(current.get("model_vendor") or "")
        if current_vendor and not any(value == current_vendor for value, _ in vendor_options):
            vendor_options.append((current_vendor, current_vendor))
        vendor = widgets.dropdown(vendor_options, current_vendor)
        protocol = widgets.dropdown(
            [
                ("openai_compat", "OpenAI 兼容"),
                ("anthropic", "Anthropic"),
            ],
            str(current.get("protocol") or "openai_compat"),
        )
        base_url = Gtk.Entry()
        base_url.set_text(str(current.get("base_url") or ""))
        base_url.set_placeholder_text("https://relay.example.com/v1")
        reasoning_style = widgets.dropdown(
            REASONING_STYLES, str(current.get("reasoning_style") or "")
        )
        effort_style = widgets.dropdown(
            REASONING_EFFORT_STYLES,
            str(current.get("reasoning_effort_style") or ""),
        )
        timeout = Gtk.SpinButton.new_with_range(1, 3600, 1)
        timeout.set_numeric(True)
        timeout.set_value(float(current.get("timeout_seconds") or 120))
        model_entry = Gtk.Entry()
        model_entry.set_placeholder_text("模型 ID，例如 deepseek-chat")
        suggestions = _SuggestMenu(model_entry)
        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_row.append(model_entry)
        model_row.append(suggestions)
        key_entry = Gtk.Entry()
        key_entry.set_visibility(False)
        key_entry.set_placeholder_text(
            "已保存（留空不修改）" if current.get("has_key") else "sk-…"
        )
        key_show = Gtk.CheckButton(label="显示")
        key_show.connect(
            "toggled", lambda w: key_entry.set_visibility(bool(w.get_active()))
        )
        key_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        key_entry.set_hexpand(True)
        key_row.append(key_entry)
        key_row.append(key_show)
        vendor_hint = widgets.muted(
            "中转站可以同时挂 Gemini/Claude/OpenAI 等模型；选对厂商才能应用视觉、视频和上下文能力。"
        )
        status = widgets.muted("")
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        test_button = widgets.button("测试连接")
        fetch_button = widgets.button("获取模型列表")
        actions.append(test_button)
        actions.append(fetch_button)

        window.add_row("预设", preset)
        window.add_row("提供商 ID", provider_id)
        window.add_row("显示名称", display)
        window.add_row("上游模型厂商（能力识别）", vendor)
        window.body_box.append(vendor_hint)
        window.add_row("协议", protocol)
        window.add_row("Base URL", base_url)
        window.add_row("API Key", key_row)
        window.add_row("模型 ID", model_row)
        window.body_box.append(actions)
        window.body_box.append(status)
        window.add_row("思考参数风格", reasoning_style)
        window.add_row("思考强度传递", effort_style)
        window.add_row("超时（秒）", timeout)

        custom_values = {
            "protocol": str(current.get("protocol") or "openai_compat"),
            "display": str(current.get("display_name") or ""),
            "base_url": str(current.get("base_url") or ""),
            "reasoning_style": str(current.get("reasoning_style") or ""),
            "reasoning_effort_style": str(
                current.get("reasoning_effort_style") or ""
            ),
        }
        last_preset = {"value": initial_preset}

        def _select_value(dropdown: Gtk.DropDown, value: str) -> None:
            values = getattr(dropdown, "_values", [])
            if value in values:
                dropdown.set_selected(values.index(value))

        def _preset_changed(*_args: Any) -> None:
            chosen = widgets.dropdown_value(preset)
            if last_preset["value"] == "":
                custom_values.update(
                    {
                        "protocol": widgets.dropdown_value(protocol),
                        "display": display.get_text(),
                        "base_url": base_url.get_text(),
                        "reasoning_style": widgets.dropdown_value(reasoning_style),
                        "reasoning_effort_style": widgets.dropdown_value(effort_style),
                    }
                )
            last_preset["value"] = chosen
            if not chosen:
                _select_value(protocol, custom_values["protocol"])
                display.set_text(custom_values["display"])
                base_url.set_text(custom_values["base_url"])
                _select_value(reasoning_style, custom_values["reasoning_style"])
                _select_value(
                    effort_style, custom_values["reasoning_effort_style"]
                )
                protocol.set_sensitive(True)
                vendor_hint.set_text(
                    "自定义端点：请填写 Base URL 与协议；模型 ID 可手动输入或从上游拉取。"
                )
                return
            found = next(
                (item for item in self._presets if str(item.get("id")) == chosen),
                None,
            )
            if not found:
                return
            display.set_text(str(found.get("display_name") or chosen))
            base_url.set_text(str(found.get("base_url") or ""))
            _select_value(protocol, str(found.get("protocol") or "openai_compat"))
            _select_value(
                reasoning_style, str(found.get("reasoning_style") or "")
            )
            _select_value(
                effort_style,
                str(found.get("reasoning_effort_style") or ""),
            )
            protocol.set_sensitive(False)
            models = found.get("models") or []
            if not model_entry.get_text().strip() and models:
                model_entry.set_text(str(models[0].get("id") or ""))
            vendor_hint.set_text(
                "已选择预设：协议、地址和思考方式跟随预设；中转站混合模型时建议手动选上游厂商。"
            )

        preset.connect("notify::selected", _preset_changed)
        if editing:
            models = []
            found = next(
                (item for item in self._presets if str(item.get("id")) == initial_preset),
                None,
            )
            if found:
                models = found.get("models") or []
            if not model_entry.get_text().strip() and models:
                model_entry.set_text(str(models[0].get("id") or ""))
        else:
            _preset_changed()
        if initial_preset:
            protocol.set_sensitive(False)

        def _model_candidates() -> list[tuple[str, str]]:
            chosen = widgets.dropdown_value(preset)
            found = next(
                (item for item in self._presets if str(item.get("id")) == chosen),
                None,
            )
            result = []
            if found:
                for item in found.get("models") or []:
                    model_id = str(item.get("id") or "")
                    if model_id:
                        result.append(
                            (model_id, str(item.get("display_name") or model_id))
                        )
            return result

        suggestions.set_candidates(_model_candidates())

        def _payload(for_probe: bool = False) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "preset": widgets.dropdown_value(preset) or None,
                "model_vendor": widgets.dropdown_value(vendor) or None,
                "protocol": widgets.dropdown_value(protocol) or None,
                "base_url": base_url.get_text().strip() or None,
                "display_name": display.get_text().strip() or None,
                "reasoning_style": widgets.dropdown_value(reasoning_style) or None,
                "reasoning_effort_style": widgets.dropdown_value(effort_style)
                or None,
                "timeout_seconds": float(timeout.get_value()),
                "model": model_entry.get_text().strip() or None,
            }
            if not editing:
                payload["id"] = provider_id.get_text().strip()
            key = key_entry.get_text().strip()
            if key:
                payload["api_key"] = key
            elif for_probe and editing and current.get("api_key_id"):
                payload["api_key_id"] = current.get("api_key_id")
            return payload

        def _validate(*, for_probe: bool = False) -> str:
            pid = provider_id.get_text().strip()
            if not pid:
                return "Provider ID 不能为空。"
            import re

            if not re.match(r"^[a-z][a-z0-9_-]{0,63}$", pid):
                return "Provider ID 只能用小写字母开头，后跟小写字母、数字、下划线或短横线。"
            if not widgets.dropdown_value(preset):
                if not base_url.get_text().strip():
                    return "自定义端点要填 Base URL。"
                if not widgets.dropdown_value(protocol):
                    return "自定义端点要选协议。"
            if not editing and not key_entry.get_text().strip():
                return "新增提供商需要填写 API Key。"
            if not model_entry.get_text().strip():
                return "还没填模型 ID。"
            _ = for_probe
            return ""

        def _test() -> None:
            if self.api is None:
                return
            error = _validate(for_probe=True)
            if error:
                status.set_text(error)
                return
            test_button.set_sensitive(False)
            status.set_text("正在测试…")
            if editing and not key_entry.get_text().strip():
                def _do() -> dict[str, Any]:
                    return self.api.post(
                        f"/api/providers/{_quote(current.get('id'))}/test",
                        {},
                        timeout=120,
                    )
            else:
                payload = _payload(for_probe=True)

                def _do() -> dict[str, Any]:
                    return self.api.post("/api/providers/test", payload, timeout=120)

            def _done(result: dict[str, Any]) -> None:
                status.set_text(
                    str(result.get("message") or ("连接正常" if result.get("ok") else "未通过"))
                )
                test_button.set_sensitive(True)

            def _failed(exc: BaseException) -> None:
                status.set_text(f"测试失败：{exc}")
                test_button.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        def _fetch_models() -> None:
            if self.api is None:
                return
            error = _validate(for_probe=True)
            if error:
                status.set_text(error)
                return
            fetch_button.set_sensitive(False)
            status.set_text("正在获取模型列表…")
            payload = _payload(for_probe=True)

            def _do() -> dict[str, Any]:
                return self.api.post(
                    "/api/providers/fetch-models", payload, timeout=120
                )

            def _done(result: dict[str, Any]) -> None:
                models = result.get("models") or []
                candidates = [
                    (str(item.get("id")), str(item.get("display_name") or item.get("id")))
                    for item in models
                    if item.get("id")
                ]
                suggestions.set_candidates(candidates)
                if not model_entry.get_text().strip() and candidates:
                    model_entry.set_text(candidates[0][0])
                vendors = {
                    str(item.get("vendor") or "")
                    for item in models
                    if item.get("vendor")
                }
                if not widgets.dropdown_value(vendor) and len(vendors) == 1:
                    vendor_id = next(iter(vendors))
                    values = getattr(vendor, "_values", [])
                    if vendor_id in values:
                        vendor.set_selected(values.index(vendor_id))
                status.set_text(f"拿到 {len(models)} 个模型，可在模型输入框中选择或手填。")
                fetch_button.set_sensitive(True)

            def _failed(exc: BaseException) -> None:
                status.set_text(f"获取模型失败：{exc}（可以直接手填模型 ID）")
                fetch_button.set_sensitive(True)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        def _save() -> None:
            if self.api is None:
                return
            error = _validate()
            if error:
                status.set_text(error)
                return
            pid = provider_id.get_text().strip()
            payload = _payload()
            if editing:
                path = f"/api/providers/{_quote(pid)}"
                method = "patch"
            else:
                payload["id"] = pid
                path = "/api/providers"
                method = "post"

            def _do() -> Any:
                return getattr(self.api, method)(path, payload, timeout=60)

            def _done(result: Any) -> None:
                window.close()
                payload_result = result if isinstance(result, dict) else {}
                self.toast(
                    str(
                        payload_result.get("message")
                        or "提供商已保存"
                    )
                )
                if payload_result.get("needs_restart"):
                    self._mark_restart()
                self.refresh()

            def _failed(exc: BaseException) -> None:
                status.set_text(f"保存失败：{exc}")

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        test_button.connect("clicked", lambda _b: _test())
        fetch_button.connect("clicked", lambda _b: _fetch_models())
        window.present()

    def _mark_restart(self) -> None:
        widgets.clear(self.restart_hint)
        self.restart_hint.set_visible(True)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(widgets.label("配置已保存，需要重启 Runtime 才能生效。"))
        restart = widgets.button("立即重启 Runtime", css="suggested-action")
        restart.connect("clicked", lambda _b: self._restart())
        row.append(restart)
        self.restart_hint.append(row)

    def _restart(self) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post("/api/system/restart", {}, timeout=120)

        widgets.run_async(
            _do,
            on_success=lambda _r: (self.restart_hint.set_visible(False), self.toast("Runtime 已重启")),
            on_error=lambda exc: self.toast(f"重启失败：{exc}"),
        )

    def _agent_dialog(self, name: str, agent: dict[str, Any]) -> None:
        window = widgets.FormWindow(
            self.app.window,
            f"编辑 {AGENT_LABEL.get(name, name)}",
            width=680,
            height=760,
            on_submit=lambda: _save(),
        )
        provider_options = [
            (str(item.get("id")), str(item.get("id"))) for item in self._providers
        ] or [("", "没有提供商")]
        provider = widgets.dropdown(provider_options, str(agent.get("provider") or ""))
        model = Gtk.Entry()
        model.set_text(str(agent.get("model") or ""))
        suggestions = _SuggestMenu(model)
        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_row.append(model)
        model_row.append(suggestions)
        temperature = Gtk.SpinButton.new_with_range(0, 2, 0.05)
        temperature.set_digits(2)
        temperature.set_value(float(agent.get("temperature") or 0))
        top_p = Gtk.SpinButton.new_with_range(0, 1, 0.05)
        top_p.set_digits(2)
        top_p.set_value(float(agent.get("top_p") or 1.0))
        max_tokens = Gtk.SpinButton.new_with_range(1, 1_000_000, 256)
        max_tokens.set_value(float(agent.get("max_tokens") or 4096))
        reasoning_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reasoning_switch = widgets.switch(bool(agent.get("reasoning")))
        reasoning_row.append(reasoning_switch)
        reasoning_row.append(widgets.label("启用思考 / reasoning"))
        options = list(agent.get("reasoning_effort_options") or ["low", "medium", "high"])
        budget_options = [("", "自动（供应商默认）")] + [
            (str(item), str(item)) for item in options
        ]
        budget = widgets.dropdown(budget_options, str(agent.get("reasoning_budget") or ""))
        budget_hint = widgets.muted(
            "自动档位不发送 reasoning 强度；选择具体档位后会按 provider 的传递风格发送。"
        )
        timeout = Gtk.SpinButton.new_with_range(1, 1800, 1)
        timeout.set_numeric(True)
        timeout.set_value(float(agent.get("first_token_timeout_seconds") or 120))
        window.add_row("Provider", provider)
        window.add_row("模型", model_row)
        window.add_row("温度", temperature)
        window.add_row("Top P", top_p)
        window.add_row("Max tokens", max_tokens)
        window.add_row("思考", reasoning_row)
        window.add_row("思考强度", budget)
        window.body_box.append(budget_hint)
        window.add_row("首包超时（秒）", timeout)
        error = widgets.muted("")
        window.body_box.append(error)

        def _sync_model_candidates(*_args: Any) -> None:
            provider_id = widgets.dropdown_value(provider)
            found_provider = next(
                (item for item in self._providers if item.get("id") == provider_id),
                None,
            )
            preset_id = str((found_provider or {}).get("preset") or "")
            found_preset = next(
                (item for item in self._presets if item.get("id") == preset_id),
                None,
            )
            candidates = []
            if found_preset:
                for item in found_preset.get("models") or []:
                    model_id = str(item.get("id") or "")
                    if model_id:
                        candidates.append(
                            (model_id, str(item.get("display_name") or model_id))
                        )
            suggestions.set_candidates(candidates)

        def _sync_reasoning(*_args: Any) -> None:
            enabled = bool(reasoning_switch.get_active())
            budget.set_sensitive(enabled)
            budget_hint.set_opacity(1.0 if enabled else 0.55)

        provider.connect("notify::selected", _sync_model_candidates)
        reasoning_switch.connect("notify::active", _sync_reasoning)
        _sync_model_candidates()
        _sync_reasoning()

        def _save() -> None:
            if self.api is None:
                return
            provider_id = widgets.dropdown_value(provider)
            model_id = model.get_text().strip()
            if not provider_id or not model_id:
                error.set_text("Provider 和模型不能为空。")
                return
            payload: dict[str, Any] = {
                "provider": provider_id,
                "model": model_id,
                "temperature": float(temperature.get_value()),
                "top_p": float(top_p.get_value()),
                "max_tokens": int(max_tokens.get_value()),
                "first_token_timeout_seconds": float(timeout.get_value()),
            }
            if reasoning_switch.get_active():
                payload["reasoning"] = True
                selected_budget = widgets.dropdown_value(budget)
                if selected_budget:
                    payload["reasoning_budget"] = selected_budget
                else:
                    payload["reasoning_budget_reset"] = True
            else:
                payload["reasoning"] = False

            def _do() -> Any:
                return self.api.patch(
                    f"/api/settings/agents/{_quote(name)}", payload, timeout=60
                )

            def _done(result: Any) -> None:
                window.close()
                payload_result = result if isinstance(result, dict) else {}
                self.toast(
                    str(
                        payload_result.get("message")
                        or "Agent 绑定已保存"
                    )
                )
                if payload_result.get("needs_restart"):
                    self._mark_restart()
                self.refresh()

            def _failed(exc: BaseException) -> None:
                error.set_text(str(exc))

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        window.present()

    # ------------------------------------------------------------------
    # Local models
    # ------------------------------------------------------------------
    def _load_models(self, *, rescan: bool = False) -> None:
        if self.api is None:
            return
        path = "/api/models" + ("?rescan=true" if rescan else "")

        def _fetch() -> dict[str, Any]:
            return self.api.get(path, timeout=90)

        def _done(data: dict[str, Any]) -> None:
            self._models = list(data.get("models") or [])
            self._render_models()

        widgets.run_async(_fetch, on_success=_done, on_error=lambda exc: self.toast(str(exc)))

    def _show_guide(self, model: dict[str, Any]) -> None:
        if self.api is None:
            return

        def _do() -> dict[str, Any]:
            return self.api.get(f"/api/models/{_quote(model.get('name'))}/guide", timeout=30)

        def _show(data: dict[str, Any]) -> None:
            window = Gtk.Window()
            window.set_title(f"{model.get('display_name')} · 安装指引")
            window.set_default_size(760, 620)
            window.set_transient_for(self.app.window)
            window.set_modal(True)
            window.set_titlebar(Adw.HeaderBar())
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            body.append(widgets.text_view(str(data.get("markdown") or ""), height=520, monospace=True))
            window.set_child(body)
            window.present()

        widgets.run_async(_do, on_success=_show, on_error=lambda exc: self.toast(str(exc)))

    def _install_deps(self, model: dict[str, Any]) -> None:
        if self.api is None:
            return

        def _do() -> Any:
            return self.api.post(
                f"/api/models/{_quote(model.get('name'))}/install-deps",
                {"source": "tsinghua"},
                timeout=60,
            )

        widgets.run_async(
            _do,
            on_success=lambda result: self.toast(str(result.get("message") or "已开始安装")),
            on_error=lambda exc: self.toast(str(exc)),
        )

    def _upload_model(self, model: dict[str, Any]) -> None:
        path = widgets.path_picker(self.app.window, title_text="选择模型 zip")
        if not path or self.api is None:
            return
        source = Path(path)

        def _do() -> Any:
            return self.api.upload_file(
                f"/api/models/{_quote(model.get('name'))}/upload",
                source,
                timeout=600,
            )

        widgets.run_async(
            _do,
            on_success=lambda result: (self.toast(str(result.get("message") or "上传完成")), self._load_models(rescan=True)),
            on_error=lambda exc: self.toast(f"上传失败：{exc}"),
        )


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")
