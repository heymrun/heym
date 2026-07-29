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
        r"""(?ix)
        ["']?
        (?:api[_-]?key|authorization|cookie|password|secret|private[_-]?key|
        access[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)
        ["']?\s*:\s*
        (?:"[^"]*"|'[^']*'|[^,\s}\]]+)
        """
    ),
    re.compile(
        r"(?i)(?:client[_-]?secret|access[_-]?token|refresh[_-]?token|api[_-]?key)\s*[=:]\s*[^\s,;]+"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.+?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*", re.DOTALL),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)
_REDACTED = "[REDACTED]"
_TRUNCATED = "...(truncated)"
_PAYLOAD_TRUNCATED = "[PAYLOAD_TRUNCATED]"
_MAX_DICT_KEYS = 200
_MAX_LIST_ITEMS = 100
_MAX_REDACTION_LOOKAHEAD_CHARS = 512
_MAX_JSON_PARSE_CHARS = 65_536
DEFAULT_MAX_PAYLOAD_CHARS = 4096
DEFAULT_MAX_PAYLOAD_DEPTH = 6
DEFAULT_MAX_PAYLOAD_TOTAL_CHARS = 32768
_GENERATED_FILE_FIELDS = (
    "id",
    "filename",
    "download_url",
    "mime_type",
    "size_bytes",
)
_GENERATED_FILES_MAX_ITEMS = 20
_GENERATED_FILES_RESERVED_CHARS = 4096


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
    if status in {"pending", "timeout"}:
        return status
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    return "unknown"


_CANCEL_STATUS_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\b(?:workflow\s+)?execution\s+cancell?ed\b"
    r"|\bworkflow\s+cancell?ed\b"
    r"|\b(?:operation|request|tool|run)\s+cancell?ed\b"
    r"|\bcancell?ed\s+by\b"
    r"|\bcancellation\b"
    r"|\bcancell?ing\b"
    r")"
)
_TIMEOUT_STATUS_RE = re.compile(r"(?i)\btimed\s+out\b|\btimeout\s+after\b")


def text_indicates_cancellation(text: str) -> bool:
    """Return True when text clearly describes cancellation (not just the word cancel)."""
    lowered = text.strip().lower()
    if not lowered:
        return False
    if lowered in {"cancelled", "canceled", "cancellation"}:
        return True
    return bool(_CANCEL_STATUS_RE.search(lowered))


def text_indicates_timeout(text: str) -> bool:
    """Return True when text clearly describes a timeout failure."""
    lowered = text.strip().lower()
    if not lowered:
        return False
    # Whole-message forms like "request timeout" — not embedded domain phrases such as
    # "Variable 'request timeout' not found".
    if lowered.endswith(" timeout"):
        return True
    return bool(_TIMEOUT_STATUS_RE.search(lowered))


def _trusted_exception_lifecycle_status(error: BaseException) -> str | None:
    """Map only trusted cancel/timeout exception types to a lifecycle status.

    Generic exceptions often carry user- or server-controlled messages (MCP tool
    text, variable names, etc.). Inferring cancel/timeout from those strings is
    unsafe — only TimeoutError and workflow cancel/timeout types qualify.
    """
    if isinstance(error, TimeoutError):
        return "timeout"
    for cls in type(error).mro():
        name = cls.__name__
        if name == "WorkflowTimeoutError":
            return "timeout"
        if name == "WorkflowCancelledError":
            return "cancelled"
    return None


def classify_tool_failure_status(
    error: BaseException | str | None,
    *,
    explicit_status: str | None = None,
) -> str:
    """Map exceptions / abort reasons onto timeout / cancelled / error.

    Trusted abort *strings* (for example from ``should_abort()``) may still be
    classified by text. Exception messages are never used for cancel/timeout
    inference — only trusted exception types are.
    """
    if explicit_status:
        normalized = normalize_tool_call_status(explicit_status)
        if normalized in {"timeout", "cancelled", "pending"}:
            return normalized
    if isinstance(error, BaseException):
        trusted = _trusted_exception_lifecycle_status(error)
        if trusted is not None:
            return trusted
        if explicit_status:
            normalized = normalize_tool_call_status(explicit_status)
            if normalized == "unknown":
                return "error"
            return normalized
        return "error"
    if error is None:
        return "error"
    text = str(error).strip()
    if not text:
        return "error"
    if text_indicates_timeout(text):
        return "timeout"
    if text_indicates_cancellation(text):
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
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= len(_TRUNCATED):
        return _TRUNCATED[:max_chars]
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


def _bounded_redact_text(value: str, max_chars: int) -> str:
    """Redact and truncate without scanning arbitrarily large payload strings."""
    if max_chars <= 0:
        return ""
    scan_limit = max_chars + _MAX_REDACTION_LOOKAHEAD_CHARS
    bounded_input = value[:scan_limit]
    return _truncate_text(_redact_sensitive_text(bounded_input), max_chars)


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
        bounded = _bounded_redact_text(value, min(max_chars, budget.remaining))
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
                parse_limit = min(_MAX_JSON_PARSE_CHARS, max(max_chars * 4, max_chars))
                if len(child) > parse_limit:
                    bounded_child = _bounded_redact_text(
                        child,
                        min(max_chars, budget.remaining),
                    )
                    budget.take(len(bounded_child))
                    output[key_text] = bounded_child
                else:
                    try:
                        parsed_child = json.loads(child)
                    except json.JSONDecodeError:
                        bounded_child = _bounded_redact_text(
                            child,
                            min(max_chars, budget.remaining),
                        )
                        budget.take(len(bounded_child))
                        output[key_text] = bounded_child
                    else:
                        child_limit = min(max_chars, budget.remaining)
                        safe_child = sanitize_tool_payload(
                            parsed_child,
                            max_chars=max_chars,
                            max_depth=max_depth,
                            max_total_chars=child_limit,
                            _depth=_depth + 1,
                            _budget=_PayloadBudget(child_limit),
                        )
                        dumped = _truncate_text(
                            json.dumps(safe_child, ensure_ascii=False),
                            child_limit,
                        )
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
    bounded = _bounded_redact_text(str(value), min(max_chars, budget.remaining))
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
    if isinstance(tool_calls, list) and _budget is None:
        bounded_calls = tool_calls[:_MAX_LIST_ITEMS]
        if not bounded_calls:
            return []
        per_entry_chars = max(1, max_total_chars // len(bounded_calls))
        priority_keys = (
            "tool_call_id",
            "id",
            "name",
            "status",
            "source",
            "mcp_server",
            "elapsed_ms",
            "started_at",
            "finished_at",
        )
        safe_calls = []
        for entry in bounded_calls:
            prioritized_entry = entry
            if isinstance(entry, dict):
                prioritized_entry = {
                    **{key: entry[key] for key in priority_keys if key in entry},
                    **{key: value for key, value in entry.items() if key not in priority_keys},
                }
            safe_calls.append(
                sanitize_tool_payload(
                    prioritized_entry,
                    max_chars=min(max_chars, per_entry_chars),
                    max_depth=max_depth,
                    max_total_chars=per_entry_chars,
                )
            )
        if len(tool_calls) > len(bounded_calls):
            safe_calls.append(_PAYLOAD_TRUNCATED)
        return safe_calls
    return sanitize_tool_payload(
        tool_calls,
        max_chars=max_chars,
        max_depth=max_depth,
        max_total_chars=max_total_chars,
        _budget=_budget,
    )


def _sanitize_generated_files(
    value: Any,
    *,
    max_chars: int,
    max_depth: int,
    max_total_chars: int,
) -> list[Any]:
    """Preserve bounded file-download metadata independently of bulky tool output."""
    if not isinstance(value, list):
        return []
    minimal_files: list[dict[str, Any]] = []
    for item in value[:_GENERATED_FILES_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        minimal_files.append({key: item[key] for key in _GENERATED_FILE_FIELDS if key in item})
    if not minimal_files:
        return []
    return sanitize_tool_payload(
        minimal_files,
        max_chars=max_chars,
        max_depth=max_depth,
        max_total_chars=min(max_total_chars, _GENERATED_FILES_RESERVED_CHARS),
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
        raw_result = safe["result"]
        generated_files: list[Any] = []
        result_without_files = raw_result
        if isinstance(raw_result, dict) and "_generated_files" in raw_result:
            generated_files = _sanitize_generated_files(
                raw_result["_generated_files"],
                max_chars=chars,
                max_depth=depth,
                max_total_chars=total,
            )
            result_without_files = {
                key: value for key, value in raw_result.items() if key != "_generated_files"
            }
        reserved_chars = (
            min(
                total,
                len(json.dumps({"_generated_files": generated_files}, ensure_ascii=False)),
            )
            if generated_files
            else 0
        )
        safe_result = sanitize_tool_payload(
            result_without_files,
            max_chars=chars,
            max_depth=depth,
            max_total_chars=max(0, total - reserved_chars),
        )
        if generated_files and isinstance(safe_result, dict):
            safe_result["_generated_files"] = generated_files
        safe["result"] = safe_result
    return safe


def _result_indicates_error(result: dict[str, Any]) -> bool:
    """True when a tool result carries a top-level or nested outputs error."""
    if result.get("error") is not None:
        return True
    outputs = result.get("outputs")
    return isinstance(outputs, dict) and outputs.get("error") is not None


def summarize_tool_calls(tool_calls: Any) -> dict[str, Any]:
    """Summarize tool-call counts and durations without exposing payloads."""
    if not isinstance(tool_calls, list):
        return {"count": 0, "success": 0, "error": 0, "pending": 0, "cancelled": 0, "timeout": 0}
    summary: dict[str, Any] = {
        "count": 0,
        "success": 0,
        "error": 0,
        "pending": 0,
        "cancelled": 0,
        "timeout": 0,
        "total_duration_ms": 0.0,
        "max_duration_ms": 0.0,
    }
    for entry in tool_calls:
        if not isinstance(entry, dict) or entry.get("name") == "_context_compression":
            continue
        summary["count"] += 1
        raw_status = entry.get("status")
        status = normalize_tool_call_status(raw_status)
        result = entry.get("result")
        # Legacy entries may omit top-level status. Prefer structured result.status,
        # then treat any non-null result.error / outputs.error as error — never
        # reclassify from free-form error text (e.g. "request timeout" in a name).
        if (raw_status is None or raw_status == "") and isinstance(result, dict):
            result_status = result.get("status")
            if isinstance(result_status, str) and result_status.strip():
                normalized_result_status = normalize_tool_call_status(result_status)
                if normalized_result_status != "unknown":
                    status = normalized_result_status
                elif _result_indicates_error(result):
                    status = "error"
            elif _result_indicates_error(result):
                status = "error"
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


def _sanitize_trace_messages(
    messages: Any,
    *,
    max_chars: int,
    max_depth: int,
    max_total_chars: int,
    per_record_chars: int,
) -> Any:
    """Copy messages while sanitizing only Agent tool-call payload sections."""
    if not isinstance(messages, list):
        return messages
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
                max_total_chars=_tool_calls_total_budget(
                    message["tool_calls"],
                    per_record_chars,
                ),
            )
        elif message.get("role") == "tool" and "content" in message:
            safe_message["content"] = sanitize_tool_payload(
                message["content"],
                max_chars=max_chars,
                max_depth=max_depth,
                max_total_chars=per_record_chars,
            )
        safe_messages.append(safe_message)
    return safe_messages


def _trace_tool_record_count(request: dict[str, Any], response: dict[str, Any]) -> int:
    """Count independently useful tool payload records before allocating the total budget."""
    count = 0

    def count_calls(value: Any) -> None:
        nonlocal count
        if isinstance(value, list):
            count += max(1, min(len(value), _MAX_LIST_ITEMS))
        elif value is not None:
            count += 1

    def count_messages(value: Any) -> None:
        nonlocal count
        if not isinstance(value, list):
            return
        for message in value:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant" and "tool_calls" in message:
                count_calls(message["tool_calls"])
            elif message.get("role") == "tool" and "content" in message:
                count += 1

    count_calls(request.get("tool_calls"))
    count_calls(response.get("tool_calls"))
    count_messages(request.get("messages"))
    hitl_pending = response.get("_hitl_pending")
    if isinstance(hitl_pending, dict):
        if "tool_arguments" in hitl_pending:
            count += 1
        agent_state = hitl_pending.get("agent_state")
        if isinstance(agent_state, dict):
            count_messages(agent_state.get("messages"))
            count_calls(agent_state.get("tool_calls"))
    return max(1, count)


def _tool_calls_total_budget(value: Any, per_record_chars: int) -> int:
    """Return the fair total allocation for one tool-call collection."""
    if isinstance(value, list):
        return per_record_chars * max(1, min(len(value), _MAX_LIST_ITEMS))
    return per_record_chars


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
    per_record_chars = max(1, max_total_chars // _trace_tool_record_count(request, response))
    if "tool_calls" in safe_request:
        safe_request["tool_calls"] = sanitize_tool_calls(
            safe_request["tool_calls"],
            max_chars=max_chars,
            max_depth=max_depth,
            max_total_chars=_tool_calls_total_budget(
                safe_request["tool_calls"],
                per_record_chars,
            ),
        )
    if "tool_calls" in safe_response:
        safe_response["tool_calls"] = sanitize_tool_calls(
            safe_response["tool_calls"],
            max_chars=max_chars,
            max_depth=max_depth,
            max_total_chars=_tool_calls_total_budget(
                safe_response["tool_calls"],
                per_record_chars,
            ),
        )

    if "messages" in request:
        safe_request["messages"] = _sanitize_trace_messages(
            request["messages"],
            max_chars=max_chars,
            max_depth=max_depth,
            max_total_chars=per_record_chars,
            per_record_chars=per_record_chars,
        )

    hitl_pending = response.get("_hitl_pending")
    if isinstance(hitl_pending, dict):
        safe_hitl_pending = dict(hitl_pending)
        if "tool_arguments" in hitl_pending:
            safe_hitl_pending["tool_arguments"] = sanitize_tool_payload(
                hitl_pending["tool_arguments"],
                max_chars=max_chars,
                max_depth=max_depth,
                max_total_chars=per_record_chars,
            )
        agent_state = hitl_pending.get("agent_state")
        if isinstance(agent_state, dict):
            safe_agent_state = dict(agent_state)
            if "messages" in agent_state:
                safe_agent_state["messages"] = _sanitize_trace_messages(
                    agent_state["messages"],
                    max_chars=max_chars,
                    max_depth=max_depth,
                    max_total_chars=per_record_chars,
                    per_record_chars=per_record_chars,
                )
            if "tool_calls" in agent_state:
                safe_agent_state["tool_calls"] = sanitize_tool_calls(
                    agent_state["tool_calls"],
                    max_chars=max_chars,
                    max_depth=max_depth,
                    max_total_chars=_tool_calls_total_budget(
                        agent_state["tool_calls"],
                        per_record_chars,
                    ),
                )
            safe_hitl_pending["agent_state"] = safe_agent_state
        safe_response["_hitl_pending"] = safe_hitl_pending
    return safe_request, safe_response
