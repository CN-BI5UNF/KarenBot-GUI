"""Overview page matching the WebUI: activity, channel, health and usage."""

from __future__ import annotations

import math
import time
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from .base import Page  # noqa: E402

REFRESH_SECONDS = 2
UPDATE_REFRESH_SECONDS = 60

RANGES = [
    ("today", "今天"),
    ("7d", "7 天"),
    ("30d", "30 天"),
    ("all", "全部"),
]

ACTIVITY_TEXT = {
    "idle": "空闲",
    "thinking": "思考中",
    "tool": "调用工具中",
    "error": "出错了",
}

OPERATION_TEXT = {
    "chat": "聊天",
    "knowledge_research": "联网考究",
    "slang_extract": "黑话学习",
    "web_search_official": "官方搜索",
    "describe_image": "看图",
    "embedding": "Embedding",
    "summary": "摘要",
    "persona": "人格后台",
    "proactive": "主动思考",
    "social": "社交",
    "provider_health": "健康检查",
}


def _number(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if not math.isfinite(number):
        return "0"
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if number >= 10_000:
        return f"{number / 10_000:.2f}万"
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def _duration(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    if total < 60:
        return f"{total} 秒"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes} 分 {total % 60} 秒"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时 {minutes % 60} 分"
    return f"{hours // 24} 天 {hours % 24} 小时"


def _percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number * 100:.1f}%"


class OverviewPage(Page):
    refresh_on_activate = True
    page_id = "overview"
    page_title = "总览"
    page_subtitle = "运行状态、模型健康与用量。数据每 2 秒自动刷新。"
    page_icon = "speedometer-symbolic"

    def build(self) -> None:
        self._refresh_inflight = False
        self._update_inflight = False
        self._overview_error = False
        self._has_usage = False
        self._last_status_state = ""
        self._last_update_check = 0.0
        self._range = "today"
        self._timer_id = 0
        self._update_timer_id = 0
        self._usage_values: dict[str, Gtk.Label] = {}
        self._range_buttons: dict[str, Gtk.Button] = {}

        head = self.header(refresh=False)
        self.update_button = widgets.button(
            "发现新版本",
            icon="software-update-available-symbolic",
            css="suggested-action compact-button",
        )
        self.update_button.set_visible(False)
        self.update_button.connect(
            "clicked", lambda _b: self.app.show_page("updates")
        )
        head.append(self.update_button)
        restart = widgets.button("重启 Runtime")
        restart.set_tooltip_text("只重建运行时，不加载新代码")
        restart.connect("clicked", lambda _b: self.app._restart_runtime())
        head.append(restart)
        self.body.append(head)

        status_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status_grid.set_homogeneous(True)
        status_grid.set_valign(Gtk.Align.START)
        self.activity_card = widgets.card(spacing=6)
        self.activity_card.set_hexpand(True)
        self.adapter_card = widgets.card(spacing=6)
        self.adapter_card.set_hexpand(True)
        status_grid.append(self.activity_card)
        status_grid.append(self.adapter_card)
        self.body.append(status_grid)

        self.provider_card = widgets.card(spacing=6)
        self.body.append(self.provider_card)
        self._render_providers([])

        self.usage_card = widgets.card(spacing=6)
        self._build_usage_card()
        self.body.append(self.usage_card)
        self._render_usage({"available": False})

    # ------------------------------------------------------------------
    # Lifecycle / polling
    # ------------------------------------------------------------------
    def activate(self) -> None:
        super().activate()
        if not self._timer_id:
            self._timer_id = GLib.timeout_add_seconds(
                REFRESH_SECONDS, self._auto_tick
            )
        if not self._update_timer_id:
            self._update_timer_id = GLib.timeout_add_seconds(
                UPDATE_REFRESH_SECONDS, self._update_tick
            )
        if time.monotonic() - self._last_update_check >= UPDATE_REFRESH_SECONDS:
            self._fetch_update()

    def _auto_tick(self) -> bool:
        if not self.get_mapped():
            self._timer_id = 0
            return False
        self.refresh()
        return True

    def _update_tick(self) -> bool:
        if not self.get_mapped():
            self._update_timer_id = 0
            return False
        self._fetch_update()
        return True

    def refresh(self) -> None:
        if self._refresh_inflight or self.api is None:
            return
        self._refresh_inflight = True
        range_name = self._range

        def _fetch() -> dict[str, Any]:
            return self.api.get(f"/api/overview?range={range_name}", timeout=20)

        widgets.run_async(_fetch, on_success=self._render, on_error=self._error)

    def _fetch_update(self) -> None:
        if self._update_inflight or self.api is None:
            return
        self._update_inflight = True
        self._last_update_check = time.monotonic()

        def _fetch() -> dict[str, Any]:
            return self.api.get("/api/update/available", timeout=15)

        widgets.run_async(
            _fetch,
            on_success=self._render_update,
            on_error=self._update_error,
        )

    def _error(self, exc: BaseException) -> None:
        self._refresh_inflight = False
        self._overview_error = True
        widgets.clear(self.activity_card)
        self.activity_card.append(widgets.label("主模型状态", css="stat-label"))
        self.activity_card.append(
            widgets.badge("不可用", css="badge badge-bad")
        )
        self.activity_card.append(widgets.muted(str(exc)))
        if not self._has_usage:
            widgets.clear(self.usage_card)
            self._build_usage_card()
            self._render_usage({"available": False, "error": str(exc)})

    def apply_status(self, status: dict[str, Any]) -> None:
        self._last_status_state = str(status.get("state") or "")
        if (
            self._last_status_state == "running"
            and (self._overview_error or not self._has_usage)
            and not self._refresh_inflight
        ):
            self.refresh()

    def _render(self, data: dict[str, Any]) -> None:
        self._refresh_inflight = False
        self._overview_error = False
        usage = data.get("usage") or {}
        self._has_usage = bool(usage.get("available"))
        self._render_activity(data.get("activity") or {})
        self._render_adapter(data.get("status") or {})
        self._render_providers(data.get("providers") or [])
        self._render_usage(usage)

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    def _render_activity(self, activity: dict[str, Any]) -> None:
        widgets.clear(self.activity_card)
        state = str(activity.get("state") or "idle")
        text = ACTIVITY_TEXT.get(state, state)
        tone = (
            "badge badge-bad"
            if state == "error"
            else ("badge" if state == "idle" else "badge badge-ok")
        )
        self.activity_card.append(widgets.label("主模型状态", css="stat-label"))
        self.activity_card.append(widgets.badge(text, css=tone))
        agent = str(activity.get("agent") or "")
        model = str(activity.get("model") or "")
        self.activity_card.append(
            widgets.muted(
                f"{agent} · {model or '未指定模型'}" if agent else "—"
            )
        )
        detail = str(activity.get("text") or "")
        if detail:
            self.activity_card.append(widgets.muted(detail))

    def _render_adapter(self, status: dict[str, Any]) -> None:
        widgets.clear(self.adapter_card)
        state = str(status.get("state") or "unknown")
        connected = bool(status.get("adapter_connected"))
        adapter = status.get("adapter") or {}
        self.adapter_card.append(widgets.label("渠道状态", css="stat-label"))
        if state == "running":
            text, tone = (
                ("已就位", "badge badge-ok")
                if connected
                else ("未连接", "badge badge-idle")
            )
        else:
            failed = state == "error"
            text, tone = (
                ("启动失败", "badge badge-bad")
                if failed
                else ("未运行", "badge badge-warn")
            )
        self.adapter_card.append(widgets.badge(text, css=tone))
        if adapter:
            path = str(adapter.get("path") or "")
            address = (
                f"{adapter.get('mode', '')} · "
                f"{adapter.get('host', '')}:{adapter.get('port', '')}"
            )
            if path and path != "/":
                address += path
            name = str(adapter.get("name") or "default")
            self.adapter_card.append(widgets.muted(f"{name} · {address}"))
        else:
            self.adapter_card.append(widgets.muted("未配置渠道"))
        self.adapter_card.append(
            widgets.muted(f"已运行 {_duration(status.get('uptime_seconds'))}")
        )

    def _render_providers(self, providers: list[dict[str, Any]]) -> None:
        widgets.clear(self.provider_card)
        self.provider_card.append(widgets.label("模型健康", css="card-title"))
        self.provider_card.append(
            widgets.label(
                "启动时探测的连通性与延迟。", css="card-sub", wrap=True
            )
        )
        rows: list[list[Any]] = []
        for provider in providers:
            status = str(provider.get("status") or "unknown")
            ok = status in {"ok", "healthy"}
            warn = status in {"degraded", "unconfigured"}
            tone = (
                "badge badge-ok"
                if ok
                else (
                    "badge badge-warn"
                    if warn
                    else ("badge badge-bad" if status == "error" else "badge")
                )
            )
            latency = provider.get("latency_ms")
            rows.append(
                [
                    widgets.label(str(provider.get("id") or ""), css="monospace"),
                    widgets.badge(str(provider.get("text") or "—"), css=tone),
                    (
                        f"{round(float(latency))} ms"
                        if latency is not None
                        else "—"
                    ),
                    str(provider.get("message") or "—"),
                ]
            )
        self.provider_card.append(
            widgets.table(
                ["Provider", "状态", "延迟", "说明"],
                rows,
                weights=[2.0, 1.2, 1.0, 3.4],
                empty_text="还没有配置任何模型提供商",
            )
        )

    # ------------------------------------------------------------------
    # Usage card
    # ------------------------------------------------------------------
    def _build_usage_card(self) -> None:
        widgets.clear(self.usage_card)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        text.append(widgets.label("用量统计", css="card-title"))
        text.append(
            widgets.label(
                "总消耗包含全部历史记录；缓存命中率只使用当前 V2 口径。",
                css="card-sub",
                wrap=True,
            )
        )
        head.append(text)
        ranges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._range_buttons = {}
        for value, text_label in RANGES:
            button = widgets.button(text_label, css="compact-button")
            button.connect(
                "clicked", lambda _b, selected=value: self._set_range(selected)
            )
            ranges.append(button)
            self._range_buttons[value] = button
        head.append(ranges)
        self.usage_card.append(head)
        self._sync_range_buttons()

        self.usage_empty = widgets.muted("暂无用量数据")
        self.usage_card.append(self.usage_empty)

        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        grid.set_column_homogeneous(True)
        grid.set_margin_top(12)
        self._usage_grid = grid
        definitions = [
            ("request_count", "请求数（全历史）"),
            ("total_tokens", "总 token（全历史）"),
            ("cache_hit", "V2 缓存命中率"),
            ("completion_tokens", "输出 token（全历史）"),
            ("current_prompt_tokens", "V2 输入 token"),
            ("current_uncached_prompt_tokens", "V2 未命中输入"),
            ("current_cached_tokens", "V2 命中缓存"),
            ("current_cache_creation_tokens", "V2 写入缓存"),
            ("reasoning_tokens", "推理 token（全历史）"),
            ("estimate_error", "V2 估算误差"),
            ("estimate_samples", "V2 估算样本"),
            ("current_estimated_prompt_tokens", "V2 估算输入"),
        ]
        self._usage_values = {}
        for index, (key, label_text) in enumerate(definitions):
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            tile.set_hexpand(True)
            tile.append(widgets.label(label_text, css="stat-label", wrap=True))
            value = widgets.label("—", css="stat-value")
            tile.append(value)
            grid.attach(tile, index % 4, index // 4, 1, 1)
            self._usage_values[key] = value
        self.usage_card.append(grid)

        self.usage_sample_note = widgets.muted("")
        self.usage_card.append(self.usage_sample_note)
        self.usage_legacy_note = widgets.muted("")
        self.usage_legacy_note.set_visible(False)
        self.usage_card.append(self.usage_legacy_note)
        self.usage_unknown_note = widgets.muted("")
        self.usage_unknown_note.set_visible(False)
        self.usage_card.append(self.usage_unknown_note)
        self.usage_inconsistent_note = widgets.muted("")
        self.usage_inconsistent_note.set_visible(False)
        self.usage_card.append(self.usage_inconsistent_note)
        self.usage_ops_label = widgets.label("按用途（V2 口径）", css="field-help")
        self.usage_ops_label.set_margin_top(10)
        self.usage_ops_label.set_visible(False)
        self.usage_card.append(self.usage_ops_label)
        self.usage_ops_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0
        )
        self.usage_ops_host.set_visible(False)
        self.usage_card.append(self.usage_ops_host)

    def _set_range(self, value: str) -> None:
        if value == self._range:
            return
        self._range = value
        self._sync_range_buttons()
        self.refresh()

    def _sync_range_buttons(self) -> None:
        for value, button in self._range_buttons.items():
            if value == self._range:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def _render_usage(self, usage: dict[str, Any]) -> None:
        available = bool(usage.get("available"))
        self.usage_empty.set_visible(not available)
        self.usage_empty.set_text(
            str(usage.get("error") or "暂无用量数据")
        )
        self._usage_grid.set_visible(available)
        self.usage_sample_note.set_visible(available)
        self.usage_ops_label.set_visible(False)
        self.usage_ops_host.set_visible(False)
        for note in (
            self.usage_legacy_note,
            self.usage_unknown_note,
            self.usage_inconsistent_note,
        ):
            note.set_visible(False)
        if not available:
            return

        current_count = int(usage.get("current_semantics_request_count") or 0)
        current_available = (
            current_count > 0
            and usage.get("current_semantics_available") is not False
        )
        ratio = usage.get("current_cache_hit_rate")
        if ratio is None:
            ratio = usage.get("cache_hit_rate")
        hit_text = _percent(ratio) if current_available else "—"
        current_value = (
            (lambda value: _number(value))
            if current_available
            else (lambda _value: "—")
        )
        estimate_samples = int(usage.get("current_estimate_samples") or 0)
        estimate_error = usage.get("current_estimate_error_rate")
        estimate_text = (
            _percent(estimate_error)
            if (
                current_available
                and estimate_samples > 0
                and estimate_error is not None
            )
            else "—"
        )

        values = {
            "request_count": _number(usage.get("request_count")),
            "total_tokens": _number(usage.get("total_tokens")),
            "cache_hit": hit_text,
            "completion_tokens": _number(usage.get("completion_tokens")),
            "current_prompt_tokens": current_value(
                usage.get("current_prompt_tokens")
            ),
            "current_uncached_prompt_tokens": current_value(
                usage.get("current_uncached_prompt_tokens")
            ),
            "current_cached_tokens": current_value(
                usage.get("current_cached_tokens")
            ),
            "current_cache_creation_tokens": current_value(
                usage.get("current_cache_creation_tokens")
            ),
            "reasoning_tokens": _number(usage.get("reasoning_tokens")),
            "estimate_error": estimate_text,
            "estimate_samples": (
                current_value(estimate_samples) if current_available else "—"
            ),
            "current_estimated_prompt_tokens": current_value(
                usage.get("current_estimated_prompt_tokens")
            ),
        }
        for key, value in values.items():
            widget = self._usage_values.get(key)
            if widget is not None:
                widget.set_text(value)

        self.usage_sample_note.set_text(
            f"V2 样本 {_number(current_count)} 条。"
            if current_available
            else "暂无新口径数据；旧记录不会被当成 V2 计算缓存命中率。"
        )
        legacy = int(usage.get("legacy_request_count") or 0)
        if legacy > 0:
            self.usage_legacy_note.set_text(
                f"含 {_number(legacy)} 条旧口径记录（输入 "
                f"{_number(usage.get('legacy_prompt_tokens'))}，总 token "
                f"{_number(usage.get('legacy_total_tokens'))}）；旧口径输入 token "
                "不含 cache 读写，没有可与新口径直接比较的命中率。"
            )
            self.usage_legacy_note.set_visible(True)
        unknown = int(usage.get("unknown_semantics_request_count") or 0)
        if unknown > 0:
            self.usage_unknown_note.set_text(
                f"含 {_number(unknown)} 条未知未来 usage 口径记录，"
                "未纳入 V2 主缓存命中率。"
            )
            self.usage_unknown_note.set_visible(True)
        inconsistent = int(usage.get("raw_cache_inconsistent_count") or 0)
        if inconsistent > 0:
            self.usage_inconsistent_note.set_text(
                f"有 {_number(inconsistent)} 条记录的缓存字段超过输入 token，"
                "展示值已做安全夹取。"
            )
            self.usage_inconsistent_note.set_visible(True)

        operations = [
            row
            for row in (usage.get("by_operation") or [])
            if float(row.get("current_total_tokens") or 0) > 0
        ][:10]
        widgets.clear(self.usage_ops_host)
        if operations:
            rows: list[list[Any]] = []
            for row in operations:
                operation = str(row.get("operation") or "")
                rows.append(
                    [
                        widgets.badge(
                            OPERATION_TEXT.get(
                                operation, operation or "unknown"
                            )
                        ),
                        _number(row.get("request_count")),
                        _number(row.get("current_prompt_tokens")),
                        _number(row.get("current_total_tokens")),
                    ]
                )
            self.usage_ops_host.append(
                widgets.table(
                    ["用途", "请求", "V2 输入 token", "V2 总 token"],
                    rows,
                    weights=[2.0, 1.2, 2.0, 2.0],
                )
            )
            self.usage_ops_label.set_visible(True)
            self.usage_ops_host.set_visible(True)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def _render_update(self, data: dict[str, Any]) -> None:
        self._update_inflight = False
        release = data.get("release") or {}
        available = bool(data.get("available") and release)
        self.update_button.set_visible(available)
        if available:
            label = str(
                release.get("name") or release.get("tag") or "新版本"
            )
            self.update_button.set_tooltip_text(f"发现新版本：{label}")

    def _update_error(self, _exc: BaseException) -> None:
        self._update_inflight = False
        self.update_button.set_visible(False)
