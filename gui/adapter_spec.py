"""协议/渠道设置页的纯数据辅助函数。

这里不导入 GTK，方便在无界面环境里单独测试表单字段、取值转换和保存载荷。
后端契约见 ``docs/protocols/backend-api-report.md``。
"""

from __future__ import annotations

import copy
import re
from typing import Any

PROTOCOL_STATUS_LABELS = {
    "stable": "稳定",
    "beta": "Beta",
    "planned": "即将支持",
}

PROTOCOL_TYPE_LABELS = {
    "napcat": "NapCatQQ",
    "onebot11": "OneBot 11",
    "telegram": "Telegram",
    "qq_official": "QQ 官方 Bot",
    "satori": "Satori",
}

TRANSPORT_LABELS = {
    "ws_client": "WebSocket 客户端",
    "ws_server": "WebSocket 服务端",
    "http": "HTTP API + Webhook",
    "long_polling": "长轮询",
    "webhook": "Webhook 回调",
    "gateway": "Gateway",
    "ws": "WebSocket",
}

DIALECT_LABELS = {
    "auto": "自动识别",
    "napcat": "NapCatQQ",
    "llonebot": "LLOneBot",
    "lagrange": "Lagrange",
    "gocqhttp": "go-cqhttp",
    "generic": "通用 OneBot 11",
}

MESSAGE_FORMAT_LABELS = {
    "array": "消息段数组",
    "string": "CQ 字符串",
}

PARSE_MODE_LABELS = {
    "HTML": "HTML",
    "MarkdownV2": "MarkdownV2",
    "none": "纯文本",
}

FIELD_LABELS = {
    "enabled": "启用渠道",
    "transport": "接入方式",
    "dialect": "协议端方言",
    "message_format": "消息格式",
    "host": "地址",
    "port": "端口",
    "path": "路径",
    "http_api_url": "HTTP API 地址",
    "webhook_enabled": "启用 HTTP 事件上报",
    "webhook_host": "Webhook 监听地址",
    "webhook_port": "Webhook 端口",
    "webhook_path": "Webhook 路径",
    "webhook_secret_id": "Webhook 密钥",
    "access_token_id": "Access Token（鉴权令牌）",
    "reconnect_interval_seconds": "重连间隔（秒）",
    "reconnect_backoff_max_seconds": "重连退避上限（秒）",
    "max_reconnect_attempts": "最大重连次数",
    "ping_interval_seconds": "心跳间隔（秒）",
    "ping_timeout_seconds": "心跳超时（秒）",
    "api_timeout_seconds": "API 超时（秒）",
    "bot_token_id": "Bot Token",
    "api_base": "Bot API 基址",
    "proxy": "代理",
    "webhook_public_url": "公网回调 URL",
    "webhook_secret_token_id": "Webhook Secret Token",
    "parse_mode": "消息解析模式",
    "allowed_updates": "订阅事件类型",
    "drop_pending_updates": "丢弃积压更新",
    "polling_timeout_seconds": "长轮询等待（秒）",
}

SECRET_FIELDS = frozenset(
    {
        "access_token_id",
        "webhook_secret_id",
        "bot_token_id",
        "webhook_secret_token_id",
    }
)

# 核心字段：直接展示。
ONEBOT_CORE_FIELDS = [
    "enabled",
    "transport",
    "dialect",
    "message_format",
    "host",
    "port",
    "path",
    "access_token_id",
]

# 高级字段：折叠展示。未展示的字段会保留服务端原值。
ONEBOT_ADVANCED_FIELDS = [
    "http_api_url",
    "webhook_enabled",
    "webhook_host",
    "webhook_port",
    "webhook_path",
    "webhook_secret_id",
    "reconnect_interval_seconds",
    "ping_interval_seconds",
    "ping_timeout_seconds",
    "api_timeout_seconds",
]

TELEGRAM_CORE_FIELDS = [
    "enabled",
    "transport",
    "bot_token_id",
    "api_base",
    "proxy",
    "parse_mode",
]

TELEGRAM_ADVANCED_FIELDS = [
    "webhook_host",
    "webhook_port",
    "webhook_path",
    "webhook_public_url",
    "webhook_secret_token_id",
    "drop_pending_updates",
    "polling_timeout_seconds",
    "api_timeout_seconds",
    "reconnect_interval_seconds",
    "allowed_updates",
]

CAPABILITY_LABELS = {
    "send_image": "图片",
    "send_voice": "语音",
    "send_video": "视频",
    "upload_file": "文件",
    "recall": "撤回",
    "reply": "引用回复",
    "mention": "提及",
    "poke": "戳一戳",
    "emoji_reaction": "表情回应",
    "voice_stt": "语音转文字",
    "forward_read": "合并转发",
    "group_history": "群历史",
    "get_message": "消息详情",
    "list_friends": "好友列表",
    "list_groups": "群列表",
    "list_group_members": "群成员",
    "friend_request": "好友审批",
    "group_request": "入群审批",
    "group_admin": "群管理",
    "proactive_private": "主动私聊",
    "proactive_group": "主动群聊",
}

_CAPABILITY_ORDER = list(CAPABILITY_LABELS)


def is_onebot(adapter_type: str) -> bool:
    return str(adapter_type or "") in {"napcat", "onebot11"}


def field_groups(adapter_type: str) -> tuple[list[str], list[str]]:
    """Return (core_fields, advanced_fields) for a protocol type."""
    if is_onebot(adapter_type):
        return list(ONEBOT_CORE_FIELDS), list(ONEBOT_ADVANCED_FIELDS)
    if adapter_type == "telegram":
        return list(TELEGRAM_CORE_FIELDS), list(TELEGRAM_ADVANCED_FIELDS)
    return [], []


def protocol_label(protocol: dict[str, Any]) -> str:
    return str(protocol.get("name") or PROTOCOL_TYPE_LABELS.get(
        str(protocol.get("id") or ""), protocol.get("id") or "未知协议"
    ))


def status_label(status: str) -> str:
    return PROTOCOL_STATUS_LABELS.get(str(status or ""), str(status or ""))


def type_label(value: str) -> str:
    return PROTOCOL_TYPE_LABELS.get(str(value or ""), str(value or ""))


def transport_label(value: str) -> str:
    return TRANSPORT_LABELS.get(str(value or ""), str(value or ""))


def dialect_label(value: str) -> str:
    return DIALECT_LABELS.get(str(value or ""), str(value or ""))


def field_label(name: str, prop: dict[str, Any] | None = None) -> str:
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    title = str((prop or {}).get("title") or name)
    return title.replace("_", " ").strip()


def enum_labels(name: str, prop: dict[str, Any]) -> dict[str, str]:
    """Map enum values to Chinese labels for the known setting fields."""
    if name == "transport":
        return {value: TRANSPORT_LABELS.get(value, value) for value in prop.get("enum") or []}
    if name == "dialect":
        return {value: DIALECT_LABELS.get(value, value) for value in prop.get("enum") or []}
    if name == "message_format":
        return {value: MESSAGE_FORMAT_LABELS.get(value, value) for value in prop.get("enum") or []}
    if name == "parse_mode":
        return {value: PARSE_MODE_LABELS.get(value, value) for value in prop.get("enum") or []}
    return {str(value): str(value) for value in prop.get("enum") or []}


def short_description(text: str, limit: int = 180) -> str:
    """Trim long Pydantic docstrings to the first sentence(s)."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    head = cleaned[:limit]
    for mark in ("。", "；", ". "):
        index = head.rfind(mark)
        if index >= 30:
            return head[: index + len(mark)].strip()
    return head.rstrip() + "…"


def schema_type(prop: dict[str, Any]) -> str:
    """Return the concrete JSON-schema type, unwrapping ``anyOf`` nullables."""
    direct = str(prop.get("type") or "")
    if direct:
        return direct
    for option in prop.get("anyOf") or []:
        option_type = str(option.get("type") or "")
        if option_type and option_type != "null":
            return option_type
    for option in prop.get("oneOf") or []:
        option_type = str(option.get("type") or "")
        if option_type and option_type != "null":
            return option_type
    return ""


def allows_null(prop: dict[str, Any]) -> bool:
    return any(
        str(option.get("type") or "") == "null"
        for option in (prop.get("anyOf") or []) + (prop.get("oneOf") or [])
    )


def default_value(prop: dict[str, Any]) -> Any:
    if "default" in prop:
        return copy.deepcopy(prop.get("default"))
    schema_kind = schema_type(prop)
    if schema_kind == "boolean":
        return False
    if schema_kind in {"integer", "number"}:
        return 0
    if schema_kind == "array":
        return []
    if allows_null(prop):
        return None
    return ""


def parse_string_list(text: Any) -> list[str]:
    """Parse comma/newline separated IDs or update names."""
    if isinstance(text, (list, tuple)):
        raw_items = list(text)
    else:
        raw_items = re.split(r"[\n,，、;；]+", str(text or ""))
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def coerce_value(prop: dict[str, Any], raw: Any = None) -> Any:
    """Convert a widget value to the JSON type expected by the backend."""
    schema_kind = schema_type(prop)
    if schema_kind == "boolean":
        return bool(raw)
    if schema_kind == "array":
        return parse_string_list(raw)
    if schema_kind == "integer":
        text = str(raw).strip()
        if not text:
            return int(default_value(prop) or 0)
        return int(text)
    if schema_kind == "number":
        text = str(raw).strip()
        if not text:
            return float(default_value(prop) or 0)
        return float(text)
    text = "" if raw is None else str(raw).strip()
    if not text and allows_null(prop):
        return None
    return text


def build_adapter_payload(
    adapter_type: str,
    baseline: dict[str, Any] | None,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Merge form values into a complete adapter config payload.

    ``baseline`` is the current ``GET /api/adapters/config`` entry. When the
    user switches protocol type, type-specific fields are dropped but the
    shared whitelist/blacklist are preserved.
    """
    base = dict(baseline or {})
    same_type = str(base.get("type") or "") == str(adapter_type or "")
    payload: dict[str, Any] = {}
    if same_type:
        payload.update(copy.deepcopy(base))
    else:
        for shared in ("whitelist", "blacklist"):
            if shared in base:
                payload[shared] = copy.deepcopy(base[shared])
    payload["type"] = adapter_type
    payload.update(values)

    if is_onebot(adapter_type):
        for key in (
            "bot_token_id",
            "api_base",
            "proxy",
            "webhook_public_url",
            "webhook_secret_token_id",
            "parse_mode",
            "allowed_updates",
            "drop_pending_updates",
            "polling_timeout_seconds",
        ):
            payload.pop(key, None)
        payload["mode"] = (
            "server" if payload.get("transport") == "ws_server" else "client"
        )
    elif adapter_type == "telegram":
        for key in (
            "mode",
            "dialect",
            "message_format",
            "host",
            "port",
            "path",
            "http_api_url",
            "webhook_enabled",
            "webhook_secret_id",
            "access_token_id",
            "reconnect_backoff_max_seconds",
            "max_reconnect_attempts",
            "ping_interval_seconds",
            "ping_timeout_seconds",
        ):
            payload.pop(key, None)
        payload.setdefault("allowed_updates", [])
    return payload


def adapter_summary(adapter: dict[str, Any] | None) -> str:
    """Human-readable ``type · transport · dialect`` summary.

    Falls back to ``mode://host:port`` for pre-adapter-API backends.
    """
    if not adapter:
        return ""
    parts: list[str] = []
    type_id = str(adapter.get("type") or "")
    transport = str(adapter.get("transport") or "")
    dialect = str(adapter.get("dialect") or "")
    if type_id:
        parts.append(type_label(type_id))
    if transport:
        parts.append(transport_label(transport))
    if dialect and dialect != "auto":
        dialect_text = dialect_label(dialect)
        # NapCat 的类型名和方言名同为 NapCatQQ，避免顶栏重复。
        if dialect_text != type_label(type_id):
            parts.append(dialect_text)
    if parts:
        return " · ".join(part for part in parts if part)
    # 旧后端 /api/status 只有 mode/host/port。
    mode = str(adapter.get("mode") or "").strip()
    host = str(adapter.get("host") or "").strip()
    port = str(adapter.get("port") or "").strip()
    endpoint = f"{host}:{port}".strip(":")
    if mode:
        return f"{mode}://{endpoint}" if endpoint else mode
    return endpoint


def adapter_address(adapter: dict[str, Any] | None) -> str:
    """Best-effort connection address without assuming OneBot fields exist."""
    if not adapter:
        return ""
    transport = str(adapter.get("transport") or "").strip()
    if transport == "http":
        http_api_url = str(adapter.get("http_api_url") or "").strip()
        if http_api_url:
            return f"API {http_api_url}"
        if adapter.get("webhook_enabled") or adapter.get("webhook_port"):
            host = str(adapter.get("webhook_host") or "127.0.0.1").strip()
            port = str(adapter.get("webhook_port") or "").strip()
            path = str(adapter.get("webhook_path") or "").strip()
            endpoint = f"{host}:{port}" if port else host
            return "Webhook " + endpoint + (path if path and path != "/" else "")
        # host/port only describe the WebSocket transport; /api/status does not
        # include webhook fields, so avoid showing a stale WS endpoint here.
        return ""
    if transport == "webhook":
        public_url = str(adapter.get("webhook_public_url") or "").strip()
        if public_url:
            return f"Webhook {public_url}"
    host = str(adapter.get("host") or "").strip()
    port = str(adapter.get("port") or "").strip()
    path = str(adapter.get("path") or "").strip()
    if host and port:
        return f"{host}:{port}" + (path if path and path != "/" else "")
    if host:
        return host + (path if path and path != "/" else "")
    api_base = str(adapter.get("api_base") or "").strip()
    if api_base:
        return api_base
    return ""


def capability_summary(capabilities: dict[str, Any] | None) -> str:
    caps = capabilities if isinstance(capabilities, dict) else {}
    labels = [
        CAPABILITY_LABELS[key]
        for key in _CAPABILITY_ORDER
        if bool(caps.get(key))
    ]
    return "、".join(labels) if labels else "—"


def adapter_source(
    adapter: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> str:
    """``default · NapCatAdapter`` style source label."""
    if not adapter:
        return ""
    name = str(adapter.get("name") or "default")
    class_name = str(adapter.get("class") or "")
    return f"{name} · {class_name}" if class_name else name


__all__ = [
    "CAPABILITY_LABELS",
    "FIELD_LABELS",
    "PROTOCOL_STATUS_LABELS",
    "SECRET_FIELDS",
    "adapter_address",
    "adapter_source",
    "adapter_summary",
    "allows_null",
    "build_adapter_payload",
    "capability_summary",
    "coerce_value",
    "default_value",
    "dialect_label",
    "enum_labels",
    "field_groups",
    "field_label",
    "is_onebot",
    "parse_string_list",
    "protocol_label",
    "schema_type",
    "short_description",
    "status_label",
    "transport_label",
    "type_label",
]
