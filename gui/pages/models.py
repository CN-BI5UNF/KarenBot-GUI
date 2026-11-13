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
FALLBACK_EFFORT_OPTIONS = ["low", "medium", "high"]
EFFORT_LABELS = {
    "minimal": "最小",
    "low": "低",
    "medium": "中",
    "high": "高",
    "xhigh": "极高",
    "max": "最大",
}
VENDOR_LABELS = {
    "gemini": "Google Gemini",
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "qwen": "通义千问 Qwen",
    "glm": "智谱 GLM",
    "moonshot": "月之暗面 Kimi",
    "xai": "xAI Grok",
    "volcengine": "火山引擎豆包",
    "mimo": "小米 MiMo",
}
_VENDOR_PREFIXES = (
    (("gemini", "gemma"), "gemini"),
    (("claude",), "anthropic"),
    (("gpt", "chatgpt", "o1", "o3", "o4"), "openai"),
    (("deepseek",), "deepseek"),
    (("qwen", "qwq"), "qwen"),
    (("glm", "chatglm"), "glm"),
    (("kimi", "moonshot"), "moonshot"),
    (("grok",), "xai"),
    (("doubao", "skylark"), "volcengine"),
    (("mimo",), "mimo"),
)


def _normalize_vendor(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text else ""


def _detect_model_vendor(model_id: Any) -> str:
    text = str(model_id or "").strip().lower().rsplit("/", 1)[-1]
    text = text.split(":", 1)[0]
    for prefixes, vendor in _VENDOR_PREFIXES:
        if any(text.startswith(prefix) for prefix in prefixes):
            return vendor
    return ""


def _vendor_label(vendor_id: str) -> str:
    return VENDOR_LABELS.get(vendor_id, vendor_id or "未识别")


def _resolve_provider_vendor(
    provider: dict[str, Any] | None,
    model_id: str,
    presets: list[dict[str, Any]],
) -> str:
    """Match backend resolution order: explicit vendor, preset, model ID."""
    preset_ids = {str(item.get("id") or "") for item in presets}
    explicit = _normalize_vendor((provider or {}).get("model_vendor"))
    preset = _normalize_vendor((provider or {}).get("preset"))
    if explicit and explicit in preset_ids:
        return explicit
    if preset and preset in preset_ids:
        return preset
    detected = _detect_model_vendor(model_id)
    if detected and detected in preset_ids:
        return detected
    return ""


def _resolve_preset_model(
    presets: list[dict[str, Any]],
    provider: dict[str, Any] | None,
    model_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    vendor = _resolve_provider_vendor(provider, model_id, presets)
    if not vendor:
        return None, None, ""
    preset = next(
        (item for item in presets if str(item.get("id") or "") == vendor),
        None,
    )
    if preset is None:
        return None, None, vendor
    full = str(model_id or "").strip()
    tail = full.rsplit("/", 1)[-1]
    model = next(
        (item for item in preset.get("models") or [] if str(item.get("id") or "") == full),
        None,
    )
    if model is None and tail:
        model = next(
            (
                item
                for item in preset.get("models") or []
                if str(item.get("id") or "").rsplit("/", 1)[-1] == tail
            ),
            None,
        )
    return preset, model, vendor



def _effort_options(
    presets: list[dict[str, Any]],
    provider: dict[str, Any] | None,
    model_id: str,
) -> list[str]:
    """Resolve effort levels from model, then preset, then generic fallback."""
    preset, model, _vendor = _resolve_preset_model(presets, provider, model_id)
    options = list((model or {}).get("reasoning_effort_options") or [])
    if not options:
        options = list((preset or {}).get("reasoning_effort_options") or [])
    return [str(item) for item in options] or list(FALLBACK_EFFORT_OPTIONS)


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
        self.scan_button = widgets.button("重新扫描本地模型")
        self.scan_button.connect("clicked", lambda _b: self._load_models(rescan=True))
        header_row.append(self.scan_button)
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
        self.models_status = widgets.muted("")
        self.body.append(self.models_status)
        self.models_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.append(self.models_box)
        self._providers: list[dict[str, Any]] = []
        self._agents: dict[str, Any] = {}
        self._presets: list[dict[str, Any]] = []
        self._vendors: list[dict[str, Any]] = []
        self._models: list[dict[str, Any]] = []
        self._models_busy = False

    def refresh(self) -> None:
        if self.api is None:
            return

        def _fetch() -> dict[str, Any]:
            from concurrent.futures import ThreadPoolExecutor

            api = self.api
            errors: dict[str, str] = {}

            def _get(key: str, path: str, timeout: float) -> dict[str, Any]:
                try:
                    payload = api.get(path, timeout=timeout)
                except Exception as exc:  # noqa: BLE001 - report per section
                    errors[key] = str(exc) or type(exc).__name__
                    return {}
                return payload if isinstance(payload, dict) else {}

            with ThreadPoolExecutor(max_workers=3) as pool:
                providers = pool.submit(_get, "providers", "/api/providers", 30)
                presets = pool.submit(
                    _get, "presets", "/api/providers/presets", 30
                )
                models = pool.submit(_get, "models", "/api/models", 60)
                return {
                    "providers": providers.result(),
                    "presets": presets.result(),
                    "models": models.result(),
                    "errors": errors,
                }

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _error(self, exc: BaseException) -> None:
        for box, name in (
            (self.providers_box, "模型提供商"),
            (self.agents_box, "Agent 绑定"),
            (self.models_box, "本地模型"),
        ):
            widgets.clear(box)
            box.append(widgets.muted(f"读取{name}失败：{exc}"))

    def _render(self, data: dict[str, Any]) -> None:
        errors = dict(data.get("errors") or {})
        provider_error = errors.get("providers", "")
        preset_error = errors.get("presets", "")
        models_error = errors.get("models", "")
        provider_data = data.get("providers") or {}
        if not provider_error:
            self._providers = list(provider_data.get("providers") or [])
            self._agents = dict(provider_data.get("agents") or {})
        presets_payload = data.get("presets") or {}
        if not preset_error:
            self._presets = list(presets_payload.get("presets") or [])
            self._vendors = list(presets_payload.get("vendors") or [])
        if not models_error:
            self._models = list((data.get("models") or {}).get("models") or [])

        if provider_error:
            widgets.clear(self.providers_box)
            self.providers_box.append(
                widgets.muted(f"读取模型提供商失败：{provider_error}")
            )
            widgets.clear(self.agents_box)
            self.agents_box.append(
                widgets.muted(f"读取 Agent 绑定失败：{provider_error}")
            )
        else:
            self._render_providers()
            if preset_error:
                self.providers_box.append(
                    widgets.muted(
                        f"读取模型预设失败：{preset_error}"
                        "。已有提供商仍可编辑，但预设联动和模型建议不可用。"
                    )
                )
            self._render_agents()
        self._render_models(error=models_error)

    def _render_providers(self) -> None:
        widgets.clear(self.providers_box)
        if not self._providers:
            self.providers_box.append(self.empty("还没有配置任何提供商。"))
            return
        for provider in self._providers:
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(
                widgets.label(str(provider.get("id") or ""), css="section-title")
            )
            display_name = str(provider.get("display_name") or "")
            if display_name and display_name != str(provider.get("id") or ""):
                head.append(widgets.muted("·"))
                head.append(widgets.label(display_name))
            if provider.get("has_key"):
                head.append(widgets.badge("密钥已配置", css="badge badge-green"))
            elif provider.get("api_key_id"):
                head.append(widgets.badge("缺密钥", css="badge badge-orange"))
            else:
                head.append(widgets.badge("无密钥", css="badge badge-idle"))
            health = provider.get("health") or {}
            status = str(health.get("status") or "")
            if status:
                health_css = {
                    "healthy": "badge badge-green",
                    "degraded": "badge badge-orange",
                    "error": "badge badge-red",
                }.get(status, "badge badge-idle")
                health_text = {
                    "healthy": "已就位",
                    "degraded": "有异常",
                    "error": "出错了",
                }.get(status, str(health.get("message") or status))
                health_badge = widgets.badge(health_text, css=health_css)
                if health.get("message"):
                    health_badge.set_tooltip_text(str(health["message"]))
                head.append(health_badge)
            else:
                head.append(widgets.badge("未检测", css="badge badge-idle"))
            head.set_hexpand(True)
            test = widgets.button("测试")
            test.connect(
                "clicked",
                lambda b, p=provider: self._test_provider(p, b),
            )
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
                details.append(
                    "厂商：" + _vendor_label(str(provider["model_vendor"]))
                )
            if provider.get("timeout_seconds") is not None:
                details.append(f"超时：{provider.get('timeout_seconds')}s")
            if used:
                details.append("用于：" + "、".join(str(x) for x in used))
            card.append(widgets.muted(" · ".join(details)))
            health_message = str(health.get("message") or "")
            if health_message:
                card.append(widgets.muted("健康检查：" + health_message))
            self.providers_box.append(card)

    def _render_agents(self) -> None:
        widgets.clear(self.agents_box)
        if not self._agents:
            self.agents_box.append(widgets.muted("没有 Agent 配置。"))
            return
        for name, agent in self._agents.items():
            title = AGENT_LABEL.get(name, name)
            if not isinstance(agent, dict):
                card = widgets.card(spacing=5)
                head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                head.append(widgets.label(title, css="section-title"))
                head.append(widgets.badge("未启用", css="badge badge-idle"))
                card.append(head)
                card.append(
                    widgets.muted("这个 Agent 当前关闭，不需要配置模型。")
                )
                self.agents_box.append(card)
                continue
            card = widgets.card(spacing=5)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(widgets.label(title, css="section-title"))
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

    def _render_models(self, *, error: str = "") -> None:
        widgets.clear(self.models_box)
        if not self._models:
            if error:
                self.models_box.append(
                    widgets.muted(f"读取本地模型失败：{error}")
                )
            else:
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
            head.append(
                widgets.label(
                    str(model.get("display_name") or model.get("name")),
                    css="section-title",
                )
            )
            head.append(
                widgets.badge(
                    str(model.get("status_text") or model.get("status") or "未知"),
                    css=status_css.get(str(model.get("status")), "badge"),
                )
            )
            missing = [str(item) for item in model.get("missing_deps") or []]
            if missing:
                head.append(
                    widgets.badge(
                        f"缺 {len(missing)} 个依赖",
                        css="badge badge-orange",
                    )
                )
            head.set_hexpand(True)
            guide = widgets.button("安装指引")
            guide.connect("clicked", lambda _b, m=model: self._show_guide(m))
            head.append(guide)
            if missing:
                install = widgets.button("安装依赖")
                install.set_tooltip_text("缺失：" + "、".join(missing))
                install.connect(
                    "clicked",
                    lambda b, m=model: self._install_deps(m, b),
                )
                head.append(install)
            upload = widgets.button("上传 zip")
            upload.connect(
                "clicked", lambda b, m=model: self._upload_model(m, b)
            )
            head.append(upload)
            card.append(head)

            description = str(model.get("description") or "")
            if description:
                card.append(widgets.muted(description))
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            details.append(
                widgets.property_row(
                    "类型", str(model.get("kind") or "—"), wrap=False
                )
            )
            details.append(
                widgets.property_row(
                    "目标目录", str(model.get("model_dir") or "—")
                )
            )
            card.append(details)
            if missing:
                card.append(
                    widgets.muted("缺失依赖：" + "、".join(missing))
                )
            download_url = str(model.get("download_url") or "")
            if download_url:
                link = Gtk.LinkButton.new_with_label(download_url, "打开下载页")
                link.set_halign(Gtk.Align.START)
                link.set_tooltip_text(download_url)
                card.append(link)
            model_error = str(model.get("error") or "")
            if model_error:
                card.append(
                    widgets.label(
                        "错误：" + model_error,
                        css="danger-text",
                        wrap=True,
                        selectable=True,
                    )
                )
            self.models_box.append(card)
        if error:
            self.models_box.append(
                widgets.muted(
                    f"本地模型列表刷新失败：{error}（显示的是上一次结果）"
                )
            )

    # ------------------------------------------------------------------
    # Provider actions
    # ------------------------------------------------------------------
    def _test_provider(
        self,
        provider: dict[str, Any],
        button: Gtk.Button | None = None,
    ) -> None:
        if self.api is None:
            return
        if button is not None:
            button.set_sensitive(False)

        def _do() -> Any:
            return self.api.post(
                f"/api/providers/{_quote(provider.get('id'))}/test",
                {},
                timeout=90,
            )

        def _done(result: dict[str, Any]) -> None:
            message = str(result.get("message") or "测试完成")
            self.toast(
                message if result.get("ok") else f"测试未通过：{message}"
            )
            self.refresh()

        def _failed(exc: BaseException) -> None:
            if button is not None:
                button.set_sensitive(True)
            self.toast(f"测试失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

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

        used_by = [str(item) for item in provider.get("used_by") or []]
        body = "已保存的密钥会保留。"
        if used_by:
            body += (
                "\n\n它仍被 " + "、".join(used_by) + " 使用，"
                "需要先把这些引用改到别的提供商，否则删除会被拒绝。"
            )
        widgets.ConfirmDialog(
            self.app.window,
            heading=f"删除提供商「{provider.get('id')}」？",
            body=body,
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
        initial_preset = str(current.get("preset") or "")
        if not editing and not initial_preset:
            initial_preset = "deepseek" if any(
                str(item.get("id")) == "deepseek" for item in self._presets
            ) else ""
        preset_options = [("", "自定义 / 中转站")] + [
            (str(item.get("id")), str(item.get("display_name") or item.get("id")))
            for item in self._presets
        ]
        if (
            editing
            and initial_preset
            and not any(value == initial_preset for value, _ in preset_options)
        ):
            preset_options.append(
                (initial_preset, f"{initial_preset}（预设信息未加载）")
            )
        preset = widgets.dropdown(preset_options, initial_preset)
        if not self._presets:
            reload_row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8
            )
            reload_row.append(
                widgets.muted("预设列表没有加载成功；可以重新读取后再打开本对话框。")
            )
            reload_presets = widgets.button("重新加载预设")
            reload_presets.connect(
                "clicked",
                lambda _b: (window.close(), self.refresh()),
            )
            reload_row.append(reload_presets)
            window.body_box.append(reload_row)
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
        timeout.set_value(
            120.0
            if current.get("timeout_seconds") is None
            else float(current["timeout_seconds"])
        )
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

        def _refresh_vendor_hint(*_args: Any) -> None:
            explicit = widgets.dropdown_value(vendor)
            if explicit:
                vendor_hint.set_text(
                    f"能力识别使用 {_vendor_label(explicit)} 的模型表；"
                    "不会改变协议或地址。"
                )
                return
            preset_id = widgets.dropdown_value(preset)
            if preset_id:
                detected = _detect_model_vendor(model_entry.get_text())
                extra = ""
                if detected and detected != preset_id:
                    extra = (
                        f"模型 ID 看起来像 {_vendor_label(detected)}，"
                        "但当前预设的识别优先级更高。"
                    )
                vendor_hint.set_text(
                    f"能力默认跟随所选预设（{_vendor_label(preset_id)}）；"
                    "中转站混合模型时建议手动选择上游厂商。" + extra
                )
                return
            detected = _detect_model_vendor(model_entry.get_text())
            if detected:
                vendor_hint.set_text(
                    f"自动识别为 {_vendor_label(detected)}；"
                    "如果识别不对，可在上面手动选择。"
                )
                return
            vendor_hint.set_text(
                "识别失败时不会猜能力；可手动选择厂商，"
                "或把视觉/视频策略改成“开启”。"
            )

        def _preset_models(found: dict[str, Any]) -> list[tuple[str, str]]:
            candidates: list[tuple[str, str]] = []
            for item in found.get("models") or []:
                model_id = str(item.get("id") or "")
                if model_id:
                    candidates.append(
                        (model_id, str(item.get("display_name") or model_id))
                    )
            return candidates

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
                suggestions.set_candidates([])
                _refresh_vendor_hint()
                return
            found = next(
                (item for item in self._presets if str(item.get("id")) == chosen),
                None,
            )
            if not found:
                # Preset metadata failed to load (or a user preset was removed).
                # Keep the existing preset id instead of silently downgrading
                # the provider to a custom openai_compat endpoint.
                protocol.set_sensitive(False)
                suggestions.set_candidates([])
                vendor_hint.set_text(
                    f"预设「{chosen}」的信息没有加载；保存时会保留原预设，"
                    "协议、地址和思考方式按当前值保存。"
                )
                return
            display.set_text(
                str(found.get("display_name") or chosen)
            )
            base_url.set_text(str(found.get("base_url") or ""))
            _select_value(
                protocol, str(found.get("protocol") or "openai_compat")
            )
            _select_value(
                reasoning_style, str(found.get("reasoning_style") or "")
            )
            _select_value(
                effort_style,
                str(found.get("reasoning_effort_style") or ""),
            )
            protocol.set_sensitive(False)
            candidates = _preset_models(found)
            suggestions.set_candidates(candidates)
            if not model_entry.get_text().strip() and candidates:
                model_entry.set_text(candidates[0][0])
            _refresh_vendor_hint()

        preset.connect("notify::selected", _preset_changed)
        model_entry.connect("changed", _refresh_vendor_hint)
        vendor.connect("notify::selected", _refresh_vendor_hint)
        _preset_changed()

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
                return (
                    "Provider ID 只能用小写字母开头，"
                    "后跟小写字母、数字、下划线或短横线。"
                )
            if not widgets.dropdown_value(preset):
                if not base_url.get_text().strip():
                    return "自定义端点要填 Base URL。"
                if not widgets.dropdown_value(protocol):
                    return "自定义端点要选协议。"
            imported_key = editing and bool(current.get("api_key_id"))
            if not key_entry.get_text().strip() and not imported_key:
                return (
                    "还没填 API Key。"
                    if not editing
                    else "这个提供商没有已保存的密钥，请先填写 API Key。"
                )
            if not for_probe and not model_entry.get_text().strip():
                return "还没填模型 ID。"
            return ""

        def _test() -> None:
            if self.api is None:
                return
            error = _validate(for_probe=True)
            if error:
                status.set_text(error)
                return
            typed_key = bool(key_entry.get_text().strip())
            saved_test = editing and not typed_key
            test_button.set_sensitive(False)
            status.set_text("正在测试…")
            if saved_test:
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
                candidates: list[tuple[str, str]] = []
                detected_vendors: set[str] = set()
                for item in models:
                    model_id = str(item.get("id") or "")
                    if not model_id:
                        continue
                    label = str(item.get("display_name") or model_id)
                    vendor_id = str(
                        item.get("vendor") or _detect_model_vendor(model_id)
                    ).lower()
                    if vendor_id:
                        detected_vendors.add(vendor_id)
                    caps = [str(cap) for cap in item.get("capabilities") or []]
                    details = [
                        part
                        for part in (
                            _vendor_label(vendor_id) if vendor_id else "",
                            "/".join(caps),
                        )
                        if part
                    ]
                    if details:
                        label += " · " + " · ".join(details)
                    candidates.append((model_id, label))
                suggestions.set_candidates(candidates)
                if not model_entry.get_text().strip() and candidates:
                    model_entry.set_text(candidates[0][0])
                if (
                    not widgets.dropdown_value(vendor)
                    and len(detected_vendors) == 1
                ):
                    vendor_id = next(iter(detected_vendors))
                    values = getattr(vendor, "_values", [])
                    if vendor_id in values:
                        vendor.set_selected(values.index(vendor_id))
                _refresh_vendor_hint()
                status.set_text(
                    f"拿到 {len(models)} 个模型，可在模型输入框中选择或手填。"
                )
                fetch_button.set_sensitive(True)

            def _failed(exc: BaseException) -> None:
                status.set_text(
                    f"获取模型失败：{exc}（可以直接手填模型 ID）"
                )
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

            def _set_saving(busy: bool) -> None:
                window.submit_button.set_sensitive(not busy)
                test_button.set_sensitive(not busy)
                fetch_button.set_sensitive(not busy)

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
                _set_saving(False)
                status.set_text(f"保存失败：{exc}")

            _set_saving(True)
            status.set_text("正在保存…")
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
        provider_ids = {
            str(item.get("id"))
            for item in self._providers
            if item.get("id")
        }
        provider_options: list[tuple[str, str]] = [
            (
                str(item.get("id")),
                f"{item.get('display_name') or item.get('id')}（{item.get('id')}）",
            )
            for item in self._providers
            if item.get("id")
        ]
        current_provider_id = str(agent.get("provider") or "")
        if current_provider_id and current_provider_id not in provider_ids:
            provider_options.append(
                (current_provider_id, f"{current_provider_id}（已不存在）")
            )
        if not provider_options:
            provider_options = [("", "没有提供商")]
        provider = widgets.dropdown(provider_options, current_provider_id)
        model = Gtk.Entry()
        model.set_text(str(agent.get("model") or ""))
        suggestions = _SuggestMenu(model)
        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_row.append(model)
        model_row.append(suggestions)

        def _effort_options_for(provider_id: str, model_id: str) -> list[str]:
            found_provider = next(
                (item for item in self._providers if item.get("id") == provider_id),
                None,
            )
            return _effort_options(
                self._presets, found_provider, model_id
            )

        agent_budget = str(agent.get("reasoning_budget") or "")
        initial_options = list(
            agent.get("reasoning_effort_options")
            or _effort_options_for(current_provider_id, str(agent.get("model") or ""))
        )
        initial_budget = agent_budget if agent_budget in initial_options else ""
        budget_options = [("", "自动（供应商默认）")] + [
            (str(item), EFFORT_LABELS.get(str(item), str(item)))
            for item in initial_options
        ]
        budget = widgets.dropdown(budget_options, initial_budget)

        temperature_value = agent.get("temperature")
        temperature = Gtk.SpinButton.new_with_range(0, 2, 0.05)
        temperature.set_digits(2)
        temperature.set_value(
            0.0 if temperature_value is None else float(temperature_value)
        )
        top_p_value = agent.get("top_p")
        top_p = Gtk.SpinButton.new_with_range(0, 1, 0.05)
        top_p.set_digits(2)
        top_p.set_value(1.0 if top_p_value is None else float(top_p_value))
        max_tokens_value = agent.get("max_tokens")
        max_tokens = Gtk.SpinButton.new_with_range(1, 1_000_000, 256)
        max_tokens.set_value(
            4096.0 if max_tokens_value is None else float(max_tokens_value)
        )
        reasoning_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reasoning_switch = widgets.switch(bool(agent.get("reasoning")))
        reasoning_row.append(reasoning_switch)
        reasoning_row.append(widgets.label("启用思考 / reasoning"))
        budget_hint = widgets.muted("")
        timeout_value = agent.get("first_token_timeout_seconds")
        timeout = Gtk.SpinButton.new_with_range(1, 1800, 1)
        timeout.set_numeric(True)
        timeout.set_value(
            120.0 if timeout_value is None else float(timeout_value)
        )
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

        def _update_effort_hint(provider_id: str) -> None:
            found_provider = next(
                (item for item in self._providers if item.get("id") == provider_id),
                None,
            )
            style = str(
                (found_provider or {}).get("reasoning_effort_style") or ""
            )
            if style in ("openai", "deepseek"):
                budget_hint.set_text(
                    "当前提供商会把档位映射为 reasoning_effort；"
                    "档位越高越慢、越贵。自动表示不发送强度字段。"
                )
            else:
                budget_hint.set_text(
                    "当前提供商没有声明 reasoning_effort 支持；"
                    "档位会保存，但不会向端点发送该字段。自动表示不发送。"
                )
            budget_hint.set_opacity(
                1.0 if reasoning_switch.get_active() else 0.55
            )

        def _refresh_budget_options() -> None:
            provider_id = widgets.dropdown_value(provider)
            model_id = model.get_text().strip()
            options = _effort_options_for(provider_id, model_id)
            current = widgets.dropdown_value(budget)
            # 保留已保存的档位；只有它确实不在当前模型支持的档位里时才
            # 选一个有效档位。绝不能因为重算选项而静默改成“自动”。
            desired = current if current in options else ""
            if not desired and agent_budget in options:
                desired = agent_budget
            if not desired and not current and options:
                desired = str(options[0])
            widgets.set_dropdown_options(
                budget,
                [("", "自动（供应商默认）")]
                + [
                    (str(item), EFFORT_LABELS.get(str(item), str(item)))
                    for item in options
                ],
                desired,
            )
            budget.set_sensitive(bool(reasoning_switch.get_active()))
            _update_effort_hint(provider_id)

        def _sync_model_candidates(*_args: Any) -> None:
            provider_id = widgets.dropdown_value(provider)
            found_provider = next(
                (item for item in self._providers if item.get("id") == provider_id),
                None,
            )
            vendor = _resolve_provider_vendor(
                found_provider, model.get_text().strip(), self._presets
            )
            found_preset = next(
                (
                    item
                    for item in self._presets
                    if str(item.get("id") or "") == vendor
                ),
                None,
            )
            candidates = []
            for item in (found_preset or {}).get("models") or []:
                model_id = str(item.get("id") or "")
                if model_id:
                    candidates.append(
                        (model_id, str(item.get("display_name") or model_id))
                    )
            suggestions.set_candidates(candidates)
            _refresh_budget_options()

        def _on_model_changed(*_args: Any) -> None:
            # Do not rebuild the suggestion popover on every keystroke: doing
            # so reopens the popover while the user is trying to type.
            _refresh_budget_options()

        def _sync_reasoning(*_args: Any) -> None:
            enabled = bool(reasoning_switch.get_active())
            budget.set_sensitive(enabled)
            _update_effort_hint(widgets.dropdown_value(provider))

        provider.connect("notify::selected", _sync_model_candidates)
        model.connect("changed", _on_model_changed)
        reasoning_switch.connect("notify::active", _sync_reasoning)
        _sync_model_candidates()
        _sync_reasoning()

        def _save() -> None:
            if self.api is None:
                return
            provider_id = widgets.dropdown_value(provider)
            model_id = model.get_text().strip()
            if not provider_id:
                error.set_text("没有可用的提供商，请先在模型管理中添加。")
                return
            if provider_id not in provider_ids:
                error.set_text(
                    f"提供商 {provider_id} 已不存在，请改选一个有效提供商。"
                )
                return
            if not model_id:
                error.set_text("模型不能为空。")
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
                window.submit_button.set_sensitive(True)
                error.set_text(str(exc))

            window.submit_button.set_sensitive(False)
            widgets.run_async(_do, on_success=_done, on_error=_failed)

        window.present()

    # ------------------------------------------------------------------
    # Local models
    # ------------------------------------------------------------------
    def _load_models(self, *, rescan: bool = False) -> None:
        if self.api is None or self._models_busy:
            return
        self._models_busy = True
        self.scan_button.set_sensitive(False)
        self.models_status.set_text("正在重新扫描本地模型…" if rescan else "正在读取本地模型…")
        path = "/api/models" + ("?rescan=true" if rescan else "")

        def _fetch() -> dict[str, Any]:
            return self.api.get(path, timeout=90)

        def _done(data: dict[str, Any]) -> None:
            self._models_busy = False
            self.scan_button.set_sensitive(True)
            self.models_status.set_text("")
            self._models = list(data.get("models") or [])
            self._render_models()

        def _failed(exc: BaseException) -> None:
            self._models_busy = False
            self.scan_button.set_sensitive(True)
            self.models_status.set_text(f"扫描失败：{exc}")
            self._render_models(error=str(exc))
            self.toast(f"扫描本地模型失败：{exc}")

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

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

    def _install_deps(
        self,
        model: dict[str, Any],
        button: Gtk.Button | None = None,
    ) -> None:
        if self.api is None:
            return
        if button is not None:
            button.set_sensitive(False)

        def _do() -> Any:
            return self.api.post(
                f"/api/models/{_quote(model.get('name'))}/install-deps",
                {"source": "tsinghua"},
                timeout=60,
            )

        def _done(result: Any) -> None:
            if button is not None:
                button.set_sensitive(True)
            payload = result if isinstance(result, dict) else {}
            self.toast(str(payload.get("message") or "已开始安装"))

        def _failed(exc: BaseException) -> None:
            if button is not None:
                button.set_sensitive(True)
            self.toast(f"安装依赖失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _upload_model(
        self,
        model: dict[str, Any],
        button: Gtk.Button | None = None,
    ) -> None:
        path = widgets.path_picker(self.app.window, title_text="选择模型 zip")
        if not path or self.api is None:
            return
        source = Path(path)
        if button is not None:
            button.set_sensitive(False)

        def _do() -> Any:
            return self.api.upload_file(
                f"/api/models/{_quote(model.get('name'))}/upload",
                source,
                timeout=600,
            )

        def _done(result: Any) -> None:
            if button is not None:
                button.set_sensitive(True)
            payload = result if isinstance(result, dict) else {}
            self.toast(str(payload.get("message") or "上传完成"))
            self._load_models(rescan=True)

        def _failed(exc: BaseException) -> None:
            if button is not None:
                button.set_sensitive(True)
            self.toast(f"上传失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")
