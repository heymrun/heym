import asyncio
import base64
import copy
import io
import json
import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from app.db.models import CredentialType
from app.http_identity import HEYM_USER_AGENT
from app.observability import tracing
from app.services.agent_tool_observability import (
    classify_tool_failure_status,
    normalize_tool_call_status,
    sanitize_persisted_tool_entry,
    sanitize_tool_payload,
    summarize_tool_calls,
)
from app.services.llm_provider import is_reasoning_model
from app.services.llm_trace import LLMTraceContext, record_llm_trace
from app.services.llm_transport import (
    ChatCompletionsTransport,
    RequestOpts,
    ResponsesTransport,
    ToolResult,
)
from app.services.model_router import (
    ModelRouter,
    fit_tool_outputs_to_budget,
    load_option_credential,
)
from app.services.openai_client import create_guarded_openai_client, create_openai_client
from app.services.ssrf_guard import get_guarded_http_client, guard_http_url

logger = logging.getLogger(__name__)

_WORKFLOW_INPUT_LOG_STR_MAX = 500


def _call_sub_workflow_inputs_for_log(raw: Any) -> Any:
    """Bounded copy of sub-workflow tool inputs for execution logs (SSE / progress)."""
    return sanitize_tool_payload(
        raw,
        max_chars=_WORKFLOW_INPUT_LOG_STR_MAX,
        max_depth=3,
        max_total_chars=2_000,
    )


def _progress_safe_tool_arguments(
    tool_name: str,
    tool_def: dict[str, Any] | None,
    args: Any,
) -> dict[str, Any]:
    """Redacted tool args for streaming progress (no input payloads)."""
    safe_args: dict[str, Any] = {}
    if not isinstance(args, dict):
        return safe_args
    safe_args["keys"] = list(args.keys())[:20]
    if isinstance(args.get("workflow_id"), str):
        safe_args["workflow_id"] = args["workflow_id"]
    if isinstance(args.get("sub_agent_label"), str):
        safe_args["sub_agent_label"] = args["sub_agent_label"]
    if tool_name == "call_sub_workflow" and tool_def:
        names_map = tool_def.get("_sub_workflow_names") or {}
        wid = args.get("workflow_id")
        if isinstance(wid, str):
            wn = names_map.get(wid)
            if isinstance(wn, str) and wn.strip():
                safe_args["workflow_name"] = wn.strip()
        if "inputs" in args:
            safe_args["inputs"] = _call_sub_workflow_inputs_for_log(args.get("inputs"))
    return safe_args


def _workflow_name_for_tool_entry(tool_def: dict[str, Any] | None, args: Any) -> str | None:
    if not tool_def or not isinstance(args, dict):
        return None
    names_map = tool_def.get("_sub_workflow_names") or {}
    wid = args.get("workflow_id")
    if isinstance(wid, str):
        wn = names_map.get(wid)
        if isinstance(wn, str) and wn.strip():
            return wn.strip()
    return None


def _tool_result_status(tool_result: Any) -> str:
    """Normalize tool result status for traces, metrics, and chat history."""
    if not isinstance(tool_result, dict):
        return "success"
    status = tool_result.get("status")
    # Empty / whitespace-only status is absent — fall through to error detection.
    if isinstance(status, str) and status.strip():
        normalized = normalize_tool_call_status(status)
        if normalized != "unknown":
            return normalized
    error_text = _tool_result_error(tool_result)
    if error_text:
        # Free-form error text may contain domain data such as "request timeout" or
        # "Cancelled deployment". Without a structured lifecycle status, it is an error.
        return "error"
    return "success"


def _coerce_tool_error_text(error: Any) -> str | None:
    """Normalize string or structured tool errors into display/status text."""
    if error is None:
        return None
    if isinstance(error, str):
        return error.strip() or None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        try:
            return json.dumps(error, default=str)
        except (TypeError, ValueError):
            return str(error)
    return str(error)


def _tool_result_error(tool_result: Any) -> str | None:
    """Return the most useful error text from a tool result, including nested outputs."""
    if not isinstance(tool_result, dict):
        return None
    formatted = _coerce_tool_error_text(tool_result.get("error"))
    if formatted:
        return formatted
    outputs = tool_result.get("outputs")
    if isinstance(outputs, dict):
        return _coerce_tool_error_text(outputs.get("error"))
    return None


def _attach_tool_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Attach aggregate tool metrics when tool_calls are present."""
    tool_calls = result.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        result["tool_metrics"] = summarize_tool_calls(tool_calls)
    return result


GOOGLE_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GOOGLE_IMAGEN_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

LLM_REQUEST_TIMEOUT = 60.0
BATCH_POLL_INTERVAL_SECONDS = 6.0
_BATCH_TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


@dataclass
class HumanReviewPause:
    review_markdown: str
    summary: str | None = None
    reason: str | None = None
    tool_name: str | None = None
    tool_source: str | None = None
    tool_arguments: dict[str, Any] | None = None
    match_strategy: str | None = None


def _batch_attr(batch: Any, name: str, default: Any = None) -> Any:
    value = getattr(batch, name, default)
    if value is default and isinstance(batch, dict):
        return batch.get(name, default)
    return value


def _normalize_batch_status(raw_status: str | None) -> str:
    status = (raw_status or "").strip().lower()
    if status == "completed":
        return "completed"
    if status in {"failed", "expired", "cancelled"}:
        return "failed"
    if status in {"in_progress", "finalizing", "cancelling"}:
        return "processing"
    return "pending"


def _extract_batch_request_counts(batch: Any, fallback_total: int) -> dict[str, int]:
    counts = _batch_attr(batch, "request_counts") or {}
    if hasattr(counts, "model_dump"):
        counts = counts.model_dump()
    total = counts.get("total") if isinstance(counts, dict) else None
    completed = counts.get("completed") if isinstance(counts, dict) else None
    failed = counts.get("failed") if isinstance(counts, dict) else None
    return {
        "total": int(total) if isinstance(total, int) else fallback_total,
        "completed": int(completed) if isinstance(completed, int) else 0,
        "failed": int(failed) if isinstance(failed, int) else 0,
    }


def _build_batch_progress_update(
    *,
    batch: Any,
    provider: str,
    model: str,
    fallback_total: int,
) -> dict[str, Any]:
    raw_status = str(_batch_attr(batch, "status") or "")
    counts = _extract_batch_request_counts(batch, fallback_total)
    return {
        "batchId": str(_batch_attr(batch, "id") or ""),
        "status": _normalize_batch_status(raw_status),
        "rawStatus": raw_status,
        "provider": provider,
        "model": model,
        "requestCounts": counts,
        "total": counts["total"],
        "completed": counts["completed"],
        "failed": counts["failed"],
        "timestamp": int(time.time() * 1000),
    }


def _extract_text_from_batch_body(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
                continue
            text_value = part.get("text")
            if isinstance(text_value, dict) and isinstance(text_value.get("value"), str):
                text_parts.append(text_value["value"])
        return "".join(text_parts)

    reasoning = message.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning
    return ""


def _error_text_from_batch_entry(
    entry: dict[str, Any], response_body: dict[str, Any]
) -> str | None:
    raw_error = entry.get("error")
    if isinstance(raw_error, dict):
        message = raw_error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return json.dumps(raw_error, default=str)
    if isinstance(raw_error, str) and raw_error.strip():
        return raw_error.strip()

    body_error = response_body.get("error")
    if isinstance(body_error, dict):
        message = body_error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return json.dumps(body_error, default=str)
    if isinstance(body_error, str) and body_error.strip():
        return body_error.strip()
    return None


def _parse_batch_output(
    raw_text: str,
    *,
    expected_count: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    items_by_index: dict[int, dict[str, Any]] = {
        index: {
            "index": index,
            "customId": f"item-{index}",
            "status": "error",
            "text": "",
            "error": "No result returned for this batch item.",
        }
        for index in range(expected_count)
    }
    aggregate_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        custom_id = str(entry.get("custom_id") or "")
        index = None
        if custom_id.startswith("item-"):
            raw_index = custom_id.removeprefix("item-")
            if raw_index.isdigit():
                index = int(raw_index)
        if index is None:
            continue

        response = entry.get("response")
        if not isinstance(response, dict):
            continue

        response_body = response.get("body") if isinstance(response.get("body"), dict) else {}
        status_code = response.get("status_code")
        usage = response_body.get("usage") if isinstance(response_body.get("usage"), dict) else {}
        for usage_key in aggregate_usage:
            usage_value = usage.get(usage_key)
            if isinstance(usage_value, int):
                aggregate_usage[usage_key] += usage_value

        error_text = _error_text_from_batch_entry(entry, response_body)
        success = isinstance(status_code, int) and 200 <= status_code < 300 and error_text is None
        items_by_index[index] = {
            "index": index,
            "customId": custom_id or f"item-{index}",
            "status": "success" if success else "error",
            "statusCode": status_code,
            "text": _extract_text_from_batch_body(response_body),
            "error": error_text,
            "usage": usage,
        }

    ordered_items = [items_by_index[index] for index in sorted(items_by_index)]
    return ordered_items, aggregate_usage


def _load_image_bytes(image_input: str) -> tuple[bytes, str]:
    if image_input.startswith("data:"):
        header, data = image_input.split(",", 1)
        mime_type = header.split(";")[0].replace("data:", "") or "image/png"
        return base64.b64decode(data), mime_type

    parsed = urlparse(image_input)
    if parsed.scheme in ("http", "https"):
        # The URL can be caller-controlled (e.g. "$userInput.body.imageUrl"), so
        # fetch through the same SSRF guard the HTTP node uses: scheme allowlist,
        # public-IP-only resolution, and dial-time egress pinning.
        guard_http_url(image_input, subject="LLM image input URL")
        response = get_guarded_http_client().get(
            image_input,
            timeout=30.0,
            headers={"User-Agent": HEYM_USER_AGENT},
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/png")
        mime_type = content_type.split(";")[0] or "image/png"
        return response.content, mime_type

    return base64.b64decode(image_input), "image/png"


def _log_request(method: str, base_url: str | None, kwargs: dict) -> None:
    safe_kwargs = {k: v for k, v in kwargs.items()}
    logger.debug(
        "\n" + "=" * 60 + "\n"
        f"[LLM REQUEST] {method}\n"
        f"Base URL: {base_url}\n"
        f"Params: {json.dumps(safe_kwargs, indent=2, default=str)}\n" + "=" * 60
    )


def _log_response(method: str, response: Any, elapsed_ms: float) -> None:
    try:
        response_dict = response.model_dump() if hasattr(response, "model_dump") else str(response)
        logger.debug(
            "\n" + "-" * 60 + "\n"
            f"[LLM RESPONSE] {method} ({elapsed_ms:.0f}ms)\n"
            f"Response: {json.dumps(response_dict, indent=2, default=str)}\n" + "-" * 60
        )
    except Exception as e:
        logger.debug(f"[LLM RESPONSE] {method} - Error logging: {e}\nRaw: {response}")


def _redact_image_input(image_input: str) -> str:
    if image_input.startswith("data:"):
        return "[data-uri]"
    if len(image_input) > 500 and not image_input.startswith("http"):
        return "[base64]"
    return image_input


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        message_copy = {**message}
        content = message_copy.get("content")
        if isinstance(content, list):
            cleaned_parts = []
            for part in content:
                if not isinstance(part, dict):
                    cleaned_parts.append(part)
                    continue
                if part.get("type") == "image_url":
                    image_url = part.get("image_url", {})
                    url = image_url.get("url")
                    if isinstance(url, str):
                        cleaned_parts.append(
                            {"type": "image_url", "image_url": {"url": _redact_image_input(url)}}
                        )
                    else:
                        cleaned_parts.append(part)
                else:
                    cleaned_parts.append(part)
            message_copy["content"] = cleaned_parts
        sanitized.append(message_copy)
    return sanitized


def _sanitize_image_response(response: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(response)
    image_value = sanitized.get("image")
    if isinstance(image_value, str) and image_value.startswith("data:"):
        sanitized["image"] = "[image-data]"
    return sanitized


def _get_provider_label(credential_type: CredentialType) -> str:
    if credential_type == CredentialType.google:
        return "Google"
    if credential_type == CredentialType.custom:
        return "Custom"
    return "OpenAI"


def _extract_text_from_response(
    response: Any,
    content_only: bool = False,
) -> str:
    """Extract text from OpenAI SDK response, handling reasoning models.

    When content_only=True (e.g. for structured JSON output), only return
    message.content. Never use reasoning - reasoning models put thinking there
    and the actual structured output goes in content.
    """
    message = response.choices[0].message
    content = message.content

    if content:
        return content

    if content_only:
        return ""

    # Cerebras reasoning models return content in 'reasoning' field
    if hasattr(message, "reasoning") and message.reasoning:
        return message.reasoning

    # Check raw dict if SDK didn't parse it
    raw = response.choices[0].model_dump() if hasattr(response.choices[0], "model_dump") else {}
    msg_dict = raw.get("message", {})
    if msg_dict.get("reasoning"):
        return msg_dict["reasoning"]

    return ""


def _has_complete_structured_content(
    content: str | None,
    response_format: dict[str, Any] | None,
) -> bool:
    """Return True when assistant content already satisfies structured output mode.

    Some providers may emit both a valid final JSON payload and extra tool calls in
    the same assistant turn. In that case we should prefer the valid structured
    content instead of blindly continuing the tool loop.
    """
    if response_format is None or not isinstance(content, str):
        return False

    text = content.strip()
    if not text:
        return False

    format_type = response_format.get("type")
    if format_type not in {"json_object", "json_schema"}:
        return False

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False

    if format_type == "json_object":
        return isinstance(parsed, dict)

    json_schema = response_format.get("json_schema")
    if not isinstance(json_schema, dict):
        return True

    schema = json_schema.get("schema")
    if not isinstance(schema, dict):
        return True

    expected_type = schema.get("type")
    if expected_type == "object":
        return isinstance(parsed, dict)
    if expected_type == "array":
        return isinstance(parsed, list)
    if expected_type == "string":
        return isinstance(parsed, str)
    if expected_type == "number":
        return isinstance(parsed, (int, float)) and not isinstance(parsed, bool)
    if expected_type == "integer":
        return isinstance(parsed, int) and not isinstance(parsed, bool)
    if expected_type == "boolean":
        return isinstance(parsed, bool)
    if expected_type == "null":
        return parsed is None
    return True


@dataclass(frozen=True)
class TurnBinding:
    """The client, provider and model serving one provider request.

    Without a router this is the credential the caller passed and never changes.
    With a router it is re-derived before every request, which is what lets an agent
    tool loop move between models mid-run.
    """

    client: OpenAI
    provider: str
    model: str
    credential_id: uuid.UUID | None = None
    credential_name: str | None = None
    router_credential_id: uuid.UUID | None = None
    router_label: str | None = None
    option_label: str | None = None
    fallback: bool = False
    routing_error: str | None = None


def _latest_tool_output_for_routing(tool_entries: list[dict[str, Any]]) -> str:
    """What the last turn's tools returned, as the router reads it beside the request."""
    texts: list[str] = []
    for entry in tool_entries or []:
        # The compressor records itself as a tool entry; it is bookkeeping, not output.
        if not isinstance(entry, dict) or entry.get("name") == "_context_compression":
            continue
        value = entry.get("result")
        if value is None:
            continue
        texts.append(
            value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
        )
    return fit_tool_outputs_to_budget(texts)


class _RoutedHistoryView:
    """Per-window history for a routed loop, where each turn can land on another model.

    The full history stays the source of truth and every append goes to it. A window
    that needed compression keeps its own compressed copy plus whatever came after, so
    squeezing a turn for a small model never shrinks a later turn on a larger one.
    """

    def __init__(self, history: list[dict[str, Any]]) -> None:
        self.history = history
        self._compressed: dict[int, tuple[list[dict[str, Any]], int]] = {}
        self._last_limit: int | None = None

    def working(self, limit: int | None) -> list[dict[str, Any]]:
        """The history as a model with this context window sees it."""
        cached = self._compressed.get(limit) if limit is not None else None
        if cached is None:
            return self.history
        compressed, covered = cached
        return [*compressed, *self.history[covered:]]

    async def for_turn(
        self, transport: Any, *, model: str, client: Any, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Fit the history to this turn's window, compressing a copy when it overflows."""
        self._last_limit = limit
        turn_history, info = await transport.compress(
            self.working(limit), model=model, client=client, context_limit_tokens=limit
        )
        if info is not None:
            self._compressed[limit] = (turn_history, len(self.history))
        return turn_history, info

    def sent(self) -> list[dict[str, Any]]:
        """What the latest turn's model is working with, later appends included."""
        return self.working(self._last_limit)


class LLMService:
    def __init__(
        self,
        credential_type: CredentialType,
        api_key: str,
        base_url: str | None = None,
        trace_context: LLMTraceContext | None = None,
        request_timeout: float = LLM_REQUEST_TIMEOUT,
        use_responses_api: bool = False,
        router: ModelRouter | None = None,
    ) -> None:
        if router is not None and use_responses_api:
            raise ValueError(
                "Auto Model does not support the Responses API. Turn the Responses API "
                "off, or pick a specific credential and model."
            )
        self.credential_type = credential_type
        self.api_key = api_key
        self.base_url = base_url
        self.trace_context = trace_context
        self.session_id = (trace_context.session_id if trace_context else None) or str(uuid.uuid4())
        self.request_timeout = request_timeout
        self.use_responses_api = use_responses_api
        self.router = router
        self._routed_calls: list[dict[str, Any]] = []
        # One clock for the whole request. Every routing decision and every provider
        # turn reports its offset from here, which is what lets the Duration
        # Breakdown draw a waterfall instead of stacking every bar at zero.
        self._request_started: float | None = None
        self._turn_timings: list[dict[str, Any]] = []

    def _get_client(self) -> tuple[OpenAI, str]:
        """Get OpenAI client configured for the credential type."""
        if self.credential_type == CredentialType.google:
            return create_openai_client(
                api_key=self.api_key,
                base_url=GOOGLE_OPENAI_BASE_URL,
                timeout=self.request_timeout,
            ), "Google"

        if self.credential_type == CredentialType.custom:
            if not self.base_url:
                raise ValueError("Base URL is required for custom provider")
            base = self.base_url.rstrip("/")
            if not base.endswith("/v1"):
                base = base + "/v1"
            return create_guarded_openai_client(
                api_key=self.api_key,
                base_url=base,
                subject="Custom LLM credential base URL",
                session_id=self.session_id,
                timeout=self.request_timeout,
            ), "Custom"

        # OpenAI (default)
        client_kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.request_timeout,
        }
        if self.base_url:
            return create_guarded_openai_client(
                base_url=self.base_url,
                subject="LLM credential base URL",
                session_id=self.session_id,
                **client_kwargs,
            ), "OpenAI"
        return create_openai_client(session_id=self.session_id, **client_kwargs), "OpenAI"

    def _client_for(
        self, credential_type: str, api_key: str, base_url: str | None
    ) -> tuple[OpenAI, str]:
        """Build a provider client for an arbitrary credential, not just self's."""
        if credential_type == CredentialType.google.value:
            return create_openai_client(
                api_key=api_key,
                base_url=GOOGLE_OPENAI_BASE_URL,
                timeout=self.request_timeout,
            ), "Google"

        if credential_type == CredentialType.custom.value:
            if not base_url:
                raise ValueError("Base URL is required for custom provider")
            base = base_url.rstrip("/")
            if not base.endswith("/v1"):
                base = base + "/v1"
            return create_guarded_openai_client(
                api_key=api_key,
                base_url=base,
                subject="Custom LLM credential base URL",
                session_id=self.session_id,
                timeout=self.request_timeout,
            ), "Custom"

        if base_url:
            return create_guarded_openai_client(
                api_key=api_key,
                base_url=base_url,
                subject="LLM credential base URL",
                session_id=self.session_id,
                timeout=self.request_timeout,
            ), "OpenAI"
        return create_openai_client(
            api_key=api_key, timeout=self.request_timeout, session_id=self.session_id
        ), "OpenAI"

    def _resolve_turn(
        self,
        *,
        model: str,
        system_instruction: str | None,
        message: str | None,
        tool_names: list[str] | None,
        latest_tool_output: str | None = None,
    ) -> TurnBinding:
        """Bind the client, provider and model for the next provider request.

        With no router this is the static credential and the caller's model, which is
        the behaviour every existing caller already gets. With a router the decision
        model picks an option first; identical states reuse the previous decision, so
        a tool loop only pays for a decision when the conversation has moved.
        """
        if self.router is None:
            client, provider = self._get_client()
            return TurnBinding(
                client=client,
                provider=provider,
                model=model,
                credential_id=self.trace_context.credential_id if self.trace_context else None,
            )

        # Most callers build their trace context after the router, so the router is
        # handed one here rather than at construction. Without this the decision call
        # writes no trace row at all and routing looks invisible in the Traces tab.
        if self.router.trace_context is None:
            self.router.trace_context = self.trace_context

        routing_started_ms = self._offset_ms()
        decision = self.router.route(
            system_instruction=system_instruction,
            message=message,
            tool_names=tool_names,
            latest_tool_output=latest_tool_output,
        )
        bound = load_option_credential(decision.option)
        client, provider = self._client_for(bound.credential_type, bound.api_key, bound.base_url)
        try:
            router_uuid: uuid.UUID | None = uuid.UUID(str(self.router.credential_id))
        except ValueError:
            router_uuid = None

        binding = TurnBinding(
            client=client,
            provider=provider,
            model=bound.option.model,
            credential_id=bound.credential_uuid,
            credential_name=bound.credential_name,
            router_credential_id=router_uuid,
            router_label=self.router.label,
            option_label=decision.option.label,
            fallback=decision.fallback,
            routing_error=decision.error,
        )
        self._routed_calls.append(
            {
                "turn": len(self._routed_calls) + 1,
                "startMs": routing_started_ms,
                "model": binding.model,
                "option": binding.option_label,
                "credentialName": binding.credential_name,
                "fallback": binding.fallback,
                "error": binding.routing_error,
                "decisionMs": decision.decision_ms,
                "decisionTraceId": decision.trace_id,
                "reused": decision.reused,
            }
        )
        return binding

    def _offset_ms(self) -> float:
        """Milliseconds since this request started, starting the clock on first use."""
        if self._request_started is None:
            self._request_started = time.time()
            return 0.0
        return round((time.time() - self._request_started) * 1000, 2)

    def _record_turn_timing(
        self,
        start_offset_ms: float,
        duration_ms: float,
        *,
        model: str | None = None,
        provider: str | None = None,
        turn_result: Any = None,
        tool_call_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """Record one provider call: when it ran, what it cost, and what it produced.

        The Traces detail shows this per turn, so it carries the same facts the
        aggregate header does rather than timing alone.
        """
        entry: dict[str, Any] = {
            "turn": len(self._turn_timings) + 1,
            "startMs": start_offset_ms,
            "durationMs": round(duration_ms, 2),
        }
        if model:
            entry["model"] = model
        if provider:
            entry["provider"] = provider
        if turn_result is not None:
            prompt = getattr(turn_result, "prompt_tokens", None)
            completion = getattr(turn_result, "completion_tokens", None)
            total = getattr(turn_result, "total_tokens", None)
            if isinstance(prompt, int):
                entry["promptTokens"] = prompt
            if isinstance(completion, int):
                entry["completionTokens"] = completion
            if isinstance(total, int):
                entry["totalTokens"] = total
            text = getattr(turn_result, "text", None)
            if isinstance(text, str) and text.strip():
                entry["textChars"] = len(text)
        if tool_call_count is not None:
            entry["toolCalls"] = tool_call_count
        if error:
            entry["error"] = error
        self._turn_timings.append(entry)

    def turn_timings(self) -> list[dict[str, Any]] | None:
        """Per-turn provider timing, or None when there is nothing to lay out."""
        return copy.deepcopy(self._turn_timings) if self._turn_timings else None

    def model_routing_summary(self) -> dict[str, Any] | None:
        """What the executor writes into node metadata, or None when no router ran."""
        if self.router is None or not self._routed_calls:
            return None
        return {
            "routerLabel": self.router.label,
            "routerCredentialId": str(self.router.credential_id),
            "decisionModel": self.router.config.decision_model,
            "decisionTotalMs": round(
                sum(float(call.get("decisionMs") or 0.0) for call in self._routed_calls), 2
            ),
            "turnTimings": self.turn_timings(),
            "calls": copy.deepcopy(self._routed_calls),
        }

    def _attach_routing_summary(self, result: dict[str, Any]) -> dict[str, Any]:
        """Hand the executor the routing summary; it pops this into node metadata."""
        routing_summary = self.model_routing_summary()
        if routing_summary:
            result["_model_routing"] = routing_summary
        return result

    def _get_transport(self) -> ChatCompletionsTransport | ResponsesTransport:
        if self.use_responses_api:
            return ResponsesTransport()
        return ChatCompletionsTransport()

    def _record_trace(
        self,
        request_type: str,
        provider: str,
        model: str | None,
        request: dict[str, Any],
        response: dict[str, Any] | None,
        error: str | None,
        elapsed_ms: float | None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        binding: TurnBinding | None = None,
    ) -> None:
        if not self.trace_context:
            return
        context = self.trace_context
        routing_summary = self.model_routing_summary()
        if routing_summary is not None:
            context = replace(context, model_routing=routing_summary)
        if binding is not None and binding.router_label is not None:
            # `replace` keeps `trace_ids` as the same list object, which the executor
            # reads back to link the node to its trace. Constructing a fresh
            # LLMTraceContext here would give it a new list and break that link.
            context = replace(
                context,
                credential_id=binding.credential_id or context.credential_id,
                router_credential_id=binding.router_credential_id,
                router_label=binding.router_label,
            )
        record_llm_trace(
            context=context,
            request_type=request_type,
            request=request,
            response=response,
            model=model,
            provider=provider,
            error=error,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            elapsed_ms=elapsed_ms,
        )

    async def execute(
        self,
        model: str,
        system_instruction: str | None,
        user_message: str,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        image_input: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        skills_included: list[str] | None = None,
        content_only: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        binding = self._resolve_turn(
            model=model,
            system_instruction=system_instruction,
            message=user_message,
            tool_names=None,
        )
        client, provider, model = binding.client, binding.provider, binding.model
        transport = self._get_transport()

        history = transport.start(
            system_instruction=system_instruction,
            conversation_history=conversation_history,
            user_message=user_message,
            image_input=image_input,
        )
        opts = RequestOpts(
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
        )
        kwargs = transport.build_kwargs(model=model, history=history, tools=None, opts=opts)

        base_url = client.base_url if hasattr(client, "base_url") else self.base_url
        _log_request(provider, str(base_url), kwargs)

        trace_request: dict[str, Any] = {**kwargs, **transport.trace_request(history, None)}
        if skills_included:
            trace_request["skills_included"] = skills_included

        turn_started_ms = self._offset_ms()
        start_time = time.time()
        turn = None
        for attempt in range(2):
            try:
                turn = await asyncio.to_thread(
                    transport.create,
                    client=client,
                    model=model,
                    history=history,
                    tools=None,
                    opts=opts,
                )
                break
            except Exception as exc:
                elapsed_ms = (time.time() - start_time) * 1000
                err_msg = str(exc).lower()
                is_422 = getattr(exc, "status_code", None) == 422 or "422" in err_msg
                has_disable_reasoning = extra_body is not None and "disable_reasoning" in (
                    extra_body or {}
                )
                if (
                    attempt == 0
                    and is_422
                    and has_disable_reasoning
                    and ("disable_reasoning" in err_msg or "disabling reasoning" in err_msg)
                ):
                    opts.extra_body = None
                    kwargs = transport.build_kwargs(
                        model=model, history=history, tools=None, opts=opts
                    )
                    logger.info(
                        "Retrying without extra_body (disable_reasoning not supported by model %s)",
                        model,
                    )
                    continue
                self._record_trace(
                    request_type=transport.name,
                    provider=provider,
                    model=model,
                    request=trace_request,
                    response=None,
                    error=str(exc),
                    elapsed_ms=round(elapsed_ms, 2),
                    binding=binding,
                )
                raise
        elapsed_ms = (time.time() - start_time) * 1000
        assert turn is not None  # loop exits via break (success) or raise (failure)
        self._record_turn_timing(
            turn_started_ms,
            elapsed_ms,
            model=model,
            provider=provider,
            turn_result=turn,
        )

        _log_response(provider, turn.raw_items[0] if turn.raw_items else None, elapsed_ms)

        total_tokens = turn.total_tokens
        tokens_per_sec = round(total_tokens / (elapsed_ms / 1000), 2) if elapsed_ms > 0 else 0

        # content_only keeps structured JSON out of the provider `reasoning` fallback.
        text = turn.text if content_only else transport.final_text(turn)

        result = {
            "text": text,
            "model": model,
            "usage": {
                "prompt_tokens": turn.prompt_tokens,
                "completion_tokens": turn.completion_tokens,
                "total_tokens": total_tokens,
            },
            "tokens_per_sec": tokens_per_sec,
            "elapsed_ms": round(elapsed_ms, 2),
        }
        self._record_trace(
            request_type=transport.name,
            provider=provider,
            model=model,
            request=trace_request,
            response=result,
            error=None,
            elapsed_ms=round(elapsed_ms, 2),
            prompt_tokens=result["usage"]["prompt_tokens"],
            completion_tokens=result["usage"]["completion_tokens"],
            total_tokens=result["usage"]["total_tokens"],
            binding=binding,
        )
        return self._attach_routing_summary(result)

    async def probe_batch_support(self) -> tuple[bool, str]:
        if self.credential_type == CredentialType.openai:
            return True, "Batch mode is available for this OpenAI credential."
        return False, "Batch mode is only available for OpenAI credentials in Heym."

    async def execute_batch(
        self,
        *,
        model: str,
        system_instruction: str | None,
        user_messages: list[str],
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        skills_included: list[str] | None = None,
        on_status_update: Callable[[dict[str, Any]], None] | None = None,
        should_abort: Callable[[], str | None] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.router is not None:
            raise ValueError(
                "Batch mode is not available for Model Router credentials: a batch job "
                "runs against one fixed model. Pick a specific credential and model."
            )
        if not user_messages:
            raise ValueError("Batch mode requires at least one item.")

        supported, support_reason = await self.probe_batch_support()
        if not supported:
            raise ValueError(support_reason)

        client, provider = self._get_client()

        is_reasoning = is_reasoning_model(model)
        batch_requests: list[dict[str, Any]] = []
        for index, item_message in enumerate(user_messages):
            messages: list[dict[str, Any]] = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            if conversation_history:
                for msg in conversation_history:
                    messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": item_message})

            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
            }
            if max_tokens is not None:
                if is_reasoning:
                    body["max_completion_tokens"] = max_tokens
                else:
                    body["max_tokens"] = max_tokens
            if is_reasoning and reasoning_effort:
                body["reasoning_effort"] = reasoning_effort
            elif temperature is not None:
                body["temperature"] = temperature
            if response_format is not None:
                body["response_format"] = response_format
            if extra_body:
                # Batch entries carry the raw request body, so extra params merge at the
                # top level instead of nesting under an "extra_body" key.
                body.update(copy.deepcopy(extra_body))

            batch_requests.append(
                {
                    "custom_id": f"item-{index}",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": body,
                }
            )

        jsonl_payload = "\n".join(json.dumps(item, ensure_ascii=True) for item in batch_requests)
        batch_file = io.BytesIO(jsonl_payload.encode("utf-8"))
        trace_request: dict[str, Any] = {
            "model": model,
            "provider": provider,
            "batch_size": len(user_messages),
            "reasoning_effort": reasoning_effort,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        if skills_included:
            trace_request["skills_included"] = skills_included

        start_time = time.time()
        try:
            uploaded_file = await asyncio.to_thread(
                client.files.create,
                file=("heym-batch-input.jsonl", batch_file),
                purpose="batch",
            )
            batch = await asyncio.to_thread(
                client.batches.create,
                completion_window="24h",
                endpoint="/v1/chat/completions",
                input_file_id=uploaded_file.id,
            )
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_trace(
                request_type="batches.chat.completions",
                provider=provider,
                model=model,
                request=trace_request,
                response=None,
                error=str(exc),
                elapsed_ms=round(elapsed_ms, 2),
            )
            raise

        last_progress_signature: tuple[object, ...] | None = None

        def emit_progress(progress: dict[str, Any]) -> None:
            nonlocal last_progress_signature
            progress_signature = (
                progress.get("status"),
                progress.get("rawStatus"),
                progress.get("total"),
                progress.get("completed"),
                progress.get("failed"),
            )
            if progress_signature == last_progress_signature:
                return
            last_progress_signature = progress_signature
            if on_status_update is None:
                return
            on_status_update(progress)

        emit_progress(
            _build_batch_progress_update(
                batch=batch,
                provider=provider,
                model=model,
                fallback_total=len(user_messages),
            )
        )

        while True:
            if should_abort is not None:
                abort_reason = should_abort()
                if abort_reason:
                    raise RuntimeError(abort_reason)

            batch = await asyncio.to_thread(client.batches.retrieve, batch.id)
            progress = _build_batch_progress_update(
                batch=batch,
                provider=provider,
                model=model,
                fallback_total=len(user_messages),
            )
            emit_progress(progress)

            raw_status = str(progress["rawStatus"]).lower()
            if raw_status in _BATCH_TERMINAL_STATUSES:
                break
            await asyncio.sleep(BATCH_POLL_INTERVAL_SECONDS)

        if str(_batch_attr(batch, "status") or "").lower() != "completed":
            elapsed_ms = (time.time() - start_time) * 1000
            error_message = f"Batch request ended with status '{_batch_attr(batch, 'status')}'."
            self._record_trace(
                request_type="batches.chat.completions",
                provider=provider,
                model=model,
                request=trace_request,
                response={
                    "batchId": str(_batch_attr(batch, "id") or ""),
                    "status": _normalize_batch_status(str(_batch_attr(batch, "status") or "")),
                },
                error=error_message,
                elapsed_ms=round(elapsed_ms, 2),
            )
            raise ValueError(error_message)

        output_file_id = _batch_attr(batch, "output_file_id")
        if not output_file_id:
            elapsed_ms = (time.time() - start_time) * 1000
            error_message = "Batch completed without an output file."
            self._record_trace(
                request_type="batches.chat.completions",
                provider=provider,
                model=model,
                request=trace_request,
                response={
                    "batchId": str(_batch_attr(batch, "id") or ""),
                    "status": "completed",
                },
                error=error_message,
                elapsed_ms=round(elapsed_ms, 2),
            )
            raise ValueError(error_message)

        file_content = await asyncio.to_thread(client.files.content, output_file_id)
        raw_output_text = (
            file_content.text if hasattr(file_content, "text") else file_content.read()
        )
        if isinstance(raw_output_text, bytes):
            raw_output_text = raw_output_text.decode("utf-8")

        results, aggregate_usage = _parse_batch_output(
            str(raw_output_text),
            expected_count=len(user_messages),
        )
        success_count = sum(1 for item in results if item.get("status") == "success")
        failed_count = len(results) - success_count
        merged_counts = _extract_batch_request_counts(batch, len(user_messages))
        merged_counts["completed"] = max(merged_counts["completed"], success_count)
        merged_counts["failed"] = max(merged_counts["failed"], failed_count)
        elapsed_ms = (time.time() - start_time) * 1000
        text = "\n\n".join(
            str(item.get("text") or "")
            for item in results
            if item.get("status") == "success" and str(item.get("text") or "").strip()
        )

        result = {
            "text": text,
            "model": model,
            "provider": provider,
            "batchId": str(_batch_attr(batch, "id") or ""),
            "status": "completed",
            "rawStatus": str(_batch_attr(batch, "status") or ""),
            "requestCounts": merged_counts,
            "total": len(results),
            "completed": success_count,
            "failed": failed_count,
            "results": results,
            "usage": aggregate_usage,
            "elapsed_ms": round(elapsed_ms, 2),
        }
        self._record_trace(
            request_type="batches.chat.completions",
            provider=provider,
            model=model,
            request=trace_request,
            response=result,
            error=None,
            elapsed_ms=round(elapsed_ms, 2),
            prompt_tokens=aggregate_usage["prompt_tokens"],
            completion_tokens=aggregate_usage["completion_tokens"],
            total_tokens=aggregate_usage["total_tokens"],
        )
        return result

    async def execute_with_tools(
        self,
        model: str,
        system_instruction: str | None,
        user_message: str,
        tools: list[dict[str, Any]],
        tool_executor: Callable[[dict[str, Any], str, dict, float], object],
        tool_timeout_seconds: float = 61.0,
        max_tool_iterations: int = 41,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        image_input: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        skills_included: list[str] | None = None,
        on_tool_call: Callable[[dict[str, Any]], None] | None = None,
        initial_messages: list[dict[str, Any]] | None = None,
        initial_tool_calls: list[dict[str, Any]] | None = None,
        initial_elapsed_ms: float = 0.0,
        initial_prompt_tokens: int = 0,
        initial_completion_tokens: int = 0,
        should_abort: Callable[[], str | None] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute LLM with tool calling loop."""
        # With a router there is no credential to bind yet: every turn binds its own
        # client, provider and model from the decision model's answer. Without one this
        # is the single static binding every existing caller already gets.
        binding: TurnBinding | None = None
        client: Any = None
        provider = ""
        if self.router is None:
            client, provider = self._get_client()

        transport = self._get_transport()
        if initial_messages is not None:
            history = transport.load(initial_messages, system_instruction)
            if system_instruction or user_message:
                logger.debug(
                    "execute_with_tools resumed from initial_messages; refreshed system prompt"
                )
        else:
            history = transport.start(
                system_instruction=system_instruction,
                conversation_history=conversation_history,
                user_message=user_message,
                image_input=image_input,
            )

        openai_tools = []
        for t in tools:
            params = t.get("parameters")
            if isinstance(params, str):
                try:
                    params = json.loads(params) if params else {"type": "object", "properties": {}}
                except json.JSONDecodeError:
                    params = {"type": "object", "properties": {}}
            elif not params:
                params = {"type": "object", "properties": {}}
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": params,
                    },
                }
            )

        tools_by_name = {t["name"]: t for t in tools}
        total_elapsed_ms = float(initial_elapsed_ms)
        total_prompt_tokens = int(initial_prompt_tokens)
        total_completion_tokens = int(initial_completion_tokens)
        tool_calls_collected: list[dict[str, Any]] = copy.deepcopy(initial_tool_calls or [])
        last_assistant_turn_had_tool_calls = False

        from app.services.context_compressor import get_context_limit

        # Recomputed per turn: a routed run can change model between iterations.
        _context_limit: int | None = None
        tool_names = [t["name"] for t in tools]
        latest_tool_output: str | None = None
        routed_tool_cursor = len(tool_calls_collected)
        # Without a router there is one window, so compression may replace the history.
        routed_view = _RoutedHistoryView(history) if self.router is not None else None

        def _sent_history() -> Any:
            return routed_view.sent() if routed_view is not None else history

        def _trace_request() -> dict[str, Any]:
            # Must go through the transport: a trace row is stored as JSON and a
            # transport's own history object is not serializable.
            req: dict[str, Any] = transport.trace_request(_sent_history(), openai_tools)
            if skills_included:
                req["skills_included"] = skills_included
            return req

        def _build_error_result(
            error_text: str,
            extra_tool_entry: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            result = {
                "text": "",
                "model": model,
                "error": error_text,
                "usage": {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens,
                },
                "elapsed_ms": round(total_elapsed_ms, 2),
            }
            combined_tool_calls = copy.deepcopy(tool_calls_collected)
            if extra_tool_entry is not None:
                patched = copy.deepcopy(extra_tool_entry)
                explicit_status = (
                    patched.get("status") if isinstance(patched.get("status"), str) else None
                )
                failure_status = classify_tool_failure_status(
                    error_text,
                    explicit_status=explicit_status,
                )
                if explicit_status not in {"success", "error", "timeout", "cancelled"} and (
                    failure_status in {"timeout", "cancelled"}
                ):
                    patched["status"] = failure_status
                    patched["result"] = {
                        "error": error_text,
                        "status": failure_status,
                    }
                combined_tool_calls.append(patched)
            if combined_tool_calls:
                result["tool_calls"] = combined_tool_calls
            _attach_tool_metrics(result)
            self._record_trace(
                request_type=transport.name,
                provider=provider,
                model=model,
                request=_trace_request(),
                response=result,
                error=error_text,
                elapsed_ms=round(total_elapsed_ms, 2),
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                binding=binding,
            )
            return self._attach_routing_summary(result)

        def _abort_reason_from_tool_result(tool_result: Any) -> str | None:
            """Return an abort reason only for explicit cancelled tool outcomes.

            Free-form error text (including MCP/server-controlled strings) must
            not stop the agent loop. Only ``status: cancelled`` is a trusted
            cancel signal from a returned tool payload; parent Stop uses
            ``should_abort()``.
            """
            if not isinstance(tool_result, dict):
                return None
            status = tool_result.get("status")
            if isinstance(status, str) and normalize_tool_call_status(status) == "cancelled":
                return _tool_result_error(tool_result) or "Workflow execution cancelled"
            return None

        for iteration in range(max_tool_iterations):
            if should_abort is not None:
                abort_reason = should_abort()
                if abort_reason:
                    return _build_error_result(abort_reason)

            # The cursor starts at the current length so a resumed agent does not replay
            # `initial_tool_calls` as if they were this turn's output.
            new_tool_entries = tool_calls_collected[routed_tool_cursor:]
            if new_tool_entries:
                latest_tool_output = _latest_tool_output_for_routing(new_tool_entries)
                routed_tool_cursor = len(tool_calls_collected)

            binding = self._resolve_turn(
                model=model,
                system_instruction=system_instruction,
                message=user_message,
                latest_tool_output=latest_tool_output,
                tool_names=tool_names,
            )
            client, provider, model = binding.client, binding.provider, binding.model
            _context_limit = get_context_limit(model, client)

            if routed_view is not None:
                turn_history, _compression_info = await routed_view.for_turn(
                    transport, model=model, client=client, limit=_context_limit
                )
            else:
                history, _compression_info = await transport.compress(
                    history, model=model, client=client, context_limit_tokens=_context_limit
                )
                turn_history = history
            if _compression_info is not None:
                _comp_entry: dict[str, Any] = {
                    "name": "_context_compression",
                    "arguments": {
                        "messages_compressed": _compression_info["messages_compressed"],
                    },
                    "result": {
                        "tokens_before": _compression_info["tokens_before"],
                        "tokens_after": _compression_info["tokens_after"],
                    },
                    "elapsed_ms": _compression_info["elapsed_ms"],
                }
                tool_calls_collected.append(_comp_entry)
                if on_tool_call:
                    on_tool_call(
                        {
                            "name": "_context_compression",
                            "arguments": {
                                "messages_compressed": _compression_info["messages_compressed"],
                                "tokens_before": _compression_info["tokens_before"],
                                "tokens_after": _compression_info["tokens_after"],
                            },
                            "result": "Context compressed successfully",
                            "elapsed_ms": _compression_info["elapsed_ms"],
                            "phase": "compression",
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                self._record_trace(
                    request_type="context.compression",
                    provider=provider,
                    model=model,
                    request={
                        "messages_before": _compression_info["messages_before_count"],
                        "tokens_estimated_before": _compression_info["tokens_before"],
                    },
                    response={
                        "messages_after": _compression_info["messages_after_count"],
                        "tokens_estimated_after": _compression_info["tokens_after"],
                    },
                    error=None,
                    elapsed_ms=_compression_info["elapsed_ms"],
                    binding=binding,
                )

            opts = RequestOpts(
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                response_format=response_format,
                extra_body=extra_body,
            )

            base_url = client.base_url if hasattr(client, "base_url") else self.base_url
            _log_request(
                provider, str(base_url), transport.trace_request(turn_history, openai_tools)
            )

            turn_started_ms = self._offset_ms()
            start_time = time.time()
            try:
                turn = await asyncio.to_thread(
                    transport.create,
                    client=client,
                    model=model,
                    history=turn_history,
                    tools=openai_tools,
                    opts=opts,
                )
            except Exception as exc:
                elapsed_ms = (time.time() - start_time) * 1000
                self._record_turn_timing(
                    turn_started_ms,
                    elapsed_ms,
                    model=model,
                    provider=provider,
                    error=str(exc),
                )
                self._record_trace(
                    request_type=transport.name,
                    provider=provider,
                    model=model,
                    request=_trace_request(),
                    response=None,
                    error=str(exc),
                    elapsed_ms=round(elapsed_ms, 2),
                    binding=binding,
                )
                raise
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_turn_timing(
                turn_started_ms,
                elapsed_ms,
                model=model,
                provider=provider,
                turn_result=turn,
                tool_call_count=len(turn.tool_calls or []),
            )
            total_elapsed_ms += elapsed_ms
            total_prompt_tokens += turn.prompt_tokens
            total_completion_tokens += turn.completion_tokens

            _log_response(provider, turn.raw_items[0] if turn.raw_items else None, elapsed_ms)

            tool_calls = turn.tool_calls
            last_assistant_turn_had_tool_calls = bool(tool_calls)
            structured_content = turn.text or None

            if (
                tool_calls
                and tool_calls_collected
                and _has_complete_structured_content(structured_content, response_format)
            ):
                result = {
                    "text": structured_content.strip(),
                    "model": model,
                    "usage": {
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                    "elapsed_ms": round(total_elapsed_ms, 2),
                }
                if tool_calls_collected:
                    result["tool_calls"] = tool_calls_collected
                _attach_tool_metrics(result)
                self._record_trace(
                    request_type=transport.name,
                    provider=provider,
                    model=model,
                    request=_trace_request(),
                    response=result,
                    error=None,
                    elapsed_ms=round(total_elapsed_ms, 2),
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                    binding=binding,
                )
                return self._attach_routing_summary(result)

            if not tool_calls:
                text = transport.final_text(turn)
                result = {
                    "text": text,
                    "model": model,
                    "usage": {
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                    "elapsed_ms": round(total_elapsed_ms, 2),
                }
                if tool_calls_collected:
                    result["tool_calls"] = tool_calls_collected
                _attach_tool_metrics(result)
                self._record_trace(
                    request_type=transport.name,
                    provider=provider,
                    model=model,
                    request=_trace_request(),
                    response=result,
                    error=None,
                    elapsed_ms=round(total_elapsed_ms, 2),
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                    binding=binding,
                )
                return self._attach_routing_summary(result)

            messages_before_tool_response = copy.deepcopy(transport.dump(history))
            hitl_tcs = [
                tc for tc in tool_calls if tools_by_name.get(tc.name, {}).get("_source") == "hitl"
            ]
            sub_agent_tcs = [
                tc
                for tc in tool_calls
                if tools_by_name.get(tc.name, {}).get("_source") == "sub_agent"
            ]
            other_tcs = [tc for tc in tool_calls if tc not in sub_agent_tcs and tc not in hitl_tcs]
            # One slot per assistant tool call (index-aligned) so duplicate tool_call ids
            # or parallel sub-agent runs cannot overwrite each other's results.
            slot_results: list[tuple[str, dict[str, Any]] | None] = [None] * len(tool_calls)
            sub_slots = [
                i
                for i, tc in enumerate(tool_calls)
                if tools_by_name.get(tc.name, {}).get("_source") == "sub_agent"
            ]
            other_slots = [
                i
                for i, tc in enumerate(tool_calls)
                if tc not in sub_agent_tcs and tc not in hitl_tcs
            ]

            def _build_pending_result(
                paused_tool_name: str,
                pause_request: HumanReviewPause,
                pending_tool_entry: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                review_markdown = pause_request.review_markdown.strip()
                if not review_markdown:
                    review_markdown = "Human review is required before this agent continues."
                pending_tool_calls = copy.deepcopy(tool_calls_collected)
                if pending_tool_entry is not None:
                    # pending_tool_entry is already sanitized in `_run_one_tool`.
                    pending_tool_calls.append(copy.deepcopy(pending_tool_entry))
                result = {
                    "text": review_markdown,
                    "model": model,
                    "usage": {
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                    "elapsed_ms": round(total_elapsed_ms, 2),
                    "_hitl_pending": {
                        "review_mode": "tool_call",
                        "resume_mode": "continue_agent",
                        "summary": (pause_request.summary or "").strip(),
                        "draft_text": review_markdown,
                        "agent_state": {
                            "messages": messages_before_tool_response,
                            "tool_calls": copy.deepcopy(pending_tool_calls),
                            "elapsed_ms": round(total_elapsed_ms, 2),
                            "prompt_tokens": total_prompt_tokens,
                            "completion_tokens": total_completion_tokens,
                            "remaining_tool_iterations": max(max_tool_iterations - iteration, 1),
                        },
                        "blocked_action": pause_request.reason,
                        "tool_name": pause_request.tool_name or paused_tool_name,
                        "tool_source": pause_request.tool_source,
                        "tool_arguments": copy.deepcopy(pause_request.tool_arguments or {}),
                        "match_strategy": pause_request.match_strategy,
                    },
                }
                if pending_tool_calls:
                    result["tool_calls"] = pending_tool_calls
                _attach_tool_metrics(result)
                self._record_trace(
                    request_type=transport.name,
                    provider=provider,
                    model=model,
                    request=_trace_request(),
                    response=result,
                    error=None,
                    elapsed_ms=round(total_elapsed_ms, 2),
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                    binding=binding,
                )
                return self._attach_routing_summary(result)

            async def _run_one_tool(
                tc: Any,
            ) -> tuple[str, str | None, dict[str, Any] | None, HumanReviewPause | None, str | None]:
                name = tc.name
                tool_call_id = getattr(tc, "id", None)
                args_str = tc.arguments or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                tool_def = tools_by_name.get(name)
                # Preflight: stop before start/executor when the run was cancelled after
                # a prior tool's terminal callbacks (or between sequential tools).
                if should_abort is not None:
                    preflight_abort = should_abort()
                    if preflight_abort:
                        return tc.id, None, None, None, preflight_abort
                # Emit "tool started" progress early (do not include values to avoid secrets).
                if on_tool_call:
                    safe_args = _progress_safe_tool_arguments(name, tool_def, args)
                    on_tool_call(
                        {
                            "name": name,
                            "arguments": safe_args,
                            "result": None,
                            "elapsed_ms": 0,
                            "phase": "start",
                            "tool_call_id": tool_call_id,
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                tool_start = time.monotonic()
                started_at = int(time.time() * 1000)
                # Offset on the request clock, so the breakdown can place this tool
                # where it ran. Parallel tools overlap, which is the point.
                tool_start_offset_ms = self._offset_ms()
                tool_trace_id: str | None = None
                tool_source = tool_def.get("_source") if tool_def else None
                mcp_server = tool_def.get("_mcp_server") if tool_def else None
                pending_pause: HumanReviewPause | None = None
                pending_entry: dict[str, Any] | None = None
                result_str = ""
                tool_result: Any = None
                abort_reason: str | None = None
                completed_tool_abort_reason: str | None = None
                tool_status = "success"
                with tracing.agent_tool_span(
                    tool_name=name,
                    tool_call_id=tool_call_id,
                    source=tool_source,
                    mcp_server=mcp_server,
                    workflow_id=(
                        str(self.trace_context.workflow_id)
                        if self.trace_context and self.trace_context.workflow_id
                        else None
                    ),
                    node_id=self.trace_context.node_id if self.trace_context else None,
                    node_label=self.trace_context.node_label if self.trace_context else None,
                    iteration=iteration,
                ) as tool_span:
                    tracing.set_span_attribute(
                        tool_span,
                        "heym.agent.tool.args_bytes",
                        len(args_str.encode("utf-8")),
                    )
                    if not tool_def:
                        result_str = json.dumps({"error": f"Unknown tool: {name}"})
                        tool_result = {"error": f"Unknown tool: {name}"}
                    else:
                        try:
                            tool_result = await asyncio.to_thread(
                                tool_executor,
                                tool_def,
                                name,
                                args,
                                tool_timeout_seconds,
                            )
                            if isinstance(tool_result, HumanReviewPause):
                                pending_pause = tool_result
                                pending_entry = sanitize_persisted_tool_entry(
                                    {
                                        "tool_call_id": tool_call_id,
                                        "name": name,
                                        "arguments": args,
                                        "result": None,
                                        "elapsed_ms": 0.0,
                                        "start_ms": tool_start_offset_ms,
                                        "status": "pending",
                                        "started_at": started_at,
                                        "finished_at": 0,
                                        **({"source": tool_source} if tool_source else {}),
                                    }
                                )
                                tracing.set_span_attribute(
                                    tool_span, "heym.agent.tool.status", "pending"
                                )
                                tracing.set_span_attribute(
                                    tool_span, "heym.agent.tool.result_bytes", 0
                                )
                            else:
                                # A tool that ran work of its own (a sub-agent, a
                                # sub-workflow) hands back the trace it wrote under a
                                # private key. Take it off before serialising, so the
                                # model never sees an id it has no use for.
                                if isinstance(tool_result, dict) and "_trace_id" in tool_result:
                                    tool_result = dict(tool_result)
                                    candidate = tool_result.pop("_trace_id", None)
                                    if isinstance(candidate, str) and candidate:
                                        tool_trace_id = candidate
                                result_str = json.dumps(tool_result, default=str)
                        except Exception as exc:
                            tracing.record_agent_tool_exception(tool_span, exc)
                            failure_status = classify_tool_failure_status(exc)
                            result_str = json.dumps(
                                {"error": str(exc), "status": failure_status},
                                default=str,
                            )
                            tool_result = {"error": str(exc), "status": failure_status}
                    if pending_pause is None:
                        abort_reason = _abort_reason_from_tool_result(tool_result)
                    if (
                        abort_reason is None
                        and pending_pause is not None
                        and should_abort is not None
                    ):
                        # HITL pause is in-flight: cancel can arrive before terminal events.
                        abort_reason = should_abort()
                    if abort_reason is not None:
                        # An in-flight HITL pause may be cancelled. Once a tool has returned,
                        # preserve cancellation reported by the tool itself.
                        pending_pause = None
                        pending_entry = None
                        tool_status = classify_tool_failure_status(
                            abort_reason,
                            explicit_status=_tool_result_status(tool_result)
                            if tool_result is not None
                            else None,
                        )
                        tool_result = {"error": abort_reason, "status": tool_status}
                        result_str = json.dumps(tool_result)
                    if pending_pause is None:
                        tracing.set_span_attribute(
                            tool_span,
                            "heym.agent.tool.result_bytes",
                            len(result_str.encode("utf-8")),
                        )
                        if abort_reason is None:
                            tool_status = _tool_result_status(tool_result)
                        tracing.set_span_attribute(tool_span, "heym.agent.tool.status", tool_status)
                        if tool_status in {"error", "timeout", "cancelled"}:
                            from opentelemetry.trace import StatusCode

                            tracing.set_span_status(
                                tool_span,
                                StatusCode.ERROR,
                                _tool_result_error(tool_result) or tool_status,
                            )
                tool_elapsed_ms = round((time.monotonic() - tool_start) * 1000, 2)
                if pending_pause is not None and pending_entry is not None:
                    pending_entry["elapsed_ms"] = tool_elapsed_ms
                    pending_entry["finished_at"] = int(time.time() * 1000)
                    if on_tool_call:
                        on_tool_call(
                            {
                                "name": name,
                                "arguments": _progress_safe_tool_arguments(name, tool_def, args),
                                "result": None,
                                "elapsed_ms": tool_elapsed_ms,
                                "phase": "end",
                                "status": "pending",
                                "tool_call_id": tool_call_id,
                                "timestamp": int(time.time() * 1000),
                            }
                        )
                        on_tool_call(
                            {
                                "name": name,
                                "arguments": _progress_safe_tool_arguments(name, tool_def, args),
                                "result": {"pending": True},
                                "elapsed_ms": tool_elapsed_ms,
                                "phase": "result",
                                "status": "pending",
                                "tool_call_id": tool_call_id,
                                "timestamp": int(time.time() * 1000),
                            }
                        )
                    return tc.id, None, pending_entry, pending_pause, None
                entry: dict[str, Any] = sanitize_persisted_tool_entry(
                    {
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "arguments": args,
                        "result": tool_result,
                        "elapsed_ms": tool_elapsed_ms,
                        "start_ms": tool_start_offset_ms,
                        "status": tool_status,
                        "started_at": started_at,
                        "finished_at": int(time.time() * 1000),
                        **({"trace_id": tool_trace_id} if tool_trace_id else {}),
                        **({"source": tool_source} if tool_source else {}),
                        **({"mcp_server": mcp_server} if mcp_server else {}),
                    }
                )
                wf_display = _workflow_name_for_tool_entry(tool_def, args)
                if wf_display:
                    entry["workflow_name"] = wf_display
                if on_tool_call:
                    # Emit "tool finished" progress without sensitive payloads.
                    on_tool_call(
                        {
                            "name": name,
                            "arguments": _progress_safe_tool_arguments(name, tool_def, args),
                            "result": None,
                            "elapsed_ms": tool_elapsed_ms,
                            "phase": "end",
                            "status": tool_status,
                            "tool_call_id": tool_call_id,
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                    # The persisted entry is already redacted and bounded. Reuse that same
                    # privacy boundary so the live Debug panel retains useful result evidence.
                    on_tool_call(
                        {
                            "name": name,
                            "arguments": _progress_safe_tool_arguments(name, tool_def, args),
                            "result": entry.get("result"),
                            "elapsed_ms": tool_elapsed_ms,
                            "phase": "result",
                            "status": tool_status,
                            "tool_call_id": tool_call_id,
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                # After terminal callbacks so Stop pressed on the first result is observed
                # before the next sequential tool emits start / reaches the executor.
                if abort_reason is None and should_abort is not None:
                    completed_tool_abort_reason = should_abort()
                return tc.id, result_str, entry, None, abort_reason or completed_tool_abort_reason

            def _commit_completed_tool_slots() -> None:
                """Persist finished tool slots before an early HITL/abort return."""
                for slot, tc in enumerate(tool_calls):
                    packed = slot_results[slot]
                    if packed is None:
                        continue
                    result_str, entry = packed
                    tool_calls_collected.append(entry)
                    transport.append_tool_results(
                        history, [ToolResult(call_id=tc.id, output=result_str)]
                    )
                    slot_results[slot] = None

            def _store_completed_tool_slot(
                slot: int,
                result_str: str | None,
                entry: dict[str, Any] | None,
            ) -> None:
                if result_str is None or entry is None:
                    return
                slot_results[slot] = (result_str, entry)

            if hitl_tcs:
                paused_tc = hitl_tcs[0]
                _tid, _result_str, entry, pause_request, abort_reason = await _run_one_tool(
                    paused_tc
                )
                if pause_request is not None:
                    return _build_pending_result(paused_tc.name, pause_request, entry)
                if abort_reason:
                    return _build_error_result(abort_reason, entry)

            transport.append_turn(history, turn)

            if len(sub_agent_tcs) >= 2:
                gathered = await asyncio.gather(*[_run_one_tool(tc) for tc in sub_agent_tcs])
                pause_info: tuple[Any, HumanReviewPause, dict[str, Any] | None] | None = None
                abort_reason_for_parallel: str | None = None
                for slot, tc, (_tid, result_str, entry, pause_request, abort_reason) in zip(
                    sub_slots, sub_agent_tcs, gathered
                ):
                    if pause_request is not None:
                        if pause_info is None:
                            pause_info = (tc, pause_request, entry)
                        continue
                    if abort_reason:
                        # Keep completed siblings in slot order. Store every finished
                        # aborting entry here so commit order matches model tool order;
                        # `_build_error_result` must not re-append the first abort last.
                        if abort_reason_for_parallel is None:
                            abort_reason_for_parallel = abort_reason
                        _store_completed_tool_slot(slot, result_str, entry)
                        continue
                    _store_completed_tool_slot(slot, result_str, entry)
                if pause_info is not None:
                    _commit_completed_tool_slots()
                    paused_tc, pause_request, entry = pause_info
                    return _build_pending_result(paused_tc.name, pause_request, entry)
                if abort_reason_for_parallel is not None:
                    _commit_completed_tool_slots()
                    return _build_error_result(abort_reason_for_parallel)
            else:
                for slot, tc in zip(sub_slots, sub_agent_tcs):
                    _tid, result_str, entry, pause_request, abort_reason = await _run_one_tool(tc)
                    if pause_request is not None:
                        _commit_completed_tool_slots()
                        return _build_pending_result(tc.name, pause_request, entry)
                    if abort_reason:
                        _commit_completed_tool_slots()
                        return _build_error_result(abort_reason, entry)
                    _store_completed_tool_slot(slot, result_str, entry)

            for slot, tc in zip(other_slots, other_tcs):
                _tid, result_str, entry, pause_request, abort_reason = await _run_one_tool(tc)
                if pause_request is not None:
                    _commit_completed_tool_slots()
                    return _build_pending_result(tc.name, pause_request, entry)
                if abort_reason:
                    _commit_completed_tool_slots()
                    return _build_error_result(abort_reason, entry)
                _store_completed_tool_slot(slot, result_str, entry)

            _commit_completed_tool_slots()

        # Final text-only completion when the loop exits immediately after tool results were
        # appended (max_tool_iterations exhausted before a non-tool assistant turn). This uses
        # successful tool outputs already in `history` instead of returning a generic limit error.
        if (
            openai_tools
            and last_assistant_turn_had_tool_calls
            and max_tool_iterations > 0
            and transport.last_item_is_tool_result(history)
        ):
            grace_opts = RequestOpts(
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                response_format=response_format,
                tool_choice="none",
            )

            base_url = client.base_url if hasattr(client, "base_url") else self.base_url
            _log_request(
                provider, str(base_url), transport.trace_request(_sent_history(), openai_tools)
            )
            grace_start = time.time()
            grace_turn = None
            try:
                grace_turn = await asyncio.to_thread(
                    transport.create,
                    client=client,
                    model=model,
                    history=_sent_history(),
                    tools=openai_tools,
                    opts=grace_opts,
                )
            except Exception:
                try:
                    grace_turn = await asyncio.to_thread(
                        transport.create,
                        client=client,
                        model=model,
                        history=_sent_history(),
                        tools=None,
                        opts=RequestOpts(
                            temperature=temperature,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens,
                            response_format=response_format,
                        ),
                    )
                except Exception:
                    grace_turn = None

            if grace_turn is not None:
                grace_elapsed_ms = (time.time() - grace_start) * 1000
                total_elapsed_ms += grace_elapsed_ms
                total_prompt_tokens += grace_turn.prompt_tokens
                total_completion_tokens += grace_turn.completion_tokens
                _log_response(
                    provider,
                    grace_turn.raw_items[0] if grace_turn.raw_items else None,
                    grace_elapsed_ms,
                )
                if not grace_turn.tool_calls:
                    grace_text = (transport.final_text(grace_turn) or "").strip()
                    if grace_text:
                        result = {
                            "text": grace_text,
                            "model": model,
                            "usage": {
                                "prompt_tokens": total_prompt_tokens,
                                "completion_tokens": total_completion_tokens,
                                "total_tokens": total_prompt_tokens + total_completion_tokens,
                            },
                            "elapsed_ms": round(total_elapsed_ms, 2),
                        }
                        if tool_calls_collected:
                            result["tool_calls"] = tool_calls_collected
                        _attach_tool_metrics(result)
                        self._record_trace(
                            request_type=transport.name,
                            provider=provider,
                            model=model,
                            request=_trace_request(),
                            response=result,
                            error=None,
                            elapsed_ms=round(total_elapsed_ms, 2),
                            prompt_tokens=total_prompt_tokens,
                            completion_tokens=total_completion_tokens,
                            total_tokens=total_prompt_tokens + total_completion_tokens,
                            binding=binding,
                        )
                        return self._attach_routing_summary(result)

        text = "Tool iteration limit reached."
        result = {
            "text": text,
            "model": model,
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
            "elapsed_ms": round(total_elapsed_ms, 2),
        }
        if tool_calls_collected:
            result["tool_calls"] = tool_calls_collected
        return _attach_tool_metrics(result)

    async def execute_image_generation(
        self,
        model: str,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "auto",
        n: int = 1,
    ) -> dict[str, Any]:
        if self.router is not None:
            raise ValueError(
                "Model Router credentials cannot generate or edit images. Pick a "
                "specific credential and image model."
            )
        trace_request = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
        }
        provider = _get_provider_label(self.credential_type)
        start_time = time.time()
        try:
            if self.credential_type == CredentialType.google:
                result = await self._execute_google_image_generation(model, prompt, size, n)
            else:
                result = await self._execute_openai_image_generation(
                    model, prompt, size, quality, n
                )
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_trace(
                request_type="images.generate",
                provider=provider,
                model=model,
                request=trace_request,
                response=None,
                error=str(exc),
                elapsed_ms=round(elapsed_ms, 2),
            )
            raise
        error = result.get("error") if isinstance(result, dict) else None
        self._record_trace(
            request_type="images.generate",
            provider=provider,
            model=model,
            request=trace_request,
            response=_sanitize_image_response(result),
            error=error,
            elapsed_ms=result.get("elapsed_ms"),
        )
        return result

    async def execute_image_edit(
        self,
        model: str,
        prompt: str,
        image_input: str,
        size: str = "1024x1024",
        quality: str = "auto",
        n: int = 1,
    ) -> dict[str, Any]:
        if self.router is not None:
            raise ValueError(
                "Model Router credentials cannot generate or edit images. Pick a "
                "specific credential and image model."
            )
        trace_request = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
            "image_input": _redact_image_input(image_input),
        }
        if self.credential_type == CredentialType.google:
            provider = _get_provider_label(self.credential_type)
            start_time = time.time()
            try:
                result = await self._execute_google_image_edit(model, prompt, image_input)
            except Exception as exc:
                elapsed_ms = (time.time() - start_time) * 1000
                self._record_trace(
                    request_type="images.edit",
                    provider=provider,
                    model=model,
                    request=trace_request,
                    response=None,
                    error=str(exc),
                    elapsed_ms=round(elapsed_ms, 2),
                )
                raise
            error = result.get("error") if isinstance(result, dict) else None
            self._record_trace(
                request_type="images.edit",
                provider=provider,
                model=model,
                request=trace_request,
                response=_sanitize_image_response(result),
                error=error,
                elapsed_ms=result.get("elapsed_ms"),
            )
            return result

        client, provider = self._get_client()
        image_bytes, mime_type = _load_image_bytes(image_input)
        image_file = io.BytesIO(image_bytes)
        extension = mime_type.split("/")[-1] or "png"
        image_file.name = f"input.{extension}"

        is_gpt_image = model in ("gpt-image-1", "chatgpt-image-latest")

        kwargs: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "image": image_file,
            "n": n,
        }

        if is_gpt_image:
            kwargs["output_format"] = "png"
        else:
            kwargs["response_format"] = "b64_json"

        if size:
            kwargs["size"] = size
        if quality and quality != "auto":
            kwargs["quality"] = quality

        base_url = client.base_url if hasattr(client, "base_url") else self.base_url
        _log_request(f"{provider} Image Edit", str(base_url), kwargs)

        edit_method = getattr(client.images, "edit", None) or getattr(client.images, "edits", None)
        if edit_method is None:
            result = {
                "image": "",
                "text": prompt,
                "model": model,
                "error": "Image edit is not available for this SDK",
            }
            self._record_trace(
                request_type="images.edit",
                provider=provider,
                model=model,
                request=trace_request,
                response=_sanitize_image_response(result),
                error=result["error"],
                elapsed_ms=None,
            )
            return result

        start_time = time.time()
        try:
            response = await asyncio.to_thread(edit_method, **kwargs)
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_trace(
                request_type="images.edit",
                provider=provider,
                model=model,
                request=trace_request,
                response=None,
                error=str(exc),
                elapsed_ms=round(elapsed_ms, 2),
            )
            raise
        elapsed_ms = (time.time() - start_time) * 1000

        _log_response(f"{provider} Image Edit", response, elapsed_ms)

        image_data = response.data[0]
        b64_image = image_data.b64_json if hasattr(image_data, "b64_json") else ""
        revised_prompt = (
            image_data.revised_prompt if hasattr(image_data, "revised_prompt") else None
        )

        result = {
            "image": f"data:image/png;base64,{b64_image}" if b64_image else "",
            "text": prompt,
            "model": model,
            "revised_prompt": revised_prompt,
            "elapsed_ms": round(elapsed_ms, 2),
        }
        self._record_trace(
            request_type="images.edit",
            provider=provider,
            model=model,
            request=trace_request,
            response=_sanitize_image_response(result),
            error=None,
            elapsed_ms=round(elapsed_ms, 2),
        )
        return result

    async def _execute_google_image_generation(
        self,
        model: str,
        prompt: str,
        size: str = "1024x1024",
        n: int = 1,
    ) -> dict[str, Any]:
        url = f"{GOOGLE_IMAGEN_BASE_URL}/{model}:generateContent"

        request_body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }

        _log_request("Google Gemini Image", url, request_body)

        start_time = time.time()
        async with httpx.AsyncClient(headers={"User-Agent": HEYM_USER_AGENT}) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=request_body,
                timeout=120.0,
            )
        elapsed_ms = (time.time() - start_time) * 1000

        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Google Gemini Image error: {response.status_code} - {error_text}")
            return {
                "image": "",
                "text": prompt,
                "model": model,
                "error": f"Google API error: {response.status_code} - {error_text}",
                "elapsed_ms": round(elapsed_ms, 2),
            }

        result = response.json()
        _log_response("Google Gemini Image", result, elapsed_ms)

        candidates = result.get("candidates", [])
        if not candidates:
            return {
                "image": "",
                "text": prompt,
                "model": model,
                "error": "No response generated",
                "elapsed_ms": round(elapsed_ms, 2),
            }

        parts = candidates[0].get("content", {}).get("parts", [])
        b64_image = ""
        response_text = ""

        for part in parts:
            # Support both camelCase (REST) and snake_case (some SDKs)
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data:
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type", "image/png")
                b64_image = inline_data.get("data", "")
                if b64_image:
                    b64_image = f"data:{mime_type};base64,{b64_image}"
            elif "text" in part:
                response_text = part["text"]

        if not b64_image:
            logger.warning(
                "Google Gemini Image: no image in response. parts=%s",
                [list(p.keys()) for p in parts],
            )
            return {
                "image": "",
                "text": response_text or prompt,
                "model": model,
                "error": "No image in response",
                "elapsed_ms": round(elapsed_ms, 2),
            }

        return {
            "image": b64_image,
            "text": response_text or prompt,
            "model": model,
            "elapsed_ms": round(elapsed_ms, 2),
        }

    async def _execute_google_image_edit(
        self,
        model: str,
        prompt: str,
        image_input: str,
    ) -> dict[str, Any]:
        url = f"{GOOGLE_IMAGEN_BASE_URL}/{model}:generateContent"

        image_bytes, mime_type = _load_image_bytes(image_input)
        b64_image_data = base64.b64encode(image_bytes).decode("utf-8")

        request_body = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_image_data,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }

        _log_request(
            "Google Gemini Image Edit", url, {**request_body, "contents": "[image+prompt]"}
        )

        start_time = time.time()
        async with httpx.AsyncClient(headers={"User-Agent": HEYM_USER_AGENT}) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=request_body,
                timeout=120.0,
            )
        elapsed_ms = (time.time() - start_time) * 1000

        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Google Gemini Image Edit error: {response.status_code} - {error_text}")
            return {
                "image": "",
                "text": prompt,
                "model": model,
                "error": f"Google API error: {response.status_code} - {error_text}",
                "elapsed_ms": round(elapsed_ms, 2),
            }

        result = response.json()
        _log_response("Google Gemini Image Edit", result, elapsed_ms)

        candidates = result.get("candidates", [])
        if not candidates:
            return {
                "image": "",
                "text": prompt,
                "model": model,
                "error": "No response generated",
                "elapsed_ms": round(elapsed_ms, 2),
            }

        parts = candidates[0].get("content", {}).get("parts", [])
        b64_result_image = ""
        response_text = ""

        for part in parts:
            if "inlineData" in part:
                inline_data = part["inlineData"]
                result_mime_type = inline_data.get("mimeType", "image/png")
                b64_result_image = inline_data.get("data", "")
                if b64_result_image:
                    b64_result_image = f"data:{result_mime_type};base64,{b64_result_image}"
            elif "text" in part:
                response_text = part["text"]

        if not b64_result_image:
            return {
                "image": "",
                "text": response_text or prompt,
                "model": model,
                "error": "No edited image in response",
                "elapsed_ms": round(elapsed_ms, 2),
            }

        return {
            "image": b64_result_image,
            "text": response_text or prompt,
            "model": model,
            "elapsed_ms": round(elapsed_ms, 2),
        }

    async def _execute_openai_image_generation(
        self,
        model: str,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "auto",
        n: int = 1,
    ) -> dict[str, Any]:
        client, provider = self._get_client()

        is_gpt_image = model in ("gpt-image-1", "chatgpt-image-latest")

        kwargs: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": n,
        }

        if is_gpt_image:
            kwargs["output_format"] = "png"
        else:
            kwargs["response_format"] = "b64_json"

        if size:
            kwargs["size"] = size
        if quality and quality != "auto":
            kwargs["quality"] = quality

        base_url = client.base_url if hasattr(client, "base_url") else self.base_url
        _log_request(f"{provider} Image", str(base_url), kwargs)

        start_time = time.time()
        response = await asyncio.to_thread(client.images.generate, **kwargs)
        elapsed_ms = (time.time() - start_time) * 1000

        _log_response(f"{provider} Image", response, elapsed_ms)

        image_data = response.data[0]
        b64_image = image_data.b64_json if hasattr(image_data, "b64_json") else ""
        revised_prompt = (
            image_data.revised_prompt if hasattr(image_data, "revised_prompt") else None
        )

        return {
            "image": f"data:image/png;base64,{b64_image}" if b64_image else "",
            "text": prompt,
            "model": model,
            "revised_prompt": revised_prompt,
            "elapsed_ms": round(elapsed_ms, 2),
        }


async def execute_llm(
    credential_type: str,
    api_key: str,
    base_url: str | None,
    model: str,
    system_instruction: str | None,
    user_message: str,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    image_input: str | None = None,
    trace_context: LLMTraceContext | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    skills_included: list[str] | None = None,
    content_only: bool = False,
    extra_body: dict[str, Any] | None = None,
    request_timeout: float = LLM_REQUEST_TIMEOUT,
    use_responses_api: bool = False,
    router: ModelRouter | None = None,
) -> dict[str, Any]:
    cred_type = CredentialType(credential_type)
    service = LLMService(
        cred_type,
        api_key,
        base_url,
        trace_context=trace_context,
        request_timeout=request_timeout,
        use_responses_api=use_responses_api,
        router=router,
    )
    return await service.execute(
        model=model,
        system_instruction=system_instruction,
        user_message=user_message,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        response_format=response_format,
        image_input=image_input,
        conversation_history=conversation_history,
        skills_included=skills_included,
        content_only=content_only,
        extra_body=extra_body,
    )


async def execute_llm_batch(
    credential_type: str,
    api_key: str,
    base_url: str | None,
    model: str,
    system_instruction: str | None,
    user_messages: list[str],
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    trace_context: LLMTraceContext | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    skills_included: list[str] | None = None,
    on_status_update: Callable[[dict[str, Any]], None] | None = None,
    should_abort: Callable[[], str | None] | None = None,
    request_timeout: float = LLM_REQUEST_TIMEOUT,
    extra_body: dict[str, Any] | None = None,
    router: ModelRouter | None = None,
) -> dict[str, Any]:
    cred_type = CredentialType(credential_type)
    service = LLMService(
        cred_type,
        api_key,
        base_url,
        trace_context=trace_context,
        request_timeout=request_timeout,
        router=router,
    )
    return await service.execute_batch(
        model=model,
        system_instruction=system_instruction,
        user_messages=user_messages,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        response_format=response_format,
        conversation_history=conversation_history,
        skills_included=skills_included,
        on_status_update=on_status_update,
        should_abort=should_abort,
        extra_body=extra_body,
    )


def _persist_skill_files(
    generated_files: list[dict[str, Any]],
    *,
    owner_id: str | None,
    workflow_id: str | None,
    node_id: str | None,
    node_label: str | None,
) -> list[dict[str, Any]]:
    """Persist skill-generated files to storage and return download link metadata.

    Runs synchronously (called from a thread via asyncio.to_thread).
    """
    if not owner_id or not generated_files:
        return []

    import secrets as _secrets
    import uuid as _uuid

    from app.config import settings
    from app.db.models import FileAccessToken, GeneratedFile
    from app.db.session import SessionLocal
    from app.services.file_storage import _storage_root, build_download_url

    file_links: list[dict[str, Any]] = []
    base_url = settings.frontend_url.rstrip("/") if settings.frontend_url else ""

    with SessionLocal() as db:
        try:
            for f in generated_files:
                filename = f["filename"]
                file_bytes = f["file_bytes"]
                mime_type = f.get("mime_type", "application/octet-stream")

                max_bytes = settings.file_max_size_mb * 1024 * 1024
                if len(file_bytes) > max_bytes:
                    logger.warning("Skill file %s exceeds size limit, skipping", filename)
                    continue

                file_uuid = _uuid.uuid4()
                owner_uuid = _uuid.UUID(owner_id)
                relative_path = f"{owner_uuid}/{file_uuid}/{filename}"
                absolute_path = _storage_root() / relative_path
                absolute_path.parent.mkdir(parents=True, exist_ok=True)
                absolute_path.write_bytes(file_bytes)

                row = GeneratedFile(
                    id=file_uuid,
                    owner_id=owner_uuid,
                    workflow_id=_uuid.UUID(workflow_id) if workflow_id else None,
                    filename=filename,
                    storage_path=relative_path,
                    mime_type=mime_type,
                    size_bytes=len(file_bytes),
                    source_node_id=node_id,
                    source_node_label=node_label,
                    metadata_json={},
                )
                db.add(row)
                db.flush()

                token_str = _secrets.token_urlsafe(32)
                token_row = FileAccessToken(
                    file_id=file_uuid,
                    token=token_str,
                    created_by_id=owner_uuid,
                )
                db.add(token_row)
                db.flush()

                download_url = build_download_url(base_url, token_str)
                file_links.append(
                    {
                        "id": str(file_uuid),
                        "filename": filename,
                        "mime_type": mime_type,
                        "size_bytes": len(file_bytes),
                        "download_url": download_url,
                    }
                )

            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist skill-generated files")
            return []

    return file_links


def _normalize_skill_file_references(
    output: object,
    file_links: list[dict[str, Any]],
) -> object:
    """Replace temp skill paths with persisted download URLs inside JSON output."""
    if not isinstance(output, (dict, list)) or not file_links:
        return output

    filename_to_link = {
        str(item["filename"]): str(item["download_url"])
        for item in file_links
        if isinstance(item.get("filename"), str) and isinstance(item.get("download_url"), str)
    }
    if not filename_to_link:
        return output

    path_like_keys = {"download_url", "file", "file_path", "link", "output_path", "path", "url"}

    def _rewrite_string(value: str, key: str | None) -> str:
        if value in filename_to_link.values():
            return value

        candidate_name: str | None = None
        if value.startswith("/api/files/dl/"):
            candidate_name = value.rsplit("/", 1)[-1]
        elif value.startswith("/"):
            candidate_name = value.rsplit("/", 1)[-1]
        elif key in path_like_keys:
            candidate_name = value.rsplit("/", 1)[-1]

        if candidate_name and candidate_name in filename_to_link:
            return filename_to_link[candidate_name]
        return value

    def _walk(value: object, key: str | None = None) -> object:
        if isinstance(value, dict):
            return {k: _walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(item, key) for item in value]
        if isinstance(value, str):
            return _rewrite_string(value, key)
        return value

    return _walk(copy.deepcopy(output))


def _load_skill_drive_files(actor_user_id: str | None) -> list[dict[str, Any]]:
    """Return Drive files the actor can read for an enabled skill run."""

    if not actor_user_id:
        return []

    import uuid as _uuid

    from app.db.models import FileTeamShare, GeneratedFile, TeamMember
    from app.db.session import SessionLocal
    from app.services.file_storage import get_file_path

    try:
        actor_uuid = _uuid.UUID(str(actor_user_id))
    except (TypeError, ValueError):
        return []

    with SessionLocal() as db:
        owned_rows = (
            db.query(GeneratedFile)
            .filter(GeneratedFile.owner_id == actor_uuid)
            .order_by(GeneratedFile.created_at.desc())
            .all()
        )
        shared_rows = (
            db.query(GeneratedFile)
            .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
            .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
            .filter(TeamMember.user_id == actor_uuid)
            .order_by(GeneratedFile.created_at.desc())
            .all()
        )

        rows_by_id: dict[Any, Any] = {}
        for row in [*owned_rows, *shared_rows]:
            rows_by_id.setdefault(row.id, row)

        rows = sorted(
            rows_by_id.values(),
            key=lambda row: row.created_at,
            reverse=True,
        )
        drive_files: list[dict[str, Any]] = []
        for row in rows:
            source_path = get_file_path(row)
            if not source_path.exists():
                continue
            drive_files.append(
                {
                    "id": str(row.id),
                    "filename": row.filename,
                    "mime_type": row.mime_type,
                    "size_bytes": row.size_bytes,
                    "workflow_id": str(row.workflow_id) if row.workflow_id else None,
                    "source_node_label": row.source_node_label,
                    "created_at": row.created_at,
                    "source_path": str(source_path),
                }
            )
        return drive_files


def _unified_tool_executor(
    tool_def: dict[str, Any],
    name: str,
    args: dict[str, Any],
    timeout_seconds: float,
) -> object:
    """Dispatch to Python, MCP, or skill tool executor based on tool_def."""
    if tool_def.get("_source") == "mcp":
        from app.services.mcp_tool_executor import execute_mcp_tool

        connection = tool_def.get("_connection") or {}
        # The MCP connection's own "Timeout (s)" governs tool execution, mirroring
        # the tool-listing path (workflow_executor._list_mcp_tools). Fall back to
        # the agent-level toolTimeoutSeconds only when the connection has none.
        mcp_timeout = float(connection.get("timeoutSeconds") or timeout_seconds)
        return execute_mcp_tool(connection, name, args, mcp_timeout)
    if tool_def.get("_source") == "skill":
        from app.services.skill_python_executor import SkillExecutionResult, execute_skill_python

        skill_files = tool_def.get("_skill_files") or []
        skill_timeout = tool_def.get("_skill_timeout")
        effective_timeout = float(skill_timeout) if skill_timeout is not None else timeout_seconds
        drive_files = (
            _load_skill_drive_files(str(tool_def.get("_actor_user_id") or ""))
            if tool_def.get("_drive_files_enabled")
            else None
        )
        result = execute_skill_python(skill_files, args, effective_timeout, drive_files=drive_files)

        if isinstance(result, SkillExecutionResult):
            if result.hitl_request:
                return HumanReviewPause(
                    review_markdown=result.hitl_request.get("draft_text", ""),
                    summary=result.hitl_request.get("summary"),
                    tool_name=name,
                    tool_source="skill",
                    tool_arguments=args,
                )

            if result.generated_files:
                output = (
                    result.output if isinstance(result.output, dict) else {"output": result.output}
                )
                owner_id = tool_def.get("_owner_id")
                workflow_id = tool_def.get("_workflow_id")
                node_id = tool_def.get("_node_id")
                node_label = tool_def.get("_node_label")
                file_links = _persist_skill_files(
                    result.generated_files,
                    owner_id=owner_id,
                    workflow_id=workflow_id,
                    node_id=node_id,
                    node_label=node_label,
                )
                if file_links:
                    output = _normalize_skill_file_references(output, file_links)
                    output["_generated_files"] = file_links
                return output

            return result.output

        return result
    from app.services.python_tool_executor import execute_tool

    code = tool_def.get("code", "")
    return execute_tool(code, name, args, timeout_seconds)


async def execute_llm_with_tools(
    credential_type: str,
    api_key: str,
    base_url: str | None,
    model: str,
    system_instruction: str | None,
    user_message: str,
    tools: list[dict[str, Any]],
    tool_timeout_seconds: float = 30.0,
    max_tool_iterations: int = 30,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    image_input: str | None = None,
    trace_context: LLMTraceContext | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    skills_included: list[str] | None = None,
    on_tool_call: Callable[[dict[str, Any]], None] | None = None,
    tool_executor: Callable[[dict[str, Any], str, dict, float], object] | None = None,
    initial_messages: list[dict[str, Any]] | None = None,
    initial_tool_calls: list[dict[str, Any]] | None = None,
    initial_elapsed_ms: float = 0.0,
    initial_prompt_tokens: int = 0,
    initial_completion_tokens: int = 0,
    should_abort: Callable[[], str | None] | None = None,
    request_timeout: float = LLM_REQUEST_TIMEOUT,
    extra_body: dict[str, Any] | None = None,
    use_responses_api: bool = False,
    router: ModelRouter | None = None,
) -> dict[str, Any]:
    cred_type = CredentialType(credential_type)
    service = LLMService(
        cred_type,
        api_key,
        base_url,
        trace_context=trace_context,
        request_timeout=request_timeout,
        use_responses_api=use_responses_api,
        router=router,
    )
    return await service.execute_with_tools(
        model=model,
        system_instruction=system_instruction,
        user_message=user_message,
        tools=tools,
        tool_executor=tool_executor if tool_executor is not None else _unified_tool_executor,
        tool_timeout_seconds=tool_timeout_seconds,
        max_tool_iterations=max_tool_iterations,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        response_format=response_format,
        image_input=image_input,
        conversation_history=conversation_history,
        skills_included=skills_included,
        on_tool_call=on_tool_call,
        initial_messages=initial_messages,
        initial_tool_calls=initial_tool_calls,
        initial_elapsed_ms=initial_elapsed_ms,
        initial_prompt_tokens=initial_prompt_tokens,
        initial_completion_tokens=initial_completion_tokens,
        should_abort=should_abort,
        extra_body=extra_body,
    )


async def execute_image_generation(
    credential_type: str,
    api_key: str,
    base_url: str | None,
    model: str,
    prompt: str,
    size: str = "1024x1024",
    quality: str = "auto",
    n: int = 1,
    trace_context: LLMTraceContext | None = None,
) -> dict[str, Any]:
    cred_type = CredentialType(credential_type)
    service = LLMService(cred_type, api_key, base_url, trace_context=trace_context)
    return await service.execute_image_generation(
        model=model,
        prompt=prompt,
        size=size,
        quality=quality,
        n=n,
    )


async def execute_image_edit(
    credential_type: str,
    api_key: str,
    base_url: str | None,
    model: str,
    prompt: str,
    image_input: str,
    size: str = "1024x1024",
    quality: str = "auto",
    n: int = 1,
    trace_context: LLMTraceContext | None = None,
) -> dict[str, Any]:
    cred_type = CredentialType(credential_type)
    service = LLMService(cred_type, api_key, base_url, trace_context=trace_context)
    return await service.execute_image_edit(
        model=model,
        prompt=prompt,
        image_input=image_input,
        size=size,
        quality=quality,
        n=n,
    )
