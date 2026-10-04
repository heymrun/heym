import ast
import asyncio
import base64
import binascii
import copy
import gc
import hashlib
import ipaddress
import json
import logging
import os
import queue
import random
import re
import shlex
import signal
import socket
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from threading import Event, Lock, Thread, local
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from simpleeval import DEFAULT_FUNCTIONS, EvalWithCompoundTypes, FeatureNotAvailable, SimpleEval

from app.api.data_tables import (
    _coerce_row_data,  # noqa: F401 - public patch alias for node handlers
)
from app.http_identity import HEYM_USER_AGENT
from app.observability import tracing
from app.services import expression_syntax
from app.services.agent_tool_policy import is_blocked_as_tool
from app.services.cancellation_bridge import CancellationBridge
from app.services.chart_payload import (
    build_chart_payload,  # noqa: F401 - public patch alias for node handlers
)
from app.services.execution_cancellation import (
    buffer_live_execution_events,
    record_execution_node_completed,
    record_execution_node_started,
)
from app.services.execution_cancellation import (
    clear_execution as _clear_sub_execution,
)
from app.services.execution_cancellation import (
    register_execution as _register_sub_execution,
)
from app.services.expression_evaluator import (
    _is_single_dollar_expression,
    should_resolve_embedded_dollar_refs_arithmetically,
)
from app.services.expression_evaluator import (
    is_top_level_ternary_expression as _is_top_level_ternary_expression,
)
from app.services.highlight.highlight_builder import build_highlight_payload
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import ModelRouterConfigError, build_router_for_credential
from app.services.node_execution import NodeExecutionContext, execute_node_handler
from app.services.node_execution.extra_body import resolve_extra_body
from app.services.node_execution.llm_batch_input import normalize_batch_user_messages
from app.services.timezone_utils import get_configured_timezone, normalize_datetime_to_timezone
from app.services.websocket_utils import (
    send_websocket_message,  # noqa: F401 - public patch alias for node handlers
)

logger = logging.getLogger(__name__)

_DRIVE_DOWNLOAD_MAX_REDIRECTS = 5
_DRIVE_DOWNLOAD_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


# Dict methods that commonly collide with JSON keys when using dot access (e.g. `$data.items`).
_DOTDICT_BUILTIN_METHOD_NAMES: frozenset[str] = frozenset(
    {"items", "keys", "values", "entries", "map", "filter"}
)
_ITEM_DOT_PATH_RE = re.compile(r"^item(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+$")
_ITEM_REF_IN_TEMPLATE_RE = re.compile(r"item\.[a-zA-Z_][a-zA-Z0-9_]*\b(?!\()")


def _is_private_python_attr(name: str) -> bool:
    """True for Python private/dunder names. Dictionary keys like ``_id`` are not this check."""
    return bool(name) and name.startswith("_")


def _guarded_lookup(value: object, part: str) -> object | None:
    """Resolve one dotted path segment without private Python attribute access.

    Dictionary keys (including ``_id``) are read with ``.get``. Attribute lookup
    on non-dict objects rejects any name that starts with ``_``.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(part)
    if _is_private_python_attr(part):
        return None
    if hasattr(value, part):
        return getattr(value, part)
    return None


def _resolve_guarded_dot_path(value: object, parts: list[str]) -> object | None:
    """Walk ``parts`` with :func:`_guarded_lookup`. Shared by all DotList item-expression paths."""
    current = value
    for part in parts:
        if not part:
            return None
        current = _guarded_lookup(current, part)
        if current is None:
            return None
    return current


def _sandbox_rejected_private_access(exc: BaseException, expr: str) -> bool:
    """True when simpleeval refused a dunder attribute or disallowed call.

    Single-underscore dict keys such as ``_id`` still go through the guarded fallback.
    """
    if "__" not in expr:
        return False
    return isinstance(exc, FeatureNotAvailable) or type(exc).__name__ == "FeatureNotAvailable"


def is_expression_callable(candidate: object) -> bool:
    """True only for methods the Dot wrappers define themselves.

    Inherited builtin methods (``list.pop``, ``dict.popitem``) are not expression
    API, so callers must never invoke or hand back one.
    """
    owner = getattr(candidate, "__self__", None)
    name = getattr(candidate, "__name__", None)
    if owner is None or not name or _is_private_python_attr(name):
        return False
    # Resolved at call time so the wrapper classes below are already defined.
    wrapper_types = (DotDict, DotList, DotStr, DotInt, DotFloat, DotBool, DotDateTime)
    return any(klass in wrapper_types and name in vars(klass) for klass in type(owner).__mro__)


_DOLLAR_NAME_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")
_ITEM_EXPRESSION_STRING_START_RE = re.compile(r"\.(?:distinctBy|distinct_by|filter|map|sort)\(\s*$")
_POSTGRES_UNSAFE_JSON_STRING_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")
_EXECUTION_CONTEXT_INPUT_KEY = "__heym_execution_context"


def _reconcile_resumed_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    decision: str,
    finished_at: int,
) -> list[dict[str, Any]]:
    """Replace persisted HITL pending records with the completed review decision."""
    reconciled = copy.deepcopy(tool_calls)
    for tool_call in reconciled:
        if tool_call.get("status") != "pending":
            continue
        tool_call["status"] = "success"
        tool_call["result"] = {
            "decision": decision,
            "reviewed": True,
        }
        tool_call["finished_at"] = finished_at
    return reconciled


def _slugify_tool_name(label: str) -> str:
    slug = _SLUG_RE.sub("_", label.strip()).strip("_").lower()
    return slug[:64] or "node_tool"


def _coerce_boolean(value: object, *, default: bool = False) -> bool:
    """Coerce configured or agent-provided boolean values without treating ``"false"`` as true."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _build_data_table_filter_clauses(filter_dict: dict, columns: list) -> list:
    """Build SQLAlchemy filter clauses for a DataTable Mongo-style filter.

    A plain value means equality. An object value applies comparison operators:
    ``$eq``, ``$ne``, ``$gt``, ``$gte``, ``$lt``, ``$lte``, ``$contains`` (ILIKE
    substring) and ``$in`` (list membership).

    User-defined schema columns live in the JSONB ``data`` blob and are matched as
    text (numeric comparisons cast to ``NUMERIC`` when the column type is ``number``).
    Row metadata (``id``, ``created_at``, ``updated_at``, ``created_by``,
    ``updated_by``, ``table_id``) are real table columns, so they are matched against
    the model attribute directly; ``$contains`` casts them to text. A schema column
    that happens to share a metadata name still resolves against the JSONB blob.
    Unknown operators are ignored.
    """
    from sqlalchemy import Numeric, String, cast

    from app.db.models import DataTableRow

    if not isinstance(filter_dict, dict) or not filter_dict:
        return []

    schema_cols = {c["name"]: c for c in (columns or [])}
    meta_columns = {
        "id": DataTableRow.id,
        "table_id": DataTableRow.table_id,
        "created_at": DataTableRow.created_at,
        "updated_at": DataTableRow.updated_at,
        "created_by": DataTableRow.created_by,
        "updated_by": DataTableRow.updated_by,
    }
    clauses: list = []

    for col_name, condition in filter_dict.items():
        is_meta = col_name not in schema_cols and col_name in meta_columns
        if is_meta:
            # Real typed column (timestamp/uuid): compare natively, no text coercion.
            field = meta_columns[col_name]
            is_json = False
            is_number = False
        else:
            # User data lives in JSONB; ``->>`` yields text.
            field = DataTableRow.data.op("->>")(col_name)
            is_json = True
            is_number = schema_cols.get(col_name, {}).get("type") == "number"

        def _coerce(value: object) -> object:
            return str(value) if is_json else value

        if isinstance(condition, dict):
            for op, raw_value in condition.items():
                if op == "$eq":
                    clauses.append(field == _coerce(raw_value))
                elif op == "$ne":
                    clauses.append(field != _coerce(raw_value))
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    if is_number:
                        left, right = cast(field, Numeric), raw_value
                    else:
                        left, right = field, _coerce(raw_value)
                    if op == "$gt":
                        clauses.append(left > right)
                    elif op == "$gte":
                        clauses.append(left >= right)
                    elif op == "$lt":
                        clauses.append(left < right)
                    else:
                        clauses.append(left <= right)
                elif op == "$contains":
                    target = field if is_json else cast(field, String)
                    clauses.append(target.ilike(f"%{raw_value}%"))
                elif op == "$in" and isinstance(raw_value, list):
                    clauses.append(field.in_([_coerce(v) for v in raw_value]))
                # Unknown operators are ignored.
        else:
            clauses.append(field == _coerce(condition))

    return clauses


def _build_agent_execution_log_output(agent_result: dict) -> dict:
    """Rich agent fields for execution logs (e.g. sub-agent node_complete)."""
    out: dict = {"text": agent_result.get("text", "")}
    if agent_result.get("error"):
        out["error"] = agent_result["error"]
    if agent_result.get("tool_calls"):
        out["tool_calls"] = copy.deepcopy(agent_result["tool_calls"])
    for key in (
        "timing_breakdown",
        "model",
        "skills_used",
        "mcp_list_ms",
        "fallbackUsed",
        "usage",
    ):
        if key in agent_result:
            out[key] = copy.deepcopy(agent_result[key])
    return out


class ExpressionFunctionError(ValueError):
    """Raised by expression functions to stop workflow execution."""


def _base64_encode_text(value: object) -> str:
    if not isinstance(value, str):
        raise ExpressionFunctionError("$base64Encode(text) requires a string")
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _base64_decode_text(value: object) -> str:
    if not isinstance(value, str):
        raise ExpressionFunctionError("$base64Decode(text) requires a string")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
        return decoded.decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise ExpressionFunctionError(
            "$base64Decode(text) requires valid Base64-encoded UTF-8 text"
        ) from exc


def _parse_json_text(value: object) -> object:
    """Parse a JSON string into wrapped Dot* values for expression chaining."""
    if not isinstance(value, str):
        raise ExpressionFunctionError("$toJson(text) requires a string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ExpressionFunctionError("$toJson(text) requires valid JSON") from exc
    return _wrap_value(parsed)


class NodeTraceableExecutionError(ValueError):
    """Raised when a node error has a trace entry that should stay linked."""

    def __init__(
        self,
        message: str,
        trace_id: str,
        model_routing: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.trace_id = trace_id
        self.model_routing = model_routing


class WorkflowCancelledError(Exception):
    """Raised when a running workflow execution is cancelled."""


class WorkflowTimeoutError(WorkflowCancelledError):
    """Raised when a workflow exceeds its configured timeout.

    Subclasses ``WorkflowCancelledError`` so existing cancellation handling
    (cooperative unwind at node boundaries, retry suppression) applies, while
    callers that care can distinguish a timeout from a user cancel.
    """


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            # Preserve the active Agent/workflow span when we must hop to a worker
            # thread to host a fresh asyncio.run() loop.
            otel_ctx = tracing.capture_context()

            def _run_with_otel() -> object:
                return tracing.run_with_context(otel_ctx, lambda: asyncio.run(coro))

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_run_with_otel)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@dataclass(frozen=True)
class _DriveDownloadTarget:
    original_url: str
    request_url: str
    host_header: str
    sni_hostname: str | None


def _format_host_for_url(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    return address.compressed


def _format_host_header(hostname: str, scheme: str, port: int | None) -> str:
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if port is not None and port != (443 if scheme == "https" else 80):
        return f"{hostname}:{port}"
    return hostname


def _resolve_drive_download_addresses(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    host = hostname.strip("[]")
    if "%" in host:
        host = host.split("%", 1)[0]

    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Drive Node: failed to resolve download URL host: {hostname}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for family, _, _, _, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        address_key = address.compressed
        if address_key in seen:
            continue
        seen.add(address_key)
        addresses.append(address)

    if not addresses:
        raise ValueError(f"Drive Node: failed to resolve download URL host: {hostname}")
    return addresses


def _resolve_drive_download_target(raw_url: str) -> _DriveDownloadTarget:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Drive Node: source URL must use http or https")
    if not parsed.hostname:
        raise ValueError("Drive Node: source URL must include a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Drive Node: source URL includes an invalid port") from exc

    addresses = _resolve_drive_download_addresses(parsed.hostname)
    global_addresses = [address for address in addresses if address.is_global]
    if not global_addresses:
        raise ValueError("Drive Node: source URL must resolve to a globally routable address")

    address = global_addresses[0]
    request_netloc = _format_host_for_url(address)
    if port is not None:
        request_netloc = f"{request_netloc}:{port}"
    request_url = parsed._replace(netloc=request_netloc).geturl()

    hostname = parsed.hostname
    sni_hostname = hostname.encode("idna").decode("ascii") if parsed.scheme == "https" else None
    return _DriveDownloadTarget(
        original_url=raw_url,
        request_url=request_url,
        host_header=_format_host_header(hostname, parsed.scheme, port),
        sni_hostname=sni_hostname,
    )


def _fetch_drive_download_url(source_url: str) -> httpx.Response:
    current_url = source_url
    for _ in range(_DRIVE_DOWNLOAD_MAX_REDIRECTS + 1):
        target = _resolve_drive_download_target(current_url)
        headers = {"Host": target.host_header}
        extensions = {"sni_hostname": target.sni_hostname} if target.sni_hostname else None

        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = client.get(target.request_url, headers=headers, extensions=extensions)
            if response.status_code not in _DRIVE_DOWNLOAD_REDIRECT_STATUS_CODES:
                response.raise_for_status()
                return response

            location = response.headers.get("location")
            if not location:
                response.raise_for_status()
                return response
            current_url = urljoin(target.original_url, location)

    raise ValueError("Drive Node: too many redirects while downloading URL")


def _ensure_additional_properties(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema

    schema = schema.copy()

    if schema.get("type") == "object":
        if "additionalProperties" not in schema:
            schema["additionalProperties"] = False

        if "properties" in schema and isinstance(schema["properties"], dict):
            for key, prop_schema in schema["properties"].items():
                schema["properties"][key] = _ensure_additional_properties(prop_schema)

    if "items" in schema:
        schema["items"] = _ensure_additional_properties(schema["items"])

    return schema


def _normalize_js_logical_ops_for_eval(processed: str) -> str:
    """Replace JavaScript ``&&`` / ``||`` with Python ``and`` / ``or`` for eval-based conditions.

    Respects string literals so embedded operators inside quoted values are unchanged.
    """
    out: list[str] = []
    i = 0
    n = len(processed)
    in_string = False
    quote_ch = ""
    while i < n:
        ch = processed[i]
        if in_string:
            out.append(ch)
            if ch == quote_ch:
                escapes = 0
                j = i - 1
                while j >= 0 and processed[j] == "\\":
                    escapes += 1
                    j -= 1
                if escapes % 2 == 0:
                    in_string = False
            i += 1
            continue
        if ch in "\"'":
            in_string = True
            quote_ch = ch
            out.append(ch)
            i += 1
            continue
        if ch == "&" and i + 1 < n and processed[i + 1] == "&":
            out.append(" and ")
            i += 2
            continue
        if ch == "|" and i + 1 < n and processed[i + 1] == "|":
            out.append(" or ")
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_SHARED_EXECUTOR = ThreadPoolExecutor(max_workers=8)

_BACKGROUND_WORKFLOW_EXECUTOR = ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="heym-bg-workflow"
)
_BACKGROUND_NODE_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="heym-bg-node")

_HTTP_CLIENT_LOCK = Lock()
_EXPRESSION_EVAL_CONTEXT_LOCAL = local()


def _submit_allow_downstream_work(work: Callable[[], None]) -> Future:
    """Run allowDownstream finalization off the shared node pool.

    The waiter must not occupy a ``_SHARED_EXECUTOR`` worker: it blocks on other
    pool futures, and scheduling it on the same pool can deadlock when workers
    are saturated by long-running / blocked side branches.
    """
    future: Future = Future()

    def _runner() -> None:
        if future.set_running_or_notify_cancel():
            try:
                work()
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(None)

    Thread(target=_runner, daemon=True, name="heym-allow-downstream").start()
    return future


@dataclass(frozen=True)
class _ExpressionEvalContext:
    names: dict[str, Any]
    functions: dict[str, Any]
    item_scope_depth: int


def _get_expression_eval_context_stack() -> list[_ExpressionEvalContext]:
    stack = getattr(_EXPRESSION_EVAL_CONTEXT_LOCAL, "stack", None)
    if stack is None:
        stack = []
        _EXPRESSION_EVAL_CONTEXT_LOCAL.stack = stack
    return stack


def _current_expression_eval_context() -> _ExpressionEvalContext | None:
    stack = getattr(_EXPRESSION_EVAL_CONTEXT_LOCAL, "stack", None)
    if not stack:
        return None
    return stack[-1]


def _is_inside_item_expression_string(text: str, index: int) -> bool:
    """Return whether ``index`` is inside a quoted map/filter-style expression argument."""
    quote: str | None = None
    quote_start = -1
    cursor = 0
    while cursor < index:
        char = text[cursor]
        if quote is not None:
            if char == "\\" and cursor + 1 < index:
                cursor += 2
                continue
            if char == quote:
                quote = None
                quote_start = -1
            cursor += 1
            continue
        if char in ('"', "'"):
            quote = char
            quote_start = cursor
        cursor += 1

    if quote is None or quote_start < 0:
        return False
    return bool(_ITEM_EXPRESSION_STRING_START_RE.search(text[:quote_start]))


def _rewrite_item_expression_dollar_refs(expr: str, item_scope_name: str) -> str:
    """Make DSL ``$`` references valid names inside a local item expression."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return item_scope_name if name == "item" else name

    return _DOLLAR_NAME_RE.sub(replace, expr)


_HTTP_CLIENT: httpx.Client | None = None
_GC_TRACKER_LOCAL = local()
_GC_TRACKER_CALLBACK_LOCK = Lock()
_GC_TRACKER_CALLBACK_REGISTERED = False

HTTP_POOL_SIZE = 100
HTTP_KEEPALIVE_CONNECTIONS = 20
HTTP_TIMEOUT = 300.0


@lru_cache(maxsize=2048)
def _parse_expression_tree(expr: str) -> ast.AST:
    """Cache parsed ASTs for repeated workflow expressions."""
    return SimpleEval.parse(expression_syntax.alias_reserved_context_names(expr))


def _is_valid_expression_syntax(expr: str) -> bool:
    try:
        _parse_expression_tree(expr)
    except Exception:  # noqa: BLE001 - syntax probing only
        return False
    return True


def _expression_root_node(parsed: ast.AST) -> ast.AST:
    """Return the expression value node for a parsed ``simpleeval`` tree."""
    if isinstance(parsed, ast.Expr):
        return parsed.value
    return parsed


@dataclass
class _NodeGcPauseTracker:
    """Tracks GC pause intervals for the node currently executing on one thread."""

    node_started_ms: float
    pauses: list[tuple[float, float, int | None]] = field(default_factory=list)
    active_starts: list[tuple[float, int | None]] = field(default_factory=list)

    def on_gc_start(self, now_ms: float, generation: int | None) -> None:
        self.active_starts.append((now_ms, generation))

    def on_gc_stop(self, now_ms: float) -> None:
        if not self.active_starts:
            return
        started_ms, generation = self.active_starts.pop()
        duration_ms = max(now_ms - started_ms, 0.0)
        relative_start_ms = max(started_ms - self.node_started_ms, 0.0)
        self.pauses.append((relative_start_ms, duration_ms, generation))

    def total_pause_ms(self) -> float:
        return sum(duration_ms for _start_ms, duration_ms, _generation in self.pauses)


def _get_active_gc_trackers() -> list[_NodeGcPauseTracker]:
    trackers = getattr(_GC_TRACKER_LOCAL, "trackers", None)
    if trackers is None:
        trackers = []
        _GC_TRACKER_LOCAL.trackers = trackers
    return trackers


def _push_gc_tracker(tracker: _NodeGcPauseTracker) -> None:
    _get_active_gc_trackers().append(tracker)


def _pop_gc_tracker(tracker: _NodeGcPauseTracker) -> None:
    trackers = getattr(_GC_TRACKER_LOCAL, "trackers", None)
    if not trackers:
        return
    if trackers[-1] is tracker:
        trackers.pop()
        return
    try:
        trackers.remove(tracker)
    except ValueError:
        return


def _current_gc_tracker() -> _NodeGcPauseTracker | None:
    trackers = getattr(_GC_TRACKER_LOCAL, "trackers", None)
    if not trackers:
        return None
    return trackers[-1]


def _workflow_gc_callback(phase: str, info: dict[str, object]) -> None:
    """Attach synchronous GC pauses to the node executing on the current worker thread."""
    tracker = _current_gc_tracker()
    if tracker is None:
        return

    try:
        generation_value = info.get("generation")
        generation = generation_value if isinstance(generation_value, int) else None
        now_ms = time.perf_counter() * 1000
        if phase == "start":
            tracker.on_gc_start(now_ms, generation)
        elif phase == "stop":
            tracker.on_gc_stop(now_ms)
    except Exception:
        return


def _ensure_gc_tracking_callback_registered() -> None:
    """Register the process-wide GC callback once."""
    global _GC_TRACKER_CALLBACK_REGISTERED

    if _GC_TRACKER_CALLBACK_REGISTERED:
        return

    with _GC_TRACKER_CALLBACK_LOCK:
        if _GC_TRACKER_CALLBACK_REGISTERED:
            return
        if _workflow_gc_callback not in gc.callbacks:
            gc.callbacks.append(_workflow_gc_callback)
        _GC_TRACKER_CALLBACK_REGISTERED = True


def get_http_client() -> httpx.Client:
    global _HTTP_CLIENT
    with _HTTP_CLIENT_LOCK:
        if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
            limits = httpx.Limits(
                max_connections=HTTP_POOL_SIZE,
                max_keepalive_connections=HTTP_KEEPALIVE_CONNECTIONS,
            )
            _HTTP_CLIENT = httpx.Client(
                limits=limits,
                timeout=HTTP_TIMEOUT,
                follow_redirects=False,
                headers={"User-Agent": HEYM_USER_AGENT},
            )
        return _HTTP_CLIENT


def close_http_client() -> None:
    global _HTTP_CLIENT
    with _HTTP_CLIENT_LOCK:
        if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
            _HTTP_CLIENT.close()
            _HTTP_CLIENT = None


class DotDict(dict):
    def __getattribute__(self, key: str):
        if key in _DOTDICT_BUILTIN_METHOD_NAMES and dict.__contains__(self, key):
            return _wrap_value(dict.__getitem__(self, key))
        return super().__getattribute__(key)

    def __getattr__(self, key: str):
        try:
            if key == "length":
                return len(self)
            value = self[key]
            if isinstance(value, dict) and not isinstance(value, DotDict):
                return DotDict(value)
            if isinstance(value, list) and not isinstance(value, DotList):
                return DotList(value)
            if isinstance(value, bool) and not isinstance(value, DotBool):
                return DotBool(value)
            if isinstance(value, int) and not isinstance(value, DotInt):
                return DotInt(value)
            if isinstance(value, float) and not isinstance(value, DotFloat):
                return DotFloat(value)
            if isinstance(value, str) and not isinstance(value, DotStr):
                return DotStr(value)
            return value
        except KeyError:
            return None

    def __setattr__(self, key: str, value):
        self[key] = value

    def toString(self) -> "DotStr":  # noqa: N802
        return DotStr(json.dumps(dict(self), ensure_ascii=False))

    def to_string(self) -> "DotStr":
        return self.toString()

    def get(self, key: str, default=None):
        value = super().get(key, default)
        if isinstance(value, dict) and not isinstance(value, DotDict):
            return DotDict(value)
        if isinstance(value, list) and not isinstance(value, DotList):
            return DotList(value)
        if isinstance(value, bool) and not isinstance(value, DotBool):
            return DotBool(value)
        if isinstance(value, int) and not isinstance(value, DotInt):
            return DotInt(value)
        if isinstance(value, float) and not isinstance(value, DotFloat):
            return DotFloat(value)
        if isinstance(value, str) and not isinstance(value, DotStr):
            return DotStr(value)
        return value

    def entries(self) -> "DotList":
        """Return a list of {key, value} entries for iteration in ``.map()`` / ``.filter()``."""
        return DotList(
            [DotDict({"key": _wrap_value(k), "value": _wrap_value(v)}) for k, v in dict.items(self)]
        )

    def keys(self) -> "DotList":  # type: ignore[override]
        return DotList([_wrap_value(k) for k in dict.keys(self)])

    def values(self) -> "DotList":  # type: ignore[override]
        return DotList([_wrap_value(v) for v in dict.values(self)])

    def map(self, expr: str) -> "DotList":
        """Iterate a dict as ``{key, value}`` entries and return a list of mapped values.

        Mirrors :meth:`DotList.map` so ``$obj.map("item.value")`` and
        ``$obj.map("concat('item.key', '=', 'item.value')")`` work on objects.
        """
        return self.entries().map(expr)

    def filter(self, expr: str) -> "DotList":
        """Iterate a dict as ``{key, value}`` entries and return the matching entries as a list."""
        return self.entries().filter(expr)


class DotList(list):
    def __getattr__(self, key: str):
        if key == "length":
            return len(self)
        raise AttributeError(f"'DotList' object has no attribute '{key}'")

    def reverse(self) -> "DotList":
        return DotList(self[::-1])

    def first(self) -> object:
        return self[0] if len(self) > 0 else None

    def last(self) -> object:
        return self[-1] if len(self) > 0 else None

    def random(self) -> object:
        return random.choice(self) if len(self) > 0 else None

    def join(self, separator: str = ",") -> "DotStr":
        return DotStr(separator.join(str(item) for item in self))

    def distinct(self) -> "DotList":
        seen = []
        for item in self:
            if item not in seen:
                seen.append(item)
        return DotList(seen)

    def distinctBy(self, key_expr: str = "item") -> "DotList":  # noqa: N802
        """Remove duplicates based on a key expression (e.g., 'item.id')."""
        seen_keys: list = []
        result: list = []
        for item in self:
            key = self._evaluate_item_expr(key_expr, item)
            if key not in seen_keys:
                seen_keys.append(key)
                result.append(item)
        return DotList(result)

    def distinct_by(self, key_expr: str = "item") -> "DotList":
        return self.distinctBy(key_expr)

    def _evaluate_item_expr(self, expr: str, item: object) -> object:
        """Evaluate an expression like 'item.id' or 'item.name' against an item."""
        if expr == "item":
            return item
        if expr.startswith("item."):
            return _resolve_guarded_dot_path(item, expr[5:].split("."))
        return item

    def flat(self, depth: int = 1) -> "DotList":
        """Flatten nested arrays up to specified depth."""
        result: list = []

        def flatten(arr: list, d: int) -> None:
            for item in arr:
                if isinstance(item, (list, DotList)) and d > 0:
                    flatten(list(item), d - 1)
                else:
                    result.append(item)

        flatten(list(self), depth)
        return DotList(result)

    def notNull(self) -> "DotList":  # noqa: N802
        return DotList([item for item in self if item is not None])

    def not_null(self) -> "DotList":
        return self.notNull()

    def add(self, item: object) -> "DotList":
        new_list = DotList(self)
        new_list.append(item)
        return new_list

    def contains(self, item: object) -> bool:
        return item in self

    def toString(self) -> "DotStr":  # noqa: N802
        return DotStr(json.dumps(list(self), ensure_ascii=False))

    def to_string(self) -> "DotStr":
        return self.toString()

    def _evaluate_item_expression(self, expr: str, item: object) -> object:
        if expr == "item":
            return item

        operators = [
            " > ",
            " < ",
            " >= ",
            " <= ",
            " == ",
            " != ",
            " + ",
            " - ",
            " * ",
            " / ",
            " and ",
            " or ",
        ]
        has_operator = any(op in expr for op in operators)

        if not has_operator and _ITEM_DOT_PATH_RE.fullmatch(expr):
            return _resolve_guarded_dot_path(item, expr[5:].split("."))

        try:
            wrapped_item = _wrap_value(item)
            inherited_context = _current_expression_eval_context()
            inherited_names = dict(inherited_context.names) if inherited_context else {}
            inherited_functions = (
                dict(inherited_context.functions) if inherited_context else dict(DEFAULT_FUNCTIONS)
            )
            item_scope_depth = inherited_context.item_scope_depth if inherited_context else 0
            item_scope_name = f"heymItemScope{item_scope_depth}"
            expr = _rewrite_item_expression_dollar_refs(expr, item_scope_name)

            def resolve_item_ref(arg):
                if not isinstance(arg, str):
                    return arg
                arg_str = arg.strip()
                if _ITEM_DOT_PATH_RE.fullmatch(arg_str):
                    return _resolve_guarded_dot_path(wrapped_item, arg_str[5:].split("."))
                if arg_str.startswith("item["):
                    import re as _re

                    match = _re.match(r'item\[(["\'])(.+?)\1\]', arg_str)
                    if match:
                        key = match.group(2)
                        if isinstance(wrapped_item, dict):
                            return wrapped_item.get(key)
                return arg

            def concat_func(*args):
                resolved = [resolve_item_ref(a) for a in args]
                result_str = "".join(str(a) if a is not None else "" for a in resolved)
                return DotStr(result_str)

            def get_func(obj, key, default=None):
                if isinstance(obj, dict):
                    value = obj.get(key, default)
                elif isinstance(key, str) and _is_private_python_attr(key):
                    return default
                elif not hasattr(obj, key):
                    return default
                else:
                    value = getattr(obj, key, default)
                # Same rule for dict values and attributes: no unlisted callables escape.
                if callable(value) and not is_expression_callable(value):
                    return default
                return value

            inherited_names.update(
                {
                    item_scope_name: wrapped_item,
                    "item": wrapped_item,
                    "true": True,
                    "false": False,
                    "null": None,
                }
            )
            inherited_functions.update(
                {
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "abs": abs,
                    "min": min,
                    "max": max,
                    "round": round,
                    "concat": concat_func,
                    "get": get_func,
                }
            )
            evaluator = HeymExpressionEval(
                names=inherited_names,
                functions=inherited_functions,
            )
            evaluator.item_scope_depth = item_scope_depth + 1
            return evaluator.eval(expr)
        except Exception:
            return None

    def filter(self, expr: str) -> "DotList":
        result = []
        for item in self:
            evaluated = self._evaluate_item_expression(expr, item)
            if evaluated:
                result.append(item)
        return DotList(result)

    def map(self, expr: str) -> "DotList":
        if (
            isinstance(expr, str)
            and "item." in expr
            and not expr.strip().startswith("concat(")
            and not _is_valid_expression_syntax(
                _rewrite_item_expression_dollar_refs(expr, "heymItemScope")
            )
        ):
            # Keep supporting template-like strings such as
            # "- item.source (Page: item.page): item.snippet".
            matches = list(_ITEM_REF_IN_TEMPLATE_RE.finditer(expr))
            if matches:
                # Try to reconstruct concat call
                # Split the string by item references and reconstruct as concat arguments
                parts = []
                last_end = 0
                for match in matches:
                    # Add text before this match
                    if match.start() > last_end:
                        text_before = expr[last_end : match.start()]
                        if text_before:
                            # Escape quotes in the string
                            text_before_escaped = text_before.replace('"', '\\"')
                            parts.append(f'"{text_before_escaped}"')
                    # Add the item reference (without quotes - it's an expression)
                    item_ref = match.group(0)
                    parts.append(item_ref)
                    last_end = match.end()
                # Add remaining text
                if last_end < len(expr):
                    text_after = expr[last_end:]
                    if text_after:
                        # Escape quotes in the string
                        text_after_escaped = text_after.replace('"', '\\"')
                        parts.append(f'"{text_after_escaped}"')
                # Reconstruct concat call
                if len(parts) > 1:
                    reconstructed = "concat(" + ", ".join(parts) + ")"
                    expr = reconstructed

        result = []
        for item in self:
            evaluated = self._evaluate_item_expression(expr, item)
            result.append(evaluated)
        return DotList(result)

    def sort(self, expr: str = "item", order: str = "asc") -> "DotList":
        def get_sort_key(item: object) -> object:
            key = self._evaluate_item_expression(expr, item)
            if key is None:
                return (1, "")
            return (0, key)

        reverse = order.lower() == "desc"
        try:
            sorted_list = sorted(self, key=get_sort_key, reverse=reverse)
            return DotList(sorted_list)
        except TypeError:
            return DotList(self)

    def take(self, count: int) -> "DotList":
        if count >= 0:
            return DotList(self[:count])
        else:
            return DotList(self[count:])


class DotInt(int):
    def toString(self) -> "DotStr":  # noqa: N802
        return DotStr(str(self))

    def to_string(self) -> "DotStr":
        return self.toString()


class DotFloat(float):
    def toString(self) -> "DotStr":  # noqa: N802
        return DotStr(str(self))

    def to_string(self) -> "DotStr":
        return self.toString()


class DotBool:
    def __init__(self, value: bool) -> None:
        self._value = value

    def __bool__(self) -> bool:
        return self._value

    def __repr__(self) -> str:
        return str(self._value)

    def __str__(self) -> str:
        return str(self._value).lower()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DotBool):
            return self._value == other._value
        return self._value == other

    def __lt__(self, other: object) -> bool:
        if isinstance(other, DotBool):
            return self._value < other._value
        return self._value < other  # type: ignore[operator]

    def __le__(self, other: object) -> bool:
        if isinstance(other, DotBool):
            return self._value <= other._value
        return self._value <= other  # type: ignore[operator]

    def __gt__(self, other: object) -> bool:
        if isinstance(other, DotBool):
            return self._value > other._value
        return self._value > other  # type: ignore[operator]

    def __ge__(self, other: object) -> bool:
        if isinstance(other, DotBool):
            return self._value >= other._value
        return self._value >= other  # type: ignore[operator]

    def toString(self) -> "DotStr":  # noqa: N802
        return DotStr(str(self._value).lower())

    def to_string(self) -> "DotStr":
        return self.toString()


class DotStr(str):
    @property
    def length(self) -> int:
        return len(self)

    def orEmpty(self) -> "DotStr":  # noqa: N802
        return DotStr(self)

    def or_empty(self) -> "DotStr":
        return self.orEmpty()

    def upper(self) -> "DotStr":
        return DotStr(str.upper(self))

    def lower(self) -> "DotStr":
        return DotStr(str.lower(self))

    def strip(self) -> "DotStr":
        return DotStr(str.strip(self))

    def capitalize(self) -> "DotStr":
        return DotStr(str.capitalize(self))

    def title(self) -> "DotStr":
        return DotStr(str.title(self))

    def toUpperCase(self) -> "DotStr":  # noqa: N802
        return self.upper()

    def to_upper_case(self) -> "DotStr":
        return self.upper()

    def toLowerCase(self) -> "DotStr":  # noqa: N802
        return self.lower()

    def to_lower_case(self) -> "DotStr":
        return self.lower()

    def trim(self) -> "DotStr":
        return self.strip()

    def charAt(self, index: int) -> str:  # noqa: N802
        if 0 <= index < len(self):
            return self[index]
        return ""

    def char_at(self, index: int) -> str:
        return self.charAt(index)

    def substring(self, start: int, end: int | None = None) -> "DotStr":
        if end is None:
            return DotStr(self[start:])
        return DotStr(self[start:end])

    def substr(self, start: int, length: int | None = None) -> "DotStr":
        if length is None:
            return DotStr(self[start:])
        return DotStr(self[start : start + length])

    def replace(self, old: str, new: str) -> "DotStr":
        return DotStr(str.replace(self, old, new))

    def replaceAll(self, old: str, new: str) -> "DotStr":  # noqa: N802
        return DotStr(str.replace(self, old, new))

    def replace_all(self, old: str, new: str) -> "DotStr":
        return self.replaceAll(old, new)

    def startswith(self, prefix: str) -> bool:
        return str.startswith(self, prefix)

    def endswith(self, suffix: str) -> bool:
        return str.endswith(self, suffix)

    def contains(self, sub: str) -> bool:
        return sub in self

    def indexOf(self, sub: str) -> int:  # noqa: N802
        return self.find(sub)

    def index_of(self, sub: str) -> int:
        return self.indexOf(sub)

    def reverse(self) -> "DotStr":
        return DotStr(self[::-1])

    def split(self, separator: str = " ") -> "DotList":
        if separator == "":
            return DotList([DotStr(c) for c in self])
        return DotList([DotStr(s) for s in str.split(self, separator)])

    def regexReplace(self, pattern: str, replacement: str) -> "DotStr":  # noqa: N802
        return DotStr(re.sub(pattern, replacement, self))

    def regex_replace(self, pattern: str, replacement: str) -> "DotStr":
        return self.regexReplace(pattern, replacement)

    def hash(self) -> "DotStr":
        return DotStr(hashlib.md5(self.encode("utf-8")).hexdigest())

    def base64Encode(self) -> "DotStr":  # noqa: N802
        return DotStr(_base64_encode_text(self))

    def base64_encode(self) -> "DotStr":
        return self.base64Encode()

    def base64Decode(self) -> "DotStr":  # noqa: N802
        return DotStr(_base64_decode_text(self))

    def base64_decode(self) -> "DotStr":
        return self.base64Decode()

    def urlEncode(self) -> "DotStr":  # noqa: N802
        return DotStr(quote(self, safe=""))

    def url_encode(self) -> "DotStr":
        return self.urlEncode()

    def urlDecode(self) -> "DotStr":  # noqa: N802
        return DotStr(unquote(self))

    def url_decode(self) -> "DotStr":
        return self.urlDecode()

    def toJson(self) -> object:  # noqa: N802
        return _parse_json_text(self)

    def to_json(self) -> object:
        return self.toJson()


class DotDateTime:
    def __init__(self, dt: datetime | None = None) -> None:
        self._dt = dt if dt is not None else datetime.now(timezone.utc)

    @property
    def year(self) -> DotInt:
        return DotInt(self._dt.year)

    @property
    def month(self) -> DotInt:
        return DotInt(self._dt.month)

    @property
    def day(self) -> DotInt:
        return DotInt(self._dt.day)

    @property
    def hour(self) -> DotInt:
        return DotInt(self._dt.hour)

    @property
    def minute(self) -> DotInt:
        return DotInt(self._dt.minute)

    @property
    def second(self) -> DotInt:
        return DotInt(self._dt.second)

    @property
    def dayOfWeek(self) -> DotInt:  # noqa: N802
        return DotInt(self._dt.weekday())

    @property
    def day_of_week(self) -> int:
        return self.dayOfWeek

    def format(self, pattern: str | None = "YYYY-MM-DD HH:mm:ss") -> DotStr:
        if not isinstance(pattern, str) or not pattern:
            pattern = "YYYY-MM-DD HH:mm:ss"

        month_names_full = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        month_names_short = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        day_names_full = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        day_names_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        hour12 = self.hour % 12 or 12
        ampm = "AM" if self.hour < 12 else "PM"

        replacements = [
            ("YYYY", str(self.year)),
            ("YY", str(self.year)[-2:]),
            ("MMMM", month_names_full[self.month - 1]),
            ("MMM", month_names_short[self.month - 1]),
            ("MM", str(self.month).zfill(2)),
            ("dddd", day_names_full[self._dt.weekday()]),
            ("ddd", day_names_short[self._dt.weekday()]),
            ("DD", str(self.day).zfill(2)),
            ("HH", str(self.hour).zfill(2)),
            ("hh", str(hour12).zfill(2)),
            ("mm", str(self.minute).zfill(2)),
            ("ss", str(self.second).zfill(2)),
            ("A", ampm),
            ("a", ampm.lower()),
            ("D", str(self.day)),
            ("H", str(self.hour)),
            ("h", str(hour12)),
            ("M", str(self.month)),
            ("m", str(self.minute)),
            ("s", str(self.second)),
        ]

        result = pattern
        placeholders = {}
        for i, (token, value) in enumerate(replacements):
            placeholder = f"\x00{i}\x00"
            if token in result:
                result = result.replace(token, placeholder)
                placeholders[placeholder] = value

        for placeholder, value in placeholders.items():
            result = result.replace(placeholder, value)

        return DotStr(result)

    def toISO(self) -> DotStr:  # noqa: N802
        return DotStr(self._dt.isoformat())

    def to_iso(self) -> DotStr:
        return self.toISO()

    def toDate(self) -> DotStr:  # noqa: N802
        return self.format("YYYY-MM-DD")

    def to_date(self) -> DotStr:
        return self.toDate()

    def toTime(self) -> DotStr:  # noqa: N802
        return self.format("HH:mm:ss")

    def to_time(self) -> DotStr:
        return self.toTime()

    def toUnix(self) -> DotInt:  # noqa: N802
        return DotInt(int(self._dt.timestamp()))

    def to_unix(self) -> int:
        return self.toUnix()

    def toMillis(self) -> DotInt:  # noqa: N802
        return DotInt(int(self._dt.timestamp() * 1000))

    def to_millis(self) -> int:
        return self.toMillis()

    def addDays(self, n: int) -> "DotDateTime":  # noqa: N802
        return DotDateTime(self._dt + timedelta(days=n))

    def add_days(self, n: int) -> "DotDateTime":
        return self.addDays(n)

    def addHours(self, n: int) -> "DotDateTime":  # noqa: N802
        return DotDateTime(self._dt + timedelta(hours=n))

    def add_hours(self, n: int) -> "DotDateTime":
        return self.addHours(n)

    def addMinutes(self, n: int) -> "DotDateTime":  # noqa: N802
        return DotDateTime(self._dt + timedelta(minutes=n))

    def add_minutes(self, n: int) -> "DotDateTime":
        return self.addMinutes(n)

    def addMonths(self, n: int) -> "DotDateTime":  # noqa: N802
        new_month = self.month + n
        new_year = self.year + (new_month - 1) // 12
        new_month = (new_month - 1) % 12 + 1
        max_day = self._days_in_month(new_year, new_month)
        new_day = min(self.day, max_day)
        return DotDateTime(self._dt.replace(year=new_year, month=new_month, day=new_day))

    def add_months(self, n: int) -> "DotDateTime":
        return self.addMonths(n)

    def addYears(self, n: int) -> "DotDateTime":  # noqa: N802
        new_year = self.year + n
        max_day = self._days_in_month(new_year, self.month)
        new_day = min(self.day, max_day)
        return DotDateTime(self._dt.replace(year=new_year, day=new_day))

    def add_years(self, n: int) -> "DotDateTime":
        return self.addYears(n)

    def startOfDay(self) -> "DotDateTime":  # noqa: N802
        return DotDateTime(self._dt.replace(hour=0, minute=0, second=0, microsecond=0))

    def start_of_day(self) -> "DotDateTime":
        return self.startOfDay()

    def endOfDay(self) -> "DotDateTime":  # noqa: N802
        return DotDateTime(self._dt.replace(hour=23, minute=59, second=59, microsecond=999999))

    def end_of_day(self) -> "DotDateTime":
        return self.endOfDay()

    def startOfMonth(self) -> "DotDateTime":  # noqa: N802
        return DotDateTime(self._dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0))

    def start_of_month(self) -> "DotDateTime":
        return self.startOfMonth()

    def endOfMonth(self) -> "DotDateTime":  # noqa: N802
        last_day = self._days_in_month(self.year, self.month)
        return DotDateTime(
            self._dt.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
        )

    def end_of_month(self) -> "DotDateTime":
        return self.endOfMonth()

    def _days_in_month(self, year: int, month: int) -> int:
        if month == 12:
            next_month_date = datetime(year + 1, 1, 1, tzinfo=self._dt.tzinfo)
        else:
            next_month_date = datetime(year, month + 1, 1, tzinfo=self._dt.tzinfo)
        last_day = next_month_date - timedelta(days=1)
        return last_day.day

    def toString(self) -> DotStr:  # noqa: N802
        return self.toISO()

    def to_string(self) -> DotStr:
        return self.toString()

    def __repr__(self) -> str:
        return f"DotDateTime({self.toISO()})"

    def __str__(self) -> str:
        return str(self.toISO())


class HeymExpressionEval(EvalWithCompoundTypes):
    """simpleeval blocks ``.format`` on all objects; allow it only for ``DotDateTime``."""

    item_scope_depth = 0

    def eval(self, expr: str, previously_parsed: ast.AST | None = None) -> object:
        """Evaluate while exposing names to nested ``map``/``filter`` item expressions."""
        if previously_parsed is None:
            # Route every parse through the shared helper so reserved names stay aliased.
            previously_parsed = _parse_expression_tree(expr)
        context = _ExpressionEvalContext(
            names=dict(self.names) if isinstance(self.names, dict) else {},
            functions=dict(self.functions),
            item_scope_depth=self.item_scope_depth,
        )
        stack = _get_expression_eval_context_stack()
        stack.append(context)
        try:
            return super().eval(expr, previously_parsed=previously_parsed)
        finally:
            stack.pop()

    def _eval_name(self, node: ast.Name):
        source = expression_syntax.RESERVED_CONTEXT_NAMES_BY_ALIAS.get(node.id)
        if source is not None and isinstance(self.names, dict) and source in self.names:
            return self.names[source]
        return super()._eval_name(node)

    def _eval_attribute(self, node: ast.Attribute):
        if node.attr == "orEmpty":
            base = self._eval(node.value)
            if base is None:
                return lambda: DotStr("")
        if node.attr == "format":
            base = self._eval(node.value)
            if isinstance(base, DotDateTime):
                return getattr(base, "format")
        return super()._eval_attribute(node)


def _wrap_value(value: object) -> object:
    if isinstance(value, dict) and not isinstance(value, DotDict):
        wrapped_dict = DotDict()
        for k, v in value.items():
            wrapped_dict[k] = _wrap_value(v)
        return wrapped_dict
    if isinstance(value, list) and not isinstance(value, DotList):
        return DotList([_wrap_value(item) for item in value])
    if isinstance(value, bool) and not isinstance(value, DotBool):
        return DotBool(value)
    if isinstance(value, int) and not isinstance(value, DotInt):
        return DotInt(value)
    if isinstance(value, float) and not isinstance(value, DotFloat):
        return DotFloat(value)
    if isinstance(value, str) and not isinstance(value, DotStr):
        return DotStr(value)
    return value


def _to_json_compatible(value: object) -> object:
    """Convert wrappers and recursively sanitize values for PostgreSQL JSON fields."""
    if isinstance(value, DotDict):
        return {
            _to_json_compatible_key(key): _to_json_compatible(item)
            for key, item in dict.items(value)
        }
    if isinstance(value, dict):
        return {
            _to_json_compatible_key(key): _to_json_compatible(item) for key, item in value.items()
        }
    if isinstance(value, DotList):
        return [_to_json_compatible(item) for item in list(value)]
    if isinstance(value, list):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, DotBool):
        return bool(value)
    if isinstance(value, DotInt):
        return int(value)
    if isinstance(value, DotFloat):
        return float(value)
    if isinstance(value, DotStr):
        return _sanitize_json_string(str(value))
    if isinstance(value, DotDateTime):
        return value.toISO()
    if isinstance(value, str):
        return _sanitize_json_string(value)
    return value


def _to_json_compatible_key(key: object) -> object:
    if isinstance(key, str):
        return _sanitize_json_string(str(key))
    return key


def _sanitize_json_string(value: str) -> str:
    return _POSTGRES_UNSAFE_JSON_STRING_RE.sub("", value)


@dataclass
class NodeResult:
    node_id: str
    node_label: str
    node_type: str
    status: str
    output: dict
    execution_time_ms: float
    error: str | None = None
    metadata: dict = field(default_factory=dict)


def _annotate_node_span(span: object, result: "NodeResult") -> None:
    """Attach status, timing, and (best-effort) LLM token attributes to a node span."""
    try:
        from opentelemetry.trace import Status, StatusCode

        span.set_attribute("heym.node.status", result.status)  # type: ignore[attr-defined]
        span.set_attribute(  # type: ignore[attr-defined]
            "heym.node.duration_ms", float(result.execution_time_ms)
        )
        usage = result.output.get("usage") if isinstance(result.output, dict) else None
        if isinstance(usage, dict):
            for src_key, attr in (
                ("prompt_tokens", "heym.llm.prompt_tokens"),
                ("completion_tokens", "heym.llm.completion_tokens"),
                ("total_tokens", "heym.llm.total_tokens"),
            ):
                value = usage.get(src_key)
                if isinstance(value, (int, float)):
                    span.set_attribute(attr, int(value))  # type: ignore[attr-defined]
        model = result.output.get("model") if isinstance(result.output, dict) else None
        if isinstance(model, str) and model:
            span.set_attribute("heym.llm.model", model)  # type: ignore[attr-defined]
        if result.status == "error":
            span.set_status(Status(StatusCode.ERROR, result.error or "node error"))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - observability must never break execution
        pass


def _attach_node_io(span: object, inputs: object, output: object, limit: int = 4096) -> None:
    """Attach truncated node input/output JSON to a node span (opt-in, privacy-gated)."""
    try:
        for attr, value in (("heym.node.input", inputs), ("heym.node.output", output)):
            try:
                text = json.dumps(value, default=str, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                text = str(value)
            if len(text) > limit:
                text = text[:limit] + "...(truncated)"
            span.set_attribute(attr, text)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - observability must never break execution
        pass


def _extract_pending_metadata(result: "NodeResult") -> dict:
    metadata = result.metadata or {}
    codex_metadata = metadata.get("codex")
    if isinstance(codex_metadata, dict):
        return copy.deepcopy(codex_metadata)
    hitl_metadata = metadata.get("hitl")
    if isinstance(hitl_metadata, dict):
        return copy.deepcopy(hitl_metadata)
    return {}


SUB_WORKFLOW_HITL_UNSUPPORTED = "HITL is not supported inside Execute node sub-workflows."


@dataclass
class SubWorkflowExecution:
    workflow_id: str
    inputs: dict
    outputs: dict
    status: str
    execution_time_ms: float
    node_results: list = field(default_factory=list)
    workflow_name: str = ""
    trigger_source: str = "SUB_WORKFLOW"
    history_written: bool = False
    execution_id: str = ""


@dataclass
class ExecutionResult:
    workflow_id: uuid.UUID
    status: str
    outputs: dict
    execution_time_ms: float
    node_results: list[NodeResult] = field(default_factory=list)
    sub_workflow_executions: list[SubWorkflowExecution] = field(default_factory=list)
    pending_review: dict | None = None
    resume_snapshot: dict | None = None
    analytics_recorded: bool = False
    # (future, done_event, wf_id, wf_name, inputs_snapshot) tuples for executeDoNotWait nodes.
    # Not serialized / not written to DB directly; drained by the API layer.
    _bg_pending: list = field(default_factory=list)
    _allow_downstream_pending: list[Future] = field(default_factory=list)
    _allow_downstream_node_results: list[NodeResult] = field(default_factory=list)
    _started_at: float = 0.0
    # Set by execute_workflow() so rows appended by the join are masked like the early ones.
    _credentials_context: dict[str, str] = field(default_factory=dict, repr=False)
    # Callers persist global variables from these rows, so their output stays as written.
    _global_variable_node_ids: frozenset[str] = field(default_factory=frozenset, repr=False)
    _downstream_global_node_ids: frozenset[str] = field(default_factory=frozenset, repr=False)

    @property
    def allow_downstream_pending(self) -> bool:
        return bool(self._allow_downstream_pending)

    def join_allow_downstream(self) -> None:
        """Wait for output allowDownstream background work to populate final results."""
        pending = list(self._allow_downstream_pending)
        self._allow_downstream_pending.clear()
        cancelled = False
        unhandled_error = False
        downstream_exception: BaseException | None = None
        for fut in pending:
            try:
                fut.result()
            except WorkflowTimeoutError as exc:
                if downstream_exception is None:
                    downstream_exception = exc
            except (WorkflowCancelledError, CancelledError, asyncio.CancelledError) as exc:
                cancelled = True
                if downstream_exception is None:
                    downstream_exception = (
                        exc
                        if isinstance(exc, WorkflowCancelledError)
                        else WorkflowCancelledError("Workflow execution cancelled")
                    )
            except Exception as exc:
                unhandled_error = True
                logger.exception("Unexpected exception in allowDownstream background execution")
                if downstream_exception is None:
                    downstream_exception = exc

        existing_ids = {item.get("node_id") for item in self.node_results if isinstance(item, dict)}
        for result in self._allow_downstream_node_results:
            if result.node_id not in existing_ids:
                row = _serialize_node_result(result)
                if self._credentials_context:
                    _mask_node_result_row(
                        row,
                        self._credentials_context,
                        keep_output=result.node_id in self._global_variable_node_ids,
                    )
                self.node_results.append(row)
                existing_ids.add(result.node_id)
        if self._started_at:
            self.execution_time_ms = (time.time() - self._started_at) * 1000

        has_downstream_node_error = any(
            (
                getattr(r, "status", None) == "error"
                and getattr(r, "metadata", {}).get("retry_stage") != "attempt_failed"
            )
            for r in self._allow_downstream_node_results
        )
        if isinstance(downstream_exception, WorkflowTimeoutError):
            self.status = "error"
        elif cancelled:
            self.status = "cancelled"
        elif unhandled_error or has_downstream_node_error:
            self.status = "error"

        if downstream_exception is not None:
            raise downstream_exception


#: Terminal mappers: sinks whose output replaces the wrapped per-label response shape.
TERMINAL_MAPPER_NODE_TYPES: frozenset[str] = frozenset({"jsonOutputMapper", "htmlOutputMapper"})

#: Every node type that terminates a branch and contributes the workflow's final output.
OUTPUT_TERMINAL_NODE_TYPES: frozenset[str] = frozenset({"output", *TERMINAL_MAPPER_NODE_TYPES})


def unwrap_single_json_output_terminal_outputs(
    wf_executor: "WorkflowExecutor",
    final_outputs: dict[str, Any],
) -> dict[str, Any]:
    """When the only terminal output is a jsonOutputMapper node, expose its object as top-level outputs.

    Default behavior wraps each terminal as {label: node_output}. For a sole jsonOutputMapper, callers
    (webhook simple response, Execute node sub-workflow) receive the mapped JSON object without an extra
    label or `result` wrapper.
    """
    contributing = [
        nid
        for nid in wf_executor.get_output_nodes()
        if nid in wf_executor.node_outputs
        and nid not in wf_executor.skipped_nodes
        and wf_executor.nodes.get(nid, {}).get("type") != "sticky"
    ]
    if len(contributing) != 1:
        return final_outputs
    sole_id = contributing[0]
    if wf_executor.nodes.get(sole_id, {}).get("type") != "jsonOutputMapper":
        return final_outputs
    inner = wf_executor.node_outputs.get(sole_id)
    if isinstance(inner, dict):
        return dict(inner)
    return final_outputs


def _serialize_node_result(result: NodeResult) -> dict:
    row: dict = {
        "node_id": result.node_id,
        "node_label": result.node_label,
        "node_type": result.node_type,
        "status": result.status,
        "output": _to_json_compatible(result.output),
        "execution_time_ms": result.execution_time_ms,
        "error": result.error,
    }
    if result.metadata:
        row["metadata"] = _to_json_compatible(result.metadata)
    return row


def _serialize_node_results(results: list[NodeResult]) -> list[dict]:
    return [_serialize_node_result(result) for result in results]


def _build_node_start_event(
    node_id: str,
    node_label: str,
    *,
    message: str | None = None,
) -> dict[str, object]:
    """Build a node-start event with the timeline's authoritative wall-clock anchor."""
    event: dict[str, object] = {
        "type": "node_start",
        "node_id": node_id,
        "node_label": node_label,
        "started_at_ms": time.time() * 1000,
    }
    if message is not None:
        event["message"] = message
    return event


def _build_node_complete_event(result: NodeResult, output: dict | None = None) -> dict:
    output_payload = result.output if output is None else output
    return {
        "type": "node_complete",
        "node_id": result.node_id,
        "node_label": result.node_label,
        "node_type": result.node_type,
        "status": result.status,
        "output": _to_json_compatible(output_payload),
        "execution_time_ms": result.execution_time_ms,
        "error": result.error,
        "metadata": _to_json_compatible(result.metadata),
    }


def _build_llm_batch_progress_event(
    *,
    node_id: str,
    node_label: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "llm_batch_progress",
        "node_id": node_id,
        "node_label": node_label,
        "entry": entry,
    }


def _node_result_sequence_value(result: NodeResult) -> int | None:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    sequence = metadata.get("sequence")
    if isinstance(sequence, int):
        return sequence
    if isinstance(sequence, float) and sequence.is_integer():
        return int(sequence)
    return None


def _order_node_results(results: list[NodeResult]) -> list[NodeResult]:
    indexed_results = list(enumerate(results))
    indexed_results.sort(
        key=lambda item: (
            _node_result_sequence_value(item[1]) is None,
            _node_result_sequence_value(item[1]) or 0,
            item[0],
        )
    )
    return [result for _, result in indexed_results]


def _max_node_result_sequence(results: list[NodeResult]) -> int:
    max_sequence = 0
    for result in results:
        sequence = _node_result_sequence_value(result)
        if sequence is not None:
            max_sequence = max(max_sequence, sequence)
    return max_sequence


def _restore_node_results(results: list[dict] | None) -> list[NodeResult]:
    restored: list[NodeResult] = []
    for result in results or []:
        if not isinstance(result, dict):
            continue
        meta = result.get("metadata")
        restored.append(
            NodeResult(
                node_id=result.get("node_id", ""),
                node_label=result.get("node_label", ""),
                node_type=result.get("node_type", "unknown"),
                status=result.get("status", "success"),
                output=result.get("output") or {},
                execution_time_ms=float(result.get("execution_time_ms", 0)),
                error=result.get("error"),
                metadata=dict(meta) if isinstance(meta, dict) else {},
            )
        )
    return restored

def _serialize_sub_workflow_executions(
    executions: list[SubWorkflowExecution],
    credentials_context: dict[str, str] | None = None,
) -> list[dict]:
    serialized = [
        {
            "workflow_id": ex.workflow_id,
            "inputs": _to_json_compatible(ex.inputs),
            "outputs": _to_json_compatible(ex.outputs),
            "status": ex.status,
            "execution_time_ms": ex.execution_time_ms,
            "node_results": _to_json_compatible(ex.node_results),
            "workflow_name": ex.workflow_name,
            "trigger_source": ex.trigger_source,
            "history_written": getattr(ex, "history_written", False),
            "execution_id": getattr(ex, "execution_id", "") or "",
        }
        for ex in executions
    ]
    if credentials_context:
        return [_mask_sub_execution_dict(item, credentials_context) for item in serialized]
    return serialized


def _restore_sub_workflow_executions(executions: list[dict] | None) -> list[SubWorkflowExecution]:
    restored: list[SubWorkflowExecution] = []
    for execution in executions or []:
        if not isinstance(execution, dict):
            continue
        restored.append(
            SubWorkflowExecution(
                workflow_id=execution.get("workflow_id", ""),
                inputs=execution.get("inputs") or {},
                outputs=execution.get("outputs") or {},
                status=execution.get("status", "success"),
                execution_time_ms=float(execution.get("execution_time_ms", 0)),
                node_results=execution.get("node_results") or [],
                workflow_name=execution.get("workflow_name", ""),
                trigger_source=execution.get("trigger_source", "SUB_WORKFLOW"),
                history_written=bool(execution.get("history_written", False)),
                execution_id=str(execution.get("execution_id", "") or ""),
            )
        )
    return restored

def _credential_secret_parts(value: str) -> list[str]:
    """Return a credential value plus the bare secret inside a composite value.

    Header credentials resolve to `Name: secret` and bearer ones to `Bearer <token>`;
    a sent request stores only the secret part, so masking the full value misses it.
    """
    if value.startswith("Bearer "):
        return [value, value[len("Bearer ") :]]
    if ": " in value:
        return [value, value.split(": ", 1)[1]]
    return [value]


def mask_sensitive_output(output: dict, credentials_context: dict[str, str]) -> dict:
    safe_output = _to_json_compatible(output)
    if not credentials_context:
        return safe_output

    output_str = json.dumps(safe_output, ensure_ascii=False)

    for value in credentials_context.values():
        for secret in _credential_secret_parts(value or ""):
            if len(secret) > 7:
                output_str = output_str.replace(secret, secret[:7] + "**")

    return json.loads(output_str)


def mask_sensitive_text(text: str, credentials_context: dict[str, str]) -> str:
    """Mask credential values inside free text, such as a node's error message."""
    for value in credentials_context.values():
        for secret in _credential_secret_parts(value or ""):
            if len(secret) > 7:
                text = text.replace(secret, secret[:7] + "**")
    return text


def _collect_global_variable_node_ids(nodes: dict[str, dict]) -> frozenset[str]:
    """Variable nodes whose output callers persist as a global variable."""
    return frozenset(
        node_id
        for node_id, node in nodes.items()
        if node.get("type") == "variable" and (node.get("data") or {}).get("isGlobal")
    )


def _collect_downstream_global_node_ids(
    executor: "WorkflowExecutor",
    output_nodes_with_downstream: set[str],
    active_edges: list[dict],
) -> frozenset[str]:
    """Collect global variable node IDs that are downstream of allowDownstream output nodes."""
    if not output_nodes_with_downstream:
        return frozenset()
    downstream: set[str] = set()
    for out_id in output_nodes_with_downstream:
        for target in executor.get_downstream_nodes(out_id):
            downstream.update(executor.get_branch_node_ids(target, active_edges))
    all_globals = _collect_global_variable_node_ids(executor.nodes)
    return frozenset(downstream & all_globals)


def _mask_node_result_row(
    row: dict, credentials_context: dict[str, str], *, keep_output: bool = False
) -> None:
    """Mask a serialized node result's output and error in place."""
    if "output" in row and not keep_output:
        row["output"] = mask_sensitive_output(row["output"], credentials_context)
    if isinstance(row.get("error"), str):
        row["error"] = mask_sensitive_text(row["error"], credentials_context)


def mask_sub_workflow_result(
    sub_result: "ExecutionResult", credentials_context: dict[str, str]
) -> tuple[dict, list]:
    """Masked copies of a sub-workflow's outputs and node results for its history row.

    Only the SubWorkflowExecution record gets the copies; the parent keeps the raw values.
    Global variable rows keep their output, since callers persist globals from these rows.
    """
    outputs, node_results = sub_result.outputs, sub_result.node_results
    if not credentials_context:
        return outputs, node_results
    keep_ids = getattr(sub_result, "_global_variable_node_ids", frozenset())
    masked_rows = []
    for row in node_results:
        if isinstance(row, dict):
            row = dict(row)
            _mask_node_result_row(
                row, credentials_context, keep_output=row.get("node_id") in keep_ids
            )
        masked_rows.append(row)
    return mask_sensitive_output(outputs, credentials_context), masked_rows


def _mask_sub_execution_dict(row: dict, credentials_context: dict[str, str] | None) -> dict:
    if not credentials_context or not isinstance(row, dict):
        return row
    sc = copy.deepcopy(row)
    if "inputs" in sc:
        sc["inputs"] = mask_sensitive_output(sc["inputs"], credentials_context)
    if "outputs" in sc:
        sc["outputs"] = mask_sensitive_output(sc["outputs"], credentials_context)
    if isinstance(sc.get("node_results"), list):
        for nr in sc["node_results"]:
            if isinstance(nr, dict):
                _mask_node_result_row(nr, credentials_context)
    return sc


def mask_credentials_context(credentials_context: dict[str, str] | None) -> dict[str, str]:
    """Return a preview-safe credentials context with secret values masked."""
    if not credentials_context:
        return {}

    masked_context: dict[str, str] = {}
    for name, value in credentials_context.items():
        if not value:
            masked_context[name] = value
        elif len(value) > 7:
            masked_context[name] = value[:7] + "**"
        else:
            masked_context[name] = "**"
    return masked_context

def execute_workflow(
    workflow_id: uuid.UUID,
    nodes: list[dict],
    edges: list[dict],
    inputs: dict,
    workflow_cache: dict[str, dict] | None = None,
    test_run: bool = False,
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    cancel_event: Event | None = None,
    public_base_url: str = "",
    return_on_chart_output: bool = False,
    timeout_seconds: float | None = None,
    workflow_name: str = "",
    workflow_description: str = "",
    execution_id: str = "",
    llm_session_id: str | None = None,
) -> ExecutionResult:
    executor = WorkflowExecutor(
        nodes,
        edges,
        workflow_cache,
        test_mode=test_run,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        workflow_id=workflow_id,
        trace_user_id=trace_user_id,
        actor_user_id=actor_user_id,
        conversation_history=conversation_history,
        cancel_event=cancel_event,
        public_base_url=public_base_url,
        return_on_chart_output=return_on_chart_output,
        timeout_seconds=timeout_seconds,
        workflow_name=workflow_name,
        workflow_description=workflow_description,
        execution_id=execution_id,
        llm_session_id=llm_session_id,
    )
    try:
        result = executor.execute(workflow_id, inputs)
    except WorkflowTimeoutError as exc:
        # A timeout unwinds the run; surface it as a failed result so every
        # caller (API, triggers) records it like any other error.
        return ExecutionResult(
            workflow_id=workflow_id,
            status="error",
            outputs={"error": str(exc)},
            execution_time_ms=0.0,
            node_results=[],
        )

    if credentials_context:
        result.outputs = mask_sensitive_output(result.outputs, credentials_context)
        downstream_globals = getattr(result, "_downstream_global_node_ids", frozenset())
        for node_result in result.node_results:
            if isinstance(node_result, dict):
                keep_output = bool(node_result.get("node_id") in downstream_globals)
                _mask_node_result_row(node_result, credentials_context, keep_output=keep_output)
        result._credentials_context = credentials_context

    return result


def _snapshot_actor_user_id(
    snapshot: dict, explicit_actor_user_id: uuid.UUID | None = None
) -> uuid.UUID | None:
    if explicit_actor_user_id is not None:
        return explicit_actor_user_id
    for key in ("actor_user_id", "credentials_owner_id"):
        value = snapshot.get(key)
        if value:
            return uuid.UUID(str(value))
    return None


def _build_hitl_resume_timeline_results(
    pending: NodeResult,
    *,
    resume_now_ms: float,
) -> tuple[NodeResult, NodeResult]:
    """Preserve pre-HITL compute and materialize the wait gap for the execution timeline.

    Resume used to drop the pending row, which left a wall-clock hole between the last
    pre-pause span and the post-resume work. Keep the paused compute as ``pre_review`` and
    emit an explicit ``hitl_wait`` span covering pause → resume.
    """
    pre_meta = dict(pending.metadata or {})
    pre_meta["hitl_phase"] = "pre_review"
    pending_output = pending.output if isinstance(pending.output, dict) else {}
    # Keep a compact historical payload so DebugPanel does not treat this row as an
    # actionable pending HITL review (that UI keys off decision === null + reviewUrl).
    pre_output = {
        "hitlPhase": "pre_review",
        "summary": str(pending_output.get("summary") or "").strip(),
        "draftText": str(
            pending_output.get("draftText") or pending_output.get("text") or ""
        ).strip(),
    }
    if pending_output.get("question"):
        pre_output["question"] = str(pending_output.get("question") or "").strip()
    pre_result = NodeResult(
        node_id=pending.node_id,
        node_label=pending.node_label,
        node_type=pending.node_type,
        status="success",
        output=pre_output,
        execution_time_ms=float(pending.execution_time_ms or 0.0),
        error=pending.error,
        metadata=pre_meta,
    )

    wait_start_raw = pre_meta.get("ended_at_ms")
    wait_start = (
        float(wait_start_raw)
        if isinstance(wait_start_raw, (int, float)) and float(wait_start_raw) > 0
        else float(resume_now_ms)
    )
    wait_end = max(float(resume_now_ms), wait_start)
    wait_ms = max(wait_end - wait_start, 0.0)
    wait_sequence = (_node_result_sequence_value(pending) or 0) + 1
    wait_result = NodeResult(
        node_id=pending.node_id,
        node_label=pending.node_label,
        node_type=pending.node_type,
        status="success",
        output={"hitlWait": True, "durationMs": wait_ms},
        execution_time_ms=wait_ms,
        metadata={
            "hitl_wait": True,
            "started_at_ms": wait_start,
            "ended_at_ms": wait_end,
            "sequence": wait_sequence,
        },
    )
    return pre_result, wait_result


def resume_workflow_execution(
    *,
    snapshot: dict,
    resolved_output: dict,
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> ExecutionResult:
    workflow_id_value = snapshot.get("workflow_id")
    if not workflow_id_value:
        raise ValueError("Missing workflow_id in HITL resume snapshot")

    workflow_id = uuid.UUID(str(workflow_id_value))
    wf_executor = WorkflowExecutor(
        nodes=snapshot.get("nodes") or [],
        edges=snapshot.get("edges") or [],
        workflow_cache=snapshot.get("workflow_cache") or {},
        test_mode=bool(snapshot.get("test_mode", False)),
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        workflow_id=workflow_id,
        trace_user_id=trace_user_id,
        actor_user_id=_snapshot_actor_user_id(snapshot, actor_user_id),
        conversation_history=snapshot.get("conversation_history"),
        llm_session_id=snapshot.get("llm_session_id"),
        sub_workflow_invocation_depth=int(snapshot.get("sub_workflow_invocation_depth", 0)),
        invoked_by_agent=bool(snapshot.get("invoked_by_agent", False)),
    )
    wf_executor.node_outputs = copy.deepcopy(snapshot.get("node_outputs") or {})
    wf_executor.node_execution_contexts = copy.deepcopy(
        snapshot.get("node_execution_contexts") or {}
    )
    wf_executor.label_to_output = copy.deepcopy(snapshot.get("label_to_output") or {})
    wf_executor._rebuild_wrapped_label_output_cache()
    wf_executor.skipped_nodes = set(snapshot.get("skipped_nodes") or [])
    wf_executor.inactive_nodes = set(snapshot.get("inactive_nodes") or [])
    wf_executor.loop_states = copy.deepcopy(snapshot.get("loop_states") or {})
    wf_executor.vars = copy.deepcopy(snapshot.get("vars") or {})
    wf_executor._mark_vars_context_dirty()
    wf_executor.sub_workflow_executions = _restore_sub_workflow_executions(
        snapshot.get("sub_workflow_executions")
    )

    node_results = _restore_node_results(snapshot.get("node_results"))
    wf_executor._node_result_sequence = _max_node_result_sequence(node_results)
    pending_count = {
        str(node_id): int(count) for node_id, count in (snapshot.get("pending_count") or {}).items()
    }
    completed_nodes: set[str] = set(snapshot.get("completed_nodes") or [])
    paused_node_id = str(snapshot.get("paused_node_id") or "")
    if not paused_node_id:
        raise ValueError("Missing paused_node_id in HITL resume snapshot")
    paused_node_label = str(
        snapshot.get("paused_node_label") or wf_executor.get_node_label(paused_node_id)
    )
    hitl_resume_mode = str(snapshot.get("hitl_resume_mode") or "inject_output")
    hitl_agent_state = copy.deepcopy(snapshot.get("hitl_agent_state") or {})
    hitl_approved_tool_call = copy.deepcopy(snapshot.get("hitl_approved_tool_call") or {})

    paused_result_ms = 0.0
    pending_paused_result: NodeResult | None = None
    filtered_results: list[NodeResult] = []
    for result in node_results:
        if result.node_id == paused_node_id and result.status == "pending":
            paused_result_ms = result.execution_time_ms
            pending_paused_result = result
            continue
        filtered_results.append(result)

    resume_now_ms = time.time() * 1000
    if pending_paused_result is not None:
        pre_review_result, hitl_wait_result = _build_hitl_resume_timeline_results(
            pending_paused_result,
            resume_now_ms=resume_now_ms,
        )
        filtered_results.append(pre_review_result)
        filtered_results.append(hitl_wait_result)
        wf_executor._node_result_sequence = _max_node_result_sequence(filtered_results)

    node_results = filtered_results

    if hitl_resume_mode in {"rerun_agent", "continue_agent"}:
        resume_context = copy.deepcopy(resolved_output)
        approved_markdown = (
            str(resolved_output.get("editedText") or "").strip()
            or str(resolved_output.get("reviewText") or "").strip()
            or str(resolved_output.get("originalDraft") or "").strip()
        )
        if hitl_resume_mode == "continue_agent" and hitl_agent_state:
            resume_context["_agent_state"] = copy.deepcopy(hitl_agent_state)
        if hitl_resume_mode == "continue_agent" and hitl_approved_tool_call:
            resume_context["_approved_tool_call"] = copy.deepcopy(hitl_approved_tool_call)
        if (
            hitl_resume_mode == "continue_agent"
            and str(resolved_output.get("decision") or "") == "edited"
        ):
            resume_context["_approved_hitl_checkpoint"] = {
                "decision": "edited",
                "summary": str(resolved_output.get("summary") or "").strip(),
                "approved_markdown": approved_markdown,
                "consumed": False,
            }
        wf_executor.hitl_resume_context[paused_node_id] = resume_context
    else:
        resumed_result = NodeResult(
            node_id=paused_node_id,
            node_label=paused_node_label,
            node_type=wf_executor.nodes.get(paused_node_id, {}).get("type", "agent"),
            status="success",
            output=copy.deepcopy(resolved_output),
            execution_time_ms=0.0,
            metadata={
                "hitl_phase": "resolved",
                "started_at_ms": resume_now_ms,
                "ended_at_ms": resume_now_ms,
                # Keep prior compute duration discoverable without relocating the span.
                "pre_review_execution_time_ms": paused_result_ms,
            },
        )
        node_results.append(wf_executor._stamp_node_result(resumed_result))
        completed_nodes.add(paused_node_id)
        wf_executor.store_node_output(
            paused_node_id, paused_node_label, copy.deepcopy(resolved_output)
        )

    start_time = time.time()
    error_flow_nodes = wf_executor.get_error_flow_nodes()
    active_edges = [
        edge
        for edge in wf_executor.get_active_edges()
        if edge["source"] not in error_flow_nodes and edge["target"] not in error_flow_nodes
    ]

    running_futures: dict = {}
    has_error = False
    error_result = None
    pending_result = None
    pending_lock = Lock()
    early_return_output = None

    output_nodes_with_downstream = set()
    for node_id, node in wf_executor.nodes.items():
        if (
            node_id not in error_flow_nodes
            and node.get("type") == "output"
            and node.get("data", {}).get("allowDownstream")
        ):
            output_nodes_with_downstream.add(node_id)
    wf_executor._downstream_global_node_ids = frozenset()

    def schedule_downstream(source_node_id: str, source_result: NodeResult | None = None) -> None:
        skip_source_handles = (
            set(source_result.metadata.get("skip_source_handles") or []) if source_result else set()
        )
        skip_loop_source_handles = (
            set(source_result.metadata.get("skip_loop_source_handles") or [])
            if source_result
            else set()
        )
        source_is_skipped = source_result is not None and source_result.status == "skipped"
        source_node = wf_executor.nodes.get(source_node_id, {})
        if (
            source_node.get("type") == "loop"
            and source_result is not None
            and source_result.output.get("branch") == "done"
        ):
            wf_executor.prepare_branch_targets_for_execution(
                start_node_ids=wf_executor.get_downstream_nodes(source_node_id, "done"),
                active_edges=active_edges,
                completed_nodes=completed_nodes,
                pending_count=pending_count,
            )
        ready_targets: list[str] = []
        for edge in active_edges:
            if edge["source"] == source_node_id:
                if wf_executor._source_handle_is_skipped(edge, skip_source_handles):
                    continue
                target = edge["target"]
                target_handle = edge.get("targetHandle")
                target_node = wf_executor.nodes.get(target, {})

                if target_node.get("type") == "loop" and target_handle == "loop":
                    if source_is_skipped:
                        continue
                    if wf_executor._source_handle_is_skipped(edge, skip_loop_source_handles):
                        continue
                    if wf_executor.prepare_loop_for_reexecution(
                        loop_node_id=target,
                        active_edges=active_edges,
                        completed_nodes=completed_nodes,
                        pending_count=pending_count,
                    ):
                        already_running = any(
                            pending_node_id == target
                            for pending_node_id in running_futures.values()
                        )
                        if not already_running:
                            new_future = wf_executor._node_pool.submit(
                                wf_executor.execute_node_parallel,
                                target,
                                wf_executor.get_loop_reexecution_inputs(
                                    target, source_node_id, active_edges
                                ),
                            )
                            running_futures[new_future] = target
                    continue

                if target not in pending_count or target in completed_nodes:
                    continue
                pending_count[target] -= 1
                if pending_count[target] == 0:
                    if target in wf_executor.skipped_nodes:
                        node = wf_executor.nodes[target]
                        node_label = node.get("data", {}).get("label", target)
                        skipped_result = wf_executor._stamp_node_result(
                            NodeResult(
                                node_id=target,
                                node_label=node_label,
                                node_type=node.get("type", "unknown"),
                                status="skipped",
                                output={},
                                execution_time_ms=0,
                            )
                        )
                        node_results.append(skipped_result)
                        completed_nodes.add(target)
                        schedule_downstream(target, skipped_result)
                    else:
                        already_running = any(
                            pending_node_id == target
                            for pending_node_id in running_futures.values()
                        )
                        if not already_running:
                            ready_targets.append(target)

        for target in wf_executor._prioritize_ready_node_ids(ready_targets):
            already_running = any(
                pending_node_id == target for pending_node_id in running_futures.values()
            )
            if already_running:
                continue
            new_future = wf_executor._node_pool.submit(
                wf_executor.execute_node_parallel,
                target,
                wf_executor.get_node_inputs_for_edges(target, active_edges),
            )
            running_futures[new_future] = target

    with pending_lock:
        if hitl_resume_mode in {"rerun_agent", "continue_agent"}:
            rerun_future = wf_executor._node_pool.submit(
                wf_executor.execute_node_parallel,
                paused_node_id,
                wf_executor.get_node_inputs_for_edges(paused_node_id, active_edges),
            )
            running_futures[rerun_future] = paused_node_id
        else:
            schedule_downstream(paused_node_id)

    allow_downstream_node_results: list[NodeResult] = []
    allow_downstream_future: Future | None = None
    while (
        running_futures and not has_error and pending_result is None and early_return_output is None
    ):
        done, _ = wait(running_futures.keys(), return_when=FIRST_COMPLETED)

        for future in done:
            node_id = running_futures.pop(future)
            result = future.result()
            node_results.append(result)

            if result.status == "error":
                has_error = True
                error_result = result
                break

            if result.status == "pending":
                pending_result = result
                break

            completed_nodes.add(node_id)

            if node_id in output_nodes_with_downstream and result.status == "success":
                early_return_output = {result.node_label: result.output}
                wf_executor._downstream_global_node_ids = _collect_downstream_global_node_ids(
                    wf_executor, {node_id}, active_edges
                )

            with pending_lock:
                schedule_downstream(node_id, result)

            if early_return_output is not None:

                def run_remaining_downstream() -> None:
                    remaining_futures = dict(running_futures)
                    while remaining_futures:
                        done_bg, _ = wait(remaining_futures.keys(), return_when=FIRST_COMPLETED)
                        for future_bg in done_bg:
                            nid = remaining_futures.pop(future_bg)
                            res = future_bg.result()
                            with pending_lock:
                                node_results.append(res)
                                allow_downstream_node_results.append(res)
                            skip_add_to_completed = False
                            if res.status == "success":
                                with pending_lock:
                                    result_node = wf_executor.nodes.get(nid, {})
                                    skip_source_handles = set(
                                        res.metadata.get("skip_source_handles") or []
                                    )
                                    skip_loop_source_handles = set(
                                        res.metadata.get("skip_loop_source_handles") or []
                                    )
                                    if (
                                        result_node.get("type") == "loop"
                                        and res.output.get("branch") == "done"
                                    ):
                                        wf_executor.prepare_branch_targets_for_execution(
                                            start_node_ids=wf_executor.get_downstream_nodes(
                                                nid, "done"
                                            ),
                                            active_edges=active_edges,
                                            completed_nodes=completed_nodes,
                                            pending_count=pending_count,
                                        )
                                    for edge in active_edges:
                                        if edge["source"] == nid:
                                            if wf_executor._source_handle_is_skipped(
                                                edge, skip_source_handles
                                            ):
                                                continue
                                            tgt = edge["target"]
                                            tgt_handle = edge.get("targetHandle")
                                            tgt_node = wf_executor.nodes.get(tgt, {})
                                            if (
                                                tgt_node.get("type") == "loop"
                                                and tgt_handle == "loop"
                                            ):
                                                if wf_executor._source_handle_is_skipped(
                                                    edge, skip_loop_source_handles
                                                ):
                                                    continue
                                                if wf_executor.prepare_loop_for_reexecution(
                                                    loop_node_id=tgt,
                                                    active_edges=active_edges,
                                                    completed_nodes=completed_nodes,
                                                    pending_count=pending_count,
                                                ):
                                                    skip_add_to_completed = True
                                                    already = any(
                                                        pending_node_id == tgt
                                                        for pending_node_id in remaining_futures.values()
                                                    )
                                                    if not already:
                                                        new_future = wf_executor._node_pool.submit(
                                                            wf_executor.execute_node_parallel,
                                                            tgt,
                                                            wf_executor.get_loop_reexecution_inputs(
                                                                tgt, nid, active_edges
                                                            ),
                                                        )
                                                        remaining_futures[new_future] = tgt
                                                continue
                                            if tgt not in pending_count or tgt in completed_nodes:
                                                continue
                                            pending_count[tgt] -= 1
                                            if (
                                                pending_count[tgt] == 0
                                                and tgt not in wf_executor.skipped_nodes
                                            ):
                                                already = any(
                                                    pending_node_id == tgt
                                                    for pending_node_id in remaining_futures.values()
                                                )
                                                if not already:
                                                    new_future = wf_executor._node_pool.submit(
                                                        wf_executor.execute_node_parallel,
                                                        tgt,
                                                        wf_executor.get_node_inputs_for_edges(
                                                            tgt, active_edges
                                                        ),
                                                    )
                                                    remaining_futures[new_future] = tgt
                            if not skip_add_to_completed:
                                completed_nodes.add(nid)
                    wf_executor.drain_bg_futures()

                allow_downstream_future = _submit_allow_downstream_work(run_remaining_downstream)
                break

    if pending_result is not None:
        for future in running_futures:
            future.cancel()

        pending_review = _extract_pending_metadata(pending_result)
        resume_snapshot = wf_executor.build_resume_snapshot(
            initial_inputs=snapshot.get("initial_inputs") or {},
            node_results=node_results,
            pending_count=pending_count,
            completed_nodes=completed_nodes,
            paused_node_id=pending_result.node_id,
            paused_node_label=pending_result.node_label,
        )
        result = wf_executor._build_execution_result(
            workflow_id=workflow_id,
            status="pending",
            outputs={pending_result.node_label: copy.deepcopy(pending_result.output)},
            start_time=start_time,
            node_results=node_results,
            pending_review=pending_review,
            resume_snapshot=resume_snapshot,
        )
    elif early_return_output is not None:
        result = wf_executor._build_execution_result(
            workflow_id=workflow_id,
            status="success",
            outputs=early_return_output,
            start_time=start_time,
            node_results=node_results,
            allow_downstream_pending=[allow_downstream_future] if allow_downstream_future else None,
            allow_downstream_node_results=allow_downstream_node_results,
        )
    elif has_error and error_result:
        error_flow_final_output = None
        if error_flow_nodes:
            error_edges = [
                edge
                for edge in wf_executor.edges
                if edge["source"] in error_flow_nodes and edge["target"] in error_flow_nodes
            ]
            error_payload = {
                "node_id": error_result.node_id,
                "node_label": error_result.node_label,
                "node_type": error_result.node_type,
                "message": error_result.error,
            }
            error_results, error_flow_final_output = wf_executor.execute_error_flow(
                error_flow_nodes, error_edges, error_payload
            )
            node_results.extend(error_results)

        final_outputs = error_flow_final_output or {"error": error_result.error}
        result = wf_executor._build_execution_result(
            workflow_id=workflow_id,
            status="error",
            outputs=final_outputs,
            start_time=start_time,
            node_results=node_results,
        )
    else:
        output_nodes = wf_executor.get_output_nodes()
        final_outputs = {}
        for node_id in output_nodes:
            if node_id in wf_executor.node_outputs and node_id not in wf_executor.skipped_nodes:
                node = wf_executor.nodes.get(node_id, {})
                if node.get("type") == "sticky":
                    continue
                node_label = wf_executor.get_node_label(node_id)
                final_outputs[node_label] = wf_executor.node_outputs[node_id]
        final_outputs = unwrap_single_json_output_terminal_outputs(wf_executor, final_outputs)
        result = wf_executor._build_execution_result(
            workflow_id=workflow_id,
            status="success",
            outputs=final_outputs,
            start_time=start_time,
            node_results=node_results,
        )

    if credentials_context:
        result.outputs = mask_sensitive_output(result.outputs, credentials_context)
        downstream_globals = getattr(result, "_downstream_global_node_ids", frozenset())
        for node_result in result.node_results:
            if isinstance(node_result, dict):
                keep_output = bool(node_result.get("node_id") in downstream_globals)
                _mask_node_result_row(node_result, credentials_context, keep_output=keep_output)
        result._credentials_context = credentials_context

    return result


def _llm_transport_attribute(node_data: dict[str, Any]) -> str:
    """Which LLM endpoint this node will use, for the heym.node.execute span."""
    if node_data.get("responsesApiEnabled") and not node_data.get("batchModeEnabled"):
        return "responses"
    return "chat.completions"


def execute_llm_batch_notification_branch(
    *,
    snapshot: dict,
    source_node_id: str,
    source_node_label: str,
    notification_output: dict,
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
    agent_progress_queue: queue.Queue | None = None,
) -> dict[str, Any]:
    workflow_id_value = snapshot.get("workflow_id")
    if not workflow_id_value:
        raise ValueError("Missing workflow_id in LLM batch notification snapshot")

    workflow_id = uuid.UUID(str(workflow_id_value))
    wf_executor = WorkflowExecutor(
        nodes=snapshot.get("nodes") or [],
        edges=snapshot.get("edges") or [],
        workflow_cache=snapshot.get("workflow_cache") or {},
        test_mode=bool(snapshot.get("test_mode", False)),
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        workflow_id=workflow_id,
        trace_user_id=trace_user_id,
        actor_user_id=_snapshot_actor_user_id(snapshot),
        conversation_history=snapshot.get("conversation_history"),
        llm_session_id=snapshot.get("llm_session_id"),
        agent_progress_queue=agent_progress_queue,
        sub_workflow_invocation_depth=int(snapshot.get("sub_workflow_invocation_depth", 0)),
        invoked_by_agent=bool(snapshot.get("invoked_by_agent", False)),
    )
    wf_executor.node_outputs = copy.deepcopy(snapshot.get("node_outputs") or {})
    wf_executor.node_execution_contexts = copy.deepcopy(
        snapshot.get("node_execution_contexts") or {}
    )
    wf_executor.label_to_output = copy.deepcopy(snapshot.get("label_to_output") or {})
    wf_executor._rebuild_wrapped_label_output_cache()
    wf_executor.skipped_nodes = set(snapshot.get("skipped_nodes") or [])
    wf_executor.inactive_nodes = set(snapshot.get("inactive_nodes") or [])
    wf_executor.loop_states = copy.deepcopy(snapshot.get("loop_states") or {})
    wf_executor.vars = copy.deepcopy(snapshot.get("vars") or {})
    wf_executor._mark_vars_context_dirty()
    wf_executor.sub_workflow_executions = _restore_sub_workflow_executions(
        snapshot.get("sub_workflow_executions")
    )
    wf_executor.store_node_output(
        source_node_id,
        source_node_label,
        copy.deepcopy(notification_output),
    )

    error_flow_nodes = wf_executor.get_error_flow_nodes()
    active_edges = [
        edge
        for edge in wf_executor.get_active_edges()
        if edge["source"] not in error_flow_nodes and edge["target"] not in error_flow_nodes
    ]

    branch_node_ids: set[str] = {source_node_id}
    queue_to_visit = deque(
        edge["target"]
        for edge in active_edges
        if edge["source"] == source_node_id and edge.get("sourceHandle") == "batchStatus"
    )
    while queue_to_visit:
        node_id = queue_to_visit.popleft()
        if node_id in branch_node_ids:
            continue
        branch_node_ids.add(node_id)
        for edge in active_edges:
            if edge["source"] == node_id:
                queue_to_visit.append(edge["target"])

    if branch_node_ids == {source_node_id}:
        return {"status": "success", "node_results": [], "execution_time_ms": 0.0}

    branch_edges = [
        edge
        for edge in active_edges
        if edge["source"] in branch_node_ids and edge["target"] in branch_node_ids
    ]
    pending_count = {node_id: 0 for node_id in branch_node_ids if node_id != source_node_id}
    for edge in branch_edges:
        target = edge["target"]
        if target in pending_count:
            pending_count[target] += 1

    completed_nodes: set[str] = {source_node_id}
    branch_node_results: list[NodeResult] = []
    running_futures: dict = {}
    pending_lock = Lock()
    start_time = time.time()

    def _enqueue_start(node_id: str) -> None:
        if agent_progress_queue is None:
            return
        node_label = wf_executor.get_node_label(node_id)
        agent_progress_queue.put(_build_node_start_event(node_id, node_label))

    def _submit_node(node_id: str, node_inputs: dict | None = None) -> None:
        already_running = any(
            pending_node_id == node_id for pending_node_id in running_futures.values()
        )
        if already_running:
            return
        _enqueue_start(node_id)
        new_future = wf_executor._node_pool.submit(
            wf_executor.execute_node_parallel,
            node_id,
            (
                node_inputs
                if node_inputs is not None
                else wf_executor.get_node_inputs_for_edges(node_id, branch_edges)
            ),
        )
        running_futures[new_future] = node_id

    def schedule_downstream(
        source_id: str,
        source_result: NodeResult | None = None,
        *,
        only_source_handles: set[str] | None = None,
    ) -> None:
        skip_source_handles = (
            set(source_result.metadata.get("skip_source_handles") or []) if source_result else set()
        )
        skip_loop_source_handles = (
            set(source_result.metadata.get("skip_loop_source_handles") or [])
            if source_result
            else set()
        )
        source_is_skipped = source_result is not None and source_result.status == "skipped"
        source_node = wf_executor.nodes.get(source_id, {})
        if (
            source_node.get("type") == "loop"
            and source_result is not None
            and source_result.output.get("branch") == "done"
        ):
            wf_executor.prepare_branch_targets_for_execution(
                start_node_ids=wf_executor.get_downstream_nodes(source_id, "done"),
                active_edges=branch_edges,
                completed_nodes=completed_nodes,
                pending_count=pending_count,
            )
        for edge in branch_edges:
            if edge["source"] != source_id:
                continue
            source_handle = edge.get("sourceHandle")
            if only_source_handles is not None and source_handle not in only_source_handles:
                continue
            if wf_executor._source_handle_is_skipped(edge, skip_source_handles):
                continue

            target = edge["target"]
            target_handle = edge.get("targetHandle")
            target_node = wf_executor.nodes.get(target, {})
            if target_node.get("type") == "loop" and target_handle == "loop":
                if source_is_skipped:
                    continue
                if wf_executor._source_handle_is_skipped(edge, skip_loop_source_handles):
                    continue
                if wf_executor.prepare_loop_for_reexecution(
                    loop_node_id=target,
                    active_edges=branch_edges,
                    completed_nodes=completed_nodes,
                    pending_count=pending_count,
                ):
                    _submit_node(
                        target,
                        wf_executor.get_loop_reexecution_inputs(target, source_id, branch_edges),
                    )
                continue

            if target not in pending_count or target in completed_nodes:
                continue
            pending_count[target] -= 1
            if pending_count[target] == 0:
                if target in wf_executor.skipped_nodes:
                    node = wf_executor.nodes[target]
                    node_label = node.get("data", {}).get("label", target)
                    skipped_result = wf_executor._stamp_node_result(
                        NodeResult(
                            node_id=target,
                            node_label=node_label,
                            node_type=node.get("type", "unknown"),
                            status="skipped",
                            output={},
                            execution_time_ms=0,
                        )
                    )
                    branch_node_results.append(skipped_result)
                    completed_nodes.add(target)
                    if agent_progress_queue is not None:
                        agent_progress_queue.put(_build_node_complete_event(skipped_result, {}))
                    schedule_downstream(target, skipped_result)
                else:
                    _submit_node(target)

    with pending_lock:
        schedule_downstream(source_node_id, only_source_handles={"batchStatus"})

    while running_futures:
        done, _ = wait(running_futures.keys(), return_when=FIRST_COMPLETED)
        for future in done:
            node_id = running_futures.pop(future)
            result = future.result()
            if result.status == "pending":
                result = wf_executor._stamp_node_result(
                    NodeResult(
                        node_id=result.node_id,
                        node_label=result.node_label,
                        node_type=result.node_type,
                        status="error",
                        output=result.output,
                        execution_time_ms=result.execution_time_ms,
                        error=("LLM batch status branches cannot pause for a human review."),
                        metadata=dict(result.metadata or {}),
                    )
                )
            branch_node_results.append(result)
            if agent_progress_queue is not None:
                output = (
                    mask_sensitive_output(result.output, credentials_context)
                    if credentials_context
                    else result.output
                )
                agent_progress_queue.put(_build_node_complete_event(result, output))
            if result.status != "success":
                continue
            completed_nodes.add(node_id)
            with pending_lock:
                schedule_downstream(node_id, result)

    combined_results = _order_node_results(
        list(branch_node_results) + list(wf_executor.notification_branch_node_results)
    )
    return {
        "status": "success",
        "node_results": combined_results,
        "execution_time_ms": (time.time() - start_time) * 1000,
    }


def execute_hitl_notification_branch(
    *,
    snapshot: dict,
    pending_output: dict,
    source_handle: str = "hitl",
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
) -> dict:
    workflow_id_value = snapshot.get("workflow_id")
    if not workflow_id_value:
        raise ValueError("Missing workflow_id in HITL notification snapshot")

    workflow_id = uuid.UUID(str(workflow_id_value))
    wf_executor = WorkflowExecutor(
        nodes=snapshot.get("nodes") or [],
        edges=snapshot.get("edges") or [],
        workflow_cache=snapshot.get("workflow_cache") or {},
        test_mode=bool(snapshot.get("test_mode", False)),
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        workflow_id=workflow_id,
        trace_user_id=trace_user_id,
        actor_user_id=_snapshot_actor_user_id(snapshot),
        conversation_history=snapshot.get("conversation_history"),
        llm_session_id=snapshot.get("llm_session_id"),
        sub_workflow_invocation_depth=int(snapshot.get("sub_workflow_invocation_depth", 0)),
        invoked_by_agent=bool(snapshot.get("invoked_by_agent", False)),
    )
    wf_executor.node_outputs = copy.deepcopy(snapshot.get("node_outputs") or {})
    wf_executor.node_execution_contexts = copy.deepcopy(
        snapshot.get("node_execution_contexts") or {}
    )
    wf_executor.label_to_output = copy.deepcopy(snapshot.get("label_to_output") or {})
    wf_executor._rebuild_wrapped_label_output_cache()
    wf_executor.skipped_nodes = set(snapshot.get("skipped_nodes") or [])
    wf_executor.inactive_nodes = set(snapshot.get("inactive_nodes") or [])
    wf_executor.loop_states = copy.deepcopy(snapshot.get("loop_states") or {})
    wf_executor.vars = copy.deepcopy(snapshot.get("vars") or {})
    wf_executor._mark_vars_context_dirty()
    wf_executor.sub_workflow_executions = _restore_sub_workflow_executions(
        snapshot.get("sub_workflow_executions")
    )

    node_results = _restore_node_results(snapshot.get("node_results"))
    wf_executor._node_result_sequence = _max_node_result_sequence(node_results)
    pending_count = {
        str(node_id): int(count) for node_id, count in (snapshot.get("pending_count") or {}).items()
    }
    completed_nodes: set[str] = set(snapshot.get("completed_nodes") or [])
    paused_node_id = str(snapshot.get("paused_node_id") or "")
    if not paused_node_id:
        raise ValueError("Missing paused_node_id in HITL notification snapshot")
    paused_node_label = str(
        snapshot.get("paused_node_label") or wf_executor.get_node_label(paused_node_id)
    )

    for result in node_results:
        if result.node_id == paused_node_id and result.status == "pending":
            result.output = copy.deepcopy(pending_output)

    wf_executor.store_node_output(paused_node_id, paused_node_label, copy.deepcopy(pending_output))

    start_time = time.time()
    error_flow_nodes = wf_executor.get_error_flow_nodes()
    active_edges = [
        edge
        for edge in wf_executor.get_active_edges()
        if edge["source"] not in error_flow_nodes and edge["target"] not in error_flow_nodes
    ]

    branch_node_results: list[NodeResult] = []
    running_futures: dict = {}
    pending_lock = Lock()

    def schedule_downstream(
        source_node_id: str,
        source_result: NodeResult | None = None,
        *,
        only_source_handles: set[str] | None = None,
    ) -> None:
        skip_source_handles = (
            set(source_result.metadata.get("skip_source_handles") or []) if source_result else set()
        )
        skip_loop_source_handles = (
            set(source_result.metadata.get("skip_loop_source_handles") or [])
            if source_result
            else set()
        )
        source_is_skipped = source_result is not None and source_result.status == "skipped"
        source_node = wf_executor.nodes.get(source_node_id, {})
        if (
            source_node.get("type") == "loop"
            and source_result is not None
            and source_result.output.get("branch") == "done"
        ):
            wf_executor.prepare_branch_targets_for_execution(
                start_node_ids=wf_executor.get_downstream_nodes(source_node_id, "done"),
                active_edges=active_edges,
                completed_nodes=completed_nodes,
                pending_count=pending_count,
            )
        for edge in active_edges:
            if edge["source"] != source_node_id:
                continue

            source_handle = edge.get("sourceHandle")
            if only_source_handles is not None and source_handle not in only_source_handles:
                continue
            if wf_executor._source_handle_is_skipped(edge, skip_source_handles):
                continue

            target = edge["target"]
            target_handle = edge.get("targetHandle")
            target_node = wf_executor.nodes.get(target, {})

            if target_node.get("type") == "loop" and target_handle == "loop":
                if source_is_skipped:
                    continue
                if wf_executor._source_handle_is_skipped(edge, skip_loop_source_handles):
                    continue
                if wf_executor.prepare_loop_for_reexecution(
                    loop_node_id=target,
                    active_edges=active_edges,
                    completed_nodes=completed_nodes,
                    pending_count=pending_count,
                ):
                    already_running = any(
                        pending_node_id == target for pending_node_id in running_futures.values()
                    )
                    if not already_running:
                        new_future = wf_executor._node_pool.submit(
                            wf_executor.execute_node_parallel,
                            target,
                            wf_executor.get_loop_reexecution_inputs(
                                target, source_node_id, active_edges
                            ),
                        )
                        running_futures[new_future] = target
                continue

            if target not in pending_count or target in completed_nodes:
                continue
            pending_count[target] -= 1
            if pending_count[target] == 0:
                if target in wf_executor.skipped_nodes:
                    node = wf_executor.nodes[target]
                    node_label = node.get("data", {}).get("label", target)
                    skipped_result = NodeResult(
                        node_id=target,
                        node_label=node_label,
                        node_type=node.get("type", "unknown"),
                        status="skipped",
                        output={},
                        execution_time_ms=0,
                    )
                    skipped_result = wf_executor._stamp_node_result(skipped_result)
                    branch_node_results.append(skipped_result)
                    node_results.append(skipped_result)
                    completed_nodes.add(target)
                    schedule_downstream(target, skipped_result)
                else:
                    already_running = any(
                        pending_node_id == target for pending_node_id in running_futures.values()
                    )
                    if not already_running:
                        new_future = wf_executor._node_pool.submit(
                            wf_executor.execute_node_parallel,
                            target,
                            wf_executor.get_node_inputs_for_edges(target, active_edges),
                        )
                        running_futures[new_future] = target

    with pending_lock:
        schedule_downstream(paused_node_id, only_source_handles={source_handle})

    while running_futures:
        done, _ = wait(running_futures.keys(), return_when=FIRST_COMPLETED)

        for future in done:
            node_id = running_futures.pop(future)
            result = future.result()
            if result.status == "pending":
                result = NodeResult(
                    node_id=result.node_id,
                    node_label=result.node_label,
                    node_type=result.node_type,
                    status="error",
                    output=result.output,
                    execution_time_ms=result.execution_time_ms,
                    error="HITL notification branches cannot pause for another human review.",
                    metadata=dict(result.metadata or {}),
                )
                result = wf_executor._stamp_node_result(result)
            branch_node_results.append(result)
            node_results.append(result)

            if result.status != "success":
                continue

            completed_nodes.add(node_id)
            with pending_lock:
                schedule_downstream(node_id, result)

    updated_snapshot = wf_executor.build_resume_snapshot(
        initial_inputs=snapshot.get("initial_inputs") or {},
        node_results=node_results,
        pending_count=pending_count,
        completed_nodes=completed_nodes,
        paused_node_id=paused_node_id,
        paused_node_label=paused_node_label,
    )

    return {
        "status": "success",
        "node_results": _serialize_node_results(branch_node_results),
        "resume_snapshot": updated_snapshot,
        "execution_time_ms": (time.time() - start_time) * 1000,
    }


def _execute_error_flow_streaming(
    wf_executor: WorkflowExecutor,
    error_nodes: set[str],
    edges: list[dict],
    error_payload: dict,
    credentials_context: dict[str, str] | None = None,
    start_time: float | None = None,
):
    pending_count = {node_id: 0 for node_id in error_nodes}
    for edge in edges:
        if edge["target"] in pending_count:
            pending_count[edge["target"]] += 1

    queue = [node_id for node_id, count in pending_count.items() if count == 0]
    completed: set[str] = set()
    final_output_emitted = False
    error_flow_output = None

    output_nodes_with_downstream = set()
    for node_id in error_nodes:
        node = wf_executor.nodes.get(node_id, {})
        if node.get("type") == "output" and node.get("data", {}).get("allowDownstream"):
            output_nodes_with_downstream.add(node_id)

    while queue:
        node_id = queue.pop(0)
        if node_id in completed:
            continue
        node = wf_executor.nodes.get(node_id, {})
        node_type = node.get("type")
        node_label = node.get("data", {}).get("label", node_id)

        if node_id in wf_executor.skipped_nodes:
            result = wf_executor._stamp_node_result(
                NodeResult(
                    node_id=node_id,
                    node_label=node_label,
                    node_type=node_type or "unknown",
                    status="skipped",
                    output={},
                    execution_time_ms=0,
                )
            )
            yield _build_node_complete_event(result, {})
            yield {"type": "_internal_node_result", "result": result}
            completed.add(node_id)
            for edge in edges:
                if edge["source"] == node_id:
                    target = edge["target"]
                    if target in pending_count:
                        pending_count[target] -= 1
                        if pending_count[target] == 0:
                            queue.append(target)
            continue

        yield _build_node_start_event(node_id, node_label)

        if node_type == "errorHandler":
            inputs = {"error": error_payload}
        else:
            inputs = wf_executor.get_node_inputs_for_edges(node_id, edges)

        result = wf_executor.execute_node_parallel(node_id, inputs)

        output = result.output
        if credentials_context:
            output = mask_sensitive_output(output, credentials_context)

        yield _build_node_complete_event(result, output)
        yield {"type": "_internal_node_result", "result": result}
        completed.add(node_id)

        if node_type in OUTPUT_TERMINAL_NODE_TYPES and result.status == "success":
            error_flow_output = {result.node_label: output}
            if not final_output_emitted:
                final_output_emitted = True
                yield {
                    "type": "final_output",
                    "node_id": node_id,
                    "node_label": result.node_label,
                    "node_type": result.node_type,
                    "output": output,
                    "execution_time_ms": ((time.time() - start_time) * 1000 if start_time else 0),
                }

        for edge in edges:
            if edge["source"] == node_id:
                target = edge["target"]
                if target in pending_count:
                    pending_count[target] -= 1
                    if pending_count[target] == 0:
                        queue.append(target)

    if error_flow_output:
        yield {"type": "_internal_error_flow_output", "output": error_flow_output}


def _serialized_graph_plus_delegated_node_results(
    graph_results: list[NodeResult],
    wf_executor: WorkflowExecutor,
) -> list[dict]:
    combined = _order_node_results(
        list(graph_results)
        + list(getattr(wf_executor, "retry_node_results", []))
        + list(getattr(wf_executor, "delegated_agent_node_results", []))
        + list(getattr(wf_executor, "notification_branch_node_results", []))
    )
    return _serialize_node_results(combined)


def build_node_start_message(
    node_id: str,
    node_label: str,
    sse_node_config: dict | None,
) -> str | None:
    """Return the configured node_start message or None when start messages are disabled."""
    config = (sse_node_config or {}).get(node_id, {})
    send_start = config.get("send_start", True)
    if not send_start:
        return None
    return config.get("start_message") or f"[START] {node_label}"


def execute_workflow_streaming(**kwargs):
    """Public streaming entry: record live events so late observers replay them."""
    yield from buffer_live_execution_events(
        _execute_workflow_streaming_traced(**kwargs),
        str(kwargs.get("execution_id") or ""),
    )


def _execute_workflow_streaming_traced(**kwargs):
    """Wrap the run in an OTel root span (no-op when disabled).

    The canvas "Run" and portal use the streaming path, which has its own node
    loop and does not call ``WorkflowExecutor.execute``. This wrapper opens the
    ``heym.workflow.execute`` root span here so node spans nest under it.
    """
    if not tracing.is_enabled():
        yield from _execute_workflow_streaming_impl(**kwargs)
        return

    from opentelemetry.trace import Status, StatusCode, set_span_in_context

    tracer = tracing.get_tracer()
    span = tracer.start_span("heym.workflow.execute")
    try:
        span.set_attribute("heym.workflow.id", str(kwargs.get("workflow_id", "")))
        span.set_attribute("heym.node.count", len(kwargs.get("nodes") or []))
        span.set_attribute("heym.workflow.test_mode", bool(kwargs.get("test_run", False)))
        span.set_attribute("heym.execution.mode", "streaming")
        yield from _execute_workflow_streaming_impl(
            otel_root_context=set_span_in_context(span), **kwargs
        )
    except Exception as exc:  # noqa: BLE001 - observe then re-raise
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    finally:
        span.end()


def _execute_workflow_streaming_impl(
    workflow_id: uuid.UUID,
    nodes: list[dict],
    edges: list[dict],
    inputs: dict,
    workflow_cache: dict[str, dict] | None = None,
    test_run: bool = False,
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    cancel_event: Event | None = None,
    executor_holder: dict | None = None,
    sse_node_config: dict | None = None,
    public_base_url: str = "",
    otel_root_context: object | None = None,
    timeout_seconds: float | None = None,
    workflow_name: str = "",
    workflow_description: str = "",
    execution_id: str = "",
    llm_session_id: str | None = None,
):
    import queue

    event_queue: queue.Queue = queue.Queue()
    wf_executor = WorkflowExecutor(
        nodes,
        edges,
        workflow_cache,
        test_mode=test_run,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        workflow_id=workflow_id,
        trace_user_id=trace_user_id,
        actor_user_id=actor_user_id,
        conversation_history=conversation_history,
        agent_progress_queue=event_queue,
        cancel_event=cancel_event,
        public_base_url=public_base_url,
        timeout_seconds=timeout_seconds,
        workflow_name=workflow_name,
        workflow_description=workflow_description,
        execution_id=execution_id,
        llm_session_id=llm_session_id,
    )
    wf_executor._ensure_execution_id()
    wf_executor._arm_deadline()
    if executor_holder is not None:
        executor_holder["executor"] = wf_executor
    # Re-attach the streaming root span context so node spans (run in worker
    # threads via execute_node) nest under heym.workflow.execute.
    if otel_root_context is not None:
        wf_executor._otel_root_context = otel_root_context
    start_time = time.time()
    node_results: list[NodeResult] = []
    has_error = False
    error_result = None
    pending_result = None
    error_flow_nodes = wf_executor.get_error_flow_nodes()
    # Set of node IDs that are connected as tools to an agent (should not run in regular flow)
    tool_node_ids_streaming = {
        edge["source"] for edge in wf_executor.edges if edge.get("targetHandle") == "tool-input"
    }
    active_edges = [
        edge
        for edge in wf_executor.get_active_edges()
        if edge["source"] not in error_flow_nodes
        and edge["target"] not in error_flow_nodes
        and edge.get("targetHandle") != "tool-input"
    ]
    active_nodes = [
        node_id
        for node_id in wf_executor.nodes
        if node_id not in error_flow_nodes and node_id not in tool_node_ids_streaming
    ]

    for node_id in wf_executor.get_input_nodes():
        node = wf_executor.nodes[node_id]
        if node.get("type") == "textInput":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
            if "text" in inputs:
                node["data"]["value"] = inputs["text"]
        elif (
            node.get("type") == "rabbitmq"
            and node.get("data", {}).get("rabbitmqOperation") == "receive"
        ):
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
        elif node.get("type") == "imapTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
        elif node.get("type") == "websocketTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
        elif node.get("type") == "slackTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
        elif node.get("type") == "discordTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
        elif node.get("type") == "telegramTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
        elif node.get("type") == "heymTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs

    pending_count: dict[str, int] = {}
    for node_id in active_nodes:
        node = wf_executor.nodes.get(node_id, {})
        if node.get("type") == "loop":
            count = sum(
                1
                for e in active_edges
                if e["target"] == node_id and e.get("targetHandle") != "loop"
            )
        else:
            count = sum(1 for e in active_edges if e["target"] == node_id)
        pending_count[node_id] = count

    completed_nodes: set[str] = set()
    running_futures: dict = {}
    pending_lock = Lock()
    nodes_to_schedule: list[str] = []
    final_output_emitted = False

    output_nodes_with_downstream = set()
    for node_id in active_nodes:
        node = wf_executor.nodes.get(node_id, {})
        if node.get("type") == "output" and node.get("data", {}).get("allowDownstream"):
            output_nodes_with_downstream.add(node_id)

    def on_retry_callback(retry_result: NodeResult, attempt: int, max_attempts: int) -> None:
        event_queue.put(
            {
                "type": "node_retry",
                "node_id": retry_result.node_id,
                "node_label": retry_result.node_label,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "retry_result": _serialize_node_result(retry_result),
            }
        )

    def execute_and_report(node_id: str, node_inputs: dict | None = None) -> NodeResult:
        wf_executor.check_cancelled()
        node = wf_executor.nodes[node_id]
        node_label = node.get("data", {}).get("label", node_id)

        start_message = build_node_start_message(node_id, node_label, sse_node_config)
        node_start_event = _build_node_start_event(
            node_id,
            node_label,
            message=start_message,
        )
        event_queue.put(node_start_event)

        if node_inputs is None:
            node_inputs = wf_executor.get_node_inputs_for_edges(node_id, active_edges)
        result = wf_executor.execute_node_parallel(node_id, node_inputs, on_retry=on_retry_callback)

        output = result.output
        if credentials_context:
            output = mask_sensitive_output(output, credentials_context)

        event_queue.put(_build_node_complete_event(result, output))

        return result

    def schedule_downstream(source_node_id: str, source_result: NodeResult | None = None) -> None:
        wf_executor.check_cancelled()
        skip_source_handles = (
            set(source_result.metadata.get("skip_source_handles") or []) if source_result else set()
        )
        skip_loop_source_handles = (
            set(source_result.metadata.get("skip_loop_source_handles") or [])
            if source_result
            else set()
        )
        source_is_skipped = source_result is not None and source_result.status == "skipped"
        source_node = wf_executor.nodes.get(source_node_id, {})
        if (
            source_node.get("type") == "loop"
            and source_result is not None
            and source_result.output.get("branch") == "done"
        ):
            wf_executor.prepare_branch_targets_for_execution(
                start_node_ids=wf_executor.get_downstream_nodes(source_node_id, "done"),
                active_edges=active_edges,
                completed_nodes=completed_nodes,
                pending_count=pending_count,
            )
        for edge in active_edges:
            if edge["source"] == source_node_id:
                if wf_executor._source_handle_is_skipped(edge, skip_source_handles):
                    continue
                target = edge["target"]
                target_handle = edge.get("targetHandle")
                target_node = wf_executor.nodes.get(target, {})

                if target_node.get("type") == "loop" and target_handle == "loop":
                    if source_is_skipped:
                        continue
                    if wf_executor._source_handle_is_skipped(edge, skip_loop_source_handles):
                        continue
                    if wf_executor.prepare_loop_for_reexecution(
                        loop_node_id=target,
                        active_edges=active_edges,
                        completed_nodes=completed_nodes,
                        pending_count=pending_count,
                    ):
                        already_running = any(nid == target for nid in running_futures.values())
                        if not already_running:
                            new_future = wf_executor._node_pool.submit(
                                execute_and_report,
                                target,
                                wf_executor.get_loop_reexecution_inputs(
                                    target, source_node_id, active_edges
                                ),
                            )
                            running_futures[new_future] = target
                    continue

                if target not in pending_count:
                    continue
                if target in completed_nodes:
                    continue
                pending_count[target] -= 1
                if pending_count[target] == 0:
                    if target in wf_executor.skipped_nodes:
                        node = wf_executor.nodes[target]
                        node_label = node.get("data", {}).get("label", target)
                        skipped_result = wf_executor._stamp_node_result(
                            NodeResult(
                                node_id=target,
                                node_label=node_label,
                                node_type=node.get("type", "unknown"),
                                status="skipped",
                                output={},
                                execution_time_ms=0,
                            )
                        )
                        node_results.append(skipped_result)
                        completed_nodes.add(target)
                        nodes_to_schedule.append(target)
                        schedule_downstream(target, skipped_result)
                    else:
                        already_running = any(nid == target for nid in running_futures.values())
                        if not already_running:
                            new_future = wf_executor._node_pool.submit(execute_and_report, target)
                            running_futures[new_future] = target

    root_nodes = [nid for nid, count in pending_count.items() if count == 0]
    for node_id in root_nodes:
        wf_executor.check_cancelled()
        if node_id in wf_executor.skipped_nodes:
            node = wf_executor.nodes[node_id]
            node_label = node.get("data", {}).get("label", node_id)
            node_results.append(
                wf_executor._stamp_node_result(
                    NodeResult(
                        node_id=node_id,
                        node_label=node_label,
                        node_type=node.get("type", "unknown"),
                        status="skipped",
                        output={},
                        execution_time_ms=0,
                    )
                )
            )
            completed_nodes.add(node_id)
            nodes_to_schedule.append(node_id)
            schedule_downstream(node_id)
        else:
            future = wf_executor._node_pool.submit(execute_and_report, node_id)
            running_futures[future] = node_id

    for skipped_id in nodes_to_schedule:
        node = wf_executor.nodes[skipped_id]
        node_label = node.get("data", {}).get("label", skipped_id)
        yield _build_node_complete_event(
            wf_executor._stamp_node_result(
                NodeResult(
                    node_id=skipped_id,
                    node_label=node_label,
                    node_type=node.get("type", "unknown"),
                    status="skipped",
                    output={},
                    execution_time_ms=0,
                )
            ),
            {},
        )
    nodes_to_schedule.clear()

    while running_futures and not has_error and pending_result is None:
        wf_executor.check_cancelled()
        while not event_queue.empty():
            yield event_queue.get_nowait()

        done, _ = wait(running_futures.keys(), timeout=0.01, return_when=FIRST_COMPLETED)

        if not done:
            continue

        for future in done:
            node_id = running_futures.pop(future)
            wf_executor.check_cancelled()
            result = future.result()
            node_results.append(result)

            if result.status == "error":
                has_error = True
                error_result = result
                break

            if result.status == "pending":
                pending_result = result
                break

            completed_nodes.add(node_id)

            node_for_final = wf_executor.nodes.get(node_id, {})
            is_json_mapper_final = node_for_final.get("type") in TERMINAL_MAPPER_NODE_TYPES
            if (
                not final_output_emitted
                and result.status == "success"
                and (node_id in output_nodes_with_downstream or is_json_mapper_final)
            ):
                final_output_emitted = True
                output_for_event = result.output
                if credentials_context:
                    output_for_event = mask_sensitive_output(output_for_event, credentials_context)
                event_queue.put(
                    {
                        "type": "final_output",
                        "node_id": node_id,
                        "node_label": result.node_label,
                        "node_type": result.node_type,
                        "output": _to_json_compatible(output_for_event),
                        "execution_time_ms": (time.time() - start_time) * 1000,
                    }
                )

            with pending_lock:
                schedule_downstream(node_id, result)

        for skipped_id in nodes_to_schedule:
            node = wf_executor.nodes[skipped_id]
            node_label = node.get("data", {}).get("label", skipped_id)
            yield _build_node_complete_event(
                wf_executor._stamp_node_result(
                    NodeResult(
                        node_id=skipped_id,
                        node_label=node_label,
                        node_type=node.get("type", "unknown"),
                        status="skipped",
                        output={},
                        execution_time_ms=0,
                    )
                ),
                {},
            )
        nodes_to_schedule.clear()

    while not event_queue.empty():
        yield event_queue.get_nowait()

    if pending_result is not None:
        for future in running_futures:
            future.cancel()

        pending_review = _extract_pending_metadata(pending_result)
        resume_snapshot = wf_executor.build_resume_snapshot(
            initial_inputs=inputs,
            node_results=node_results,
            pending_count=pending_count,
            completed_nodes=completed_nodes,
            paused_node_id=pending_result.node_id,
            paused_node_label=pending_result.node_label,
        )
        yield {
            "type": "execution_complete",
            "workflow_id": str(workflow_id),
            "status": "pending",
            "outputs": _to_json_compatible(
                {pending_result.node_label: copy.deepcopy(pending_result.output)}
            ),
            "execution_time_ms": (time.time() - start_time) * 1000,
            "node_results": _serialized_graph_plus_delegated_node_results(
                node_results, wf_executor
            ),
            "highlight": build_highlight_payload(
                _serialized_graph_plus_delegated_node_results(node_results, wf_executor),
                nodes,
                inputs,
            ),
            "sub_workflow_executions": _serialize_sub_workflow_executions(
                wf_executor.sub_workflow_executions
            ),
            "_pending_review": pending_review,
            "_resume_snapshot": resume_snapshot,
        }
        return

    if has_error and error_result:
        error_flow_nodes = wf_executor.get_error_flow_nodes()
        error_flow_final_output = None
        if error_flow_nodes:
            error_edges = [
                edge
                for edge in wf_executor.edges
                if edge["source"] in error_flow_nodes and edge["target"] in error_flow_nodes
            ]
            error_payload = {
                "node_id": error_result.node_id,
                "node_label": error_result.node_label,
                "node_type": error_result.node_type,
                "message": error_result.error,
            }
            for event in _execute_error_flow_streaming(
                wf_executor,
                error_flow_nodes,
                error_edges,
                error_payload,
                credentials_context,
                start_time,
            ):
                if event["type"] == "_internal_node_result":
                    node_results.append(event["result"])
                elif event["type"] == "_internal_error_flow_output":
                    error_flow_final_output = event["output"]
                else:
                    yield event

        final_outputs = error_flow_final_output or {"error": error_result.error}
        serialized_results = _serialized_graph_plus_delegated_node_results(
            node_results, wf_executor
        )
        yield {
            "type": "execution_complete",
            "workflow_id": str(workflow_id),
            "status": "error",
            "outputs": _to_json_compatible(final_outputs),
            "execution_time_ms": (time.time() - start_time) * 1000,
            "node_results": serialized_results,
            "highlight": build_highlight_payload(serialized_results, nodes, inputs),
            "sub_workflow_executions": _serialize_sub_workflow_executions(
                wf_executor.sub_workflow_executions
            ),
        }
        return

    output_nodes = wf_executor.get_output_nodes()
    final_outputs = {}
    for node_id in output_nodes:
        if node_id in wf_executor.node_outputs and node_id not in wf_executor.skipped_nodes:
            node = wf_executor.nodes.get(node_id, {})
            if node.get("type") == "sticky":
                continue
            node_label = wf_executor.get_node_label(node_id)
            final_outputs[node_label] = wf_executor.node_outputs[node_id]

    final_outputs = unwrap_single_json_output_terminal_outputs(wf_executor, final_outputs)

    serialized_results = _serialized_graph_plus_delegated_node_results(node_results, wf_executor)
    yield {
        "type": "execution_complete",
        "workflow_id": str(workflow_id),
        "status": "success",
        "outputs": _to_json_compatible(final_outputs),
        "execution_time_ms": (time.time() - start_time) * 1000,
        "node_results": serialized_results,
        "highlight": build_highlight_payload(serialized_results, nodes, inputs),
        "sub_workflow_executions": _serialize_sub_workflow_executions(
            wf_executor.sub_workflow_executions
        ),
    }
