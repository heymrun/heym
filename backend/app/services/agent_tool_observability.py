"""Shared helpers for safe Agent tool-call observability."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|cookie|password|secret|private[_-]?key|access[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret)",
    re.IGNORECASE,
)
# Exact "token" (and hyphen/underscore variants) only — avoid redacting tokens/token_count.
_SENSITIVE_EXACT_KEYS = frozenset({"token", "api_key", "apikey", "private_key", "access_key"})
_SAFE_KEY_ALLOWLIST = frozenset(
    {
        "tokens",
        "token_count",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "max_tokens",
        "input_tokens",
        "output_tokens",
    }
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]+"),
    re.compile(
        r"(?i)(?:client[_-]?secret|access[_-]?token|refresh[_-]?token|api[_-]?key)\s*[=:]\s*[^\s,;]+"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.+?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)
_REDACTED = "[REDACTED]"
_TRUNCATED = "...(truncated)"
_PAYLOAD_TRUNCATED = "[PAYLOAD_TRUNCATED]"
_MAX_DICT_KEYS = 200
_MAX_LIST_ITEMS = 100
DEFAULT_MAX_PAYLOAD_CHARS = 4096
DEFAULT_MAX_PAYLOAD_DEPTH = 6
DEFAULT_MAX_PAYLOAD_TOTAL_CHARS = 32768


def _is_sensitive_key(key_text: str) -> bool:
    """Return True when a dict key looks like a credential field name."""
    normalized = key_text.strip().lower().replace("-", "_")
    if normalized in _SAFE_KEY_ALLOWLIST:
        return False
    if normalized in _SENSITIVE_EXACT_KEYS:
        return True
    if (
        normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
    ):
        return True
    return bool(_SENSITIVE_KEY_PATTERN.search(normalized))


def normalize_tool_call_status(value: Any) -> str:
    """Normalize persisted and streamed tool-call statuses.

    Unknown success-like aliases (``ok``, ``completed``, …) map to ``success``.
    Unrecognized values return ``unknown`` so callers can fall back to error-field
    detection instead of treating every custom status as a failure.
    """
    if value is None or value == "":
        return "success"
    status = str(value).lower().strip()
    if status in {"success", "ok", "completed", "complete", "done"}:
        return "success"
    if status in {"error", "failed", "failure"}:
        return "error"
    if status in {"pending", "timeout", "cancelled"}:
        return status
    return "unknown"


def classify_tool_failure_status(
    error: BaseException | str | None,
    *,
    explicit_status: str | None = None,
) -> str:
    """Map exceptions / abort reasons onto timeout / cancelled / error."""
    if explicit_status:
        normalized = normalize_tool_call_status(explicit_status)
        if normalized in {"timeout", "cancelled", "pending"}:
            return normalized
    if isinstance(error, TimeoutError):
        return "timeout"
    if error is None:
        return "error"
    text = str(error).strip().lower()
    if not text:
        return "error"
    if "timed out" in text or text.endswith(" timeout") or "timeout after" in text:
        return "timeout"
    if "cancel" in text:
        return "cancelled"
    if explicit_status:
        normalized = normalize_tool_call_status(explicit_status)
        if normalized == "unknown":
            return "error"
        return normalized
    return "error"


def get_agent_tool_payload_limits() -> tuple[int, int, int]:
    """Return (max_chars, max_depth, max_total_chars) for persisted tool payloads."""
    return (
        DEFAULT_MAX_PAYLOAD_CHARS,
        DEFAULT_MAX_PAYLOAD_DEPTH,
        DEFAULT_MAX_PAYLOAD_TOTAL_CHARS,
    )


@dataclass
class _PayloadBudget:
    remaining: int

    def take(self, amount: int) -> bool:
        if amount <= self.remaining:
            self.remaining -= amount
            return True
        self.remaining = 0
        return False


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - len(_TRUNCATED))] + _TRUNCATED


def _redact_sensitive_text(value: str) -> str:
    """Redact common credential formats even when the surrounding key is generic."""
    redacted = value
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.pattern.startswith("(?i)(bearer") or pattern.pattern.startswith("(?i)(basic"):
            replacement = r"\1[REDACTED]"
        else:
            replacement = _REDACTED
        redacted = pattern.sub(replacement, redacted)
    return redacted


def sanitize_tool_payload(
    value: Any,
    *,
    max_chars: int = DEFAULT_MAX_PAYLOAD_CHARS,
    max_depth: int = DEFAULT_MAX_PAYLOAD_DEPTH,
    max_total_chars: int = DEFAULT_MAX_PAYLOAD_TOTAL_CHARS,
    _depth: int = 0,
    _budget: _PayloadBudget | None = None,
    _active_ids: set[int] | None = None,
) -> Any:
    """Return a bounded, JSON-compatible payload with common secrets redacted."""
    budget = _budget or _PayloadBudget(max_total_chars)
    active_ids = _active_ids if _active_ids is not None else set()
    if _depth > max_depth:
        return "[MAX_DEPTH]"
    if isinstance(value, str):
        if budget.remaining <= 0:
            return _PAYLOAD_TRUNCATED
        bounded = _truncate_text(_redact_sensitive_text(value), min(max_chars, budget.remaining))
        budget.take(len(bounded))
        return bounded
    if value is None or isinstance(value, (bool, int, float)):
        return value
    value_id = id(value)
    if value_id in active_ids:
        return "[CYCLE]"
    active_ids.add(value_id)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= _MAX_DICT_KEYS or budget.remaining <= 0:
                output["_truncated"] = _PAYLOAD_TRUNCATED
                break
            key_text = str(key)
            if not budget.take(len(key_text) + 2):
                output["_truncated"] = _PAYLOAD_TRUNCATED
                break
            if _is_sensitive_key(key_text):
                output[key_text] = _REDACTED
            elif key_text.lower() in {"args", "arguments", "result"} and isinstance(child, str):
                try:
                    parsed_child = json.loads(child)
                except json.JSONDecodeError:
                    bounded_child = _truncate_text(
                        _redact_sensitive_text(child),
                        min(max_chars, budget.remaining),
                    )
                    budget.take(len(bounded_child))
                    output[key_text] = bounded_child
                else:
                    safe_child = sanitize_tool_payload(
                        parsed_child,
                        max_chars=max_chars,
                        max_depth=max_depth,
                        max_total_chars=max_total_chars,
                        _depth=_depth + 1,
                        _budget=budget,
                        _active_ids=active_ids,
                    )
                    dumped = json.dumps(safe_child, ensure_ascii=False)
                    if len(dumped) > max_chars or len(dumped) > budget.remaining:
                        dumped = _truncate_text(dumped, min(max_chars, max(0, budget.remaining)))
                    budget.take(len(dumped))
                    output[key_text] = dumped
            else:
                output[key_text] = sanitize_tool_payload(
                    child,
                    max_chars=max_chars,
                    max_depth=max_depth,
                    max_total_chars=max_total_chars,
                    _depth=_depth + 1,
                    _budget=budget,
                    _active_ids=active_ids,
                )
        active_ids.remove(value_id)
        return output
    if isinstance(value, (list, tuple)):
        output_list: list[Any] = []
        for child in value[:_MAX_LIST_ITEMS]:
            if budget.remaining <= 0:
                output_list.append(_PAYLOAD_TRUNCATED)
                break
            output_list.append(
                sanitize_tool_payload(
                    child,
                    max_chars=max_chars,
                    max_depth=max_depth,
                    max_total_chars=max_total_chars,
                    _depth=_depth + 1,
                    _budget=budget,
                    _active_ids=active_ids,
                )
            )
        active_ids.remove(value_id)
        return output_list
    bounded = _truncate_text(_redact_sensitive_text(str(value)), min(max_chars, budget.remaining))
    budget.take(len(bounded))
    active_ids.remove(value_id)
    return bounded


def sanitize_tool_calls(
    tool_calls: Any,
    *,
    max_chars: int = DEFAULT_MAX_PAYLOAD_CHARS,
    max_depth: int = DEFAULT_MAX_PAYLOAD_DEPTH,
    max_total_chars: int = DEFAULT_MAX_PAYLOAD_TOTAL_CHARS,
    _budget: _PayloadBudget | None = None,
) -> Any:
    """Sanitize persisted tool-call records while preserving their shape."""
    return sanitize_tool_payload(
        tool_calls,
        max_chars=max_chars,
        max_depth=max_depth,
        max_total_chars=max_total_chars,
        _budget=_budget,
    )


def sanitize_persisted_tool_entry(
    entry: dict[str, Any],
    *,
    capture_raw: bool = False,
    max_chars: int | None = None,
    max_depth: int | None = None,
    max_total_chars: int | None = None,
) -> dict[str, Any]:
    """Sanitize args/result on a tool-call record used for persistence / history.

    LLM message content is left untouched by callers; this only affects the
    observability record attached to agent results, HITL state, and traces.
    ``capture_raw`` is a test/debug escape hatch and is not exposed as an env var.
    """
    cfg_chars, cfg_depth, cfg_total = get_agent_tool_payload_limits()
    if capture_raw:
        return entry
    chars = cfg_chars if max_chars is None else max_chars
    depth = cfg_depth if max_depth is None else max_depth
    total = cfg_total if max_total_chars is None else max_total_chars
    safe = dict(entry)
    if "arguments" in safe:
        safe["arguments"] = sanitize_tool_payload(
            safe["arguments"],
            max_chars=chars,
            max_depth=depth,
            max_total_chars=total,
        )
    if "result" in safe and safe["result"] is not None:
        safe["result"] = sanitize_tool_payload(
            safe["result"],
            max_chars=chars,
            max_depth=depth,
            max_total_chars=total,
        )
    return safe


def summarize_tool_calls(tool_calls: Any) -> dict[str, Any]:
    """Summarize tool-call counts and durations without exposing payloads."""
    if not isinstance(tool_calls, list):
        return {"count": 0, "success": 0, "error": 0, "pending": 0, "cancelled": 0, "timeout": 0}
    summary: dict[str, Any] = {
        "count": len(tool_calls),
        "success": 0,
        "error": 0,
        "pending": 0,
        "cancelled": 0,
        "timeout": 0,
        "total_duration_ms": 0.0,
        "max_duration_ms": 0.0,
    }
    for entry in tool_calls:
        if not isinstance(entry, dict):
            continue
        status = normalize_tool_call_status(entry.get("status"))
        if status == "unknown":
            status = "error"
        if status in summary:
            summary[status] += 1
        duration = entry.get("elapsed_ms")
        if isinstance(duration, (int, float)):
            summary["total_duration_ms"] += float(duration)
            summary["max_duration_ms"] = max(summary["max_duration_ms"], float(duration))
    summary["total_duration_ms"] = round(summary["total_duration_ms"], 2)
    summary["max_duration_ms"] = round(summary["max_duration_ms"], 2)
    return summary


def sanitize_trace_tool_payloads(
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    max_chars: int,
    max_depth: int,
    max_total_chars: int = DEFAULT_MAX_PAYLOAD_TOTAL_CHARS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sanitize only tool-related portions of an LLM trace for compatibility."""
    # Avoid deepcopying a complete provider response before applying limits.
    # A very large tool result would otherwise defeat the sanitizer's memory bound.
    safe_request = dict(request)
    safe_response = dict(response)
    budget = _PayloadBudget(max_total_chars)
    if "tool_calls" in safe_request:
        safe_request["tool_calls"] = sanitize_tool_calls(
            safe_request["tool_calls"],
            max_chars=max_chars,
            max_depth=max_depth,
            max_total_chars=max_total_chars,
            _budget=budget,
        )
    if "tool_calls" in safe_response:
        safe_response["tool_calls"] = sanitize_tool_calls(
            safe_response["tool_calls"],
            max_chars=max_chars,
            max_depth=max_depth,
            max_total_chars=max_total_chars,
            _budget=budget,
        )

    messages = request.get("messages")
    if isinstance(messages, list):
        safe_messages: list[Any] = []
        for message in messages:
            if not isinstance(message, dict):
                safe_messages.append(message)
                continue
            safe_message = dict(message)
            if message.get("role") == "assistant" and "tool_calls" in message:
                safe_message["tool_calls"] = sanitize_tool_calls(
                    message["tool_calls"],
                    max_chars=max_chars,
                    max_depth=max_depth,
                    max_total_chars=max_total_chars,
                    _budget=budget,
                )
            elif message.get("role") == "tool" and "content" in message:
                safe_message["content"] = sanitize_tool_payload(
                    message["content"],
                    max_chars=max_chars,
                    max_depth=max_depth,
                    max_total_chars=max_total_chars,
                    _budget=budget,
                )
            safe_messages.append(safe_message)
        safe_request["messages"] = safe_messages
    return safe_request, safe_response
