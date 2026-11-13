"""First-run configuration wizard matching the WebUI step flow."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

PROTOCOLS = [
    ("openai_compat", "OpenAI 兼容"),
    ("anthropic", "Anthropic"),
]
VENDOR_OPTIONS = [
    ("", "自动识别（按模型 ID）"),
    ("gemini", "Google Gemini"),
    ("anthropic", "Anthropic Claude"),
    ("openai", "OpenAI"),
    ("deepseek", "DeepSeek"),
    ("qwen", "通义千问 Qwen"),
    ("glm", "智谱 GLM"),
    ("moonshot", "月之暗面 Kimi"),
    ("xai", "xAI Grok"),
    ("volcengine", "火山引擎豆包"),
    ("mimo", "小米 MiMo"),
]
REASONING_STYLES = [
    ("", "跟随预设（自定义则不发任何字段）"),
    ("thinking_extra_body", "thinking_extra_body — DeepSeek / GLM / MiMo 风格"),
    ("qwen_enable_thinking", "qwen_enable_thinking — 通义千问"),
    ("openai_native", "openai_native — OpenAI 官方（不发字段）"),
    ("none", "none — 什么都不发"),
]
REASONING_EFFORT_STYLES = [
    ("", "跟随预设（自定义则不发送）"),
    ("none", "none — 不发送 reasoning_effort"),
    ("openai", "openai — 发送 reasoning_effort"),
    ("deepseek", "deepseek — DeepSeek 风格"),
]
MODEL_IMAGES = [
    ("auto", "auto（按预设能力自动附图）"),
    ("on", "on（明确允许主模型接收图片）"),
    ("off", "off（不向主模型附图）"),
]
EFFORT_LABELS = {
    "minimal": "最小",
    "low": "低",
    "medium": "中",
    "high": "高",
    "xhigh": "极高",
    "max": "最大",
}
SEARCH_PROVIDERS = [
    ("bing_rss", "Bing RSS（默认，免密钥）"),
    ("baidu", "百度"),
    ("searxng", "SearXNG（自建实例）"),
]
WHITELIST_MODES = [
    ("open", "open（对所有人开放，注意 API 费用）"),
    ("verify", "verify（陌生人走管理员审核）"),
    ("whitelist", "whitelist（仅名单内可用）"),
]
SUB_AGENTS = [
    ("proactive", "主动思考", "隔一段时间自己想想有没有话要说。", 0.3, 64),
    ("summary", "滚动摘要", "上下文快满时把旧对话压成摘要。", 0.1, 8192),
    ("persona_gen", "人格生成", "后台按时间慢慢丰满人格设定。", 0.7, 8192),
]


class SetupPage(Page):
    page_id = "setup"
    page_title = "首次配置"
    page_subtitle = "创建独立的数据目录与第一份配置"
    page_icon = "emblem-system-symbolic"

    def build(self) -> None:
        self.loaded = True
        self._options: dict[str, Any] = {}
        self._steps_meta: dict[str, dict[str, Any]] = {}
        self._presets: list[dict[str, Any]] = []
        self._personas: list[dict[str, Any]] = []
        self._path = "recommended"
        self._current = "welcome"
        self._is_last = False
        self._progress = [0, 1]
        self._progress_ok = False
        self._progress_retry_source = 0
        self._busy = False
        self._building_step = False
        self._error = ""
        self._validate_step: Callable[[], str | None] = lambda: None
        self._provider: dict[str, Any] = {}
        # 切到预设再切回“自定义”时恢复手填的中转站字段。
        self._custom_provider_draft: dict[str, Any] = {}
        self._chat: dict[str, Any] = {}
        self._agents: dict[str, dict[str, Any]] = {}
        self._features: dict[str, dict[str, Any]] = {}
        self._adapter: dict[str, Any] = {}
        self._persona = "大肥鱼"
        self._persona_source = "builtin"
        self._persona_brief = ""
        self._max_context_tokens: int | None = None

        # 向导自身不再滚动整页：步骤内容放进内部滚动区，底部按钮始终可见。
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.body.set_vexpand(True)
        self.body.append(self.header())
        intro = widgets.card(spacing=4)
        intro.append(
            widgets.label(
                "这是 Karen Desktop 的独立实例。配置、密钥、聊天记录都会保存在本地数据目录，"
                "不会改动已有 KarenBot 服务的数据。",
                wrap=True,
            )
        )
        self.path_label = widgets.muted("正在读取路径…")
        intro.append(self.path_label)
        self.body.append(intro)

        progress_card = widgets.card(spacing=6, padding=12)
        self.progress_label = widgets.label("", css="field-label")
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        self.step_title = widgets.label("", css="section-title", wrap=True)
        self.step_subtitle = widgets.muted("")
        progress_card.append(self.progress_label)
        progress_card.append(self.progress_bar)
        progress_card.append(self.step_title)
        progress_card.append(self.step_subtitle)
        self.body.append(progress_card)

        self.step_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.step_card = widgets.card(spacing=10)
        self.step_card.append(
            widgets.muted("正在准备向导…")
        )
        self.error_label = widgets.label("", css="danger-text", wrap=True)
        self.error_label.set_visible(False)
        step_scroll = Gtk.ScrolledWindow()
        step_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        step_scroll.set_vexpand(True)
        step_scroll.set_child(self.step_card)
        self.body.append(step_scroll)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.back_button = widgets.button("上一步")
        self.back_button.connect("clicked", lambda _b: self._go_back())
        self.skip_button = widgets.button("跳过")
        self.skip_button.connect("clicked", lambda _b: self._skip())
        self.next_button = widgets.button("下一步", css="suggested-action")
        self.next_button.connect("clicked", lambda _b: self._advance())
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(self.back_button)
        footer.append(spacer)
        footer.append(self.skip_button)
        footer.append(self.next_button)
        self.body.append(footer)
        self.status_label = widgets.muted("")
        self.body.append(self.status_label)
        self.body.append(self.error_label)
        self._set_ready(False)
        self.refresh()

    # ------------------------------------------------------------------
    # Boot / navigation
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.api is None:
            return
        self._set_busy(True, "正在读取向导选项…")

        def _fetch() -> dict[str, Any]:
            options = self.api.get("/api/setup/options", timeout=60)
            try:
                copy_data = self.api.get("/api/setup/copy", timeout=30)
            except BaseException:  # noqa: BLE001
                copy_data = {}
            return {"options": options, "copy": copy_data}

        def _done(data: dict[str, Any]) -> None:
            self._render_options(data.get("options") or {})

        def _failed(exc: BaseException) -> None:
            self._set_busy(False)
            self._set_ready(False)
            self.status_label.set_text(f"读取向导选项失败：{exc}")
            self.status_label.add_css_class("danger-text")

        widgets.run_async(_fetch, on_success=_done, on_error=_failed)

    def _render_options(self, data: dict[str, Any]) -> None:
        self._options = data
        self._presets = list(data.get("presets") or [])
        self._personas = list(data.get("personas") or [])
        self._steps_meta = {
            str(step.get("id")): step for step in data.get("steps") or []
        }
        defaults = data.get("defaults") or {}
        preset_id = str(defaults.get("preset") or "")
        model_id = str(defaults.get("model") or "")
        preset = self._preset(preset_id)
        self._provider = {
            "id": f"{preset_id}_main" if preset_id else "main_provider",
            "preset": preset_id or None,
            "display_name": str((preset or {}).get("display_name") or "主模型"),
            "protocol": str((preset or {}).get("protocol") or "openai_compat"),
            "base_url": str((preset or {}).get("base_url") or ""),
            "model": model_id,
            "api_key": "",
            "reasoning_style": str((preset or {}).get("reasoning_style") or ""),
            "timeout_seconds": 120.0,
        }
        self._chat = {
            "temperature": 0.6,
            "top_p": 1.0,
            "max_tokens": 16384,
            "reasoning": False,
            "reasoning_budget": "medium",
        }
        self._agents = {
            key: {
                "enabled": True,
                "provider": "",
                "model": "",
                "temperature": temp,
                "max_tokens": tokens,
            }
            for key, _label, _desc, temp, tokens in SUB_AGENTS
        }
        self._features = {}
        adapter = defaults.get("adapter") or {}
        self._adapter = {
            "enabled": True,
            "mode": str(adapter.get("mode") or "client"),
            "host": str(adapter.get("host") or "127.0.0.1"),
            "port": int(adapter.get("port") or 3000),
            "path": str(adapter.get("path") or "/"),
            "access_token": "",
            "manage_process": False,
            "process_path": "",
            "auto_restart": True,
            "whitelist": {
                "mode": str(adapter.get("whitelist_mode") or "verify"),
                "qq_ids": [],
                "group_ids": [],
            },
        }
        persona_options = [
            str(item.get("id") or item.get("name") or "") for item in self._personas
        ]
        self._persona = (
            str(defaults.get("persona") or "")
            if str(defaults.get("persona") or "") in persona_options
            else (persona_options[0] if persona_options else "大肥鱼")
        )
        self._persona_source = "builtin"
        self._persona_brief = ""
        self._max_context_tokens = None
        self.path_label.set_text(
            f"数据目录：{data.get('data_dir') or '—'}\n"
            f"配置文件：{data.get('config_file') or '—'}"
        )
        self.status_label.remove_css_class("danger-text")
        self.status_label.set_text("按提示完成配置后，会自动写入 config.yaml 并启动 Runtime。")
        self._set_busy(False)
        self._set_ready(True)
        self._show_step("welcome")

    def _show_step(self, step_id: str, *, refresh_progress: bool = True) -> None:
        self._current = step_id
        self._error = ""
        self.error_label.set_visible(False)
        meta = self._steps_meta.get(step_id) or {}
        self.step_title.set_text(str(meta.get("title") or step_id))
        self.step_subtitle.set_text(str(meta.get("subtitle") or ""))
        self.step_subtitle.set_visible(bool(meta.get("subtitle")))
        self.skip_button.set_visible(bool(meta.get("can_skip")))
        self.back_button.set_sensitive(step_id != "welcome" and not self._busy)
        self._validate_step = lambda: None
        widgets.clear(self.step_card)
        self.step_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.step_card.append(self.step_host)
        builder = getattr(self, f"_step_{step_id}", None)
        self._building_step = True
        try:
            if callable(builder):
                builder()
            else:
                self.step_host.append(
                    widgets.muted(
                        "这一步暂时没有可视化表单，可以直接点「下一步」。"
                        "配置完成后可在设置页调整。"
                    )
                )
        finally:
            self._building_step = False
        if refresh_progress:
            self._refresh_progress()

    def _refresh_progress(self) -> None:
        if self.api is None:
            return
        self._progress_ok = False
        if not self._busy:
            self.next_button.set_sensitive(False)
            self.skip_button.set_sensitive(False)
        token = (self._current, self._path, self._persona_source)

        def _do() -> dict[str, Any]:
            return self.api.post(
                "/api/setup/step",
                {
                    "current": self._current,
                    "path": self._path,
                    "direction": "next",
                    "context": {"persona_source": self._persona_source},
                },
                timeout=30,
            )

        def _done(result: dict[str, Any]) -> None:
            if token != (self._current, self._path, self._persona_source):
                return
            self._progress_ok = True
            if self._progress_retry_source:
                GLib.source_remove(self._progress_retry_source)
                self._progress_retry_source = 0
            progress = result.get("progress") or [0, 1]
            try:
                index, total = int(progress[0]), int(progress[1])
            except (TypeError, ValueError, IndexError):
                index, total = 0, 1
            self._progress = [index, total]
            self._is_last = bool(result.get("is_last"))
            self.progress_label.set_text(f"第 {index} / {total} 步")
            self.progress_bar.set_fraction(
                max(0.0, min(1.0, index / total if total else 0.0))
            )
            self.next_button.set_label("完成配置" if self._is_last else "下一步")
            self.skip_button.set_visible(
                not self._is_last
                and bool((self._steps_meta.get(self._current) or {}).get("can_skip"))
            )
            if not self._busy:
                self.next_button.set_sensitive(True)
                self.skip_button.set_sensitive(True)

        def _failed(exc: BaseException) -> None:
            if token != (self._current, self._path, self._persona_source):
                return
            self._progress_ok = False
            self.next_button.set_sensitive(False)
            self.skip_button.set_sensitive(False)
            self._set_error(f"读取向导进度失败：{exc}，请稍后重试")
            if not self._progress_retry_source:
                self._progress_retry_source = GLib.timeout_add_seconds(
                    3, self._retry_progress
                )

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _retry_progress(self) -> bool:
        self._progress_retry_source = 0
        if self._busy or self._progress_ok or self.api is None:
            return False
        self._refresh_progress()
        return False

    def _advance(self) -> None:
        if self._busy:
            return
        problem = self._validate_step()
        if problem:
            self._set_error(problem)
            return
        self._error = ""
        self.error_label.set_visible(False)
        if not self._progress_ok:
            self._set_error("向导进度尚未确认，请稍后重试。")
            self._refresh_progress()
            return
        if self._is_last:
            self._submit()
            return
        self._ask_flow("next", validate_first=False)

    def _skip(self) -> None:
        if not self._busy:
            self._ask_flow("next", validate_first=False)

    def _go_back(self) -> None:
        if not self._busy:
            self._ask_flow("prev", validate_first=False)

    def _ask_flow(self, direction: str, *, validate_first: bool) -> None:
        if validate_first:
            problem = self._validate_step()
            if problem:
                self._set_error(problem)
                return
        if self.api is None:
            return
        self._set_busy(True, "正在准备下一步…")

        def _do() -> dict[str, Any]:
            return self.api.post(
                "/api/setup/step",
                {
                    "current": self._current,
                    "path": self._path,
                    "direction": direction,
                    "context": {"persona_source": self._persona_source},
                },
                timeout=30,
            )

        def _done(result: dict[str, Any]) -> None:
            self._set_busy(False)
            target = result.get("next") if direction == "next" else result.get("prev")
            if not target:
                if direction == "next":
                    self._submit()
                return
            self._show_step(str(target))

        def _failed(exc: BaseException) -> None:
            self._set_busy(False)
            self._set_error(f"步骤切换失败：{exc}")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if busy:
            self.status_label.set_text(message)
            self.next_button.set_sensitive(False)
            self.back_button.set_sensitive(False)
            self.skip_button.set_sensitive(False)
        else:
            self.next_button.set_sensitive(self._progress_ok)
            self.back_button.set_sensitive(self._current != "welcome")
            self.skip_button.set_sensitive(self._progress_ok)

    def _set_ready(self, ready: bool) -> None:
        self.next_button.set_sensitive(ready and self._progress_ok)
        self.back_button.set_sensitive(False)
        self.skip_button.set_sensitive(ready and self._progress_ok)

    def _set_error(self, message: str) -> None:
        self._error = message
        self.error_label.set_text(message)
        self.error_label.set_visible(bool(message))

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------
    def _field(self, title: str, control: Gtk.Widget, help_text: str = "") -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(widgets.label(title, css="field-label"))
        box.append(control)
        if help_text:
            box.append(widgets.muted(help_text))
        return box

    def _switch_row(self, title: str, subtitle: str, active: bool) -> tuple[Gtk.Box, Gtk.Switch]:
        card = widgets.card(spacing=3, padding=10)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toggle = widgets.switch(active)
        row.append(toggle)
        row.append(widgets.label(title, css="section-title"))
        card.append(row)
        card.append(widgets.muted(subtitle))
        return card, toggle

    def _add(self, *children: Gtk.Widget) -> None:
        for child in children:
            self.step_host.append(child)

    def _preset(self, preset_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self._presets if str(item.get("id")) == preset_id),
            None,
        )

    def _preset_models(self, preset_id: str) -> list[dict[str, Any]]:
        preset = self._preset(preset_id)
        return list((preset or {}).get("models") or [])

    def _reasoning_options(self) -> list[str]:
        preset = self._preset(str(self._provider.get("preset") or ""))
        model_id = str(self._provider.get("model") or "")
        model = next(
            (
                item
                for item in (preset or {}).get("models") or []
                if str(item.get("id") or "") == model_id
            ),
            None,
        )
        options = list((model or {}).get("reasoning_effort_options") or [])
        if not options:
            options = list(
                (preset or {}).get("reasoning_effort_options") or []
            )
        return [str(item) for item in options] or ["low", "medium", "high"]

    def _apply_preset(self, preset_id: str) -> None:
        preset = self._preset(preset_id)
        if not self._provider.get("preset"):
            # 离开展开中的自定义表单前，把手填内容存进草稿。
            self._custom_provider_draft = {
                key: self._provider.get(key)
                for key in (
                    "id",
                    "display_name",
                    "protocol",
                    "base_url",
                    "model",
                    "model_vendor",
                    "reasoning_style",
                    "reasoning_effort_style",
                )
            }
        self._provider["preset"] = preset_id or None
        if preset is None:
            draft = self._custom_provider_draft
            self._provider["id"] = str(draft.get("id") or "main_provider")
            self._provider["display_name"] = str(
                draft.get("display_name") or "自定义提供商"
            )
            self._provider["protocol"] = str(
                draft.get("protocol") or "openai_compat"
            )
            self._provider["base_url"] = str(draft.get("base_url") or "")
            self._provider["model"] = str(draft.get("model") or "")
            self._provider["model_vendor"] = draft.get("model_vendor") or None
            self._provider["reasoning_style"] = str(
                draft.get("reasoning_style") or ""
            )
            self._provider["reasoning_effort_style"] = str(
                draft.get("reasoning_effort_style") or ""
            )
            return
        self._provider["id"] = (
            f"{preset_id}_main" if preset_id != "deepseek" else "deepseek_main"
        )
        self._provider["display_name"] = str(
            preset.get("display_name") or preset_id
        )
        self._provider["protocol"] = str(preset.get("protocol") or "openai_compat")
        self._provider["base_url"] = str(preset.get("base_url") or "")
        self._provider["model_vendor"] = preset.get("model_vendor") or None
        self._provider["reasoning_style"] = str(
            preset.get("reasoning_style") or ""
        )
        self._provider["reasoning_effort_style"] = str(
            preset.get("reasoning_effort_style") or ""
        )
        models = self._preset_models(preset_id)
        if not self._provider.get("model") or not any(
            item.get("id") == self._provider.get("model") for item in models
        ):
            self._provider["model"] = str((models[0] if models else {}).get("id") or "")

    @staticmethod
    def _replace_dropdown(
        dropdown: Gtk.DropDown, options: list[tuple[str, str]], selected: str = ""
    ) -> None:
        labels = Gtk.StringList.new([name for _value, name in options])
        dropdown.set_model(labels)
        dropdown._values = [value for value, _name in options]  # type: ignore[attr-defined]
        values = getattr(dropdown, "_values", [])
        if selected in values:
            dropdown.set_selected(values.index(selected))
        elif options:
            dropdown.set_selected(0)

    # ------------------------------------------------------------------
    # Step: welcome
    # ------------------------------------------------------------------
    def _step_welcome(self) -> None:
        note = widgets.muted(
            "选一条路。两条路配出来的东西一样，只是问的问题多少不同。"
        )
        self._add(note)
        choices = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        choices.set_homogeneous(True)
        group: list[Gtk.ToggleButton] = []

        def _choice(
            path_value: str,
            title: str,
            desc: str,
            detail: str,
        ) -> Gtk.ToggleButton:
            button = Gtk.ToggleButton()
            button.add_css_class("choice-card")
            child = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            child.append(widgets.label(title, css="section-title"))
            child.append(widgets.label(desc, wrap=True))
            child.append(widgets.muted(detail))
            button.set_child(child)
            if group:
                button.set_group(group[0])

            def _toggled(widget: Gtk.ToggleButton, value: str = path_value) -> None:
                if widget.get_active():
                    self._path = value
                    self._refresh_progress()

            button.connect("toggled", _toggled)
            group.append(button)
            return button

        recommended = _choice(
            "recommended",
            "推荐",
            "只要一个主模型就能跑起来，大约 3 分钟。",
            "主模型 → 功能 → 记忆 → 渠道 → 人格 → 完成",
        )
        custom = _choice(
            "custom",
            "自定义",
            "每个 Agent 用哪个模型、参数怎么调，都由你决定。",
            "主模型 → 子 Agent → 功能 → 记忆 → 渠道 → 人格 → 完成",
        )
        (custom if self._path == "custom" else recommended).set_active(True)
        choices.append(recommended)
        choices.append(custom)
        self._add(choices)

    # ------------------------------------------------------------------
    # Step: main model
    # ------------------------------------------------------------------
    def _step_main_model_quick(self) -> None:
        if not self._presets:
            self._add(widgets.muted("没有可用的提供商预设；可返回自定义路径手动填写。"))
            self._validate_step = lambda: "没有可用的提供商预设"
            return
        preset_options = [
            (str(item.get("id") or ""), str(item.get("display_name") or item.get("id")))
            for item in self._presets
        ]
        preset_select = widgets.dropdown(
            preset_options, str(self._provider.get("preset") or "")
        )
        model_select = widgets.dropdown([("", "正在加载…")], "")
        self._replace_dropdown(
            model_select,
            [
                (str(item.get("id") or ""), str(item.get("display_name") or item.get("id")))
                for item in self._preset_models(str(self._provider.get("preset") or ""))
            ],
            str(self._provider.get("model") or ""),
        )
        key_entry = Gtk.Entry()
        key_entry.set_visibility(False)
        key_entry.set_placeholder_text("sk-…（只写入本地加密密钥库）")
        key_entry.set_text(str(self._provider.get("api_key") or ""))
        key_entry.connect(
            "changed",
            lambda entry: self._provider.__setitem__(
                "api_key", entry.get_text().strip()
            ),
        )
        link = Gtk.LinkButton(uri="", label="去获取 API Key")
        link.set_halign(Gtk.Align.START)
        hint = widgets.muted("")

        def _sync_link(*_args: Any) -> None:
            preset = self._preset(str(self._provider.get("preset") or ""))
            registration = str((preset or {}).get("registration_url") or "")
            if registration:
                link.set_uri(registration)
                link.set_visible(True)
            else:
                link.set_visible(False)
            hint.set_text(
                "当前预设："
                + str((preset or {}).get("display_name") or "自定义")
                + "；不确定选哪个就用 DeepSeek，中文便宜、缓存命中率高。"
            )

        def _preset_changed(*_args: Any) -> None:
            self._apply_preset(widgets.dropdown_value(preset_select))
            self._replace_dropdown(
                model_select,
                [
                    (str(item.get("id") or ""), str(item.get("display_name") or item.get("id")))
                    for item in self._preset_models(
                        str(self._provider.get("preset") or "")
                    )
                ],
                str(self._provider.get("model") or ""),
            )
            _sync_link()

        def _model_changed(*_args: Any) -> None:
            self._provider["model"] = widgets.dropdown_value(model_select)

        preset_select.connect("notify::selected", _preset_changed)
        model_select.connect("notify::selected", _model_changed)
        _sync_link()
        self._add(
            self._field("平台", preset_select),
            self._field("模型", model_select),
            self._field(
                "API Key",
                key_entry,
                "只写进加密的密钥库，不会出现在 config.yaml。",
            ),
            link,
            hint,
        )
        self._validate_step = self._validate_provider_quick

    def _validate_provider_quick(self) -> str | None:
        if not self._provider.get("api_key"):
            return "还没填 API Key。"
        if not self._provider.get("model"):
            return "还没选择模型。"
        if not re.match(
            r"^[a-z][a-z0-9_-]{0,63}$", str(self._provider.get("id") or "")
        ):
            return "Provider ID 只能用小写字母开头，后跟小写字母、数字、下划线或短横线。"
        return None

    def _step_main_model_custom(self) -> None:
        preset_options = [("", "自定义 / 中转站（不选预设）")] + [
            (str(item.get("id") or ""), str(item.get("display_name") or item.get("id")))
            for item in self._presets
        ]
        preset_select = widgets.dropdown(
            preset_options, str(self._provider.get("preset") or "")
        )
        provider_id = Gtk.Entry()
        provider_id.set_text(str(self._provider.get("id") or ""))
        provider_id.connect(
            "changed",
            lambda entry: self._provider.__setitem__(
                "id", entry.get_text().strip()
            ),
        )
        display_name = Gtk.Entry()
        display_name.set_text(str(self._provider.get("display_name") or ""))
        display_name.connect(
            "changed",
            lambda entry: self._provider.__setitem__(
                "display_name", entry.get_text().strip()
            ),
        )
        protocol = widgets.dropdown(
            PROTOCOLS, str(self._provider.get("protocol") or "openai_compat")
        )
        protocol.connect(
            "notify::selected",
            lambda *_args: self._provider.__setitem__(
                "protocol", widgets.dropdown_value(protocol)
            ),
        )
        model_vendor = widgets.dropdown(
            VENDOR_OPTIONS, str(self._provider.get("model_vendor") or "")
        )
        model_vendor.connect(
            "notify::selected",
            lambda *_args: self._provider.__setitem__(
                "model_vendor",
                widgets.dropdown_value(model_vendor) or None,
            ),
        )
        reasoning_style = widgets.dropdown(
            REASONING_STYLES, str(self._provider.get("reasoning_style") or "")
        )
        reasoning_style.connect(
            "notify::selected",
            lambda *_args: self._provider.__setitem__(
                "reasoning_style", widgets.dropdown_value(reasoning_style)
            ),
        )
        effort_style = widgets.dropdown(
            REASONING_EFFORT_STYLES,
            str(self._provider.get("reasoning_effort_style") or ""),
        )
        effort_style.connect(
            "notify::selected",
            lambda *_args: self._provider.__setitem__(
                "reasoning_effort_style",
                widgets.dropdown_value(effort_style),
            ),
        )
        base_url = Gtk.Entry()
        base_url.set_text(str(self._provider.get("base_url") or ""))
        base_url.set_placeholder_text("https://api.example.com/v1")
        base_url.connect(
            "changed",
            lambda entry: self._provider.__setitem__(
                "base_url", entry.get_text().strip()
            ),
        )
        model_entry = Gtk.Entry()
        model_entry.set_text(str(self._provider.get("model") or ""))
        model_entry.set_placeholder_text("例如 deepseek-v4-flash")
        model_entry.connect(
            "changed",
            lambda entry: self._provider.__setitem__(
                "model", entry.get_text().strip()
            ),
        )
        key_entry = Gtk.Entry()
        key_entry.set_visibility(False)
        key_entry.set_placeholder_text("sk-…")
        key_entry.set_text(str(self._provider.get("api_key") or ""))
        key_entry.connect(
            "changed",
            lambda entry: self._provider.__setitem__(
                "api_key", entry.get_text().strip()
            ),
        )
        key_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        key_entry.set_hexpand(True)
        key_row.append(key_entry)
        key_toggle = widgets.button("显示")
        key_toggle.connect(
            "clicked",
            lambda _b: (
                key_entry.set_visibility(not key_entry.get_visibility()),
                key_toggle.set_label(
                    "隐藏" if key_entry.get_visibility() else "显示"
                ),
            ),
        )
        key_row.append(key_toggle)
        timeout = Gtk.SpinButton.new_with_range(5, 600, 1)
        timeout.set_value(float(self._provider.get("timeout_seconds") or 120))
        timeout.connect(
            "value-changed",
            lambda spin: self._provider.__setitem__(
                "timeout_seconds", float(spin.get_value())
            ),
        )
        temp = _float_spin(0.0, 2.0, 0.1, float(self._chat["temperature"]))
        top_p = _float_spin(0.0, 1.0, 0.05, float(self._chat["top_p"]))
        max_tokens = _int_spin(1, 2_000_000, int(self._chat["max_tokens"]))
        temp.connect(
            "value-changed",
            lambda spin: self._chat.__setitem__("temperature", float(spin.get_value())),
        )
        top_p.connect(
            "value-changed",
            lambda spin: self._chat.__setitem__("top_p", float(spin.get_value())),
        )
        max_tokens.connect(
            "value-changed",
            lambda spin: self._chat.__setitem__("max_tokens", int(spin.get_value())),
        )
        reasoning = widgets.switch(bool(self._chat.get("reasoning")))
        reasoning_options = self._reasoning_options()
        current_budget = str(self._chat.get("reasoning_budget") or "")
        if current_budget not in reasoning_options:
            current_budget = (
                "medium"
                if "medium" in reasoning_options
                else reasoning_options[0]
            )
            self._chat["reasoning_budget"] = current_budget
        budget = widgets.dropdown(
            [
                (
                    value,
                    EFFORT_LABELS.get(value, value),
                )
                for value in reasoning_options
            ],
            current_budget,
        )

        def _toggle_reasoning(
            widget: Gtk.Switch, *_args: Any
        ) -> None:
            active = bool(widget.get_active())
            self._chat["reasoning"] = active
            budget_field.set_visible(active)

        reasoning.connect("notify::active", _toggle_reasoning)
        budget.connect(
            "notify::selected",
            lambda *_args: self._chat.__setitem__(
                "reasoning_budget", widgets.dropdown_value(budget)
            ),
        )

        def _apply_and_rebuild(*_args: Any) -> None:
            self._apply_preset(widgets.dropdown_value(preset_select))
            self._show_step("main_model_custom", refresh_progress=False)

        preset_select.connect("notify::selected", _apply_and_rebuild)
        reasoning_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reasoning_row.append(reasoning)
        reasoning_row.append(widgets.label("启用思考模式"))
        budget_field = self._field(
            "思考强度",
            budget,
            (
                "档位来自当前预设模型文档；越高越慢越贵。"
                if "max" in reasoning_options
                else "越高越慢越贵，复杂任务再调高。"
            ),
        )
        budget_field.set_visible(bool(self._chat.get("reasoning")))
        self._add(
            widgets.muted(
                "中转站也走这里：预设选「自定义」，把 Base URL 换成中转地址即可。"
            ),
            self._field("预设", preset_select),
            self._field("Provider ID", provider_id),
            self._field("显示名称", display_name),
            self._field("协议", protocol),
            self._field("上游模型厂商（能力识别）", model_vendor),
            self._field("Base URL", base_url),
            self._field("模型 ID", model_entry),
            self._field("API Key", key_row),
            self._field("思考参数风格", reasoning_style),
            self._field("思考强度传递", effort_style),
            self._field("请求超时（秒）", timeout),
            self._field("温度", temp),
            self._field("top_p", top_p),
            self._field("最大输出 token", max_tokens),
            reasoning_row,
            budget_field,
        )
        self._validate_step = self._validate_provider_custom

    def _validate_provider_custom(self) -> str | None:
        if not re.match(
            r"^[a-z][a-z0-9_-]{0,63}$", str(self._provider.get("id") or "")
        ):
            return "Provider ID 只能用小写字母开头，后跟小写字母、数字、下划线或短横线。"
        if not self._provider.get("api_key"):
            return "还没填 API Key。"
        if not self._provider.get("model"):
            return "还没填模型 ID。"
        if (
            not self._provider.get("preset")
            and not self._provider.get("base_url")
        ):
            return "自定义提供商必须填写 Base URL。"
        return None

    # ------------------------------------------------------------------
    # Step: other agents
    # ------------------------------------------------------------------
    def _step_other_agents(self) -> None:
        self._add(
            widgets.muted(
                "这三个可以各自用不同的模型。不折腾的话让它们跟随主模型就行。"
            )
        )
        for key, label, desc, default_temp, default_tokens in SUB_AGENTS:
            cfg = self._agents.setdefault(
                key,
                {
                    "enabled": True,
                    "provider": "",
                    "model": "",
                    "temperature": default_temp,
                    "max_tokens": default_tokens,
                },
            )
            card, toggle = self._switch_row(label, desc, bool(cfg.get("enabled", True)))
            toggle.connect(
                "notify::active",
                lambda widget, _pspec, c=cfg: c.__setitem__(
                    "enabled", bool(widget.get_active())
                ),
            )
            provider = Gtk.Entry()
            provider.set_placeholder_text("留空跟随主模型")
            provider.set_text(str(cfg.get("provider") or ""))
            provider.connect(
                "changed",
                lambda entry, c=cfg: c.__setitem__(
                    "provider", entry.get_text().strip()
                ),
            )
            model = Gtk.Entry()
            model.set_placeholder_text("留空跟随主模型")
            model.set_text(str(cfg.get("model") or ""))
            model.connect(
                "changed",
                lambda entry, c=cfg: c.__setitem__(
                    "model", entry.get_text().strip()
                ),
            )
            temp = _float_spin(
                0.0, 2.0, 0.1, float(cfg.get("temperature", default_temp))
            )
            temp.connect(
                "value-changed",
                lambda spin, c=cfg: c.__setitem__(
                    "temperature", float(spin.get_value())
                ),
            )
            tokens = _int_spin(
                1, 2_000_000, int(cfg.get("max_tokens", default_tokens))
            )
            tokens.connect(
                "value-changed",
                lambda spin, c=cfg: c.__setitem__(
                    "max_tokens", int(spin.get_value())
                ),
            )
            card.append(self._field("提供商 ID", provider))
            card.append(self._field("模型 ID", model))
            card.append(self._field("温度", temp))
            card.append(self._field("最大输出 token", tokens))
            self._add(card)

    # ------------------------------------------------------------------
    # Step: features
    # ------------------------------------------------------------------
    def _feature(self, key: str) -> dict[str, Any]:
        return self._features.setdefault(key, {})

    def _step_features(self) -> None:
        self._add(
            widgets.muted("这些功能都可以之后再开，这里不选也不影响启动。")
        )
        # 主模型原生附图与独立 describe_image 是两条独立链路：即使不开
        # 独立视觉服务，也要让用户能声明主模型能否直接收图。
        vision_section = self._feature("vision")
        native_card = widgets.card(spacing=4, padding=10)
        native_card.append(
            widgets.label("主模型原生图片输入", css="section-title")
        )
        native_images = widgets.dropdown(
            MODEL_IMAGES,
            str(vision_section.get("main_model_images") or "auto"),
        )
        native_images.connect(
            "notify::selected",
            lambda *_args: vision_section.__setitem__(
                "main_model_images", widgets.dropdown_value(native_images)
            ),
        )
        native_card.append(native_images)
        native_card.append(
            widgets.muted(
                "关闭不影响下面的独立视觉接口；同时开启也不代表自动双调用。"
            )
        )
        self._add(native_card)
        for key, title, desc in (
            ("vision", "独立视觉识别", "主模型不能看图时，用另一个多模态模型提供 describe_image。"),
            ("web_search", "联网搜索", "让模型查实时信息；免费后端优先。"),
            ("weather", "天气", "和风天气 API；需要单独的密钥。"),
            ("tts", "语音合成", "把回复合成语音；EdgeTTS 无需密钥。"),
        ):
            section = self._feature(key)
            card, toggle = self._switch_row(
                title, desc, bool(section.get("enabled"))
            )

            def _toggle(widget: Gtk.ToggleButton, _pspec: Any = None, k: str = key) -> None:
                self._feature(k)["enabled"] = bool(widget.get_active())
                self._show_step("features", refresh_progress=False)

            toggle.connect("notify::active", _toggle)
            if section.get("enabled"):
                self._feature_fields(key, card)
            self._add(card)
        self._validate_step = self._validate_features

    def _feature_fields(self, key: str, card: Gtk.Box) -> None:
        section = self._feature(key)
        if key == "vision":
            default_provider = str(self._provider.get("id") or "")
            if default_provider and not section.get("provider"):
                section["provider"] = default_provider
            provider = Gtk.Entry()
            provider.set_placeholder_text("已有 provider ID（可复用其密钥/地址）")
            provider.set_text(str(section.get("provider") or ""))
            provider.connect(
                "changed",
                lambda entry: section.__setitem__(
                    "provider", entry.get_text().strip()
                ),
            )
            base_url = Gtk.Entry()
            base_url.set_placeholder_text("自定义 OpenAI 兼容端点（可选）")
            base_url.set_text(str(section.get("base_url") or ""))
            base_url.connect(
                "changed",
                lambda entry: section.__setitem__(
                    "base_url", entry.get_text().strip()
                ),
            )
            model = Gtk.Entry()
            model.set_placeholder_text("例如 glm-4v / qwen-vl-max")
            model.set_text(str(section.get("model") or ""))
            model.connect(
                "changed",
                lambda entry: section.__setitem__(
                    "model", entry.get_text().strip()
                ),
            )
            api_key = Gtk.Entry()
            api_key.set_visibility(False)
            api_key.set_placeholder_text("自定义端点时的独立密钥（可选）")
            api_key.set_text(str(section.get("api_key") or ""))
            api_key.connect(
                "changed",
                lambda entry: section.__setitem__(
                    "api_key", entry.get_text().strip()
                ),
            )
            reserve = _int_spin(
                256,
                65536,
                int(section.get("image_token_reserve") or 8192),
            )
            reserve.connect(
                "value-changed",
                lambda spin: section.__setitem__(
                    "image_token_reserve", int(spin.get_value())
                ),
            )
            limits = section.setdefault("image_limits", {})
            max_images = _int_spin(
                1,
                20,
                int(limits.get("max_images_per_request") or 20),
            )

            def _set_max_images(spin: Gtk.SpinButton) -> None:
                limits["max_images_per_request"] = int(spin.get_value())

            max_images.connect("value-changed", _set_max_images)
            card.append(self._field("视觉 provider", provider))
            card.append(self._field("视觉模型", model))
            card.append(self._field("独立 Base URL", base_url))
            card.append(self._field("独立 API Key", api_key))
            card.append(
                self._field(
                    "每图 token 预留",
                    reserve,
                    "项目资源预留，不是供应商精确账单；默认 8192。",
                )
            )
            card.append(
                self._field(
                    "单请求最大图片数",
                    max_images,
                    "资源护栏，只能调低到 1–20；需重启生效。",
                )
            )
        elif key == "web_search":
            free = widgets.switch(bool(section.get("free_enabled", True)))
            free.connect(
                "notify::active",
                lambda widget, *_args: section.__setitem__(
                    "free_enabled", bool(widget.get_active())
                ),
            )
            provider = widgets.dropdown(
                SEARCH_PROVIDERS, str(section.get("provider") or "bing_rss")
            )
            provider.connect(
                "notify::selected",
                lambda *_args: section.__setitem__(
                    "provider", widgets.dropdown_value(provider)
                ),
            )
            searxng = Gtk.Entry()
            searxng.set_placeholder_text("https://searxng.example.com")
            searxng.set_text(str(section.get("searxng_base_url") or ""))
            searxng.connect(
                "changed",
                lambda entry: section.__setitem__(
                    "searxng_base_url", entry.get_text().strip()
                ),
            )
            results = _int_spin(1, 20, int(section.get("max_results") or 5))
            results.connect(
                "value-changed",
                lambda spin: section.__setitem__(
                    "max_results", int(spin.get_value())
                ),
            )
            free_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            free_row.append(free)
            free_row.append(widgets.label("启用免费搜索后端"))
            card.append(free_row)
            card.append(self._field("免费后端", provider))
            card.append(self._field("SearXNG 地址", searxng))
            card.append(self._field("最多返回结果", results))
        elif key == "weather":
            host = Gtk.Entry()
            host.set_text(str(section.get("host") or "devapi.qweather.com"))
            host.connect(
                "changed",
                lambda entry: section.__setitem__("host", entry.get_text().strip()),
            )
            api_key = Gtk.Entry()
            api_key.set_visibility(False)
            api_key.set_placeholder_text("和风天气 API Key")
            api_key.set_text(str(section.get("api_key") or ""))
            api_key.connect(
                "changed",
                lambda entry: section.__setitem__(
                    "api_key", entry.get_text().strip()
                ),
            )
            card.append(self._field("API 主机", host))
            card.append(self._field("API Key", api_key))
        elif key == "tts":
            tts_type = widgets.dropdown(
                [("api", "云端 API"), ("local", "本地模型")],
                str(section.get("type") or "api"),
            )
            tts_type.connect(
                "notify::selected",
                lambda *_args: (
                    section.__setitem__("type", widgets.dropdown_value(tts_type)),
                    self._show_step("features", refresh_progress=False),
                ),
            )
            card.append(self._field("类型", tts_type))
            if str(section.get("type") or "api") == "api":
                provider = widgets.dropdown(
                    [("edge", "EdgeTTS（免密钥）"), ("xfyun", "讯飞（需要密钥）")],
                    str(section.get("provider") or "edge"),
                )
                def _provider_changed(*_args: Any) -> None:
                    section["provider"] = widgets.dropdown_value(provider)
                    self._show_step("features", refresh_progress=False)

                provider.connect("notify::selected", _provider_changed)
                card.append(self._field("云端厂商", provider))
                if str(section.get("provider") or "edge") == "xfyun":
                    api_key = Gtk.Entry()
                    api_key.set_visibility(False)
                    api_key.set_placeholder_text("讯飞 API Key")
                    api_key.set_text(str(section.get("api_key") or ""))
                    api_key.connect(
                        "changed",
                        lambda entry: section.__setitem__(
                            "api_key", entry.get_text().strip()
                        ),
                    )
                    card.append(self._field("API Key", api_key))
            else:
                local_model = Gtk.Entry()
                local_model.set_text(
                    str(section.get("local_model") or "voxcpm2")
                )
                local_model.connect(
                    "changed",
                    lambda entry: section.__setitem__(
                        "local_model", entry.get_text().strip()
                    ),
                )
                card.append(self._field("本地模型", local_model))
                card.append(
                    widgets.muted(
                        "本地模型首次使用时会提示下载，也可以在「模型管理」里提前装好。"
                    )
                )

    def _validate_features(self) -> str | None:
        vision = self._features.get("vision") or {}
        if vision.get("enabled"):
            if not vision.get("model"):
                return "启用独立视觉后必须填写视觉模型 ID。"
            # provider 留空时后端会继承主 provider 的地址与密钥；只有
            # 用户显式填写自定义端点时才需要额外配置。
        search = self._features.get("web_search") or {}
        if search.get("enabled"):
            if not search.get("free_enabled"):
                return "联网搜索目前需要在向导中启用免费搜索后端。"
            if search.get("provider") == "searxng" and not search.get(
                "searxng_base_url"
            ):
                return "选择 SearXNG 后必须填写实例地址。"
        weather = self._features.get("weather") or {}
        if weather.get("enabled") and not weather.get("api_key"):
            return "启用天气后必须填写和风天气 API Key。"
        tts = self._features.get("tts") or {}
        if tts.get("enabled"):
            if str(tts.get("type") or "api") == "api":
                if str(tts.get("provider") or "edge") == "xfyun" and not tts.get(
                    "api_key"
                ):
                    return "讯飞 TTS 需要填写 API Key。"
            elif not str(tts.get("local_model") or "").strip():
                return "本地 TTS 需要填写本地模型名。"
        return None

    # ------------------------------------------------------------------
    # Step: embedding / memory
    # ------------------------------------------------------------------
    def _step_embedding(self) -> None:
        memory = self._features.setdefault("long_term_memory", {"mode": "file"})
        embedding = self._features.setdefault("embedding", {})
        mode = widgets.dropdown(
            [
                ("file", "重要记忆文件（够用且省钱）"),
                ("rag", "向量检索（对话多时更聪明）"),
            ],
            str(memory.get("mode") or "file"),
        )
        mode.connect(
            "notify::selected",
            lambda *_args: (
                memory.__setitem__("mode", widgets.dropdown_value(mode)),
                self._show_step("embedding", refresh_progress=False),
            ),
        )
        self._add(
            widgets.muted('决定人格怎么"记住"以前的事。'),
            self._field("长期记忆方式", mode),
        )
        if str(memory.get("mode") or "file") != "rag":
            embedding["enabled"] = False
            self._validate_step = lambda: None
            return
        embedding["enabled"] = True
        emb_type = widgets.dropdown(
            [("api", "云端 API"), ("local", "本地模型")],
            str(embedding.get("type") or "api"),
        )
        emb_type.connect(
            "notify::selected",
            lambda *_args: (
                embedding.__setitem__("type", widgets.dropdown_value(emb_type)),
                self._show_step("embedding", refresh_progress=False),
            ),
        )
        self._add(self._field("Embedding 类型", emb_type))
        if str(embedding.get("type") or "api") == "api":
            provider = Gtk.Entry()
            provider.set_placeholder_text("引用一个支持 embeddings 的 provider ID")
            provider.set_text(str(embedding.get("provider") or ""))
            provider.connect(
                "changed",
                lambda entry: embedding.__setitem__(
                    "provider", entry.get_text().strip()
                ),
            )
            model = Gtk.Entry()
            model.set_placeholder_text("如 text-embedding-3-small")
            model.set_text(str(embedding.get("api_model") or ""))
            model.connect(
                "changed",
                lambda entry: embedding.__setitem__(
                    "api_model", entry.get_text().strip()
                ),
            )
            self._add(
                self._field("provider", provider),
                self._field("模型", model),
            )
        else:
            quality = widgets.dropdown(
                [
                    ("performance", "performance — all-MiniLM-L6（约 23MB）"),
                    ("quality", "quality — bge-large-zh（约 400MB）"),
                ],
                str(embedding.get("local_quality") or "performance"),
            )
            quality.connect(
                "notify::selected",
                lambda *_args: embedding.__setitem__(
                    "local_quality", widgets.dropdown_value(quality)
                ),
            )
            self._add(
                self._field("本地档位", quality),
                widgets.muted(
                    "本地模型首次使用时会自动下载，也可以在「模型管理」里提前装好。"
                ),
            )
        self._validate_step = self._validate_embedding

    def _validate_embedding(self) -> str | None:
        memory = self._features.get("long_term_memory") or {}
        if str(memory.get("mode") or "file") != "rag":
            return None
        embedding = self._features.get("embedding") or {}
        if (
            str(embedding.get("type") or "api") == "api"
            and not embedding.get("provider")
        ):
            return "选了向量检索，就得填一个 embedding provider。"
        return None

    # ------------------------------------------------------------------
    # Step: adapter
    # ------------------------------------------------------------------
    def _step_adapter(self) -> None:
        adapter = self._adapter
        enabled = widgets.switch(bool(adapter.get("enabled", True)))
        enabled.connect(
            "notify::active",
            lambda widget, *_args: adapter.__setitem__("enabled", bool(widget.get_active())),
        )
        enabled_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        enabled_row.append(enabled)
        enabled_row.append(widgets.label("启用 NapCat 渠道"))
        mode = widgets.dropdown(
            [
                ("client", "client（连接 NapCat 正向 WS）"),
                ("server", "server（等待 NapCat 接入）"),
            ],
            str(adapter.get("mode") or "client"),
        )
        mode.connect(
            "notify::selected",
            lambda *_args: adapter.__setitem__("mode", widgets.dropdown_value(mode)),
        )
        host = Gtk.Entry()
        host.set_text(str(adapter.get("host") or "127.0.0.1"))
        host.connect(
            "changed",
            lambda entry: adapter.__setitem__("host", entry.get_text().strip()),
        )
        port = _int_spin(1, 65535, int(adapter.get("port") or 3000))
        port.connect(
            "value-changed",
            lambda spin: adapter.__setitem__("port", int(spin.get_value())),
        )
        path = Gtk.Entry()
        path.set_text(str(adapter.get("path") or "/"))
        path.connect(
            "changed",
            lambda entry: adapter.__setitem__("path", entry.get_text().strip()),
        )
        token = Gtk.Entry()
        token.set_visibility(False)
        token.set_placeholder_text("NapCat Access Token（可选）")
        token.set_text(str(adapter.get("access_token") or ""))
        token.connect(
            "changed",
            lambda entry: adapter.__setitem__(
                "access_token", entry.get_text().strip()
            ),
        )
        manage = widgets.switch(bool(adapter.get("manage_process")))
        manage.connect(
            "notify::active",
            lambda widget, *_args: adapter.__setitem__(
                "manage_process", bool(widget.get_active())
            ),
        )
        manage_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        manage_row.append(manage)
        manage_row.append(widgets.label("由 Karen 拉起 NapCat"))
        process_path = Gtk.Entry()
        process_path.set_placeholder_text("NapCat 可执行文件或启动脚本")
        process_path.set_text(str(adapter.get("process_path") or ""))
        process_path.connect(
            "changed",
            lambda entry: adapter.__setitem__(
                "process_path", entry.get_text().strip()
            ),
        )
        auto_restart = widgets.switch(bool(adapter.get("auto_restart", True)))
        auto_restart.connect(
            "notify::active",
            lambda widget, *_args: adapter.__setitem__(
                "auto_restart", bool(widget.get_active())
            ),
        )
        restart_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        restart_row.append(auto_restart)
        restart_row.append(widgets.label("连接断开时自动重启"))
        whitelist = adapter.setdefault(
            "whitelist", {"mode": "verify", "qq_ids": [], "group_ids": []}
        )
        wl_mode = widgets.dropdown(
            WHITELIST_MODES, str(whitelist.get("mode") or "verify")
        )
        wl_mode.connect(
            "notify::selected",
            lambda *_args: whitelist.__setitem__(
                "mode", widgets.dropdown_value(wl_mode)
            ),
        )
        wl_qq = widgets.text_view(
            ", ".join(str(x) for x in whitelist.get("qq_ids") or []),
            height=72,
        )
        wl_qq.text_view.get_buffer().connect(
            "changed",
            lambda buffer: whitelist.__setitem__(
                "qq_ids",
                _parse_ids(
                    buffer.get_text(
                        buffer.get_start_iter(), buffer.get_end_iter(), True
                    )
                ),
            ),
        )
        wl_group = widgets.text_view(
            ", ".join(str(x) for x in whitelist.get("group_ids") or []),
            height=72,
        )
        wl_group.text_view.get_buffer().connect(
            "changed",
            lambda buffer: whitelist.__setitem__(
                "group_ids",
                _parse_ids(
                    buffer.get_text(
                        buffer.get_start_iter(), buffer.get_end_iter(), True
                    )
                ),
            ),
        )
        process_field = self._field("NapCat 进程路径", process_path)
        wl_mode_field = self._field("入站策略", wl_mode)
        wl_qq_field = self._field(
            "白名单 QQ",
            wl_qq,
            "一行一个，也可用逗号、空格、顿号或分号分隔。",
        )
        wl_group_field = self._field(
            "白名单群",
            wl_group,
            "一行一个，也可用逗号、空格、顿号或分号分隔。",
        )

        def _sync_adapter_visibility(*_args: Any) -> None:
            managing = bool(manage.get_active())
            process_field.set_visible(managing)
            restart_row.set_visible(managing)
            whitelisted = widgets.dropdown_value(wl_mode) == "whitelist"
            wl_qq_field.set_visible(whitelisted)
            wl_group_field.set_visible(whitelisted)

        manage.connect("notify::active", _sync_adapter_visibility)
        wl_mode.connect("notify::selected", _sync_adapter_visibility)
        _sync_adapter_visibility()
        self._add(
            widgets.muted(
                "连接 NapCat 后才会收发 QQ 消息；先跳过也不影响人格试跑。"
            ),
            enabled_row,
            self._field("NapCat 连接模式", mode),
            self._field("主机", host),
            self._field("端口", port),
            self._field("WebSocket 路径", path),
            self._field("Access Token", token),
            manage_row,
            process_field,
            restart_row,
            wl_mode_field,
            wl_qq_field,
            wl_group_field,
        )
        self._validate_step = lambda: None

    # ------------------------------------------------------------------
    # Step: persona
    # ------------------------------------------------------------------
    def _step_persona(self) -> None:
        persona_names = [
            str(item.get("name") or item.get("id") or "")
            for item in self._personas
        ] or ["大肥鱼"]
        persona_select = widgets.dropdown(
            [(name, name) for name in persona_names], self._persona
        )
        persona_select.connect(
            "notify::selected",
            lambda *_args: setattr(
                self, "_persona", widgets.dropdown_value(persona_select)
            ),
        )
        self._add(
            widgets.muted("先挑一个人格。之后可以在「人格」页随时新建或换。"),
            self._field("用哪个人格", persona_select),
        )
        choices = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        choices.set_homogeneous(True)
        group: list[Gtk.ToggleButton] = []

        def _source_button(value: str, title: str, desc: str) -> Gtk.ToggleButton:
            button = Gtk.ToggleButton()
            button.add_css_class("choice-card")
            child = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            child.append(widgets.label(title, css="section-title"))
            child.append(widgets.label(desc, wrap=True))
            button.set_child(child)
            if group:
                button.set_group(group[0])

            def _toggled(widget: Gtk.ToggleButton, v: str = value) -> None:
                if self._building_step:
                    return
                if widget.get_active():
                    self._persona_source = v
                    self._show_step("persona", refresh_progress=False)

            button.connect("toggled", _toggled)
            group.append(button)
            return button

        builtin = _source_button(
            "builtin", "用内置人格", "先用自带的角色试跑，之后随时能换。"
        )
        create = _source_button(
            "create", "生成一个新人格", "填几个关键词，让模型帮你写人设。"
        )
        (create if self._persona_source == "create" else builtin).set_active(True)
        choices.append(builtin)
        choices.append(create)
        self._add(widgets.label("或者", css="stat-label"), choices)
        if self._persona_source == "create":
            brief = widgets.text_view(self._persona_brief, height=120)
            brief.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            brief.text_view.get_buffer().connect(
                "changed",
                lambda buffer: setattr(
                    self,
                    "_persona_brief",
                    buffer.get_text(
                        buffer.get_start_iter(), buffer.get_end_iter(), True
                    ),
                ),
            )
            self._add(
                self._field(
                    "想要什么样的人格",
                    brief,
                    "先写下来。配置完成后到「人格 → 新建人格」，这段描述会替你填好，"
                    "再让 AI 生成完整人设。",
                )
            )
        self._validate_step = lambda: None

    def _step_persona_create(self) -> None:
        brief = widgets.text_view(self._persona_brief, height=140)
        brief.text_view.get_buffer().connect(
            "changed",
            lambda buffer: setattr(
                self,
                "_persona_brief",
                buffer.get_text(
                    buffer.get_start_iter(), buffer.get_end_iter(), True
                ),
            ),
        )
        self._add(
            widgets.muted(
                "写几句话描述你想要的人格。这一步先存下来——配置完成后到"
                "「人格 → 新建人格」，这段描述会替你填好，再让 AI 生成完整人设。"
            ),
            self._field("人格描述", brief),
        )
        self._validate_step = lambda: None

    # ------------------------------------------------------------------
    # Step: summary
    # ------------------------------------------------------------------
    def _step_summary(self) -> None:
        provider = self._provider
        rows = [
            ["路径", "自定义" if self._path == "custom" else "推荐"],
            [
                "主模型",
                f"{provider.get('preset') or '自定义'} · "
                f"{provider.get('model') or '（未填）'}",
            ],
            ["API Key", "已填写" if provider.get("api_key") else "未填（启动后调用会失败）"],
        ]
        if provider.get("base_url"):
            rows.append(["Base URL", str(provider["base_url"])])
        for key, label, _desc, _temp, _tokens in SUB_AGENTS:
            cfg = self._agents.get(key) or {}
            rows.append(
                [
                    label,
                    "启用"
                    + (f" · {cfg.get('model')}" if cfg.get("model") else " · 跟随主模型")
                    if cfg.get("enabled", True)
                    else "关闭",
                ]
            )
        enabled = [
            {"vision": "视觉", "web_search": "联网搜索", "weather": "天气", "tts": "语音"}[key]
            for key in ("vision", "web_search", "weather", "tts")
            if (self._features.get(key) or {}).get("enabled")
        ]
        rows.append(["功能", "、".join(enabled) if enabled else "都关着"])
        memory = self._features.get("long_term_memory") or {}
        rows.append(
            [
                "长期记忆",
                "向量检索" if str(memory.get("mode") or "file") == "rag" else "重要记忆文件",
            ]
        )
        adapter = self._adapter
        rows.append(
            ["渠道", f"{adapter.get('mode')}://{adapter.get('host')}:{adapter.get('port')}"]
        )
        rows.append(
            ["入站策略", str((adapter.get("whitelist") or {}).get("mode") or "verify")]
        )
        rows.append(["人格", self._persona])
        self._add(
            widgets.muted("确认一下。点「完成配置」就会写盘并启动 Runtime。"),
            widgets.table(["项目", "值"], rows, weights=[0.7, 2.3]),
        )
        self._validate_step = self._validate_summary

    def _validate_summary(self) -> str | None:
        if not self._provider.get("api_key"):
            return "还没有填 API Key —— 没有密钥人格无法说话。"
        if not self._provider.get("model"):
            return "还没有选择模型。"
        # ``跳过`` 有意不逐步校验；汇总页再兜一次底，避免最后才由后端报错。
        provider_validator = (
            self._validate_provider_custom
            if self._path == "custom"
            else self._validate_provider_quick
        )
        for validator in (
            provider_validator,
            self._validate_features,
            self._validate_embedding,
        ):
            problem = validator()
            if problem:
                return problem
        return None

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def _submit(self) -> None:
        if self.api is None or self._busy:
            return
        problem = self._validate_step()
        if problem:
            self._set_error(problem)
            return
        self._set_busy(True, "正在写入配置并启动 Runtime…")
        self.status_label.remove_css_class("danger-text")
        payload = self._payload()

        def _do() -> dict[str, Any]:
            return self.api.post("/api/setup/apply", payload, timeout=180)

        def _done(result: dict[str, Any]) -> None:
            self._set_busy(False)
            message = str(result.get("message") or "配置已写入")
            self.status_label.set_text(message)
            self.toast(message)
            if result.get("ok"):
                if result.get("started") is False:
                    self.toast("配置已写入，但 Runtime 启动失败；请到总览查看错误")
                self.app.on_setup_finished()

        def _failed(exc: BaseException) -> None:
            self._set_busy(False)
            self.status_label.set_text(f"首次配置失败：{exc}")
            self.status_label.add_css_class("danger-text")

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def _payload(self) -> dict[str, Any]:
        provider = self._provider
        provider_id = str(provider.get("id") or "main_provider")
        provider_payload = {
            "id": provider_id,
            "preset": provider.get("preset") or None,
            "display_name": provider.get("display_name") or provider_id,
            "protocol": provider.get("protocol") or None,
            "base_url": provider.get("base_url") or None,
            "api_key": provider.get("api_key") or "",
            "model_vendor": provider.get("model_vendor") or None,
            "reasoning_style": provider.get("reasoning_style") or None,
            "reasoning_effort_style": (
                provider.get("reasoning_effort_style") or None
            ),
            "timeout_seconds": float(provider.get("timeout_seconds") or 120.0),
        }
        agents: dict[str, Any] = {}
        for key, _label, _desc, _temp, _tokens in SUB_AGENTS:
            cfg = self._agents.get(key) or {}
            if not cfg.get("enabled", True):
                agents[key] = {"enabled": False}
                continue
            agents[key] = {
                "enabled": True,
                "provider": cfg.get("provider") or provider_id,
                "model": cfg.get("model") or provider.get("model") or "",
                "temperature": float(cfg.get("temperature") or 0.3),
                "max_tokens": int(cfg.get("max_tokens") or 4096),
            }
        features: dict[str, Any] = {}
        secrets: dict[str, str] = {}
        vision = self._features.get("vision") or {}
        image_limits = vision.get("image_limits") or {}
        vision_common = {
            "main_model_images": str(
                vision.get("main_model_images") or "auto"
            ),
            "image_token_reserve": int(
                vision.get("image_token_reserve") or 8192
            ),
            "image_limits": {
                "max_images_per_request": int(
                    image_limits.get("max_images_per_request") or 20
                )
            },
        }
        if vision.get("enabled"):
            vision_payload = {
                "enabled": True,
                "type": "api",
                **vision_common,
                "provider": vision.get("provider") or None,
                "model": str(vision.get("model") or ""),
                "base_url": vision.get("base_url") or None,
            }
            if vision.get("api_key"):
                vision_payload["api_key"] = str(vision["api_key"])
                secrets["vision_key"] = str(vision["api_key"])
            features["vision"] = vision_payload
        else:
            features["vision"] = {"enabled": False, **vision_common}
        search = self._features.get("web_search") or {}
        if search.get("enabled"):
            features["web_search"] = {
                "enabled": True,
                "free_enabled": bool(search.get("free_enabled", True)),
                "provider": str(search.get("provider") or "bing_rss"),
                "searxng_base_url": str(search.get("searxng_base_url") or ""),
                "max_results": int(search.get("max_results") or 5),
            }
        else:
            features["web_search"] = {"enabled": False}
        weather = self._features.get("weather") or {}
        if weather.get("enabled"):
            features["weather"] = {
                "enabled": True,
                "host": str(weather.get("host") or "devapi.qweather.com"),
                "api_key_id": "weather_key",
            }
            if weather.get("api_key"):
                secrets["weather_key"] = str(weather["api_key"])
        else:
            features["weather"] = {"enabled": False}
        tts = self._features.get("tts") or {}
        if tts.get("enabled"):
            tts_type = str(tts.get("type") or "api")
            if tts_type == "api":
                tts_payload = {
                    "enabled": True,
                    "type": "api",
                    "provider": str(tts.get("provider") or "edge"),
                }
                if (
                    str(tts.get("provider") or "edge") == "xfyun"
                    and tts.get("api_key")
                ):
                    tts_payload["api_key_id"] = "tts_key"
                    secrets["tts_key"] = str(tts["api_key"])
            else:
                tts_payload = {
                    "enabled": True,
                    "type": "local",
                    "local_model": str(tts.get("local_model") or "voxcpm2"),
                }
            features["tts"] = tts_payload
        else:
            features["tts"] = {"enabled": False}
        memory = self._features.get("long_term_memory") or {}
        features["long_term_memory"] = {
            "mode": str(memory.get("mode") or "file")
        }
        embedding = self._features.get("embedding") or {}
        if str(memory.get("mode") or "file") == "rag":
            features["embedding"] = {
                "enabled": True,
                "type": str(embedding.get("type") or "api"),
                "provider": embedding.get("provider") or None,
                "api_model": str(embedding.get("api_model") or ""),
                "local_quality": str(
                    embedding.get("local_quality") or "performance"
                ),
            }
        else:
            features["embedding"] = {"enabled": False}
        adapter = self._adapter
        payload = {
            "providers": [provider_payload],
            "chat": {
                "provider": provider_id,
                "model": provider.get("model") or "",
                "temperature": float(self._chat.get("temperature") or 0.6),
                "top_p": float(self._chat.get("top_p") or 1.0),
                "max_tokens": int(self._chat.get("max_tokens") or 16384),
                "reasoning": bool(self._chat.get("reasoning")),
                "reasoning_budget": self._chat.get("reasoning_budget") or None,
            },
            "agents": agents,
            "features": features,
            "adapter": {
                "enabled": bool(adapter.get("enabled", True)),
                "mode": str(adapter.get("mode") or "client"),
                "host": str(adapter.get("host") or "127.0.0.1"),
                "port": int(adapter.get("port") or 3000),
                "path": str(adapter.get("path") or "/"),
                "access_token": str(adapter.get("access_token") or ""),
                "manage_process": bool(adapter.get("manage_process")),
                "process_path": str(adapter.get("process_path") or ""),
                "auto_restart": bool(adapter.get("auto_restart", True)),
                "whitelist": {
                    "mode": str(
                        (adapter.get("whitelist") or {}).get("mode") or "verify"
                    ),
                    "qq_ids": list(
                        (adapter.get("whitelist") or {}).get("qq_ids") or []
                    ),
                    "group_ids": list(
                        (adapter.get("whitelist") or {}).get("group_ids") or []
                    ),
                },
            },
            "persona": self._persona,
            "secrets": secrets,
        }
        if self._persona_source == "create" and self._persona_brief.strip():
            payload["persona_brief"] = {
                "personality": self._persona_brief.strip()
            }
        return payload


def _int_spin(low: int, high: int, value: int) -> Gtk.SpinButton:
    spin = Gtk.SpinButton.new_with_range(low, high, 1)
    spin.set_numeric(True)
    spin.set_value(int(value))
    return spin


def _float_spin(
    low: float, high: float, step: float, value: float
) -> Gtk.SpinButton:
    spin = Gtk.SpinButton.new_with_range(low, high, step)
    spin.set_digits(2 if step < 0.1 else 1)
    spin.set_value(float(value))
    return spin


def _parse_ids(text: str) -> list[int]:
    result: list[int] = []
    for chunk in re.split(r"[\s,，、;；]+", str(text or "")):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value > 0:
            result.append(value)
    return sorted(set(result))
