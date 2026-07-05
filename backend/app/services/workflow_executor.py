import ast
import asyncio
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
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from threading import Event, Lock, Thread, local
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from simpleeval import DEFAULT_FUNCTIONS, EvalWithCompoundTypes, SimpleEval

from app.api.data_tables import (
    _coerce_row_data,  # noqa: F401 - public patch alias for node handlers
)
from app.http_identity import HEYM_USER_AGENT
from app.observability import tracing
from app.services.chart_payload import (
    build_chart_payload,  # noqa: F401 - public patch alias for node handlers
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
from app.services.highlight.highlight_builder import build_highlight_payload
from app.services.llm_trace import LLMTraceContext
from app.services.node_execution import NodeExecutionContext, execute_node_handler
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

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")
_EXECUTION_CONTEXT_INPUT_KEY = "__heym_execution_context"


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


class NodeTraceableExecutionError(ValueError):
    """Raised when a node error has a trace entry that should stay linked."""

    def __init__(self, message: str, trace_id: str) -> None:
        super().__init__(message)
        self.trace_id = trace_id


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

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
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

_HTTP_CLIENT_LOCK = Lock()


def _build_playwright_script(
    user_code: str,
    inputs: dict,
    headless: bool = True,
    timeout_ms: int = 30000,
    capture_network: bool = False,
    heym_api_url: str = "",
    heym_execution_token: str = "",
) -> str:
    """Wrap user Playwright code with imports and inputs."""
    inputs_json = json.dumps(inputs)
    headless_py = repr(headless)  # True/False for Python, not json true/false
    capture_network_py = repr(capture_network)
    api_url_py = repr(heym_api_url)
    token_py = repr(heym_execution_token)
    return f"""import json
import sys

inputs = {inputs_json}
headless = {headless_py}
timeout_ms = {timeout_ms}
capture_network = {capture_network_py}
_heym_api_url = {api_url_py}
_heym_execution_token = {token_py}

try:
{_indent(user_code, 4)}
except Exception as e:
    print(json.dumps({{"status": "error", "error": str(e)}}), file=sys.stderr)
    sys.exit(1)
"""


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


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
    return SimpleEval.parse(expr)


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
            path = expr[5:].split(".")
            value = item
            for part in path:
                if value is None:
                    return None
                if isinstance(value, dict):
                    value = value.get(part)
                elif hasattr(value, part):
                    value = getattr(value, part)
                else:
                    return None
            return value
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
            path = expr[5:].split(".")
            value = item
            for part in path:
                if isinstance(value, dict):
                    value = value.get(part)
                elif hasattr(value, part):
                    value = getattr(value, part)
                else:
                    return None
            return value

        try:
            wrapped_item = _wrap_value(item)

            def resolve_item_ref(arg):
                if not isinstance(arg, str):
                    return arg
                arg_str = arg.strip()
                if _ITEM_DOT_PATH_RE.fullmatch(arg_str):
                    path = arg_str[5:].split(".")
                    value = wrapped_item
                    for part in path:
                        if isinstance(value, dict):
                            value = value.get(part)
                        elif hasattr(value, part):
                            value = getattr(value, part)
                        else:
                            return None
                    return value
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
                    return obj.get(key, default)
                return getattr(obj, key, default) if hasattr(obj, key) else default

            evaluator = HeymExpressionEval(
                names={
                    "item": wrapped_item,
                    "true": True,
                    "false": False,
                    "null": None,
                },
                functions={
                    **DEFAULT_FUNCTIONS,
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
                },
            )
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
            and not _is_valid_expression_syntax(expr)
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

    def urlEncode(self) -> "DotStr":  # noqa: N802
        return DotStr(quote(self, safe=""))

    def url_encode(self) -> "DotStr":
        return self.urlEncode()

    def urlDecode(self) -> "DotStr":  # noqa: N802
        return DotStr(unquote(self))

    def url_decode(self) -> "DotStr":
        return self.urlDecode()


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
    """Convert expression wrapper types back to plain JSON-safe containers."""
    if isinstance(value, DotDict):
        return {key: _to_json_compatible(item) for key, item in dict.items(value)}
    if isinstance(value, dict):
        return {key: _to_json_compatible(item) for key, item in value.items()}
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
        return str(value)
    if isinstance(value, DotDateTime):
        return value.toISO()
    return value


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
    # (future, done_event, wf_id, wf_name, inputs_snapshot) tuples for executeDoNotWait nodes.
    # Not serialized / not written to DB directly; drained by the API layer.
    _bg_pending: list = field(default_factory=list)
    _allow_downstream_pending: list[Future] = field(default_factory=list)
    _allow_downstream_node_results: list[NodeResult] = field(default_factory=list)
    _started_at: float = 0.0

    @property
    def allow_downstream_pending(self) -> bool:
        return bool(self._allow_downstream_pending)

    def join_allow_downstream(self) -> None:
        """Wait for output allowDownstream background work to populate final results."""
        pending = list(self._allow_downstream_pending)
        self._allow_downstream_pending.clear()
        for fut in pending:
            fut.result()
        existing_ids = {item.get("node_id") for item in self.node_results if isinstance(item, dict)}
        for result in self._allow_downstream_node_results:
            if result.node_id not in existing_ids:
                self.node_results.append(_serialize_node_result(result))
                existing_ids.add(result.node_id)
        if self._started_at:
            self.execution_time_ms = (time.time() - self._started_at) * 1000


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
) -> list[dict]:
    return [
        {
            "workflow_id": execution.workflow_id,
            "inputs": _to_json_compatible(execution.inputs),
            "outputs": _to_json_compatible(execution.outputs),
            "status": execution.status,
            "execution_time_ms": execution.execution_time_ms,
            "node_results": _to_json_compatible(execution.node_results),
            "workflow_name": execution.workflow_name,
            "trigger_source": execution.trigger_source,
        }
        for execution in executions
    ]


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
            )
        )
    return restored


def _detect_pandoc_format(mime_type: str, filename: str) -> str | None:
    """Return pandoc input format string for the given MIME type / filename, or None if unsupported."""
    _mime_map: dict[str, str] = {
        "text/markdown": "markdown",
        "text/html": "html",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "markdown",
        "text/csv": "csv",
    }
    if mime_type in _mime_map:
        return _mime_map[mime_type]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    _ext_map: dict[str, str] = {
        "md": "markdown",
        "markdown": "markdown",
        "html": "html",
        "htm": "html",
        "docx": "docx",
        "txt": "markdown",
        "csv": "csv",
    }
    return _ext_map.get(ext)


def _extract_pdf_text(src_bytes: bytes) -> str:
    """Extract plain text from a PDF via pypdf."""
    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(src_bytes))
    parts = [page.extract_text() for page in reader.pages if page.extract_text()]
    return "\n\n".join(parts)


def _convert_image(src_bytes: bytes, target_format: str) -> tuple[bytes, str]:
    """Convert image bytes to target_format. Returns (output_bytes, output_mime_type)."""
    import io

    from PIL import Image

    _fmt_map: dict[str, tuple[str, str]] = {
        "jpg": ("JPEG", "image/jpeg"),
        "jpeg": ("JPEG", "image/jpeg"),
        "png": ("PNG", "image/png"),
        "bmp": ("BMP", "image/bmp"),
        "webp": ("WEBP", "image/webp"),
    }
    if target_format not in _fmt_map:
        raise ValueError(f"Drive Node: unsupported image output format '{target_format}'")
    pil_format, mime_type = _fmt_map[target_format]
    img = Image.open(io.BytesIO(src_bytes))
    if pil_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format=pil_format)
    return buf.getvalue(), mime_type


class WorkflowExecutor:
    def __init__(
        self,
        nodes: list[dict],
        edges: list[dict],
        workflow_cache: dict[str, dict] | None = None,
        test_mode: bool = False,
        credentials_context: dict[str, str] | None = None,
        global_variables_context: dict[str, object] | None = None,
        workflow_id: uuid.UUID | None = None,
        trace_user_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        agent_progress_queue: queue.Queue | None = None,
        sub_workflow_invocation_depth: int = 0,
        cancel_event: Event | None = None,
        configured_timezone: tzinfo | None = None,
        invoked_by_agent: bool = False,
        public_base_url: str = "",
        return_on_chart_output: bool = False,
        timeout_seconds: float | None = None,
        workflow_name: str = "",
        workflow_description: str = "",
        execution_id: str = "",
    ) -> None:
        self.nodes = {node["id"]: node for node in nodes}
        self.agent_progress_queue = agent_progress_queue
        self.edges = edges
        self.node_outputs: dict[str, dict] = {}
        self.node_execution_contexts: dict[str, dict[str, object]] = {}
        self.skipped_nodes: set[str] = set()
        self.inactive_nodes: set[str] = set()
        self.label_to_output: dict[str, dict] = {}
        self._wrapped_label_output_cache: dict[str, object] = {}
        self._incoming_edge_sources: dict[str, list[str]] = {}
        self._upstream_node_ids_cache: dict[str, set[str]] = {}
        self._upstream_node_labels_cache: dict[str, set[str]] = {}
        self.lock = Lock()
        self.workflow_cache = workflow_cache or {}
        self.sub_workflow_executions: list[SubWorkflowExecution] = []
        self.test_mode = test_mode
        self.credentials_context = credentials_context or {}
        self.global_variables_context = global_variables_context or {}
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.workflow_description = workflow_description
        self.execution_id = execution_id
        self.trace_user_id = trace_user_id
        self.actor_user_id = actor_user_id
        self.conversation_history = conversation_history
        self._sub_workflow_invocation_depth = sub_workflow_invocation_depth
        # True when this executor is running a workflow that was invoked (directly or
        # transitively) by an agent's ``call_sub_workflow`` tool. Used to propagate the
        # "AI Agents" trigger_source tag down to Execute Workflow nodes inside the chain.
        self._invoked_by_agent = invoked_by_agent
        self._base_url = public_base_url
        self.return_on_chart_output = return_on_chart_output
        self.cancel_event = cancel_event
        # Cooperative timeout: a monotonic deadline checked at every node boundary
        # via ``check_cancelled``. ``None`` (or non-positive timeout) disables it.
        self.timeout_seconds = timeout_seconds
        self._deadline: float | None = None
        self.hitl_resume_context: dict[str, dict] = {}
        self.error_handler_nodes = {
            node_id for node_id, node in self.nodes.items() if node.get("type") == "errorHandler"
        }
        self.loop_states: dict[str, dict] = {}
        self.vars: dict[str, object] = {}
        self._wrapped_vars_cache: DotDict | None = None
        self._wrapped_global_cache: DotDict | None = None
        self._merged_global_context_cache: dict[str, object] | None = None
        self._vars_context_dirty = True
        self._sub_agent_call_depth = 0
        self.delegated_agent_node_results: list[NodeResult] = []
        self.notification_branch_node_results: list[NodeResult] = []
        self.retry_node_results: list[NodeResult] = []
        self._node_result_sequence = 0
        self._node_result_sequence_lock = Lock()
        self._bg_futures: list = []
        self._bg_futures_lock = Lock()
        self.configured_timezone = configured_timezone or get_configured_timezone()
        # Active OTel context (with the workflow root span) captured during execute();
        # re-attached inside worker threads so node spans nest under the workflow span.
        self._otel_root_context: object | None = None

        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
            if isinstance(source, str) and isinstance(target, str):
                self._incoming_edge_sources.setdefault(target, []).append(source)

        for node_id, node in self.nodes.items():
            if node.get("data", {}).get("active") is False:
                self.inactive_nodes.add(node_id)
                self.skipped_nodes.add(node_id)

        sub_agent_labels: set[str] = set()
        for node in self.nodes.values():
            if node.get("type") == "agent":
                data = node.get("data", {}) or {}
                if data.get("isOrchestrator") and data.get("subAgentLabels"):
                    sub_agent_labels.update(data.get("subAgentLabels") or [])
        for node_id, node in self.nodes.items():
            if node.get("type") == "agent":
                label = node.get("data", {}).get("label", "")
                if label in sub_agent_labels:
                    self.skipped_nodes.add(node_id)

        for node_id, node in self.nodes.items():
            if node.get("type") == "output":
                has_input = any(edge["target"] == node_id for edge in self.edges)
                if not has_input:
                    self.skipped_nodes.add(node_id)

    def _get_accessible_credential(self, db, credential_id: object):
        from app.db.models import Credential, CredentialShare, CredentialTeamShare, TeamMember

        actor_user_id = self._require_actor_user_id("Credential")

        credential = (
            db.query(Credential)
            .filter(
                Credential.id == credential_id,
                Credential.owner_id == actor_user_id,
            )
            .first()
        )
        if credential is not None:
            return credential

        credential = (
            db.query(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .filter(
                Credential.id == credential_id,
                CredentialShare.user_id == actor_user_id,
            )
            .first()
        )
        if credential is not None:
            return credential

        return (
            db.query(Credential)
            .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
            .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
            .filter(
                Credential.id == credential_id,
                TeamMember.user_id == actor_user_id,
            )
            .first()
        )

    def _run_clickhouse_node(self, node_data: dict, inputs: dict, node_id: str) -> dict:
        import json as _json

        from app.db.session import SessionLocal
        from app.services.clickhouse_service import ClickHouseService
        from app.services.encryption import decrypt_config

        credential_id = node_data.get("credentialId")
        if not credential_id:
            raise ValueError("ClickHouse node requires a credential")

        ch_config: dict = {}
        with SessionLocal() as db:
            cred = self._get_accessible_credential(db, credential_id)
            if cred:
                ch_config = decrypt_config(cred.encrypted_config)
        if not ch_config:
            raise ValueError("ClickHouse credential not found or invalid")

        operation = str(node_data.get("clickhouseOperation", "") or "").strip()
        if not operation:
            raise ValueError("ClickHouse node requires an operation")

        service = ClickHouseService(ch_config)

        def _resolve(field: str, default: str = "") -> str:
            return self.evaluate_message_template(
                str(node_data.get(field, default) or default), inputs, node_id
            ).strip()

        def _resolve_filters() -> dict:
            raw = self.evaluate_message_template(
                str(node_data.get("clickhouseFilter", "{}") or "{}"), inputs, node_id
            )
            parsed = _json.loads(raw or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("clickhouseFilter must be a JSON object")
            return parsed

        def _resolve_limit(default: int = 100) -> int:
            raw = _resolve("clickhouseLimit", str(default))
            try:
                return int(float(raw or default))
            except (TypeError, ValueError):
                return default

        def _resolve_rows() -> list:
            input_mode = str(node_data.get("clickhouseInputMode", "raw") or "raw").strip()
            if input_mode == "selective":
                mappings = node_data.get("clickhouseMappings", []) or []
                row: dict = {}
                for mapping in mappings:
                    key = str(mapping.get("key", "") or "")
                    if not key:
                        continue
                    row[key] = self.evaluate_message_template(
                        str(mapping.get("value", "")), inputs, node_id
                    )
                return [row]
            raw = self.evaluate_message_template(
                str(node_data.get("clickhouseData", "[]") or "[]"), inputs, node_id
            )
            parsed = _json.loads(raw or "[]")
            if isinstance(parsed, dict):
                return [parsed]
            if not isinstance(parsed, list):
                raise ValueError("clickhouseData must be a JSON array or object")
            return parsed

        if operation == "query":
            sql = self.evaluate_message_template(
                str(node_data.get("clickhouseQuery", "") or ""), inputs, node_id
            ).strip()
            return service.query(sql)
        if operation == "find":
            return service.find(
                _resolve("clickhouseTable"),
                filters=_resolve_filters(),
                limit=_resolve_limit(),
                sort=_resolve("clickhouseSort"),
            )
        if operation == "getAll":
            return service.get_all(_resolve("clickhouseTable"), limit=_resolve_limit())
        if operation == "count":
            return service.count(_resolve("clickhouseTable"), filters=_resolve_filters())
        if operation == "getById":
            return service.get_by_id(_resolve("clickhouseTable"), _resolve("clickhouseRowId"))
        if operation == "insert":
            return service.insert(_resolve("clickhouseTable"), _resolve_rows())
        if operation == "upsert":
            return service.upsert(_resolve("clickhouseTable"), _resolve_rows())
        if operation == "update":
            raw_data = self.evaluate_message_template(
                str(node_data.get("clickhouseData", "{}") or "{}"), inputs, node_id
            )
            data = _json.loads(raw_data or "{}")
            if not isinstance(data, dict):
                raise ValueError("clickhouseData must be a JSON object for update")
            return service.update(
                _resolve("clickhouseTable"), data=data, filters=_resolve_filters()
            )
        if operation == "remove":
            return service.remove(_resolve("clickhouseTable"), filters=_resolve_filters())
        raise ValueError(f"Unknown ClickHouse operation: {operation}")

    def _get_vector_store_backing_credential(self, db, credential_id: object):
        from app.db.models import Credential

        return db.query(Credential).filter(Credential.id == credential_id).first()

    def _get_accessible_vector_store(self, db, vector_store_id: object):
        from app.db.models import (
            TeamMember,
            VectorStore,
            VectorStoreShare,
            VectorStoreTeamShare,
        )

        actor_user_id = self._require_actor_user_id("Vector store")

        store = (
            db.query(VectorStore)
            .filter(
                VectorStore.id == vector_store_id,
                VectorStore.owner_id == actor_user_id,
            )
            .first()
        )
        if store is not None:
            return store

        store = (
            db.query(VectorStore)
            .join(VectorStoreShare, VectorStoreShare.vector_store_id == VectorStore.id)
            .filter(
                VectorStore.id == vector_store_id,
                VectorStoreShare.user_id == actor_user_id,
            )
            .first()
        )
        if store is not None:
            return store

        return (
            db.query(VectorStore)
            .join(VectorStoreTeamShare, VectorStoreTeamShare.vector_store_id == VectorStore.id)
            .join(TeamMember, TeamMember.team_id == VectorStoreTeamShare.team_id)
            .filter(
                VectorStore.id == vector_store_id,
                TeamMember.user_id == actor_user_id,
            )
            .first()
        )

    def _get_accessible_data_table(self, db, data_table_id: object, operation: str):
        from app.db.models import DataTable, DataTableShare, DataTableTeamShare, TeamMember

        write_required = operation not in ("find", "getAll", "getById", "count")
        actor_user_id = self._require_actor_user_id("DataTable")

        table = (
            db.query(DataTable)
            .filter(
                DataTable.id == data_table_id,
                DataTable.owner_id == actor_user_id,
            )
            .first()
        )
        if table is not None:
            return table

        has_read_share = False
        user_shares = (
            db.query(DataTable, DataTableShare.permission)
            .join(DataTableShare, DataTableShare.table_id == DataTable.id)
            .filter(
                DataTable.id == data_table_id,
                DataTableShare.user_id == actor_user_id,
            )
            .all()
        )
        for table, permission in user_shares:
            has_read_share = True
            if not write_required or permission == "write":
                return table

        team_shares = (
            db.query(DataTable, DataTableTeamShare.permission)
            .join(DataTableTeamShare, DataTableTeamShare.table_id == DataTable.id)
            .join(TeamMember, TeamMember.team_id == DataTableTeamShare.team_id)
            .filter(
                DataTable.id == data_table_id,
                TeamMember.user_id == actor_user_id,
            )
            .all()
        )
        for table, permission in team_shares:
            has_read_share = True
            if not write_required or permission == "write":
                return table

        if has_read_share and write_required:
            raise ValueError("Write access required for this operation")
        return None

    def _require_actor_user_id(self, resource_label: str) -> uuid.UUID:
        if self.actor_user_id is None:
            raise ValueError(
                f"{resource_label} lookup requires actor_user_id; refusing unrestricted lookup."
            )
        return self.actor_user_id

    def get_node_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        if node:
            return node.get("data", {}).get("label", node_id)
        return node_id

    def _stamp_node_result(self, result: NodeResult) -> NodeResult:
        if _node_result_sequence_value(result) is not None:
            return result
        finished_ms = time.time() * 1000
        duration_ms = max(float(result.execution_time_ms or 0), 0.0)
        with self._node_result_sequence_lock:
            self._node_result_sequence += 1
            sequence = self._node_result_sequence
        metadata = dict(result.metadata or {})
        metadata["sequence"] = sequence
        metadata.setdefault("ended_at_ms", finished_ms)
        metadata.setdefault("started_at_ms", max(finished_ms - duration_ms, 0.0))
        result.metadata = metadata
        return result

    def _attach_gc_pause_metadata(
        self,
        result: NodeResult,
        tracker: _NodeGcPauseTracker,
    ) -> NodeResult:
        """Persist measured GC pauses onto node metadata for timeline/debug consumers."""
        if not tracker.pauses:
            return result

        metadata = dict(result.metadata or {})
        metadata["gc_pause_ms"] = round(tracker.total_pause_ms(), 3)
        metadata["gc_pause_count"] = len(tracker.pauses)
        metadata["gc_pause_intervals"] = [
            {
                "start_ms": round(start_ms, 3),
                "duration_ms": round(duration_ms, 3),
                "generation": generation,
            }
            for start_ms, duration_ms, generation in tracker.pauses
        ]
        result.metadata = metadata
        return result

    def _record_retry_attempt_result(
        self,
        *,
        node_id: str,
        node_label: str,
        node_type: str,
        error: Exception,
        attempt: int,
        max_attempts: int,
        retry_wait_seconds: int | float,
        execution_time_ms: float,
    ) -> NodeResult:
        message = f"Attempt {attempt}/{max_attempts} failed. Retrying in {retry_wait_seconds}s."
        retry_result = self._stamp_node_result(
            NodeResult(
                node_id=node_id,
                node_label=node_label,
                node_type=node_type,
                status="error",
                output={
                    "error": str(error),
                    "message": message,
                    "retry_attempt": attempt,
                    "retry_max_attempts": max_attempts,
                    "retry_wait_seconds": retry_wait_seconds,
                },
                execution_time_ms=execution_time_ms,
                error=str(error),
                metadata={
                    "retry_stage": "attempt_failed",
                    "retry_attempt": attempt,
                    "retry_max_attempts": max_attempts,
                    "retry_wait_seconds": retry_wait_seconds,
                },
            )
        )
        with self.lock:
            self.retry_node_results.append(retry_result)
        return retry_result

    def _arm_deadline(self) -> None:
        """Start the timeout clock. Call once at the beginning of a run."""
        if self.timeout_seconds and self.timeout_seconds > 0:
            self._deadline = time.monotonic() + self.timeout_seconds

    def check_cancelled(self) -> None:
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise WorkflowTimeoutError(
                f"Workflow timed out after {int(self.timeout_seconds or 0)} seconds"
            )
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise WorkflowCancelledError("Workflow execution cancelled")

    def _terminate_subprocess(self, process: Any) -> None:
        if process.poll() is not None:
            return

        import subprocess

        try:
            if os.name == "nt":
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                return

            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        except ProcessLookupError:
            return

    def _get_workflow_name_for_log(self) -> str:
        if not self.workflow_id:
            return "?"
        if hasattr(self, "_workflow_name_for_log"):
            return self._workflow_name_for_log
        try:
            from app.db.models import Workflow
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                w = db.query(Workflow).filter(Workflow.id == self.workflow_id).first()
                self._workflow_name_for_log = w.name if w else str(self.workflow_id)
        except Exception:
            self._workflow_name_for_log = str(self.workflow_id)
        return self._workflow_name_for_log

    def _get_workflow_metadata(self) -> tuple[str, str]:
        """Return (name, description). Prefer explicitly supplied values; otherwise
        lazily fetch once from the DB by workflow_id (mirrors
        ``_get_workflow_name_for_log``)."""
        if self.workflow_name or self.workflow_description:
            return self.workflow_name, self.workflow_description
        if not self.workflow_id:
            return "", ""
        if hasattr(self, "_workflow_metadata_cache"):
            return self._workflow_metadata_cache
        name, description = "", ""
        try:
            from app.db.models import Workflow
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                w = db.query(Workflow).filter(Workflow.id == self.workflow_id).first()
                if w is not None:
                    name = w.name or ""
                    description = w.description or ""
        except Exception:
            pass
        self._workflow_metadata_cache = (name, description)
        return self._workflow_metadata_cache

    def _build_workflow_url(self, workflow_path: str) -> str:
        if not workflow_path:
            return ""
        base = (self._base_url or "").rstrip("/")
        if not base:
            from app.config import settings

            base = (settings.frontend_url or "").rstrip("/")
        if not base:
            return ""
        return f"{base}{workflow_path}"

    def _build_llm_trace_context(
        self, credential_id: str | None, node_id: str | None
    ) -> LLMTraceContext | None:
        if not credential_id or not self.trace_user_id:
            return None
        try:
            credential_uuid = uuid.UUID(credential_id)
        except ValueError:
            return None
        node_label = self.get_node_label(node_id) if node_id else None
        return LLMTraceContext(
            user_id=self.trace_user_id,
            credential_id=credential_uuid,
            workflow_id=self.workflow_id,
            node_id=node_id,
            node_label=node_label,
            source="workflow",
        )

    @staticmethod
    def _latest_trace_id(trace_context: LLMTraceContext | None) -> str | None:
        if trace_context is None or not trace_context.trace_ids:
            return None
        return str(trace_context.trace_ids[-1])

    @classmethod
    def _attach_latest_trace_id(
        cls, output: dict[str, Any], trace_context: LLMTraceContext | None
    ) -> None:
        trace_id = cls._latest_trace_id(trace_context)
        if trace_id:
            output["_trace_id"] = trace_id

    @staticmethod
    def _pop_internal_trace_id(output: dict[str, Any]) -> str | None:
        trace_id = output.pop("_trace_id", None)
        return trace_id if isinstance(trace_id, str) and trace_id else None

    @staticmethod
    def _restore_internal_trace_id(output: dict[str, Any], trace_id: str | None) -> None:
        if trace_id:
            output["_trace_id"] = trace_id

    def get_input_nodes(self) -> list[str]:
        error_flow_nodes = self.get_error_flow_nodes()
        target_ids = {edge["target"] for edge in self.get_active_edges()}
        return [
            node_id
            for node_id in self.nodes
            if node_id not in target_ids and node_id not in error_flow_nodes
        ]

    def get_output_nodes(self) -> list[str]:
        error_flow_nodes = self.get_error_flow_nodes()
        source_ids = {edge["source"] for edge in self.get_active_edges()}
        output_nodes = [
            node_id
            for node_id, node in self.nodes.items()
            if node.get("type") in ("output", "jsonOutputMapper")
            and node_id not in self.error_handler_nodes
            and node_id not in error_flow_nodes
        ]
        leaf_nodes = [
            node_id
            for node_id in self.nodes
            if node_id not in source_ids
            and node_id not in self.error_handler_nodes
            and node_id not in error_flow_nodes
        ]
        return list({*output_nodes, *leaf_nodes})

    def get_active_edges(self) -> list[dict]:
        edges = []
        for edge in self.edges:
            source_node = self.nodes.get(edge["source"])
            target_node = self.nodes.get(edge["target"])
            if not source_node or not target_node:
                continue
            if (
                edge["source"] in self.error_handler_nodes
                or edge["target"] in self.error_handler_nodes
            ):
                continue
            if source_node.get("type") == "jsonOutputMapper":
                continue
            if source_node.get("type") == "output":
                allow_downstream = source_node.get("data", {}).get("allowDownstream")
                if not allow_downstream:
                    continue
            edges.append(edge)
        return edges

    def get_error_flow_nodes(self) -> set[str]:
        if not self.error_handler_nodes:
            return set()
        visited: set[str] = set(self.error_handler_nodes)
        queue = list(self.error_handler_nodes)

        while queue:
            current = queue.pop(0)
            for edge in self.edges:
                if edge["source"] == current:
                    target = edge["target"]
                    if target not in visited:
                        visited.add(target)
                        queue.append(target)
        return visited

    def get_node_inputs_for_edges(self, node_id: str, edges: list[dict]) -> dict:
        inputs = {}
        execution_context: dict[str, object] = {}
        for edge in edges:
            if edge["target"] == node_id:
                source_id = edge["source"]
                if source_id in self.node_outputs and source_id not in self.skipped_nodes:
                    source_label = self.get_node_label(source_id)
                    source_output = self.node_outputs[source_id]
                    execution_context.update(self.node_execution_contexts.get(source_id, {}))
                    execution_context[source_label] = source_output
                    inputs[source_label] = source_output
        if execution_context:
            inputs[_EXECUTION_CONTEXT_INPUT_KEY] = execution_context
        return inputs

    def get_node_inputs(self, node_id: str) -> dict:
        inputs = {}
        execution_context: dict[str, object] = {}
        for edge in self.edges:
            if edge["target"] == node_id:
                source_id = edge["source"]
                if source_id in self.node_outputs and source_id not in self.skipped_nodes:
                    source_label = self.get_node_label(source_id)
                    source_output = self.node_outputs[source_id]
                    execution_context.update(self.node_execution_contexts.get(source_id, {}))
                    execution_context[source_label] = source_output
                    inputs[source_label] = source_output
        if execution_context:
            inputs[_EXECUTION_CONTEXT_INPUT_KEY] = execution_context
        return inputs

    def _edge_matches_source_handle(self, edge: dict, handle_id: str | None) -> bool:
        if handle_id is None:
            return True

        source_handle = edge.get("sourceHandle")
        if source_handle == handle_id:
            return True

        source_node = self.nodes.get(edge.get("source"), {})
        if handle_id == "true" and source_node.get("type") == "condition" and not source_handle:
            return True

        return False

    def _source_handle_is_skipped(self, edge: dict, skipped_handles: set[str]) -> bool:
        """Return whether an edge's source handle is suppressed by node metadata."""
        for handle_id in skipped_handles:
            if self._edge_matches_source_handle(edge, handle_id):
                return True
        return False

    def _loop_back_targets_for_source_handle(self, node_id: str, handle_id: str) -> set[str]:
        """Return loop nodes reached directly by a specific branch handle."""
        targets: set[str] = set()
        for edge in self.edges:
            if edge.get("source") != node_id:
                continue
            target = edge.get("target")
            target_node = self.nodes.get(target, {})
            if (
                edge.get("targetHandle") == "loop"
                and target_node.get("type") == "loop"
                and self._edge_matches_source_handle(edge, handle_id)
            ):
                targets.add(target)
        return targets

    def get_downstream_nodes(self, node_id: str, handle_id: str | None = None) -> list[str]:
        downstream = []
        for edge in self.edges:
            if edge["source"] == node_id:
                if self._edge_matches_source_handle(edge, handle_id):
                    downstream.append(edge["target"])
        return downstream

    def get_branch_node_ids(
        self,
        start_node_id: str,
        edges: list[dict],
        *,
        exclude_node_ids: set[str] | None = None,
    ) -> set[str]:
        """Return the start node plus all downstream nodes reachable through the given edges."""
        excluded = exclude_node_ids or set()
        visited: set[str] = set()
        queue = [start_node_id]

        while queue:
            current = queue.pop(0)
            if current in visited or current in excluded:
                continue
            visited.add(current)

            for edge in edges:
                if edge["source"] != current:
                    continue
                target = edge["target"]
                if target not in visited and target not in excluded:
                    queue.append(target)

        return visited

    def get_incoming_edge_count_for_execution(self, node_id: str, edges: list[dict]) -> int:
        """Return the pending dependency count for a node under the active execution graph."""
        node = self.nodes.get(node_id, {})
        if node.get("type") == "loop":
            return sum(
                1
                for edge in edges
                if edge["target"] == node_id and edge.get("targetHandle") != "loop"
            )
        return sum(1 for edge in edges if edge["target"] == node_id)

    def get_upstream_node_ids(self, node_id: str) -> set[str]:
        cached = self._upstream_node_ids_cache.get(node_id)
        if cached is not None:
            return cached

        upstream: set[str] = set()
        visited: set[str] = set()
        pending: deque[str] = deque([node_id])

        while pending:
            current = pending.popleft()
            if current in visited:
                continue
            visited.add(current)

            for source_id in self._incoming_edge_sources.get(current, []):
                if source_id in visited:
                    continue
                upstream.add(source_id)
                pending.append(source_id)

        self._upstream_node_ids_cache[node_id] = upstream
        return upstream

    def get_upstream_node_labels(self, node_id: str) -> set[str]:
        cached = self._upstream_node_labels_cache.get(node_id)
        if cached is not None:
            return cached

        upstream_ids = self.get_upstream_node_ids(node_id)
        upstream_labels = {self.get_node_label(nid) for nid in upstream_ids}
        self._upstream_node_labels_cache[node_id] = upstream_labels
        return upstream_labels

    def get_reachable_node_ids(
        self,
        start_node_ids: list[str],
        *,
        exclude_node_ids: set[str] | None = None,
    ) -> set[str]:
        """Return all nodes reachable from any start node, optionally stopping at excluded nodes."""
        excluded = exclude_node_ids or set()
        reachable: set[str] = set()
        queue = list(start_node_ids)

        while queue:
            current = queue.pop(0)
            if current in reachable or current in excluded:
                continue
            reachable.add(current)

            for edge in self.edges:
                if edge["source"] != current:
                    continue
                target = edge["target"]
                if target not in reachable and target not in excluded:
                    queue.append(target)

        return reachable

    def mark_branch_as_skipped(
        self,
        node_id: str,
        *,
        preserve_node_ids: set[str] | None = None,
        stop_node_ids: set[str] | None = None,
    ) -> None:
        preserved = preserve_node_ids or set()
        stopped = stop_node_ids or set()
        if node_id in preserved or node_id in stopped:
            return
        self.skipped_nodes.add(node_id)
        for edge in self.edges:
            if edge["source"] == node_id:
                target = edge["target"]
                if target in preserved or target in stopped:
                    continue
                self.mark_branch_as_skipped(
                    target,
                    preserve_node_ids=preserved,
                    stop_node_ids=stopped,
                )

    def skip_branch_targets_preserving_shared_downstream(
        self,
        node_id: str,
        *,
        active_targets: list[str],
        inactive_targets: list[str],
        active_exclude_node_ids: set[str] | None = None,
        inactive_stop_node_ids: set[str] | None = None,
    ) -> None:
        """Skip only nodes exclusive to inactive targets; keep shared downstream merge nodes active."""
        preserved_node_ids = self.get_reachable_node_ids(
            active_targets,
            exclude_node_ids=active_exclude_node_ids,
        )
        for target in inactive_targets:
            self.mark_branch_as_skipped(
                target,
                preserve_node_ids=preserved_node_ids,
                stop_node_ids=inactive_stop_node_ids,
            )

    def get_loop_body_node_ids(self, loop_node_id: str, edges: list[dict]) -> set[str]:
        """Return nodes in a loop body, stopping before the loop-back edge reaches the loop node."""
        visited: set[str] = set()
        queue = [
            edge["target"]
            for edge in edges
            if edge["source"] == loop_node_id and edge.get("sourceHandle") == "loop"
        ]

        while queue:
            current = queue.pop(0)
            if current in visited or current == loop_node_id:
                continue
            visited.add(current)

            for edge in edges:
                if edge["source"] != current:
                    continue
                target = edge["target"]
                if target != loop_node_id and target not in visited:
                    queue.append(target)

        return visited

    def reset_nodes_for_execution(
        self,
        node_ids: set[str],
        active_edges: list[dict],
        completed_nodes: set[str],
        pending_count: dict[str, int],
    ) -> None:
        """Reactivate nodes that were skipped/completed in an earlier branch or loop iteration."""
        for branch_node in node_ids:
            completed_nodes.discard(branch_node)
            if branch_node not in self.inactive_nodes:
                self.skipped_nodes.discard(branch_node)
            pending_count[branch_node] = self.get_incoming_edge_count_for_execution(
                branch_node, active_edges
            )

    def prepare_branch_targets_for_execution(
        self,
        *,
        start_node_ids: list[str],
        active_edges: list[dict],
        completed_nodes: set[str],
        pending_count: dict[str, int],
    ) -> None:
        branch_nodes: set[str] = set()
        for start_node_id in start_node_ids:
            branch_nodes.update(self.get_branch_node_ids(start_node_id, active_edges))
        self.reset_nodes_for_execution(branch_nodes, active_edges, completed_nodes, pending_count)

    def prepare_loop_for_reexecution(
        self,
        *,
        loop_node_id: str,
        active_edges: list[dict],
        completed_nodes: set[str],
        pending_count: dict[str, int],
    ) -> bool:
        """Reset loop state so the loop node can emit the next item or the final done output."""
        loop_state = self.loop_states.get(loop_node_id)
        if not loop_state or loop_state["current_index"] >= loop_state["total"]:
            return False

        completed_nodes.discard(loop_node_id)
        self.skipped_nodes.discard(loop_node_id)
        self.reset_nodes_for_execution(
            self.get_loop_body_node_ids(loop_node_id, active_edges),
            active_edges,
            completed_nodes,
            pending_count,
        )
        return True

    def get_execution_order(self) -> list[str]:
        in_degree: dict[str, int] = {node_id: 0 for node_id in self.nodes}
        for edge in self.edges:
            if edge["target"] in in_degree:
                in_degree[edge["target"]] += 1

        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        order = []

        while queue:
            node_id = queue.pop(0)
            order.append(node_id)

            for edge in self.edges:
                if edge["source"] == node_id:
                    target = edge["target"]
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        return order

    def get_execution_levels(self) -> list[list[str]]:
        """Get nodes grouped by execution level for parallel execution."""
        in_degree: dict[str, int] = {node_id: 0 for node_id in self.nodes}
        for edge in self.edges:
            if edge["target"] in in_degree:
                in_degree[edge["target"]] += 1

        levels: list[list[str]] = []
        current_level = [node_id for node_id, degree in in_degree.items() if degree == 0]

        while current_level:
            levels.append(current_level)
            next_level = []

            for node_id in current_level:
                for edge in self.edges:
                    if edge["source"] == node_id:
                        target = edge["target"]
                        in_degree[target] -= 1
                        if in_degree[target] == 0:
                            next_level.append(target)

            current_level = next_level

        return levels

    def _snapshot_execution_context(
        self,
        inputs: dict | None,
        node_label: str,
        output: dict,
    ) -> dict[str, object]:
        """Build the label context downstream nodes should inherit from this output."""
        context: dict[str, object] = {}
        if isinstance(inputs, dict):
            inherited_context = inputs.get(_EXECUTION_CONTEXT_INPUT_KEY)
            if isinstance(inherited_context, dict):
                context.update(inherited_context)
            for label, value in inputs.items():
                if label == _EXECUTION_CONTEXT_INPUT_KEY:
                    continue
                context[label] = value
        context[node_label] = output
        return copy.deepcopy(context)

    def _visible_inputs(self, inputs: dict) -> dict:
        """Return user-facing node inputs without internal execution context."""
        return {key: value for key, value in inputs.items() if key != _EXECUTION_CONTEXT_INPUT_KEY}

    def _first_visible_input(self, inputs: dict) -> object:
        """Return the first user-facing input value, preserving legacy `$input` behavior."""
        visible_inputs = self._visible_inputs(inputs)
        return next(iter(visible_inputs.values()), {})

    def store_node_output(
        self,
        node_id: str,
        node_label: str,
        output: dict,
        inputs: dict | None = None,
    ) -> None:
        """Store node output in shared state (thread-safe)."""
        if inputs is None and node_id in self.node_execution_contexts:
            execution_context = copy.deepcopy(self.node_execution_contexts[node_id])
            execution_context[node_label] = copy.deepcopy(output)
        else:
            execution_context = self._snapshot_execution_context(inputs, node_label, output)
        with self.lock:
            self.node_outputs[node_id] = output
            self.node_execution_contexts[node_id] = execution_context
            self.label_to_output[node_label] = output
            self._wrapped_label_output_cache[node_label] = self._wrap_value(output)

    def _rebuild_wrapped_label_output_cache(self) -> None:
        """Rebuild wrapped node output cache from stored plain outputs."""
        self._wrapped_label_output_cache = {
            node_label: self._wrap_value(output)
            for node_label, output in self.label_to_output.items()
        }

    def build_resume_snapshot(
        self,
        *,
        initial_inputs: dict,
        node_results: list[NodeResult],
        pending_count: dict[str, int],
        completed_nodes: set[str],
        paused_node_id: str,
        paused_node_label: str,
    ) -> dict:
        return {
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "nodes": copy.deepcopy(list(self.nodes.values())),
            "edges": copy.deepcopy(self.edges),
            "workflow_cache": copy.deepcopy(self.workflow_cache),
            "initial_inputs": copy.deepcopy(initial_inputs),
            "conversation_history": copy.deepcopy(self.conversation_history),
            "node_results": _serialize_node_results(
                _order_node_results(
                    list(node_results)
                    + list(getattr(self, "retry_node_results", []))
                    + list(getattr(self, "delegated_agent_node_results", []))
                    + list(getattr(self, "notification_branch_node_results", []))
                )
            ),
            "node_outputs": copy.deepcopy(self.node_outputs),
            "node_execution_contexts": copy.deepcopy(self.node_execution_contexts),
            "label_to_output": copy.deepcopy(self.label_to_output),
            "skipped_nodes": sorted(self.skipped_nodes),
            "inactive_nodes": sorted(self.inactive_nodes),
            "loop_states": copy.deepcopy(self.loop_states),
            "vars": copy.deepcopy(self.vars),
            "sub_workflow_executions": _serialize_sub_workflow_executions(
                self.sub_workflow_executions
            ),
            "completed_nodes": sorted(completed_nodes),
            "pending_count": copy.deepcopy(pending_count),
            "paused_node_id": paused_node_id,
            "paused_node_label": paused_node_label,
            "sub_workflow_invocation_depth": self._sub_workflow_invocation_depth,
            "invoked_by_agent": self._invoked_by_agent,
            "test_mode": self.test_mode,
        }

    def build_notification_snapshot(self) -> dict[str, Any]:
        return {
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "nodes": copy.deepcopy(list(self.nodes.values())),
            "edges": copy.deepcopy(self.edges),
            "workflow_cache": copy.deepcopy(self.workflow_cache),
            "conversation_history": copy.deepcopy(self.conversation_history),
            "node_outputs": copy.deepcopy(self.node_outputs),
            "node_execution_contexts": copy.deepcopy(self.node_execution_contexts),
            "label_to_output": copy.deepcopy(self.label_to_output),
            "skipped_nodes": sorted(self.skipped_nodes),
            "inactive_nodes": sorted(self.inactive_nodes),
            "loop_states": copy.deepcopy(self.loop_states),
            "vars": copy.deepcopy(self.vars),
            "sub_workflow_executions": _serialize_sub_workflow_executions(
                self.sub_workflow_executions
            ),
            "sub_workflow_invocation_depth": self._sub_workflow_invocation_depth,
            "invoked_by_agent": self._invoked_by_agent,
            "test_mode": self.test_mode,
        }

    def drain_bg_futures(self) -> None:
        """Block until all executeDoNotWait background sub-workflows have finished.

        Each future appends to ``sub_workflow_executions`` via a done-callback when it
        completes; this method only waits so callers (e.g. streaming API) can safely
        serialize traces after the parent workflow returns.
        """
        with self._bg_futures_lock:
            pending = list(self._bg_futures)
            self._bg_futures.clear()
        for item in pending:
            if len(item) == 5:
                fut, done_event, _wf_id, _wf_name, _inputs_snapshot = item
            else:
                fut, _wf_id, _wf_name, _inputs_snapshot = item
                done_event = None
            try:
                fut.result()
            except Exception as exc:
                logger.warning(
                    "drain_bg_futures: background sub-workflow raised: %s",
                    exc,
                    exc_info=True,
                )
            finally:
                if done_event is not None:
                    done_event.wait()

    @staticmethod
    def _record_bg_sub_workflow_done(
        fut: Future,
        parent: "WorkflowExecutor",
        wf_id: str,
        wf_name: str,
        inputs_snapshot: dict,
    ) -> None:
        """Append SubWorkflowExecution when a fire-and-forget sub-workflow finishes."""
        bg_trigger_source = "AI Agents" if parent._invoked_by_agent else "SUB_WORKFLOW"
        try:
            sub_res: ExecutionResult = fut.result()
        except Exception:
            with parent.lock:
                parent.sub_workflow_executions.append(
                    SubWorkflowExecution(
                        workflow_id=wf_id,
                        inputs=inputs_snapshot,
                        outputs={},
                        status="error",
                        execution_time_ms=0.0,
                        node_results=[],
                        workflow_name=wf_name,
                        trigger_source=bg_trigger_source,
                    )
                )
            return
        if sub_res.allow_downstream_pending:
            sub_res.join_allow_downstream()
        sub_exec = SubWorkflowExecution(
            workflow_id=wf_id,
            inputs=inputs_snapshot,
            outputs=sub_res.outputs,
            status=sub_res.status,
            execution_time_ms=sub_res.execution_time_ms,
            node_results=sub_res.node_results,
            workflow_name=wf_name,
            trigger_source=bg_trigger_source,
        )
        with parent.lock:
            parent.sub_workflow_executions.append(sub_exec)
            parent.sub_workflow_executions.extend(sub_res.sub_workflow_executions)

    def _build_execution_result(
        self,
        *,
        workflow_id: uuid.UUID,
        status: str,
        outputs: dict,
        start_time: float,
        node_results: list[NodeResult],
        pending_review: dict | None = None,
        resume_snapshot: dict | None = None,
        allow_downstream_pending: list[Future] | None = None,
        allow_downstream_node_results: list[NodeResult] | None = None,
    ) -> ExecutionResult:
        combined = _order_node_results(
            list(node_results)
            + list(getattr(self, "retry_node_results", []))
            + list(getattr(self, "delegated_agent_node_results", []))
            + list(getattr(self, "notification_branch_node_results", []))
        )
        with self._bg_futures_lock:
            bg_pending = list(self._bg_futures)
        return ExecutionResult(
            workflow_id=workflow_id,
            status=status,
            outputs=_to_json_compatible(outputs),
            execution_time_ms=(time.time() - start_time) * 1000,
            node_results=_serialize_node_results(combined),
            sub_workflow_executions=self.sub_workflow_executions,
            pending_review=pending_review,
            resume_snapshot=resume_snapshot,
            _bg_pending=bg_pending,
            _allow_downstream_pending=list(allow_downstream_pending or []),
            _allow_downstream_node_results=(
                allow_downstream_node_results if allow_downstream_node_results is not None else []
            ),
            _started_at=start_time,
        )

    def execute_node_parallel(
        self,
        node_id: str,
        inputs: dict,
        on_retry: Callable[[NodeResult, int, int], None] | None = None,
    ) -> NodeResult:
        """Execute node and store output atomically for parallel execution."""
        _ensure_gc_tracking_callback_registered()
        gc_tracker = _NodeGcPauseTracker(node_started_ms=time.perf_counter() * 1000)
        _push_gc_tracker(gc_tracker)
        try:
            result = self.execute_node(node_id, inputs, on_retry=on_retry)
        finally:
            _pop_gc_tracker(gc_tracker)
        result = self._attach_gc_pause_metadata(result, gc_tracker)
        result = self._stamp_node_result(result)
        if result.status == "success":
            self.store_node_output(node_id, result.node_label, result.output, inputs)
            if result.output.get("_errorBranch"):
                self._handle_error_branch_routing(node_id)
            else:
                self._handle_success_branch_routing(node_id)
        return result

    def _handle_success_branch_routing(self, node_id: str) -> None:
        """Skip error-handle branches when the source node completed successfully."""
        active_edges = [
            edge for edge in self.get_active_edges() if edge.get("targetHandle") != "tool-input"
        ]
        success_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") != "error"
        ]
        error_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") == "error"
        ]
        if not error_targets:
            return

        preserved_node_ids: set[str] = set()
        for target in success_targets:
            preserved_node_ids.update(self.get_branch_node_ids(target, active_edges))

        exclusive_nodes = self.get_exclusive_branch_node_ids(
            root_node_id=node_id,
            start_node_ids=error_targets,
            edges=active_edges,
            preserve_node_ids=preserved_node_ids,
        )
        self.skipped_nodes.update(exclusive_nodes)

    def _handle_error_branch_routing(self, node_id: str) -> None:
        """Skip only non-error downstream nodes that depend exclusively on the failed node."""
        active_edges = [
            edge for edge in self.get_active_edges() if edge.get("targetHandle") != "tool-input"
        ]
        error_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") == "error"
        ]
        inactive_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") != "error"
        ]
        preserved_node_ids: set[str] = set()
        for target in error_targets:
            preserved_node_ids.update(self.get_branch_node_ids(target, active_edges))

        exclusive_nodes = self.get_exclusive_branch_node_ids(
            root_node_id=node_id,
            start_node_ids=inactive_targets,
            edges=active_edges,
            preserve_node_ids=preserved_node_ids,
        )
        self.skipped_nodes.update(exclusive_nodes)

    def get_exclusive_branch_node_ids(
        self,
        *,
        root_node_id: str,
        start_node_ids: list[str],
        edges: list[dict],
        preserve_node_ids: set[str] | None = None,
    ) -> set[str]:
        """Return downstream nodes whose execution depends only on the branch root.

        Shared downstream nodes, such as a common output reached by another parallel branch, must
        stay active so the other branch can still complete the workflow.
        """
        preserved = preserve_node_ids or set()
        branch_node_ids: set[str] = set()
        for start_node_id in start_node_ids:
            branch_node_ids.update(
                self.get_branch_node_ids(
                    start_node_id,
                    edges,
                    exclude_node_ids=preserved,
                )
            )

        exclusive_node_ids: set[str] = set()
        changed = True
        while changed:
            changed = False
            for candidate in branch_node_ids - exclusive_node_ids - preserved:
                incoming_edges = [
                    edge
                    for edge in edges
                    if edge["target"] == candidate
                    and not (
                        self.nodes.get(candidate, {}).get("type") == "loop"
                        and edge.get("targetHandle") == "loop"
                    )
                ]
                if not incoming_edges:
                    continue

                depends_only_on_root_or_exclusive_nodes = all(
                    edge["source"] == root_node_id or edge["source"] in exclusive_node_ids
                    for edge in incoming_edges
                )
                if depends_only_on_root_or_exclusive_nodes:
                    exclusive_node_ids.add(candidate)
                    changed = True

        return exclusive_node_ids

    def _record_notification_branch_results(self, results: list[NodeResult]) -> None:
        if not results:
            return
        self.notification_branch_node_results.extend(results)

    def _handle_llm_batch_status_update(
        self,
        *,
        node_id: str,
        node_label: str,
        payload: dict[str, Any],
    ) -> None:
        event_payload = copy.deepcopy(payload)
        if "batchStatus" not in event_payload:
            event_payload["batchStatus"] = event_payload.get("status")
        if self.agent_progress_queue is not None:
            self.agent_progress_queue.put(
                _build_llm_batch_progress_event(
                    node_id=node_id,
                    node_label=node_label,
                    entry=event_payload,
                )
            )

        has_status_branch = any(
            edge.get("source") == node_id and edge.get("sourceHandle") == "batchStatus"
            for edge in self.edges
        )
        if not has_status_branch:
            return

        snapshot = self.build_notification_snapshot()
        try:
            branch_result = execute_llm_batch_notification_branch(
                snapshot=snapshot,
                source_node_id=node_id,
                source_node_label=node_label,
                notification_output=event_payload,
                credentials_context=self.credentials_context,
                global_variables_context=self.global_variables_context,
                trace_user_id=self.trace_user_id,
                agent_progress_queue=self.agent_progress_queue,
            )
        except Exception:
            logger.exception("Failed to execute LLM batch status branch for node %s", node_id)
            return

        self._record_notification_branch_results(branch_result.get("node_results") or [])

    def _resolve_template(self, template: str, inputs: dict, node_id: str) -> str:
        if not template or "$" not in template:
            return template

        if template.startswith("$") and " " not in template:
            result = self.resolve_expression(template, inputs, node_id)
            return str(result) if result is not None else ""

        def replace_expr(expr: str) -> str:
            result = self.resolve_expression(expr, inputs, node_id)
            return str(result) if result is not None else expr

        return self._replace_expressions(template, replace_expr)

    def _execute_llm_node(
        self,
        credential_id: str | None,
        node_id: str | None,
        model: str,
        system_instruction: str | None,
        user_message: str | list[str],
        temperature: float,
        reasoning_effort: str | None,
        max_tokens: int | None,
        json_output_enabled: bool,
        json_output_schema: str | None,
        image_input: str | None,
        output_type: str = "text",
        image_size: str = "1024x1024",
        image_quality: str = "auto",
        guardrails_config: dict | None = None,
        fallback_credential_id: str | None = None,
        fallback_model: str | None = None,
        batch_mode_enabled: bool = False,
        on_batch_status_update: Callable[[dict[str, Any]], None] | None = None,
        should_abort: Callable[[], str | None] | None = None,
        request_timeout: float = 60.0,
    ) -> dict:
        if not credential_id or not model:
            return {
                "text": f"LLM processed (no credential): {user_message}",
                "model": model or "none",
                "error": "No credential or model configured",
            }

        attempts: list[tuple[str, str]] = [(credential_id, model)]
        if fallback_credential_id and fallback_model:
            attempts.append((fallback_credential_id, fallback_model))

        from app.db.session import SessionLocal
        from app.services.encryption import decrypt_config

        guardrail_texts = user_message if isinstance(user_message, list) else [user_message]

        if guardrails_config and guardrails_config.get("enabled"):
            from app.services.guardrails_service import (
                GuardrailCategory,
                GuardrailConfig,
                GuardrailSeverity,
                check_guardrails,
            )
            from app.services.llm_service import GOOGLE_OPENAI_BASE_URL

            raw_categories = guardrails_config.get("categories") or []
            parsed_categories: list[GuardrailCategory] = []
            for cat in raw_categories:
                try:
                    parsed_categories.append(GuardrailCategory(cat))
                except ValueError:
                    pass
            raw_severity = guardrails_config.get("severity", "medium")
            try:
                parsed_severity = GuardrailSeverity(raw_severity)
            except ValueError:
                parsed_severity = GuardrailSeverity.MEDIUM

            guardrail_credential_id = (guardrails_config.get("credential_id") or "").strip()
            guardrail_model = (guardrails_config.get("model") or "").strip()
            if not guardrail_credential_id or not guardrail_model:
                return {
                    "text": "",
                    "model": model,
                    "error": (
                        "Guardrails are enabled but credential and model are required. "
                        "Please select a Guardrail Credential and Guardrail Model in the node."
                    ),
                }

            try:
                with SessionLocal() as db:
                    guardrail_cred = self._get_accessible_credential(db, guardrail_credential_id)
                    if not guardrail_cred:
                        return {
                            "text": "",
                            "model": model,
                            "error": "Guardrail credential not found or not accessible.",
                        }
                    guardrail_credential_type = guardrail_cred.type
                    gcred_cfg = decrypt_config(guardrail_cred.encrypted_config)
                    guardrail_api_key = gcred_cfg.get("api_key")
                    guardrail_base_url = gcred_cfg.get("base_url")
                    if not guardrail_base_url and guardrail_cred.type.value == "google":
                        guardrail_base_url = GOOGLE_OPENAI_BASE_URL
                    elif guardrail_base_url and guardrail_cred.type.value == "custom":
                        guardrail_base_url = guardrail_base_url.rstrip("/")
                        if not guardrail_base_url.endswith("/v1"):
                            guardrail_base_url = guardrail_base_url + "/v1"
            except Exception as e:
                return {
                    "text": "",
                    "model": model,
                    "error": f"Failed to load guardrail credential: {e}",
                }

            if guardrail_api_key:
                cfg = GuardrailConfig(
                    enabled=True,
                    categories=parsed_categories,
                    severity=parsed_severity,
                )
                guardrail_trace_context = self._build_llm_trace_context(
                    guardrail_credential_id, node_id
                )
                for guardrail_text in guardrail_texts:
                    check_guardrails(
                        text=guardrail_text,
                        config=cfg,
                        credential_type=guardrail_credential_type.value,
                        api_key=guardrail_api_key,
                        base_url=guardrail_base_url,
                        model=guardrail_model,
                        trace_context=guardrail_trace_context,
                    )

        response_format = None
        if json_output_enabled:
            if json_output_schema:
                try:
                    schema = json.loads(json_output_schema)
                except json.JSONDecodeError as exc:
                    return {
                        "text": "",
                        "model": model,
                        "error": f"Invalid JSON output schema: {str(exc)}",
                    }
                if not isinstance(schema, dict):
                    return {
                        "text": "",
                        "model": model,
                        "error": "JSON output schema must be an object",
                    }
                schema = _ensure_additional_properties(schema)
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": schema, "strict": True},
                }
            else:
                response_format = {"type": "json_object"}

        if batch_mode_enabled:
            if output_type == "image":
                return {
                    "text": "",
                    "model": model,
                    "error": "Batch mode is only supported for text outputs.",
                }
            if image_input:
                return {
                    "text": "",
                    "model": model,
                    "error": "Batch mode does not support image input.",
                }
            if not isinstance(user_message, list):
                return {
                    "text": "",
                    "model": model,
                    "error": (
                        "Batch mode requires the User Message expression to resolve to an array. "
                        'Example: $input.items.map("item.text")'
                    ),
                }
            if not user_message:
                return {
                    "text": "",
                    "model": model,
                    "error": "Batch mode requires at least one item in the User Message array.",
                }
            normalized_user_messages: list[str] = []
            for batch_item in user_message:
                if batch_item is None:
                    normalized_user_messages.append("")
                elif isinstance(batch_item, (str, int, float, bool)):
                    normalized_user_messages.append(str(batch_item))
                else:
                    return {
                        "text": "",
                        "model": model,
                        "error": (
                            "Batch mode items must resolve to strings or primitive values. "
                            "Map objects into prompt strings before sending them to the LLM node."
                        ),
                    }
            user_message = normalized_user_messages

        last_error: Exception | None = None
        last_model = model
        last_trace_id: str | None = None
        for attempt_idx, (cid, mod) in enumerate(attempts):
            credential_type = None
            api_key = None
            base_url = None
            try:
                with SessionLocal() as db:
                    cred = self._get_accessible_credential(db, cid)
                    if cred:
                        credential_type = cred.type
                        config = decrypt_config(cred.encrypted_config)
                        api_key = config.get("api_key")
                        base_url = config.get("base_url")
            except Exception as e:
                last_error = e
                last_model = mod
                continue

            if not api_key:
                last_error = ValueError("Credential has no API key")
                last_model = mod
                continue

            trace_context = self._build_llm_trace_context(cid, node_id)

            if output_type == "image":
                try:
                    if image_input:
                        from app.services.llm_service import execute_image_edit

                        result = run_async(
                            execute_image_edit(
                                credential_type=credential_type.value,
                                api_key=api_key,
                                base_url=base_url,
                                model=mod,
                                prompt=user_message,
                                image_input=image_input,
                                size=image_size,
                                quality=image_quality,
                                trace_context=trace_context,
                            )
                        )
                        out = dict(result)
                        self._attach_latest_trace_id(out, trace_context)
                        last_trace_id = self._latest_trace_id(trace_context) or last_trace_id
                        if attempt_idx > 0:
                            out["fallbackUsed"] = True
                            out["model"] = mod
                        return out

                    from app.services.llm_service import execute_image_generation

                    result = run_async(
                        execute_image_generation(
                            credential_type=credential_type.value,
                            api_key=api_key,
                            base_url=base_url,
                            model=mod,
                            prompt=user_message,
                            size=image_size,
                            quality=image_quality,
                            trace_context=trace_context,
                        )
                    )
                    out = dict(result)
                    self._attach_latest_trace_id(out, trace_context)
                    last_trace_id = self._latest_trace_id(trace_context) or last_trace_id
                    if attempt_idx > 0:
                        out["fallbackUsed"] = True
                        out["model"] = mod
                    return out
                except Exception as e:
                    last_error = e
                    last_model = mod
                    last_trace_id = self._latest_trace_id(trace_context) or last_trace_id
                    continue

            try:
                if batch_mode_enabled:
                    from app.services.llm_service import execute_llm_batch

                    result = run_async(
                        execute_llm_batch(
                            credential_type=credential_type.value,
                            api_key=api_key,
                            base_url=base_url,
                            model=mod,
                            system_instruction=system_instruction,
                            user_messages=user_message,
                            temperature=temperature,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens,
                            response_format=response_format,
                            trace_context=trace_context,
                            conversation_history=self.conversation_history,
                            on_status_update=on_batch_status_update,
                            should_abort=should_abort,
                            request_timeout=request_timeout,
                        )
                    )
                else:
                    from app.services.llm_service import execute_llm

                    result = run_async(
                        execute_llm(
                            credential_type=credential_type.value,
                            api_key=api_key,
                            base_url=base_url,
                            model=mod,
                            system_instruction=system_instruction,
                            user_message=user_message,
                            temperature=temperature,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens,
                            response_format=response_format,
                            image_input=image_input,
                            trace_context=trace_context,
                            conversation_history=self.conversation_history,
                            request_timeout=request_timeout,
                        )
                    )
                out = dict(result)
                self._attach_latest_trace_id(out, trace_context)
                last_trace_id = self._latest_trace_id(trace_context) or last_trace_id
                if attempt_idx > 0:
                    out["fallbackUsed"] = True
                    out["model"] = mod
                return out
            except Exception as e:
                last_error = e
                last_model = mod
                last_trace_id = self._latest_trace_id(trace_context) or last_trace_id
                continue

        error_output = {
            "text": "",
            "model": last_model,
            "error": str(last_error) if last_error else "All credential/model attempts failed",
        }
        if last_trace_id:
            error_output["_trace_id"] = last_trace_id
        return error_output

    def _resolve_mcp_connection(self, conn: dict, inputs: dict, node_id: str | None) -> dict:
        """Resolve expression DSL in MCP connection env/url/header values."""
        nid = node_id or ""
        resolved = dict(conn)

        def _resolve_json_like(raw: object, expected_type: type) -> object | None:
            if isinstance(raw, str) and raw.strip():
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    return None
            if not isinstance(raw, expected_type):
                return None
            return self._resolve_mcp_config_value(raw, inputs, nid)

        env = _resolve_json_like(resolved.get("env"), dict)
        if env is not None:
            resolved["env"] = env
        url = resolved.get("url")
        if isinstance(url, str) and "$" in url:
            resolved["url"] = self._resolve_template(url, inputs, nid)
        headers = _resolve_json_like(resolved.get("headers"), dict)
        if headers is not None:
            resolved["headers"] = headers
        args = _resolve_json_like(resolved.get("args"), list)
        if args is not None:
            resolved["args"] = args
        return resolved

    def _resolve_mcp_config_value(
        self,
        raw: object,
        inputs: dict,
        node_id: str | None,
    ) -> object:
        """Resolve MCP config/tool argument expressions while preserving arrays and objects."""
        if isinstance(raw, dict):
            return {
                key: self._resolve_mcp_config_value(value, inputs, node_id)
                for key, value in raw.items()
            }
        if isinstance(raw, list):
            return [self._resolve_mcp_config_value(value, inputs, node_id) for value in raw]
        if not isinstance(raw, str) or "$" not in raw:
            return raw

        trimmed = raw.strip()
        if trimmed.startswith(("{", "[")):
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                return self._resolve_mcp_config_value(parsed, inputs, node_id)

        if self._is_single_dollar_expression(trimmed):
            return self.resolve_expression(trimmed, inputs, node_id, preserve_type=True)
        if should_resolve_embedded_dollar_refs_arithmetically(trimmed, self):
            return self.resolve_arithmetic_expression(
                raw,
                inputs,
                node_id,
                preserve_type=True,
            )
        return self.evaluate_message_template(raw, inputs, node_id, preserve_type=True)

    def _list_mcp_tools(self, connection: dict, timeout_seconds: float) -> list[dict]:
        """List tools from an MCP server connection."""
        from app.services.mcp_tool_executor import list_mcp_tools

        conn = dict(connection)
        conn.setdefault("id", conn.get("label", "default"))
        return list_mcp_tools(conn, timeout_seconds)

    def _parse_json_output(self, text: str) -> object:
        if not text:
            raise ValueError("LLM returned empty JSON output")
        parsed = json.loads(text)
        if isinstance(parsed, str):
            parsed_str = parsed.strip()
            if parsed_str.startswith("{") or parsed_str.startswith("["):
                parsed = json.loads(parsed_str)
        return parsed

    def _execute_sub_agent_tool(
        self,
        tool_def: dict,
        _name: str,
        args: dict,
        _timeout_seconds: float,
    ) -> dict:
        """Execute a sub-agent node when orchestrator calls call_sub_agent tool."""
        sub_agent_label = args.get("sub_agent_label", "")
        prompt = args.get("prompt", "")
        sub_agent_labels = tool_def.get("_sub_agent_labels") or []
        if sub_agent_label not in sub_agent_labels:
            return {"error": f"Invalid sub_agent_label: '{sub_agent_label}'"}
        target_node_id = None
        target_node_data = None
        for nid, node in self.nodes.items():
            if node.get("type") == "agent" and node.get("data", {}).get("label") == sub_agent_label:
                target_node_id = nid
                target_node_data = node.get("data", {})
                break
        if not target_node_id or not target_node_data:
            return {"error": f"Sub-agent '{sub_agent_label}' not found"}
        target_node = self.nodes.get(target_node_id)
        if target_node and target_node.get("data", {}).get("active") is False:
            return {"error": f"Sub-agent '{sub_agent_label}' is disabled"}
        if self._sub_agent_call_depth >= 5:
            return {"error": "Max sub-agent call depth exceeded (5)"}
        self._sub_agent_call_depth += 1
        sub_agent_label_display = target_node_data.get("label", sub_agent_label)
        if self.agent_progress_queue is not None:
            self.agent_progress_queue.put(
                {
                    "type": "node_start",
                    "node_id": target_node_id,
                    "node_label": sub_agent_label_display,
                }
            )
        start_ms = time.time() * 1000
        try:
            synthetic_inputs = {"input": {"text": prompt, "body": {"text": prompt}}}
            result = self._execute_agent_node(target_node_id, synthetic_inputs, target_node_data)
            trace_id = self._pop_internal_trace_id(result)
            if result.get("_hitl_pending"):
                return {
                    "text": "",
                    "error": "HITL is not supported inside sub-agent tools. Request review from the parent agent before calling the sub-agent.",
                }
            elapsed_ms = round((time.time() * 1000) - start_ms)
            status = "error" if result.get("error") else "success"
            log_output = _build_agent_execution_log_output(result)
            llm_tool_result = {"text": result.get("text", "")}
            if result.get("error"):
                llm_tool_result["error"] = result["error"]
            metadata: dict[str, Any] = {"invocation": "sub_agent_tool"}
            if trace_id:
                metadata["trace_id"] = trace_id
            delegated_result = self._stamp_node_result(
                NodeResult(
                    node_id=target_node_id,
                    node_label=sub_agent_label_display,
                    node_type="agent",
                    status=status,
                    output=log_output,
                    execution_time_ms=float(elapsed_ms),
                    error=result.get("error"),
                    metadata=metadata,
                )
            )
            self.delegated_agent_node_results.append(delegated_result)
            if self.agent_progress_queue is not None:
                self.agent_progress_queue.put(
                    _build_node_complete_event(delegated_result, log_output)
                )
            return llm_tool_result
        except Exception as exc:
            elapsed_ms = round((time.time() * 1000) - start_ms)
            metadata: dict[str, Any] = {"invocation": "sub_agent_tool"}
            trace_id = getattr(exc, "trace_id", None)
            if isinstance(trace_id, str) and trace_id:
                metadata["trace_id"] = trace_id
            delegated_result = self._stamp_node_result(
                NodeResult(
                    node_id=target_node_id,
                    node_label=sub_agent_label_display,
                    node_type="agent",
                    status="error",
                    output={},
                    execution_time_ms=float(elapsed_ms),
                    error=str(exc),
                    metadata=metadata,
                )
            )
            self.delegated_agent_node_results.append(delegated_result)
            if self.agent_progress_queue is not None:
                self.agent_progress_queue.put(_build_node_complete_event(delegated_result, {}))
            return {"text": "", "error": str(exc)}
        finally:
            self._sub_agent_call_depth -= 1

    def _execute_sub_workflow_tool(
        self,
        tool_def: dict,
        _name: str,
        args: dict,
        _timeout_seconds: float,
    ) -> dict:
        """Execute a sub-workflow when agent calls call_sub_workflow tool."""
        workflow_id_str = args.get("workflow_id", "")
        inputs = args.get("inputs")
        if inputs is None:
            inputs = {}
        if not isinstance(inputs, dict):
            inputs = {"text": str(inputs)}

        sub_workflow_ids = tool_def.get("_sub_workflow_ids") or []
        if workflow_id_str not in sub_workflow_ids:
            return {"error": f"Invalid workflow_id: '{workflow_id_str}'"}

        if self._sub_workflow_invocation_depth >= 5:
            return {"error": "Max sub-workflow call depth exceeded (5)"}

        if workflow_id_str not in self.workflow_cache:
            return {"error": f"Workflow '{workflow_id_str}' not found in cache"}

        target_workflow = self.workflow_cache[workflow_id_str]
        input_fields = target_workflow.get("input_fields") or []
        for f in input_fields:
            key = f.get("key", "text")
            if key not in inputs and f.get("defaultValue"):
                inputs[key] = f.get("defaultValue")
        self._refresh_vars_context_cache()
        merged_global = (
            self._merged_global_context_cache
            if self._merged_global_context_cache is not None
            else {}
        )
        _sub_execution_id = uuid.uuid4()
        sub_cancel_event = Event()
        _register_sub_execution(
            workflow_id=uuid.UUID(workflow_id_str),
            execution_id=_sub_execution_id,
            event=sub_cancel_event,
            recoverable=False,
        )
        # Propagate parent cancellation into the sub's cancel event.
        if self.cancel_event is not None:
            _parent_event = self.cancel_event

            def _bridge_parent_cancel() -> None:
                _parent_event.wait()
                sub_cancel_event.set()

            Thread(target=_bridge_parent_cancel, daemon=True).start()
        sub_executor = WorkflowExecutor(
            nodes=target_workflow["nodes"],
            edges=target_workflow["edges"],
            workflow_cache=self.workflow_cache,
            test_mode=False,
            credentials_context=self.credentials_context,
            global_variables_context=merged_global,
            workflow_id=uuid.UUID(workflow_id_str),
            trace_user_id=self.trace_user_id,
            actor_user_id=self.actor_user_id,
            sub_workflow_invocation_depth=self._sub_workflow_invocation_depth + 1,
            cancel_event=sub_cancel_event,
            invoked_by_agent=True,
        )
        enriched_inputs = {
            "headers": {},
            "query": {},
            "body": inputs,
        }
        start_ms = time.time() * 1000
        try:
            sub_result = sub_executor.execute(
                workflow_id=uuid.UUID(workflow_id_str),
                initial_inputs=enriched_inputs,
            )
            if sub_result.status == "pending":
                return {
                    "status": "error",
                    "outputs": {},
                    "execution_time_ms": round((time.time() * 1000) - start_ms),
                    "error": "HITL is not supported inside sub-workflow tools.",
                }
            elapsed_ms = round((time.time() * 1000) - start_ms)
            with self.lock:
                self.sub_workflow_executions.append(
                    SubWorkflowExecution(
                        workflow_id=workflow_id_str,
                        inputs=inputs,
                        outputs=sub_result.outputs,
                        status=sub_result.status,
                        execution_time_ms=sub_result.execution_time_ms,
                        node_results=sub_result.node_results,
                        workflow_name=target_workflow.get("name", ""),
                        trigger_source="AI Agents",
                    )
                )
                self.sub_workflow_executions.extend(sub_executor.sub_workflow_executions)
            out = {
                "status": sub_result.status,
                "outputs": sub_result.outputs,
                "execution_time_ms": elapsed_ms,
            }
            if sub_result.status == "error":
                err = sub_result.outputs.get("error") if sub_result.outputs else None
                if err:
                    out["error"] = err
                elif sub_result.node_results:
                    for nr in sub_result.node_results:
                        if isinstance(nr, dict) and nr.get("error"):
                            out["error"] = nr["error"]
                            break
            return out
        except Exception as exc:
            elapsed_ms = round((time.time() * 1000) - start_ms)
            return {
                "status": "error",
                "outputs": {},
                "execution_time_ms": elapsed_ms,
                "error": str(exc),
            }
        finally:
            _clear_sub_execution(_sub_execution_id)

    @staticmethod
    def _normalize_hitl_policy_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    @staticmethod
    def _split_hitl_policy_segments(policy_text: str) -> list[str]:
        raw_segments = re.split(r"[\r\n]+|(?<=[.!?;])\s+", policy_text or "")
        return [segment.strip(" -\t") for segment in raw_segments if segment.strip()]

    @staticmethod
    def _segment_enables_hitl(segment: str) -> bool:
        lowered = segment.lower()
        positive_patterns = (
            r"\bask before\b",
            r"\bask\b.{0,24}\bbefore\b",
            r"\balways\b.{0,24}\bask\b",
            r"\bask\b.{0,24}\bfor\b.{0,24}\b(review|approval|permission|hitl)\b",
            r"\bask\b.{0,24}\bfor\b.{0,24}\b(mcp|tool|workflow|sub[- ]workflow|sub[- ]agent)\b",
            r"\bask\b.{0,24}\b(on each|each|every)\b",
            r"\brequest human review\b",
            r"\brequires?\b.{0,24}\b(review|approval|permission)\b",
            r"\bneeds?\b.{0,24}\b(review|approval|permission)\b",
            r"\bhuman review\b.{0,24}\bbefore\b",
            r"\bapproval\b.{0,24}\bbefore\b",
            r"\bpermission\b.{0,24}\bbefore\b",
        )
        return any(re.search(pattern, lowered) for pattern in positive_patterns)

    @staticmethod
    def _segment_disables_hitl(segment: str) -> bool:
        lowered = segment.lower()
        negative_patterns = (
            r"\bdo not ask\b",
            r"\bdon't ask\b",
            r"\bnever\b.{0,24}\bask\b",
            r"\bdo not require\b",
            r"\bdoes not require\b",
            r"\bwithout\b.{0,24}\b(review|approval|permission|hitl)\b",
            r"\bskip\b.{0,24}\b(review|approval|permission|hitl)\b",
            r"\bno\b.{0,24}\b(review|approval|permission|hitl)\b",
            r"\balways approved\b",
            r"\balready approved\b",
            r"\bpre[- ]approved\b",
            r"\bauto(?:matically)? approved\b",
        )
        return any(re.search(pattern, lowered) for pattern in negative_patterns)

    @staticmethod
    def _segment_uses_once_only_mode(segment: str) -> bool:
        lowered = segment.lower()
        once_patterns = (
            r"\bonly once\b",
            r"\bjust once\b",
            r"\bonce per\b",
            r"\bfirst time only\b",
            r"\bonly on the first\b",
            r"\bask once\b",
        )
        return any(re.search(pattern, lowered) for pattern in once_patterns)

    @staticmethod
    def _normalize_mcp_approval_mode(mode: str | None) -> str | None:
        normalized = (mode or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"always", "every_time", "each_time", "for_each", "on_each"}:
            return "always"
        if normalized in {"once", "once_per_tool", "only_once", "first_time_only"}:
            return "once"
        if normalized in {"never", "no", "disabled"}:
            return "never"
        return None

    def _build_hitl_mcp_policy(self, policy_text: str, tools: list[dict]) -> dict:
        segments = self._split_hitl_policy_segments(policy_text)
        available_mcp_tools = [
            str(tool.get("name") or "") for tool in tools if tool.get("_source") == "mcp"
        ]
        named_mcp_tool_modes: dict[str, str] = {}
        default_mcp_tool_mode: str | None = None

        for segment in segments:
            lowered_segment = segment.lower()
            normalized_segment = self._normalize_hitl_policy_token(segment)
            enables_hitl = self._segment_enables_hitl(segment)
            disables_hitl = self._segment_disables_hitl(segment)
            approval_mode = "once" if self._segment_uses_once_only_mode(segment) else "always"

            if "mcp" in lowered_segment:
                if disables_hitl:
                    default_mcp_tool_mode = "never"
                elif enables_hitl:
                    default_mcp_tool_mode = approval_mode

            for tool_name in available_mcp_tools:
                normalized_name = self._normalize_hitl_policy_token(tool_name)
                if not normalized_name or normalized_name not in normalized_segment:
                    continue
                if disables_hitl:
                    named_mcp_tool_modes[tool_name] = "never"
                elif enables_hitl:
                    named_mcp_tool_modes[tool_name] = approval_mode

        return {
            "default_mcp_tool_mode": default_mcp_tool_mode,
            "named_mcp_tool_modes": named_mcp_tool_modes,
            "available_mcp_tools": available_mcp_tools,
        }

    def _coerce_hitl_mcp_policy(
        self,
        raw_policy: dict | None,
        *,
        available_mcp_tools: list[str],
        fallback_policy: dict | None = None,
    ) -> dict:
        fallback_policy = fallback_policy or {}
        fallback_default_mode = self._normalize_mcp_approval_mode(
            fallback_policy.get("default_mcp_tool_mode")
        )
        fallback_named_modes = {
            str(tool_name): normalized_mode
            for tool_name, mode in (fallback_policy.get("named_mcp_tool_modes") or {}).items()
            if (normalized_mode := self._normalize_mcp_approval_mode(str(mode)))
        }

        if not isinstance(raw_policy, dict):
            return {
                "default_mcp_tool_mode": fallback_default_mode,
                "named_mcp_tool_modes": fallback_named_modes,
                "available_mcp_tools": list(available_mcp_tools),
            }

        coerced_default_mode = self._normalize_mcp_approval_mode(
            raw_policy.get("default_mcp_tool_mode")
            or raw_policy.get("global_mode")
            or fallback_default_mode
        )
        named_modes: dict[str, str] = {}
        for tool_name, mode in fallback_named_modes.items():
            if tool_name in available_mcp_tools:
                named_modes[tool_name] = mode

        raw_named_modes = raw_policy.get("named_mcp_tool_modes")
        if isinstance(raw_named_modes, dict):
            for tool_name, mode in raw_named_modes.items():
                normalized_mode = self._normalize_mcp_approval_mode(str(mode))
                if normalized_mode and str(tool_name) in available_mcp_tools:
                    named_modes[str(tool_name)] = normalized_mode

        raw_tool_modes = raw_policy.get("tool_modes")
        if isinstance(raw_tool_modes, list):
            for item in raw_tool_modes:
                if not isinstance(item, dict):
                    continue
                tool_name = str(item.get("tool_name") or "").strip()
                normalized_mode = self._normalize_mcp_approval_mode(item.get("mode"))
                if tool_name in available_mcp_tools and normalized_mode:
                    named_modes[tool_name] = normalized_mode

        return {
            "default_mcp_tool_mode": coerced_default_mode,
            "named_mcp_tool_modes": named_modes,
            "available_mcp_tools": list(available_mcp_tools),
        }

    def _resolve_mcp_approval_mode(
        self, hitl_mcp_policy: dict | None, tool_name: str
    ) -> str | None:
        if not isinstance(hitl_mcp_policy, dict):
            return None
        named_modes = hitl_mcp_policy.get("named_mcp_tool_modes") or {}
        resolved_mode = named_modes.get(tool_name)
        if resolved_mode is not None:
            return self._normalize_mcp_approval_mode(str(resolved_mode))
        return self._normalize_mcp_approval_mode(hitl_mcp_policy.get("default_mcp_tool_mode"))

    def _classify_hitl_mcp_policy_with_model(
        self,
        *,
        credential_type: str,
        api_key: str,
        base_url: str | None,
        model: str,
        policy_text: str,
        available_mcp_tools: list[str],
        trace_context: LLMTraceContext | None,
    ) -> dict | None:
        if not policy_text.strip() or not available_mcp_tools:
            return None

        from app.services.llm_service import execute_llm

        classifier_system_instruction = (
            "You extract human-review scope for MCP tools from freeform workflow instructions.\n"
            "Classify MCP approval into exactly three modes:\n"
            "- `always`: ask before each / every / for-each call\n"
            "- `once`: ask only once / first time only, then keep it approved for that tool\n"
            "- `never`: do not ask / pre-approved / always approved\n"
            "If the instructions do not give a clear MCP policy, return `null` for the default.\n"
            "You may also return tool-specific overrides.\n"
            "Respond with JSON only."
        )
        classifier_user_message = json.dumps(
            {
                "instructions": policy_text,
                "mcp_tools": available_mcp_tools,
                "output_contract": {
                    "default_mcp_tool_mode": "always | once | never | null",
                    "tool_modes": [
                        {"tool_name": "exact MCP tool name", "mode": "always | once | never"}
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            result = run_async(
                execute_llm(
                    credential_type=credential_type,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    system_instruction=classifier_system_instruction,
                    user_message=classifier_user_message,
                    temperature=0,
                    max_tokens=250,
                    response_format={"type": "json_object"},
                    trace_context=trace_context,
                    content_only=True,
                )
            )
            parsed = json.loads(str(result.get("text") or "").strip() or "{}")
        except Exception as exc:
            logger.warning("Failed to classify HITL MCP policy with model: %s", exc)
            return None

        return self._coerce_hitl_mcp_policy(
            parsed,
            available_mcp_tools=available_mcp_tools,
        )

    def _build_mcp_policy_interpretation_hint(self, hitl_mcp_policy: dict | None) -> str:
        if not isinstance(hitl_mcp_policy, dict):
            return ""

        parts: list[str] = []
        default_mode = self._normalize_mcp_approval_mode(
            hitl_mcp_policy.get("default_mcp_tool_mode")
        )
        if default_mode:
            parts.append(f"default MCP approval scope: {default_mode}")

        named_modes = hitl_mcp_policy.get("named_mcp_tool_modes") or {}
        named_parts = []
        for tool_name, mode in named_modes.items():
            normalized_mode = self._normalize_mcp_approval_mode(str(mode))
            if normalized_mode:
                named_parts.append(f"{tool_name}={normalized_mode}")
        if named_parts:
            parts.append("tool-specific MCP approval scope: " + ", ".join(sorted(named_parts)))

        if not parts:
            return ""

        return "Interpreted MCP approval scope from the current instructions:\n- " + "\n- ".join(
            parts
        )

    def _hitl_request_targets_preapproved_mcp(
        self,
        *,
        summary: str | None,
        review_markdown: str,
        reason: str | None,
        hitl_mcp_policy: dict | None,
    ) -> bool:
        if not isinstance(hitl_mcp_policy, dict):
            return False

        combined_text = "\n".join(
            value for value in (summary or "", review_markdown or "", reason or "") if value
        )
        lowered = combined_text.lower()
        normalized = self._normalize_hitl_policy_token(combined_text)
        available_mcp_tools = set(hitl_mcp_policy.get("available_mcp_tools") or [])
        referenced_mcp_tools = {
            tool_name
            for tool_name in available_mcp_tools
            if self._normalize_hitl_policy_token(tool_name) in normalized
        }

        if any(
            self._resolve_mcp_approval_mode(hitl_mcp_policy, tool_name) == "never"
            for tool_name in referenced_mcp_tools
        ):
            return True

        if self._normalize_mcp_approval_mode(
            hitl_mcp_policy.get("default_mcp_tool_mode")
        ) == "never" and ("mcp" in lowered or bool(referenced_mcp_tools)):
            return True

        return False

    def _build_preapproved_hitl_tool_result(
        self,
        *,
        tool_name: str,
        reason: str | None,
    ) -> dict[str, str]:
        target = reason or tool_name
        return {
            "status": "not_required",
            "message": (
                "Human review is not required for this step under the current HITL guidelines. "
                f"Continue without pausing and execute the pre-approved action: {target}."
            ),
        }

    def _extract_referenced_mcp_tool_name(
        self,
        *,
        summary: str | None,
        review_markdown: str,
        reason: str | None,
        hitl_mcp_policy: dict | None,
    ) -> str | None:
        if not isinstance(hitl_mcp_policy, dict):
            return None

        combined_text = "\n".join(
            value for value in (summary or "", review_markdown or "", reason or "") if value
        )
        lowered = combined_text.lower()
        normalized = self._normalize_hitl_policy_token(combined_text)
        available_mcp_tools = [
            str(tool_name)
            for tool_name in (hitl_mcp_policy.get("available_mcp_tools") or [])
            if str(tool_name).strip()
        ]

        referenced_mcp_tools = [
            tool_name
            for tool_name in available_mcp_tools
            if self._normalize_hitl_policy_token(tool_name) in normalized
        ]
        if len(referenced_mcp_tools) == 1:
            return referenced_mcp_tools[0]

        if "mcp" in lowered and len(available_mcp_tools) == 1:
            return available_mcp_tools[0]

        return None

    def _get_active_edited_hitl_checkpoint(self, node_id: str | None) -> dict | None:
        if not node_id:
            return None
        node_context = self.hitl_resume_context.get(node_id) or {}
        checkpoint = node_context.get("_approved_hitl_checkpoint")
        if not isinstance(checkpoint, dict):
            return None
        if str(checkpoint.get("decision") or "") != "edited":
            return None
        if bool(checkpoint.get("consumed")):
            return None
        return checkpoint

    def _consume_edited_hitl_checkpoint(self, node_id: str | None) -> None:
        checkpoint = self._get_active_edited_hitl_checkpoint(node_id)
        if checkpoint is not None:
            checkpoint["consumed"] = True

    def _build_edited_hitl_tool_result(self, approved_hitl_checkpoint: dict) -> dict[str, str]:
        approved_markdown = str(approved_hitl_checkpoint.get("approved_markdown") or "").strip()
        message = (
            "This checkpoint was already edited and approved by a human. "
            "Do not request approval again for the same step. Follow the approved instructions and continue."
        )
        result = {
            "status": "already_approved",
            "message": message,
        }
        if approved_markdown:
            result["approved_markdown"] = approved_markdown
        return result

    @staticmethod
    def _approved_tool_call_matches(
        approved_tool_call: dict | None,
        *,
        source: str,
        name: str,
        args: dict,
    ) -> bool:
        if not isinstance(approved_tool_call, dict):
            return False
        if str(approved_tool_call.get("tool_source") or "") != source:
            return False
        if str(approved_tool_call.get("tool_name") or "") != name:
            return False

        match_strategy = str(approved_tool_call.get("match_strategy") or "exact_args")
        if match_strategy in {"tool_name", "next_tool_call"}:
            return True

        approved_args = approved_tool_call.get("tool_arguments") or {}
        try:
            return json.dumps(approved_args, sort_keys=True, default=str) == json.dumps(
                args or {}, sort_keys=True, default=str
            )
        except TypeError:
            return approved_args == (args or {})

    def _build_mcp_hitl_review_markdown(self, name: str, args: dict) -> str:
        rendered_args = json.dumps(args or {}, indent=2, sort_keys=True, default=str)
        return (
            "## Approval Required\n\n"
            f"The agent is about to call the MCP tool `{name}`.\n\n"
            "### Planned Arguments\n"
            f"```json\n{rendered_args}\n```\n\n"
            "Approve to let this MCP call run."
        )

    @staticmethod
    def _normalize_hitl_summary_candidate(text: str) -> str:
        cleaned = re.sub(r"```[\s\S]*?```", " ", text or "")
        cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
        cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.")
        return cleaned

    @staticmethod
    def _is_generic_hitl_summary_candidate(text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        return normalized in {
            "approval required",
            "human review",
            "human review required",
            "planned arguments",
            "review required",
        }

    @staticmethod
    def _truncate_hitl_summary(text: str, max_length: int = 140) -> str:
        if len(text) <= max_length:
            return text
        trimmed = text[: max_length - 3].rsplit(" ", 1)[0].strip()
        if not trimmed:
            trimmed = text[: max_length - 3].strip()
        return f"{trimmed}..."

    def _generate_hitl_summary(
        self,
        *,
        summary: str | None,
        review_markdown: str,
        reason: str | None,
        fallback: str,
    ) -> str:
        explicit_summary = self._normalize_hitl_summary_candidate(summary or "")
        if explicit_summary:
            return self._truncate_hitl_summary(explicit_summary)

        for paragraph in re.split(r"\n\s*\n", review_markdown or ""):
            candidate = self._normalize_hitl_summary_candidate(paragraph)
            if candidate and not self._is_generic_hitl_summary_candidate(candidate):
                return self._truncate_hitl_summary(candidate)

        reason_summary = self._normalize_hitl_summary_candidate(reason or "")
        if reason_summary:
            return self._truncate_hitl_summary(reason_summary)

        fallback_summary = self._normalize_hitl_summary_candidate(fallback or "")
        if fallback_summary:
            return self._truncate_hitl_summary(fallback_summary)
        return "Human review required"

    def _build_agent_tool_executor(
        self,
        *,
        node_id: str | None,
        hitl_fallback_summary: str | None = None,
        hitl_mcp_policy: dict | None = None,
    ) -> Callable:
        """Build tool executor for agent nodes, including HITL, sub-agents, and sub-workflows."""

        from app.services.llm_service import HumanReviewPause, _unified_tool_executor

        def executor(
            tool_def: dict,
            name: str,
            args: dict,
            timeout_seconds: float,
        ) -> object:
            tool_source = str(tool_def.get("_source") or "python")
            edited_hitl_checkpoint = self._get_active_edited_hitl_checkpoint(node_id)
            if tool_source == "hitl":
                if edited_hitl_checkpoint is not None:
                    return self._build_edited_hitl_tool_result(edited_hitl_checkpoint)
                review_markdown = str(
                    args.get("review_markdown") or args.get("markdown") or args.get("text") or ""
                ).strip()
                if not review_markdown:
                    review_markdown = "Human review is required before this agent continues."
                reason = str(args.get("reason") or args.get("blocked_action") or "").strip() or None
                raw_summary = str(args.get("summary") or "").strip() or None
                if self._hitl_request_targets_preapproved_mcp(
                    summary=raw_summary,
                    review_markdown=review_markdown,
                    reason=reason,
                    hitl_mcp_policy=hitl_mcp_policy,
                ):
                    return self._build_preapproved_hitl_tool_result(
                        tool_name=name,
                        reason=reason,
                    )
                summary = self._generate_hitl_summary(
                    summary=raw_summary,
                    review_markdown=review_markdown,
                    reason=reason,
                    fallback=hitl_fallback_summary or "",
                )
                referenced_mcp_tool_name = self._extract_referenced_mcp_tool_name(
                    summary=raw_summary,
                    review_markdown=review_markdown,
                    reason=reason,
                    hitl_mcp_policy=hitl_mcp_policy,
                )
                referenced_mcp_match_strategy: str | None = None
                if referenced_mcp_tool_name:
                    referenced_mcp_mode = self._resolve_mcp_approval_mode(
                        hitl_mcp_policy, referenced_mcp_tool_name
                    )
                    if referenced_mcp_mode == "once":
                        referenced_mcp_match_strategy = "tool_name"
                    elif referenced_mcp_mode == "always":
                        referenced_mcp_match_strategy = "next_tool_call"
                return HumanReviewPause(
                    review_markdown=review_markdown,
                    summary=summary,
                    reason=reason,
                    tool_name=referenced_mcp_tool_name,
                    tool_source="mcp" if referenced_mcp_match_strategy else None,
                    tool_arguments={} if referenced_mcp_match_strategy else None,
                    match_strategy=referenced_mcp_match_strategy,
                )
            approved_tool_call = None
            if node_id:
                approved_tool_call = (
                    self.hitl_resume_context.get(node_id, {}).get("_approved_tool_call") or None
                )

            mcp_approval_mode = self._resolve_mcp_approval_mode(hitl_mcp_policy, name)
            should_gate_mcp = (
                tool_source == "mcp"
                and hitl_mcp_policy is not None
                and edited_hitl_checkpoint is None
                and mcp_approval_mode in {"always", "once"}
            )
            if should_gate_mcp:
                effective_approved_tool_call = (
                    copy.deepcopy(approved_tool_call)
                    if isinstance(approved_tool_call, dict)
                    else None
                )
                if isinstance(effective_approved_tool_call, dict):
                    effective_approved_tool_call["match_strategy"] = str(
                        effective_approved_tool_call.get("match_strategy")
                        or ("tool_name" if mcp_approval_mode == "once" else "exact_args")
                    )
                approved_match_strategy = str(
                    (effective_approved_tool_call or {}).get("match_strategy") or "exact_args"
                )
                if self._approved_tool_call_matches(
                    effective_approved_tool_call,
                    source=tool_source,
                    name=name,
                    args=args,
                ):
                    if (
                        node_id
                        and node_id in self.hitl_resume_context
                        and approved_match_strategy != "tool_name"
                    ):
                        self.hitl_resume_context[node_id].pop("_approved_tool_call", None)
                else:
                    review_markdown = self._build_mcp_hitl_review_markdown(name, args)
                    reason = f"Call MCP tool `{name}`"
                    return HumanReviewPause(
                        review_markdown=review_markdown,
                        summary=self._generate_hitl_summary(
                            summary=None,
                            review_markdown=review_markdown,
                            reason=reason,
                            fallback=hitl_fallback_summary or "",
                        ),
                        reason=reason,
                        tool_name=name,
                        tool_source=tool_source,
                        tool_arguments=copy.deepcopy(args),
                        match_strategy=(
                            "tool_name" if mcp_approval_mode == "once" else "exact_args"
                        ),
                    )

            if edited_hitl_checkpoint is not None:
                self._consume_edited_hitl_checkpoint(node_id)

            if tool_source == "sub_agent":
                return self._execute_sub_agent_tool(tool_def, name, args, timeout_seconds)
            if tool_source == "sub_workflow":
                return self._execute_sub_workflow_tool(tool_def, name, args, timeout_seconds)
            if tool_source == "node_tool":
                return self._execute_node_tool(tool_def, args)

            return _unified_tool_executor(tool_def, name, args, timeout_seconds)

        return executor

    def _build_node_tool_schemas(self, agent_node_id: str) -> list[dict]:
        """Build OpenAI-compatible tool schemas for canvas nodes on the tool-input handle."""
        tool_node_ids = [
            edge["source"]
            for edge in self.edges
            if edge.get("target") == agent_node_id and edge.get("targetHandle") == "tool-input"
        ]

        schemas: list[dict] = []
        seen_names: set[str] = set()

        for node_id in tool_node_ids:
            node = self.nodes.get(node_id)
            if node is None:
                continue
            node_data = node.get("data", {})
            label = node_data.get("label") or node_id
            base_name = _slugify_tool_name(label)

            name = base_name
            suffix = 2
            while name in seen_names:
                name = f"{base_name}_{suffix}"
                suffix += 1
            seen_names.add(name)

            agent_provided: list[str] = node_data.get("agentProvidedFields") or []
            properties = {
                field: {"type": "string", "description": f"Value for {field}"}
                for field in agent_provided
            }

            schemas.append(
                {
                    "name": name,
                    "description": f"Execute the '{label}' node",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(agent_provided),
                    },
                    "_source": "node_tool",
                    "_node_id": node_id,
                }
            )

        return schemas

    def _execute_node_tool(self, tool_def: dict, args: dict) -> dict:
        node_id = tool_def.get("_node_id", "")
        node = self.nodes.get(node_id)
        if node is None:
            return {"error": f"Tool node '{node_id}' not found"}

        original_data = copy.deepcopy(node["data"])
        if original_data.get("active") is False:
            return {"error": f"Tool node '{original_data.get('label', node_id)}' is disabled"}

        agent_provided: list[str] = original_data.get("agentProvidedFields") or []
        merged_data = {**original_data}
        for fname in agent_provided:
            if fname in args:
                merged_data[fname] = args[fname]

        node_label = original_data.get("label", node_id)
        _queue = getattr(self, "agent_progress_queue", None)
        if _queue is not None:
            _queue.put({"type": "node_start", "node_id": node_id, "node_label": node_label})

        node["data"] = merged_data
        try:
            result = self.execute_node(node_id, {}, allow_branch_skip=False)
        finally:
            node["data"] = original_data

        if _queue is not None:
            _queue.put(_build_node_complete_event(result))

        if result.status == "error":
            return {"error": result.error or "Node execution failed"}
        return result.output or {}

    def _execute_agent_node(
        self,
        node_id: str | None,
        inputs: dict,
        node_data: dict,
        guardrails_config: dict | None = None,
    ) -> dict:
        """Execute agent node with optional tool calling."""
        combined_input = ""
        for data in self._visible_inputs(inputs).values():
            if isinstance(data, dict) and "text" in data:
                combined_input += str(data["text"]) + " "
            else:
                combined_input += str(data) + " "
        combined_input = combined_input.strip()

        credential_id = node_data.get("credentialId")
        model = node_data.get("model", "")
        system_instruction_template = node_data.get("systemInstruction", "")
        user_message_template = node_data.get("userMessage", "$input.text")
        temperature = node_data.get("temperature", 0.7)
        reasoning_effort = node_data.get("reasoningEffort")
        max_tokens = node_data.get("maxTokens")
        tools = node_data.get("tools") or []
        tool_timeout_seconds = float(node_data.get("toolTimeoutSeconds") or 30)
        request_timeout_seconds = float(node_data.get("requestTimeoutSeconds") or 60)
        max_tool_iterations = int(node_data.get("maxToolIterations") or 30)
        image_input_enabled = bool(node_data.get("imageInputEnabled", False))
        image_input_template = node_data.get("imageInput", "")
        json_output_enabled = bool(node_data.get("jsonOutputEnabled", False))
        json_output_schema = node_data.get("jsonOutputSchema", "")
        hitl_enabled = bool(node_data.get("hitlEnabled", False))
        hitl_resolution = copy.deepcopy(self.hitl_resume_context.get(node_id or "") or {})
        hitl_agent_state = copy.deepcopy(hitl_resolution.get("_agent_state") or {})
        is_hitl_resume = bool(hitl_resolution)
        node_label = str(node_data.get("label") or node_id or "agent")
        hitl_guidelines_template = str(node_data.get("hitlSummary", "") or "")
        hitl_guidelines = self._resolve_template(hitl_guidelines_template, inputs, node_id).strip()
        hitl_fallback_summary = f"{node_label} requires review."

        base_system_instruction = (
            self._resolve_template(system_instruction_template, inputs, node_id)
            if system_instruction_template
            else None
        )

        skills = node_data.get("skills") or []
        skills_used: list[str] = [s.get("name", "") for s in skills if s.get("name")]
        skills_content_parts: list[str] = []
        for s in skills:
            content = s.get("content", "")
            if content:
                skills_content_parts.append(content)
        skills_content = "\n\n---\n\n".join(skills_content_parts) if skills_content_parts else ""
        system_instruction = (
            (skills_content + "\n\n" + (base_system_instruction or "")).strip()
            if skills_content
            else base_system_instruction
        )

        if json_output_enabled and json_output_schema:
            schema_hint = (
                f"\n\nIMPORTANT: You MUST respond with valid JSON that follows this "
                f"exact structure:\n{json_output_schema}\n"
                "Do NOT use any other JSON structure. Match the field names exactly."
            )
            if system_instruction:
                system_instruction = system_instruction + schema_hint
            else:
                system_instruction = schema_hint.strip()

        user_message = self._resolve_template(user_message_template, inputs, node_id)
        if not user_message:
            user_message = combined_input

        image_input = None
        if image_input_enabled:
            resolved = self.resolve_expression(image_input_template.strip(), inputs, node_id)
            if resolved:
                image_input = resolved
        conversation_history = (
            copy.deepcopy(self.conversation_history) if self.conversation_history else None
        )
        approved_markdown = ""
        resume_messages: list[dict] | None = None
        resume_tool_calls: list[dict] | None = None
        resume_elapsed_ms = 0.0
        resume_prompt_tokens = 0
        resume_completion_tokens = 0
        resume_max_tool_iterations = max_tool_iterations
        hitl_history = []

        if is_hitl_resume:
            hitl_decision = str(hitl_resolution.get("decision") or "")
            raw_hitl_history = hitl_resolution.get("hitlHistory")
            if isinstance(raw_hitl_history, list):
                hitl_history = [
                    copy.deepcopy(entry) for entry in raw_hitl_history if isinstance(entry, dict)
                ]
            elif hitl_decision in {"accepted", "edited", "refused"}:
                fallback_history_entry = {
                    "decision": hitl_decision,
                    "summary": str(hitl_resolution.get("summary") or "").strip(),
                    "originalDraft": str(hitl_resolution.get("originalDraft") or "").strip(),
                    "reviewText": str(hitl_resolution.get("reviewText") or "").strip(),
                    "requestId": str(hitl_resolution.get("requestId") or "").strip(),
                }
                if hitl_resolution.get("editedText") is not None:
                    fallback_history_entry["editedText"] = hitl_resolution.get("editedText")
                if hitl_resolution.get("refusalReason") is not None:
                    fallback_history_entry["refusalReason"] = hitl_resolution.get("refusalReason")
                hitl_history = [fallback_history_entry]
            if hitl_decision == "refused":
                refused_output = {
                    key: copy.deepcopy(value)
                    for key, value in hitl_resolution.items()
                    if not str(key).startswith("_")
                }
                refused_output["_skip_source_handles"] = ["hitl"]
                return refused_output

            approved_markdown = (
                str(hitl_resolution.get("editedText") or "").strip()
                or str(hitl_resolution.get("originalDraft") or "").strip()
                or str(hitl_resolution.get("reviewText") or "").strip()
                or str(hitl_resolution.get("text") or "").strip()
            )
            edited_checkpoint_note = ""
            if hitl_decision == "edited":
                edited_checkpoint_note = (
                    "The human edited this checkpoint. The edited Markdown replaces the original "
                    "plan for this step. Do not ask for human review again for the same "
                    "checkpoint; carry out the edited instructions directly."
                )
            edited_checkpoint_block = (
                f"{edited_checkpoint_note}\n\n" if edited_checkpoint_note else ""
            )
            approval_resume_text = (
                "Human review decision received for a previous approval checkpoint.\n"
                f"Decision: {hitl_decision}\n"
                f"Summary: {str(hitl_resolution.get('summary') or hitl_fallback_summary).strip()}\n\n"
                "Approved Markdown:\n"
                f"{approved_markdown}\n\n"
                f"{edited_checkpoint_block}"
            ) + (
                "Continue from this approved checkpoint. Do not repeat the same approval request "
                "unless the approved plan materially changes. If a different later step also "
                "requires human review, you may request another one at that point."
            )
            approval_resume_text = approval_resume_text.strip()
            review_context = (
                "A human reviewer has already reviewed a prior checkpoint in this agent run.\n"
                f"Decision: {hitl_decision}\n"
                "Treat the approved Markdown below as the source of truth for that checkpoint.\n"
                "Continue the task from there. If a later, different action still requires human "
                "review, you may request it again when needed.\n\n"
                f"{approved_markdown}"
            ).strip()
            if edited_checkpoint_note:
                review_context = f"{review_context}\n\n{edited_checkpoint_note}"
            user_message = (
                "Continue the original task after human review.\n\n"
                "Original task:\n"
                f"{user_message}\n\n"
                "Human-approved Markdown plan:\n"
                f"{approved_markdown}\n\n"
                f"{edited_checkpoint_block}"
            ) + (
                "Execute the approved plan now. Use tools, sub-agents, or sub-workflows only as "
                "needed to carry it out. Do not repeat the exact same approval request. You may "
                "ask for another human review later only if a different step genuinely requires it."
            )
            user_message = user_message.strip()
            approval_history = [
                {"role": "assistant", "content": approved_markdown},
                {
                    "role": "user",
                    "content": (
                        "This plan has been reviewed by a human. Continue from it and execute it "
                        "now."
                    ),
                },
            ]
            if conversation_history:
                conversation_history.extend(approval_history)
            else:
                conversation_history = approval_history
            if system_instruction:
                system_instruction = f"{system_instruction}\n\n{review_context}"
            else:
                system_instruction = review_context

            if hitl_agent_state:
                resume_messages = copy.deepcopy(hitl_agent_state.get("messages") or [])
                resume_messages.append({"role": "user", "content": approval_resume_text})
                resume_tool_calls = copy.deepcopy(hitl_agent_state.get("tool_calls") or [])
                resume_elapsed_ms = float(hitl_agent_state.get("elapsed_ms") or 0.0)
                resume_prompt_tokens = int(hitl_agent_state.get("prompt_tokens") or 0)
                resume_completion_tokens = int(hitl_agent_state.get("completion_tokens") or 0)
                resume_max_tool_iterations = max(
                    1, int(hitl_agent_state.get("remaining_tool_iterations") or max_tool_iterations)
                )

        if not credential_id or not model:
            return {
                "text": f"Agent processed (no credential): {user_message}",
                "model": model or "none",
                "error": "No credential or model configured",
            }

        fallback_credential_id = (node_data.get("fallbackCredentialId") or "").strip() or None
        fallback_model = (node_data.get("fallbackModel") or "").strip() or None
        attempts: list[tuple[str, str]] = [(credential_id, model)]
        if fallback_credential_id and fallback_model:
            attempts.append((fallback_credential_id, fallback_model))

        from app.db.session import SessionLocal
        from app.services.encryption import decrypt_config
        from app.services.llm_service import execute_llm, execute_llm_with_tools

        if guardrails_config and guardrails_config.get("enabled"):
            from app.services.guardrails_service import (
                GuardrailCategory,
                GuardrailConfig,
                GuardrailSeverity,
                check_guardrails,
            )
            from app.services.llm_service import GOOGLE_OPENAI_BASE_URL

            raw_categories = guardrails_config.get("categories") or []
            parsed_categories: list[GuardrailCategory] = []
            for cat in raw_categories:
                try:
                    parsed_categories.append(GuardrailCategory(cat))
                except ValueError:
                    pass
            raw_severity = guardrails_config.get("severity", "medium")
            try:
                parsed_severity = GuardrailSeverity(raw_severity)
            except ValueError:
                parsed_severity = GuardrailSeverity.MEDIUM

            guardrail_credential_id = (guardrails_config.get("credential_id") or "").strip()
            guardrail_model = (guardrails_config.get("model") or "").strip()
            if not guardrail_credential_id or not guardrail_model:
                return {
                    "text": "",
                    "model": model,
                    "error": (
                        "Guardrails are enabled but credential and model are required. "
                        "Please select a Guardrail Credential and Guardrail Model in the node."
                    ),
                }

            try:
                with SessionLocal() as db:
                    guardrail_cred = self._get_accessible_credential(db, guardrail_credential_id)
                    if not guardrail_cred:
                        return {
                            "text": "",
                            "model": model,
                            "error": "Guardrail credential not found or not accessible.",
                        }
                    guardrail_credential_type = guardrail_cred.type
                    gcred_cfg = decrypt_config(guardrail_cred.encrypted_config)
                    guardrail_api_key = gcred_cfg.get("api_key")
                    guardrail_base_url = gcred_cfg.get("base_url")
                    if not guardrail_base_url and guardrail_cred.type.value == "google":
                        guardrail_base_url = GOOGLE_OPENAI_BASE_URL
                    elif guardrail_base_url and guardrail_cred.type.value == "custom":
                        guardrail_base_url = guardrail_base_url.rstrip("/")
                        if not guardrail_base_url.endswith("/v1"):
                            guardrail_base_url = guardrail_base_url + "/v1"
            except Exception as e:
                return {
                    "text": "",
                    "model": model,
                    "error": f"Failed to load guardrail credential: {e}",
                }

            if guardrail_api_key:
                cfg = GuardrailConfig(
                    enabled=True,
                    categories=parsed_categories,
                    severity=parsed_severity,
                )
                guardrail_trace_context = self._build_llm_trace_context(
                    guardrail_credential_id, node_id
                )
                check_guardrails(
                    text=user_message,
                    config=cfg,
                    credential_type=guardrail_credential_type.value,
                    api_key=guardrail_api_key,
                    base_url=guardrail_base_url,
                    model=guardrail_model,
                    trace_context=guardrail_trace_context,
                )

        mcp_connections = node_data.get("mcpConnections") or []
        merged_tools: list[dict] = list(tools)

        if hitl_enabled:
            if hitl_guidelines:
                hitl_guidelines_instruction = (
                    f"Human review guidelines from the node configuration:\n{hitl_guidelines}"
                )
                if system_instruction:
                    system_instruction = f"{system_instruction}\n\n{hitl_guidelines_instruction}"
                else:
                    system_instruction = hitl_guidelines_instruction
            hitl_guidance = (
                "Human review is available through the `request_human_review` tool.\n"
                "Use it only when the system prompt or node HITL guidelines explicitly require "
                "approval before a specific tool call, sub-agent, sub-workflow, MCP action, "
                "skill execution, or other external/important action.\n"
                "If those guidelines explicitly say an action is already approved or should not "
                "use HITL, do not request human review for it.\n"
                "Do not call it for every step.\n"
                "When you call it, provide:\n"
                "- `summary`: optional short reviewer-facing context that you generate when useful\n"
                "- `review_markdown`: a single Markdown body describing the plan or action to approve\n"
                "- `reason`: the action currently blocked on human approval\n"
                "If you omit `summary`, Heym derives one from the review Markdown.\n"
                "You may call it multiple times in the same run if new approval-required steps "
                "appear later."
            )
            if system_instruction:
                system_instruction = f"{system_instruction}\n\n{hitl_guidance}"
            else:
                system_instruction = hitl_guidance
            merged_tools.append(
                {
                    "name": "request_human_review",
                    "description": (
                        "Pause and ask a human reviewer to approve a specific next step. Use only "
                        "when the instructions explicitly require human approval before continuing."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": (
                                    "Optional short reviewer-facing summary. If omitted, Heym "
                                    "derives one from the review Markdown."
                                ),
                            },
                            "review_markdown": {
                                "type": "string",
                                "description": (
                                    "Single Markdown body that explains the exact plan or action "
                                    "the human should approve."
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "The action currently blocked on approval.",
                            },
                        },
                        "required": ["review_markdown"],
                    },
                    "_source": "hitl",
                }
            )

        for skill in skills:
            skill_files = skill.get("files") or []
            if not any(f.get("path", "").endswith(".py") for f in skill_files):
                continue
            skill_name = (skill.get("name") or "skill").replace(" ", "_").lower()
            skill_timeout = float(skill.get("timeoutSeconds") or tool_timeout_seconds)
            merged_tools.append(
                {
                    "name": f"skill_{skill_name}",
                    "description": f"Run {skill.get('name', 'skill')} Python script. Pass arguments as JSON.",
                    "parameters": json.dumps(
                        {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "description": "Input for the script"}
                            },
                            "required": [],
                        }
                    ),
                    "_source": "skill",
                    "_skill_files": skill_files,
                    "_skill_timeout": skill_timeout,
                    "_owner_id": str(self.trace_user_id) if self.trace_user_id else None,
                    "_workflow_id": str(self.workflow_id) if self.workflow_id else None,
                    "_node_id": node_id,
                    "_node_label": node_label,
                }
            )

        mcp_list_start = time.time()
        for conn in mcp_connections:
            conn = self._resolve_mcp_connection(conn, inputs, node_id)
            conn_timeout = float(conn.get("timeoutSeconds") or tool_timeout_seconds)
            try:
                mcp_tools = self._list_mcp_tools(conn, conn_timeout)
                merged_tools.extend(mcp_tools)
            except Exception as e:
                logger.warning("MCP list_tools failed for %s: %s", conn.get("label", "?"), e)
        mcp_list_ms = round((time.time() - mcp_list_start) * 1000, 2) if mcp_connections else 0.0
        hitl_policy_text = "\n\n".join(
            part for part in (base_system_instruction or "", hitl_guidelines) if part
        )
        fallback_hitl_mcp_policy = self._build_hitl_mcp_policy(hitl_policy_text, merged_tools)
        mcp_tool_names = [
            str(tool.get("name") or "") for tool in merged_tools if tool.get("_source") == "mcp"
        ]
        if hitl_enabled and mcp_tool_names:
            mcp_tool_list = ", ".join(sorted(name for name in mcp_tool_names if name))
            mcp_hint = (
                "MCP tools available in this run: "
                f"{mcp_tool_list}. If your instructions say to ask for approval before MCP calls, "
                "that includes these tool names."
            )
            if system_instruction:
                system_instruction = f"{system_instruction}\n\n{mcp_hint}"
            else:
                system_instruction = mcp_hint

        is_orchestrator = bool(node_data.get("isOrchestrator", False))
        sub_agent_labels = node_data.get("subAgentLabels") or []
        sub_workflow_ids = [
            wf_id
            for wf_id in (node_data.get("subWorkflowIds") or [])
            if isinstance(wf_id, str) and wf_id in self.workflow_cache
        ]
        if is_orchestrator and sub_agent_labels:
            call_sub_agent_tool = {
                "name": "call_sub_agent",
                "description": "Delegate a task to a specialized sub-agent. Use when the task requires expertise from another agent. When multiple sub-agents are needed for the same task (e.g. distance + food for a city), call them all in one turn—they will run in parallel.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sub_agent_label": {
                            "type": "string",
                            "enum": sub_agent_labels,
                            "description": "Label of the sub-agent to call",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Task or prompt to send to the sub-agent",
                        },
                    },
                    "required": ["sub_agent_label", "prompt"],
                },
                "_source": "sub_agent",
                "_sub_agent_labels": sub_agent_labels,
            }
            merged_tools.append(call_sub_agent_tool)

        if sub_workflow_ids:
            sub_workflow_names: dict[str, str] = {}
            configured_names = node_data.get("subWorkflowNames") or {}
            if isinstance(configured_names, dict):
                for wf_id in sub_workflow_ids:
                    raw = configured_names.get(wf_id)
                    if isinstance(raw, str) and raw.strip():
                        sub_workflow_names[str(wf_id)] = raw.strip()
            for wf_id in sub_workflow_ids:
                if wf_id in sub_workflow_names:
                    continue
                wf = self.workflow_cache.get(wf_id, {})
                cached_name = wf.get("name")
                if isinstance(cached_name, str) and cached_name.strip():
                    sub_workflow_names[wf_id] = cached_name.strip()
            workflow_hints = []
            for wf_id in sub_workflow_ids:
                wf = self.workflow_cache.get(wf_id, {})
                name = sub_workflow_names.get(wf_id) or wf.get("name") or wf_id[:8] + "..."
                input_fields = wf.get("input_fields") or []
                field_keys = [f.get("key", "text") for f in input_fields if f.get("key")]
                if not field_keys:
                    field_keys = ["text"]
                fields_desc = ", ".join(field_keys)
                workflow_hints.append(f"{name} ({wf_id}) expects inputs: {{{fields_desc}}}")
            hints_str = "; ".join(workflow_hints)
            call_sub_workflow_tool = {
                "name": "call_sub_workflow",
                "description": f"Execute a sub-workflow and get its result. Use when the task requires running a predefined workflow. Available workflows (each lists its required input keys): {hints_str}. Pass inputs as an object with those exact keys.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "enum": sub_workflow_ids,
                            "description": "ID of the workflow to execute",
                        },
                        "inputs": {
                            "type": "object",
                            "description": 'Input object. Keys must match the target workflow\'s expected fields (see workflow hints above). E.g. for text input use {"text": "value"}, for name+dob use {"name": "...", "dob": "..."}.',
                        },
                    },
                    "required": ["workflow_id", "inputs"],
                },
                "_source": "sub_workflow",
                "_sub_workflow_ids": sub_workflow_ids,
                "_sub_workflow_names": sub_workflow_names,
            }
            merged_tools.append(call_sub_workflow_tool)

        node_tool_schemas = self._build_node_tool_schemas(node_id) if node_id is not None else []
        merged_tools.extend(node_tool_schemas)

        needs_custom_executor = (
            hitl_enabled
            or (is_orchestrator and sub_agent_labels)
            or bool(sub_workflow_ids)
            or bool(node_tool_schemas)
        )

        def on_tool_call(entry: dict) -> None:
            if self.agent_progress_queue is not None:
                self.agent_progress_queue.put(
                    {
                        "type": "agent_progress",
                        "node_id": node_id,
                        "node_label": node_data.get("label", node_id or ""),
                        "entry": entry,
                    }
                )

        agent_response_format: dict | None = None
        if json_output_enabled:
            if json_output_schema:
                try:
                    schema = json.loads(json_output_schema)
                except json.JSONDecodeError as exc:
                    return {
                        "text": "",
                        "model": model,
                        "error": f"Invalid JSON output schema: {str(exc)}",
                    }
                if not isinstance(schema, dict):
                    return {
                        "text": "",
                        "model": model,
                        "error": "JSON output schema must be an object",
                    }
                schema = _ensure_additional_properties(schema)
                agent_response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": schema, "strict": True},
                }
            else:
                agent_response_format = {"type": "json_object"}

        from app.services.agent_memory_service import augment_system_instruction_with_memory

        system_instruction = augment_system_instruction_with_memory(
            system_instruction,
            self.workflow_id,
            str(node_id) if node_id else None,
            enabled=bool(node_data.get("persistentMemoryEnabled")),
            workflow_nodes=self.nodes,
            trace_user_id=self.trace_user_id,
        )

        agent_last_error: Exception | None = None
        agent_last_model = model
        agent_last_trace_id: str | None = None
        for attempt_idx, (cid, mod) in enumerate(attempts):
            credential_type = None
            api_key = None
            base_url = None
            try:
                with SessionLocal() as db:
                    cred = self._get_accessible_credential(db, cid)
                    if cred:
                        credential_type = cred.type
                        config = decrypt_config(cred.encrypted_config)
                        api_key = config.get("api_key")
                        base_url = config.get("base_url")
            except Exception as e:
                agent_last_error = e
                agent_last_model = mod
                continue

            if not api_key:
                agent_last_error = ValueError("Credential has no API key")
                agent_last_model = mod
                continue

            trace_context = self._build_llm_trace_context(cid, node_id)
            effective_hitl_mcp_policy = fallback_hitl_mcp_policy
            attempt_system_instruction = system_instruction
            if hitl_enabled and mcp_tool_names:
                classified_hitl_mcp_policy = self._classify_hitl_mcp_policy_with_model(
                    credential_type=credential_type.value,
                    api_key=api_key,
                    base_url=base_url,
                    model=mod,
                    policy_text=hitl_policy_text,
                    available_mcp_tools=mcp_tool_names,
                    trace_context=trace_context,
                )
                effective_hitl_mcp_policy = self._coerce_hitl_mcp_policy(
                    classified_hitl_mcp_policy,
                    available_mcp_tools=mcp_tool_names,
                    fallback_policy=fallback_hitl_mcp_policy,
                )
                interpreted_mcp_policy_hint = self._build_mcp_policy_interpretation_hint(
                    effective_hitl_mcp_policy
                )
                if interpreted_mcp_policy_hint:
                    if attempt_system_instruction:
                        attempt_system_instruction = (
                            f"{attempt_system_instruction}\n\n{interpreted_mcp_policy_hint}"
                        )
                    else:
                        attempt_system_instruction = interpreted_mcp_policy_hint

            custom_tool_executor = (
                self._build_agent_tool_executor(
                    node_id=node_id,
                    hitl_fallback_summary=hitl_fallback_summary,
                    hitl_mcp_policy=effective_hitl_mcp_policy,
                )
                if needs_custom_executor
                else None
            )

            try:
                if merged_tools:

                    def should_abort_tool_loop() -> str | None:
                        if self.cancel_event is not None and self.cancel_event.is_set():
                            return "Workflow execution cancelled"
                        return None

                    result = run_async(
                        execute_llm_with_tools(
                            credential_type=credential_type.value,
                            api_key=api_key,
                            base_url=base_url,
                            model=mod,
                            system_instruction=attempt_system_instruction,
                            user_message=user_message,
                            tools=merged_tools,
                            tool_timeout_seconds=tool_timeout_seconds,
                            max_tool_iterations=resume_max_tool_iterations,
                            temperature=temperature,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens,
                            response_format=agent_response_format,
                            image_input=image_input,
                            trace_context=trace_context,
                            conversation_history=conversation_history,
                            skills_included=skills_used or None,
                            on_tool_call=on_tool_call,
                            tool_executor=custom_tool_executor,
                            initial_messages=resume_messages,
                            initial_tool_calls=resume_tool_calls,
                            initial_elapsed_ms=resume_elapsed_ms,
                            initial_prompt_tokens=resume_prompt_tokens,
                            initial_completion_tokens=resume_completion_tokens,
                            should_abort=should_abort_tool_loop,
                            request_timeout=request_timeout_seconds,
                        )
                    )
                else:
                    result = run_async(
                        execute_llm(
                            credential_type=credential_type.value,
                            api_key=api_key,
                            base_url=base_url,
                            model=mod,
                            system_instruction=attempt_system_instruction,
                            user_message=user_message,
                            temperature=temperature,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens,
                            response_format=agent_response_format,
                            image_input=image_input,
                            trace_context=trace_context,
                            conversation_history=conversation_history,
                            skills_included=skills_used or None,
                            request_timeout=request_timeout_seconds,
                        )
                    )
            except Exception as e:
                agent_last_error = e
                agent_last_model = mod
                agent_last_trace_id = self._latest_trace_id(trace_context) or agent_last_trace_id
                continue

            result = dict(result)
            self._attach_latest_trace_id(result, trace_context)
            agent_last_trace_id = self._latest_trace_id(trace_context) or agent_last_trace_id
            if attempt_idx > 0:
                result["fallbackUsed"] = True
                result["model"] = mod
            if skills_used:
                tool_calls_list = result.get("tool_calls") or []
                invoked_tool_names = {
                    tc.get("name", "") for tc in tool_calls_list if tc.get("source") == "skill"
                }
                actually_used = [
                    s_name
                    for s_name in skills_used
                    if f"skill_{s_name.replace(' ', '_').lower()}" in invoked_tool_names
                ]
                if actually_used:
                    result["skills_used"] = actually_used
            if mcp_list_ms > 0:
                result["mcp_list_ms"] = mcp_list_ms
            tool_calls = result.get("tool_calls") or []
            sub_agent_times = [
                tc.get("elapsed_ms", 0) for tc in tool_calls if tc.get("name") == "call_sub_agent"
            ]
            other_times = [
                tc.get("elapsed_ms", 0) for tc in tool_calls if tc.get("name") != "call_sub_agent"
            ]
            tools_total_ms = (max(sub_agent_times) if sub_agent_times else 0) + sum(other_times)
            result["timing_breakdown"] = {
                "llm_ms": result.get("elapsed_ms", 0),
                "tools_ms": round(tools_total_ms, 2),
                "mcp_list_ms": mcp_list_ms,
            }
            if is_hitl_resume and hitl_history:
                result["hitlHistory"] = copy.deepcopy(hitl_history)
            if is_hitl_resume and not result.get("error") and "_hitl_pending" not in result:
                result["_skip_source_handles"] = ["hitl"]
                result["decision"] = hitl_resolution.get("decision")
                result["summary"] = hitl_resolution.get("summary")
                result["originalDraft"] = hitl_resolution.get("originalDraft")
                result["reviewText"] = hitl_resolution.get("reviewText")
                result["requestId"] = hitl_resolution.get("requestId")
                if hitl_resolution.get("editedText") is not None:
                    result["editedText"] = hitl_resolution.get("editedText")
                if hitl_resolution.get("refusalReason") is not None:
                    result["refusalReason"] = hitl_resolution.get("refusalReason")
                if approved_markdown:
                    result["approvedMarkdown"] = approved_markdown
            if (
                self.workflow_id
                and node_id
                and not result.get("error")
                and "_hitl_pending" not in result
            ):
                from app.services.agent_memory_service import (
                    memory_extraction_targets_for_agent_node,
                    schedule_agent_memory_extraction,
                )

                extraction_targets = memory_extraction_targets_for_agent_node(
                    self.nodes,
                    self.workflow_id,
                    str(node_id),
                    bool(node_data.get("persistentMemoryEnabled")),
                    self.trace_user_id,
                )
                for mem_wf_id, mem_canvas_id in extraction_targets:
                    schedule_agent_memory_extraction(
                        workflow_id=mem_wf_id,
                        canvas_node_id=mem_canvas_id,
                        credential_id=str(cid),
                        model=str(result.get("model") or mod),
                        user_message=user_message,
                        agent_result=copy.deepcopy(result),
                        trace_context=trace_context,
                    )
            return result

        error_output = {
            "text": "",
            "model": agent_last_model,
            "error": str(agent_last_error)
            if agent_last_error
            else "All credential/model attempts failed",
        }
        if agent_last_trace_id:
            error_output["_trace_id"] = agent_last_trace_id
        return error_output

    def _wrap_value(self, value: object) -> object:
        """Wrap value in appropriate Dot* class for attribute access (recursive)."""
        if isinstance(value, dict) and not isinstance(value, DotDict):
            wrapped_dict = DotDict()
            for k, v in value.items():
                wrapped_dict[k] = self._wrap_value(v)
            return wrapped_dict
        if isinstance(value, list) and not isinstance(value, DotList):
            return DotList([self._wrap_value(item) for item in value])
        if isinstance(value, bool) and not isinstance(value, DotBool):
            return DotBool(value)
        if isinstance(value, int) and not isinstance(value, DotInt):
            return DotInt(value)
        if isinstance(value, float) and not isinstance(value, DotFloat):
            return DotFloat(value)
        if isinstance(value, str) and not isinstance(value, DotStr):
            return DotStr(value)
        return value

    def _unwrap_value(self, value: object) -> object:
        """Convert Dot* types back to native Python types for JSON serialization."""
        if isinstance(value, DotDateTime):
            return str(value.toISO())
        if isinstance(value, DotDict):
            return {k: self._unwrap_value(v) for k, v in dict.items(value)}
        if isinstance(value, DotList):
            return [self._unwrap_value(item) for item in value]
        if isinstance(value, DotBool):
            return value._value
        if isinstance(value, DotInt):
            return int(value)
        if isinstance(value, DotFloat):
            return float(value)
        if isinstance(value, DotStr):
            return str(value)
        if isinstance(value, dict):
            return {k: self._unwrap_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._unwrap_value(item) for item in value]
        return value

    def _unwrap_scalar_value(self, value: object) -> object:
        """Convert Dot* scalars to native Python types without copying nested containers."""
        if isinstance(value, DotDateTime):
            return str(value.toISO())
        if isinstance(value, DotBool):
            return value._value
        if isinstance(value, DotInt):
            return int(value)
        if isinstance(value, DotFloat):
            return float(value)
        if isinstance(value, DotStr):
            return str(value)
        return value

    def _resolve_expression_body_raw(
        self,
        expression_body: str,
        inputs: dict,
        current_node_id: str | None = None,
    ) -> object:
        """Evaluate an expression body without a leading ``$`` and keep raw Dot* results."""
        combined = self._build_context(inputs, current_node_id)
        expr = self._transform_ternary_expression(expression_body)

        if "$" in expr:
            expr = self._substitute_nested_dollar_refs_for_eval(expr, inputs, current_node_id)

        try:
            evaluator = HeymExpressionEval(
                functions=self._get_evaluator_functions(),
                names=combined,
            )
            return evaluator.eval(expr, previously_parsed=_parse_expression_tree(expr))
        except Exception as e:
            if isinstance(e, ExpressionFunctionError):
                raise
            return self._resolve_simple_expression(expr, combined)

    def _string_concat_leaf_nodes(self, node: ast.AST) -> list[ast.AST] | None:
        """Flatten a safe string-concat ``+`` chain into leaf nodes for one-shot joining."""
        root = _expression_root_node(node)

        if isinstance(root, ast.BinOp) and isinstance(root.op, ast.Add):
            left_nodes = self._string_concat_leaf_nodes(root.left)
            if left_nodes is None:
                return None
            right_nodes = self._string_concat_leaf_nodes(root.right)
            if right_nodes is None:
                return None
            return left_nodes + right_nodes

        if isinstance(root, ast.Constant) and isinstance(root.value, str):
            return [root]

        if (
            isinstance(root, ast.Call)
            and isinstance(root.func, ast.Name)
            and root.func.id == "str"
            and len(root.args) == 1
            and not root.keywords
        ):
            return [root]

        return None

    def _try_evaluate_string_concat_expression(
        self,
        parsed: ast.AST,
        evaluator: HeymExpressionEval,
    ) -> str | None:
        """Fast path for long ``'literal' + str(...) + ...`` chains used in set/output nodes."""
        leaf_nodes = self._string_concat_leaf_nodes(parsed)
        if leaf_nodes is None or len(leaf_nodes) < 4:
            return None

        parts: list[str] = []
        for leaf in leaf_nodes:
            value = evaluator._eval(leaf)
            parts.append(str(value))
        return "".join(parts)

    def _try_resolve_variable_self_append(
        self,
        var_name: str,
        var_value_template: str,
        inputs: dict,
        current_node_id: str | None = None,
    ) -> DotList | None:
        """Optimize ``$vars.<sameVar>.add(item)`` by appending in place for array vars."""
        trimmed = var_value_template.strip()
        if not trimmed.startswith("$vars.") or not trimmed.endswith(")"):
            return None

        parts = self._split_expression_parts(trimmed[1:])
        if len(parts) != 3 or parts[0] != "vars" or parts[1] != var_name:
            return None

        method_name, method_args = self._parse_method_call(parts[2])
        if method_name != "add" or method_args is None or len(method_args) != 1:
            return None

        current_value = self.vars.get(var_name)
        if isinstance(current_value, DotList):
            target_list = current_value
        elif isinstance(current_value, list):
            wrapped_value = self._wrap_value(current_value)
            if not isinstance(wrapped_value, DotList):
                return None
            target_list = wrapped_value
        else:
            return None

        append_value = self._resolve_expression_body_raw(
            method_args[0],
            inputs,
            current_node_id,
        )
        target_list.append(append_value)
        return target_list

    def _mark_vars_context_dirty(self) -> None:
        """Invalidate cached wrapped vars/global contexts after a variable change."""
        self._wrapped_vars_cache = None
        self._wrapped_global_cache = None
        self._merged_global_context_cache = None
        self._vars_context_dirty = True

    def _refresh_vars_context_cache(self) -> None:
        """Refresh wrapped vars/global caches once per vars mutation."""
        if (
            not self._vars_context_dirty
            and self._wrapped_vars_cache is not None
            and self._wrapped_global_cache is not None
            and self._merged_global_context_cache is not None
        ):
            return

        wrapped_vars = self._wrap_value(self.vars)
        self._wrapped_vars_cache = wrapped_vars if isinstance(wrapped_vars, DotDict) else DotDict()

        merged_global = dict(self.global_variables_context)
        merged_global.update(self.vars)
        self._merged_global_context_cache = merged_global

        wrapped_global = self._wrap_value(merged_global)
        self._wrapped_global_cache = (
            wrapped_global if isinstance(wrapped_global, DotDict) else DotDict()
        )
        self._vars_context_dirty = False

    def _build_context(self, inputs: dict, current_node_id: str | None = None) -> DotDict:
        combined = DotDict()
        inherited_context = (
            inputs.get(_EXECUTION_CONTEXT_INPUT_KEY) if isinstance(inputs, dict) else None
        )
        if isinstance(inherited_context, dict):
            for label, data in inherited_context.items():
                combined[label] = self._wrap_value(data)

        for label, data in inputs.items():
            if label == _EXECUTION_CONTEXT_INPUT_KEY:
                continue
            wrapped_data = self._wrap_value(data)
            if isinstance(data, dict):
                for key, val in data.items():
                    combined[key] = self._wrap_value(val)
            combined[label] = wrapped_data

        with self.lock:
            label_to_output_snapshot = dict(self.label_to_output)
            wrapped_cache_snapshot = dict(self._wrapped_label_output_cache)

        if current_node_id:
            upstream_labels = self.get_upstream_node_labels(current_node_id)
            for label in upstream_labels:
                if label in combined:
                    continue
                if label in wrapped_cache_snapshot:
                    combined[label] = wrapped_cache_snapshot[label]
                elif label in label_to_output_snapshot:
                    combined[label] = self._wrap_value(label_to_output_snapshot[label])
        else:
            for label, data in label_to_output_snapshot.items():
                if label in combined:
                    continue
                if label in wrapped_cache_snapshot:
                    combined[label] = wrapped_cache_snapshot[label]
                else:
                    combined[label] = self._wrap_value(data)

        combined["now"] = DotDateTime(self._current_datetime())
        combined["UUID"] = uuid.uuid4().hex
        combined["null"] = None
        combined["None"] = None
        combined["undefined"] = None
        combined["true"] = True
        combined["false"] = False

        workflow_name, workflow_description = self._get_workflow_metadata()
        workflow_path = f"/workflows/{self.workflow_id}" if self.workflow_id else ""
        combined["workflowName"] = DotStr(workflow_name)
        combined["workflowDescription"] = DotStr(workflow_description)
        combined["workflowPath"] = DotStr(workflow_path)
        combined["workflowUrl"] = DotStr(self._build_workflow_url(workflow_path))
        combined["executionId"] = DotStr(self.execution_id or "")

        if self.credentials_context:
            credentials_dict = DotDict()
            for name, value in self.credentials_context.items():
                credentials_dict[name] = DotStr(value)
            combined["credentials"] = credentials_dict

        self._refresh_vars_context_cache()
        combined["vars"] = (
            self._wrapped_vars_cache if self._wrapped_vars_cache is not None else DotDict()
        )
        combined["global"] = (
            self._wrapped_global_cache if self._wrapped_global_cache is not None else DotDict()
        )
        # Keep `$input.foo` semantics without creating a self-referential cycle on `combined`.
        combined["input"] = DotDict(combined)

        return combined

    def _current_datetime(self) -> datetime:
        return datetime.now(self.configured_timezone)

    def _serialize_result(self, value: object) -> object:
        unwrapped = self._unwrap_value(value)
        if isinstance(unwrapped, (dict, list)):
            return json.dumps(unwrapped, ensure_ascii=False)
        return unwrapped

    def _has_arithmetic(self, expression: str) -> bool:
        """Check if expression contains arithmetic operators after $ references."""
        if "$" not in expression:
            return False
        arithmetic_pattern = (
            r"\$[a-zA-Z_][a-zA-Z0-9_.]*(?:\([^)]*\)|\[[^\]]*\])*"
            r"(?:\.[a-zA-Z_][a-zA-Z0-9_]*(?:\([^)]*\)|\[[^\]]*\])*)*\s*[+\-*/%]"
        )
        return bool(re.search(arithmetic_pattern, expression))

    def _resolve_value_with_dollar_refs(
        self,
        template: str,
        inputs: dict,
        node_id: str,
        *,
        preserve_type: bool = False,
    ) -> object:
        """Use arithmetic resolution for code-like ``$`` usage (e.g. ``int($x)``), else templates."""
        trimmed = template.strip()
        if not trimmed:
            return template
        if should_resolve_embedded_dollar_refs_arithmetically(trimmed, self):
            return self.resolve_arithmetic_expression(
                template, inputs, node_id, preserve_type=preserve_type
            )
        return self.evaluate_message_template(
            template, inputs, node_id, preserve_type=preserve_type
        )

    def _get_evaluator_functions(self) -> dict:
        if hasattr(self, "_evaluator_functions_cache"):
            return self._evaluator_functions_cache

        def create_date(value: str | int | None = None) -> DotDateTime:
            if value is None:
                return DotDateTime(self._current_datetime())
            if isinstance(value, str):
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = normalize_datetime_to_timezone(dt, self.configured_timezone)
                    return DotDateTime(dt)
                except ValueError:
                    return DotDateTime(self._current_datetime())
            if isinstance(value, int):
                dt = datetime.fromtimestamp(value, tz=timezone.utc)
                return DotDateTime(dt)
            return DotDateTime(self._current_datetime())

        def random_int(min_val: int = 0, max_val: int = 100) -> int:
            return random.randint(min_val, max_val)

        def _as_int_strict(value: object, name: str) -> int:
            # Note: `bool` is a subclass of `int` in Python, so disallow it explicitly.
            if isinstance(value, bool):
                raise ExpressionFunctionError(f"{name} must be an integer, not boolean")
            if isinstance(value, int):
                return int(value)
            if isinstance(value, float):
                if value.is_integer():
                    return int(value)
                raise ExpressionFunctionError(f"{name} must be an integer")
            if isinstance(value, str):
                try:
                    parsed = int(value.strip())
                except ValueError as e:
                    raise ExpressionFunctionError(f"{name} must be an integer") from e
                return parsed
            raise ExpressionFunctionError(f"{name} must be an integer")

        def range_func(a: object, b: object) -> DotList:
            start = _as_int_strict(a, "a")
            end = _as_int_strict(b, "b")
            if start > end:
                raise ExpressionFunctionError("$range(a,b) requires a <= b")
            # b is excluded: [a, a+1, ..., b-1]
            return DotList(list(range(start, end)))

        def concat_func(*args) -> DotStr:
            return DotStr("".join(str(a) if a is not None else "" for a in args))

        self._evaluator_functions_cache = {
            **DEFAULT_FUNCTIONS,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "abs": abs,
            "min": min,
            "max": max,
            "round": round,
            "sum": sum,
            "sorted": lambda lst: DotList(sorted(lst)) if isinstance(lst, list) else lst,
            "list": lambda x: DotList(x) if hasattr(x, "__iter__") else DotList([x]),
            "dict": dict,
            "array": lambda *args: DotList(args),
            "notNull": lambda lst: (
                DotList([x for x in lst if x is not None]) if isinstance(lst, list) else lst
            ),
            "upper": lambda s: s.upper() if isinstance(s, str) else s,
            "lower": lambda s: s.lower() if isinstance(s, str) else s,
            "strip": lambda s: s.strip() if isinstance(s, str) else s,
            "capitalize": lambda s: s.capitalize() if isinstance(s, str) else s,
            "title": lambda s: s.title() if isinstance(s, str) else s,
            "split": lambda s, sep=None: (
                DotList(list(s) if sep == "" else s.split(sep)) if isinstance(s, str) else s
            ),
            "join": lambda sep, lst: sep.join(lst) if isinstance(lst, list) else lst,
            "replace": lambda s, old, new: s.replace(old, new) if isinstance(s, str) else s,
            "concat": concat_func,
            "Date": create_date,
            "randomInt": random_int,
            "range": range_func,
        }
        return self._evaluator_functions_cache

    def _split_ternary_expression(self, expression: str) -> tuple[str, str, str] | None:
        depth = 0
        in_string = False
        string_char = ""
        question_index = -1

        for index, char in enumerate(expression):
            if in_string:
                if char == string_char and expression[index - 1] != "\\":
                    in_string = False
                continue

            if char in ("'", '"'):
                in_string = True
                string_char = char
                continue

            if char in "([{":
                depth += 1
                continue

            if char in ")]}":
                depth -= 1
                continue

            if char == "?" and depth == 0:
                question_index = index
                break

        if question_index == -1:
            return None

        depth = 0
        in_string = False
        string_char = ""
        colon_index = -1

        for index in range(question_index + 1, len(expression)):
            char = expression[index]
            if in_string:
                if char == string_char and expression[index - 1] != "\\":
                    in_string = False
                continue

            if char in ("'", '"'):
                in_string = True
                string_char = char
                continue

            if char in "([{":
                depth += 1
                continue

            if char in ")]}":
                depth -= 1
                continue

            if char == ":" and depth == 0:
                colon_index = index
                break

        if colon_index == -1:
            return None

        condition = expression[:question_index].strip()
        truthy = expression[question_index + 1 : colon_index].strip()
        falsy = expression[colon_index + 1 :].strip()

        return condition, truthy, falsy

    def _transform_ternary_expression(self, expression: str) -> str:
        split = self._split_ternary_expression(expression)
        if not split:
            return expression

        condition, truthy, falsy = split
        transformed_condition = self._transform_ternary_expression(condition)
        transformed_truthy = self._transform_ternary_expression(truthy)
        transformed_falsy = self._transform_ternary_expression(falsy)

        return f"({transformed_truthy}) if ({transformed_condition}) else ({transformed_falsy})"

    def _substitute_nested_dollar_refs_for_eval(
        self,
        expr: str,
        inputs: dict,
        current_node_id: str | None,
    ) -> str:
        """Turn ``range(1, int($node.field))`` into literals so ``HeymExpressionEval`` can run."""
        for _ in range(64):
            spans = self._find_expressions(expr)
            if not spans:
                break
            for start, end, dollar_expr in sorted(spans, key=lambda t: t[0], reverse=True):
                resolved = self.resolve_expression(
                    dollar_expr, inputs, current_node_id, preserve_type=True
                )
                if resolved is None:
                    replacement = "None"
                elif isinstance(resolved, str):
                    replacement = repr(resolved)
                elif isinstance(resolved, bool):
                    replacement = "True" if resolved else "False"
                elif isinstance(resolved, (dict, list)):
                    replacement = json.dumps(resolved, ensure_ascii=False)
                else:
                    replacement = str(resolved)
                expr = expr[:start] + replacement + expr[end:]
        return expr

    def resolve_expression(
        self,
        expression: str,
        inputs: dict,
        current_node_id: str | None = None,
        preserve_type: bool = False,
        raw: bool = False,
    ) -> object:
        if not expression.startswith("$"):
            return expression

        combined = self._build_context(inputs, current_node_id)
        expr = self._transform_ternary_expression(expression[1:])

        if expr == "input":
            first_input = self._first_visible_input(inputs)
            data = first_input if isinstance(first_input, dict) else {"value": first_input}
            if preserve_type or raw:
                return data
            return json.dumps(data, ensure_ascii=False)

        if "$" in expr:
            expr = self._substitute_nested_dollar_refs_for_eval(expr, inputs, current_node_id)

        try:
            parsed = _parse_expression_tree(expr)
            evaluator = HeymExpressionEval(
                functions=self._get_evaluator_functions(),
                names=combined,
            )
            result = self._try_evaluate_string_concat_expression(parsed, evaluator)
            if result is None:
                result = evaluator.eval(expr, previously_parsed=parsed)
            if raw:
                return result
            if preserve_type:
                return self._unwrap_value(result)
            return self._serialize_result(result)
        except Exception as e:
            # Critical: expression functions that indicate workflow-breaking failures must propagate.
            if isinstance(e, ExpressionFunctionError):
                raise
            result = self._resolve_simple_expression(expr, combined)
            if raw:
                return result
            if preserve_type:
                return self._unwrap_value(result)
            return self._serialize_result(result)

    def resolve_arithmetic_expression(
        self,
        expression: str,
        inputs: dict,
        current_node_id: str | None = None,
        preserve_type: bool = False,
    ) -> object:
        """Resolve expression that may contain arithmetic operations with $ references."""
        combined = self._build_context(inputs, current_node_id)

        def replace_dollar_ref(dollar_expr: str) -> str:
            expr = dollar_expr[1:] if dollar_expr.startswith("$") else dollar_expr
            expr = self._substitute_nested_dollar_refs_for_eval(expr, inputs, current_node_id)
            try:
                evaluator = HeymExpressionEval(
                    functions=self._get_evaluator_functions(),
                    names=combined,
                )
                result = evaluator.eval(expr, previously_parsed=_parse_expression_tree(expr))
                if result is None:
                    return "None"
                if isinstance(result, str):
                    return f'"{result}"'
                return str(result)
            except Exception:
                result = self._resolve_simple_expression(expr, combined)
                if result is None:
                    return "None"
                if isinstance(result, str):
                    return f'"{result}"'
                return str(result)

        processed = self._replace_expressions(expression, replace_dollar_ref)
        processed = self._transform_ternary_expression(processed)

        try:
            evaluator = HeymExpressionEval(
                functions=self._get_evaluator_functions(),
                names={},
            )
            result = evaluator.eval(
                processed,
                previously_parsed=_parse_expression_tree(processed),
            )
            if preserve_type:
                return self._unwrap_value(result)
            return self._serialize_result(result)
        except Exception as e:
            if isinstance(e, ExpressionFunctionError):
                raise
            return processed

    def _resolve_simple_expression(self, expr: str, combined: dict) -> object:
        try:
            normalized_expr = expr.lstrip("$") if expr.startswith("$") else expr

            if "(" in normalized_expr and normalized_expr.endswith(")"):
                func_name, raw_args = normalized_expr.split("(", 1)
                func_name = func_name.strip()
                raw_args = raw_args[:-1].strip()
                functions = {
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "abs": abs,
                    "min": min,
                    "max": max,
                    "round": round,
                    "sum": sum,
                    "sorted": lambda lst: DotList(sorted(lst)) if isinstance(lst, list) else lst,
                    "list": lambda x: DotList(x) if hasattr(x, "__iter__") else DotList([x]),
                    "dict": dict,
                    "array": lambda *args: DotList(args),
                    "notNull": lambda lst: (
                        DotList([x for x in lst if x is not None]) if isinstance(lst, list) else lst
                    ),
                }
                if func_name in functions:
                    args = []
                    if raw_args:
                        parsed_args = self._split_function_args(raw_args)
                        for arg in parsed_args:
                            args.append(self._resolve_simple_expression(arg.strip(), combined))
                    return functions[func_name](*args)

            parts = self._split_expression_parts(normalized_expr)
            value = combined

            string_methods = {
                "orEmpty": lambda s: s if s is not None else "",
                "or_empty": lambda s: s if s is not None else "",
                "upper": lambda s: s.upper(),
                "uppercase": lambda s: s.upper(),
                "lower": lambda s: s.lower(),
                "lowercase": lambda s: s.lower(),
                "strip": lambda s: s.strip(),
                "trim": lambda s: s.strip(),
                "capitalize": lambda s: s.capitalize(),
                "title": lambda s: s.title(),
                "length": lambda s: len(s),
                "urlEncode": lambda s: quote(s, safe=""),
                "urlDecode": lambda s: unquote(s),
                "escape": lambda s: json.dumps(s),
                "unescape": lambda s: self._safe_json_parse(s),
            }

            for index, part in enumerate(parts):
                method_name, method_args = self._parse_method_call(part)
                if (
                    value is None
                    and method_name in {"orEmpty", "or_empty"}
                    and method_args is not None
                ):
                    value = ""
                elif method_name in string_methods and isinstance(value, str):
                    value = string_methods[method_name](value)
                elif method_name == "length" and isinstance(value, (str, list)):
                    value = len(value)
                elif method_args is not None:
                    if isinstance(value, dict) and method_name == "get":
                        parsed_args = []
                        for arg in method_args:
                            if (arg.startswith('"') and arg.endswith('"')) or (
                                arg.startswith("'") and arg.endswith("'")
                            ):
                                parsed_args.append(arg[1:-1])
                            elif arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
                                parsed_args.append(int(arg))
                            elif arg.replace(".", "", 1).isdigit():
                                parsed_args.append(float(arg))
                            else:
                                parsed_args.append(self._resolve_simple_expression(arg, combined))
                        value = value.get(*parsed_args) if parsed_args else None
                    elif hasattr(value, method_name):
                        attr = getattr(value, method_name)
                        if callable(attr) and method_args is not None:
                            parsed_args = []
                            for arg in method_args:
                                if (arg.startswith('"') and arg.endswith('"')) or (
                                    arg.startswith("'") and arg.endswith("'")
                                ):
                                    parsed_args.append(arg[1:-1])
                                elif arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
                                    parsed_args.append(int(arg))
                                elif arg.replace(".", "", 1).isdigit():
                                    parsed_args.append(float(arg))
                                else:
                                    parsed_args.append(
                                        self._resolve_simple_expression(arg, combined)
                                    )
                            value = attr(*parsed_args)
                        else:
                            value = attr
                    else:
                        return None
                else:
                    splitp = self._split_property_and_subscripts(part)
                    if splitp is None:
                        return None
                    value = self._read_property_with_subscripts(value, splitp)

                if value is None:
                    next_part = parts[index + 1] if index + 1 < len(parts) else ""
                    next_method_name, next_method_args = self._parse_method_call(next_part)
                    if next_method_name in {"orEmpty", "or_empty"} and next_method_args is not None:
                        continue
                    return None

                # Re-wrap intermediate scalars so chained calls like `.length.toString()`
                # and `$Date().year.toString()` keep Dot* behavior on the next segment.
                value = self._wrap_value(value)

            return value
        except Exception:
            return None

    def _safe_json_parse(self, value: str | None) -> str | None:
        """Safely parse JSON string, handling errors gracefully."""
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # Return original string if JSON parsing fails
            return value

    def _split_expression_parts(self, expr: str) -> list[str]:
        parts = []
        current = ""
        depth = 0
        for char in expr:
            if char == "(" or char == "[":
                depth += 1
                current += char
            elif char == ")" or char == "]":
                depth -= 1
                current += char
            elif char == "." and depth == 0:
                if current:
                    parts.append(current)
                current = ""
            else:
                current += char
        if current:
            parts.append(current)
        return parts

    def _split_function_args(self, args_str: str) -> list[str]:
        """Split function arguments properly handling nested parentheses, brackets, and strings."""
        args: list[str] = []
        current = ""
        depth = 0
        in_string = False
        string_char: str | None = None

        for char in args_str:
            if in_string:
                current += char
                if char == string_char and (len(current) < 2 or current[-2] != "\\"):
                    in_string = False
                    string_char = None
                continue

            if char in ('"', "'"):
                in_string = True
                string_char = char
                current += char
                continue

            if char in ("(", "[", "{"):
                depth += 1
                current += char
                continue

            if char in (")", "]", "}"):
                depth -= 1
                current += char
                continue

            if char == "," and depth == 0:
                if current.strip():
                    args.append(current.strip())
                current = ""
                continue

            current += char

        if current.strip():
            args.append(current.strip())

        return args

    def _parse_method_call(self, part: str) -> tuple[str, list[str] | None]:
        if "(" not in part:
            return part, None
        idx = part.index("(")
        method_name = part[:idx]
        depth = 1
        end_idx = idx + 1
        in_string = False
        string_char = None
        while end_idx < len(part) and depth > 0:
            char = part[end_idx]
            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
            elif char == "(" and not in_string:
                depth += 1
            elif char == ")" and not in_string:
                depth -= 1
            end_idx += 1
        args_str = part[idx + 1 : end_idx - 1].strip() if depth == 0 else ""
        if not args_str:
            return method_name, []
        args = []
        current = ""
        depth = 0
        in_string = False
        string_char = None
        for char in args_str:
            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
                current += char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
                current += char
            elif char == "(" and not in_string:
                depth += 1
                current += char
            elif char == ")" and not in_string:
                depth -= 1
                current += char
            elif char == "," and depth == 0 and not in_string:
                args.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            args.append(current.strip())
        return method_name, args

    @staticmethod
    def _has_odd_trailing_backslashes(chars: list[str]) -> bool:
        count = 0
        for char in reversed(chars):
            if char != "\\":
                break
            count += 1
        return count % 2 == 1

    def _split_curl_tokens_tolerant(self, command: str) -> list[str]:
        """Split curl DSL that contains JSON strings inside single-quoted data args.

        Users commonly paste curl like ``-d '{"content": "..."}'`` and then interpolate
        JSON-escaped values. Apostrophes inside that JSON string (for example "What's")
        are invalid for a real shell, but Heym parses the DSL directly instead of
        executing a shell. This fallback preserves those apostrophes when they are inside
        a double-quoted JSON string nested in a single-quoted token.
        """
        tokens: list[str] = []
        current: list[str] = []
        quote: str | None = None
        in_json_double_string = False
        token_started = False
        index = 0

        while index < len(command):
            char = command[index]

            if quote is not None:
                json_like_single_quote = quote == "'" and "".join(current).lstrip().startswith(
                    ("{", "[")
                )
                if (
                    json_like_single_quote
                    and char == '"'
                    and not self._has_odd_trailing_backslashes(current)
                ):
                    in_json_double_string = not in_json_double_string
                    current.append(char)
                    index += 1
                    continue

                if char == quote and not (quote == "'" and in_json_double_string):
                    quote = None
                    token_started = True
                    index += 1
                    continue

                current.append(char)
                index += 1
                continue

            if char.isspace():
                if token_started or current:
                    tokens.append("".join(current))
                    current = []
                    token_started = False
                    in_json_double_string = False
                index += 1
                continue

            if char in ("'", '"'):
                quote = char
                token_started = True
                index += 1
                continue

            if char == "\\" and index + 1 < len(command):
                current.append(command[index + 1])
                token_started = True
                index += 2
                continue

            current.append(char)
            token_started = True
            index += 1

        if quote is not None:
            raise ValueError("No closing quotation")
        if token_started or current:
            tokens.append("".join(current))
        return tokens

    def _split_curl_tokens(self, command: str) -> list[str]:
        try:
            return shlex.split(command)
        except ValueError as original_error:
            try:
                return self._split_curl_tokens_tolerant(command)
            except ValueError:
                raise original_error from None

    def parse_curl(self, curl_command: str) -> tuple[str, str, dict[str, str], str | None, bool]:
        if not curl_command:
            return "GET", "", {}, None, False
        normalized_cmd = curl_command.replace("\\\n", " ").replace("\\\r\n", " ")
        tokens = self._split_curl_tokens(normalized_cmd)
        if tokens and tokens[0].lower() == "curl":
            tokens = tokens[1:]

        method = "GET"
        headers: dict[str, str] = {}
        data = None
        url = ""
        follow_redirects = False
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token in ("-X", "--request") and i + 1 < len(tokens):
                i += 1
                method = tokens[i].upper()
            elif token in ("-H", "--header") and i + 1 < len(tokens):
                i += 1
                header = tokens[i]
                if ":" in header:
                    key, value = header.split(":", 1)
                    headers[key.strip()] = value.strip()
            elif token in ("-L", "--location"):
                follow_redirects = True
            elif token in (
                "-d",
                "--data",
                "--data-raw",
                "--data-binary",
                "--data-urlencode",
            ) and i + 1 < len(tokens):
                i += 1
                data = tokens[i]
                if method == "GET":
                    method = "POST"
            elif token == "--url" and i + 1 < len(tokens):
                i += 1
                url = tokens[i]
            elif token.startswith("http://") or token.startswith("https://"):
                url = token
            i += 1

        if not url:
            for token in reversed(tokens):
                if token.startswith("http://") or token.startswith("https://"):
                    url = token
                    break

        return method, url, headers, data, follow_redirects

    def _find_expressions(self, text: str) -> list[tuple[int, int, str]]:
        """Find all $ expressions with proper nested parentheses handling."""
        expressions = []
        i = 0
        while i < len(text):
            if text[i] == "$" and (i + 1 < len(text)) and text[i + 1].isalpha():
                start = i
                i += 1
                while i < len(text) and (text[i].isalnum() or text[i] in "_."):
                    i += 1
                while i < len(text):
                    while i < len(text) and text[i] in "([":
                        bracket = text[i]
                        close_bracket = ")" if bracket == "(" else "]"
                        depth = 1
                        i += 1
                        while i < len(text) and depth > 0:
                            if text[i] == bracket:
                                depth += 1
                            elif text[i] == close_bracket:
                                depth -= 1
                            elif text[i] == '"' or text[i] == "'":
                                quote = text[i]
                                i += 1
                                while i < len(text) and text[i] != quote:
                                    if text[i] == "\\":
                                        i += 1
                                    i += 1
                            i += 1
                    if i < len(text) and text[i] == ".":
                        i += 1
                        while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                            i += 1
                        continue
                    break
                expressions.append((start, i, text[start:i]))
            else:
                i += 1
        return expressions

    def _is_single_dollar_expression(self, template: str) -> bool:
        """True when the whole trimmed string is a single expression, not a text template."""
        return _is_single_dollar_expression(
            template,
            find_expressions=self._find_expressions,
            transform_ternary_expression=self._transform_ternary_expression,
        )

    def _extract_square_bracket_inner(self, s: str, start: int) -> tuple[str | None, int]:
        """s[start] must be '['. Returns (inner_content, index_after_closing_bracket)."""
        if start >= len(s) or s[start] != "[":
            return None, start
        i = start + 1
        depth = 1
        in_string = False
        string_char: str | None = None
        inner_start = i
        while i < len(s) and depth > 0:
            c = s[i]
            if in_string:
                if c == "\\" and i + 1 < len(s):
                    i += 2
                    continue
                if c == string_char:
                    in_string = False
                    string_char = None
                i += 1
                continue
            if c in ('"', "'"):
                in_string = True
                string_char = c
                i += 1
                continue
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return s[inner_start:i], i + 1
            i += 1
        return None, start

    def _split_property_and_subscripts(self, part: str) -> tuple[str, list[str]] | None:
        """Parse 'name', 'name[0]', 'name[\"a-b\"]' into base identifier and bracket contents."""
        if "(" in part:
            return None
        if "[" not in part:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", part):
                return None
            return (part, [])
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)(.*)$", part)
        if not m:
            return None
        base = m.group(1)
        rest = m.group(2)
        inners: list[str] = []
        idx = 0
        while idx < len(rest):
            if rest[idx] != "[":
                return None
            inner, nxt = self._extract_square_bracket_inner(rest, idx)
            if inner is None:
                return None
            inners.append(inner)
            idx = nxt
        return (base, inners)

    def _coerce_subscript_key(self, inner: str) -> str | int:
        """Turn bracket inner text into a dict key or integer index."""
        inner_st = inner.strip()
        if len(inner_st) >= 2 and inner_st[0] == inner_st[-1] and inner_st[0] in ('"', "'"):
            raw = inner_st[1:-1]
            return bytes(raw, "utf-8").decode("unicode_escape")
        if inner_st.isdigit() or (inner_st.startswith("-") and inner_st[1:].isdigit()):
            return int(inner_st)
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", inner_st):
            return inner_st
        return inner_st

    def _read_property_with_subscripts(
        self, value: object, splitp: tuple[str, list[str]]
    ) -> object | None:
        base, inners = splitp
        if isinstance(value, dict):
            cur = value.get(base)
        elif hasattr(value, base):
            cur = getattr(value, base, None)
        else:
            return None
        for inner in inners:
            key = self._coerce_subscript_key(inner)
            if cur is None:
                return None
            if isinstance(key, int):
                if isinstance(cur, (list, str)) and 0 <= key < len(cur):
                    cur = cur[key]
                else:
                    return None
            elif isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        return cur

    def _replace_expressions(self, text: str, replacer: Callable[[str], str]) -> str:
        """Replace all $ expressions in text using the replacer function."""
        expressions = self._find_expressions(text)
        if not expressions:
            return text
        result = []
        last_end = 0
        for start, end, expr in expressions:
            result.append(text[last_end:start])
            result.append(replacer(expr))
            last_end = end
        result.append(text[last_end:])
        return "".join(result)

    def _eval_substituted_python_expression(
        self,
        processed: str,
        *,
        coerce_bool: bool,
    ) -> Any:
        """Evaluate Python text after ``$...`` spans were replaced (shared by condition vs value).

        SECURITY: This must NEVER use Python's built-in `eval()`. Clearing `__builtins__`
        does not stop attribute traversal — exposing real Python types (`str`, `int`,
        `len`) in the locals lets a workflow author reach `object.__subclasses__()`
        and from there any class loaded in the interpreter (sandbox escape -> RCE).
        The verified gadget is `str.__class__.__bases__[0].__subclasses__()` -> pick a
        class whose `__init__.__globals__` exposes `__builtins__["__import__"]`.

        We route through `HeymExpressionEval` (a `simpleeval.EvalWithCompoundTypes`
        subclass) which walks an AST and refuses dunder attribute access. The JS-style
        literal aliases (`true`/`false`/`null`/`undefined`) are passed via `names`
        because simpleeval only recognises Python's `True`/`False`/`None` natively;
        without them, conditions like `$x == true` raise `NameNotDefined`.

        See security advisory GHSA-pm6h-x3h5-j38h, finding C1.
        """
        processed = _normalize_js_logical_ops_for_eval(processed)
        evaluator = HeymExpressionEval(
            functions=self._get_evaluator_functions(),
            names={
                # JS-style literal aliases — simpleeval doesn't recognise these
                # as Python literals, so they must be in `names`. `True`/`False`/
                # `None` are Python literals and simpleeval handles them natively.
                "true": True,
                "false": False,
                "null": None,
                "undefined": None,
            },
        )
        try:
            result = evaluator.eval(processed)
        except Exception as exc:
            # Re-raise as ValueError so callers (evaluate_condition) can fall back
            # to False without surfacing internal exception types. The service path
            # (ExpressionEvaluatorService.evaluate) catches this ValueError and
            # returns ExpressionEvaluateResponse(result=None, result_type="null",
            # error=str(exc)) -- so the executor raises and the service returns an
            # error response, but both reject the same payloads.
            raise ValueError(f"Invalid condition expression: {exc}") from exc
        return bool(result) if coerce_bool else result

    def evaluate_expression_tail_strict(
        self,
        expression: str,
        inputs: dict,
        current_node_id: str | None = None,
    ) -> Any:
        """Evaluate one leading ``$...`` span plus a non-boolean tail (e.g. arithmetic); raw result."""

        def replace_expr(expr: str) -> str:
            result = self.resolve_expression(expr, inputs, current_node_id)
            if result is None:
                return "None"
            if isinstance(result, str):
                return repr(result)
            return str(result)

        processed = self._replace_expressions(expression, replace_expr)
        return self._eval_substituted_python_expression(processed, coerce_bool=False)

    def evaluate_condition_strict(
        self, condition: str, inputs: dict, current_node_id: str | None = None
    ) -> bool:
        """Evaluate a condition string like the workflow branch node; propagate errors."""

        def replace_expr(expr: str) -> str:
            result = self.resolve_expression(expr, inputs, current_node_id)
            if result is None:
                return "None"
            if isinstance(result, str):
                return repr(result)
            return str(result)

        processed = self._replace_expressions(condition, replace_expr)
        return self._eval_substituted_python_expression(processed, coerce_bool=True)

    def evaluate_condition(
        self, condition: str, inputs: dict, current_node_id: str | None = None
    ) -> bool:
        try:
            return self.evaluate_condition_strict(condition, inputs, current_node_id)
        except Exception:
            return False

    def evaluate_message_template(
        self,
        template: str,
        inputs: dict,
        current_node_id: str | None = None,
        preserve_type: bool = False,
    ) -> str:
        if not template:
            return str(inputs)

        def replace_expr(expr: str) -> str:
            result = self.resolve_expression(
                expr, inputs, current_node_id, preserve_type=preserve_type
            )
            if preserve_type and isinstance(result, str):
                return result
            return str(result) if result is not None else expr

        return self._replace_expressions(template, replace_expr)

    def evaluate_nonempty_message_template(
        self,
        template: str,
        inputs: dict,
        current_node_id: str | None = None,
    ) -> str:
        """Evaluate a template; blank templates return empty instead of str(inputs)."""
        normalized = str(template or "")
        if not normalized.strip():
            return ""
        return self.evaluate_message_template(normalized, inputs, current_node_id)

    def _resolve_expressions_in_code(self, code: str, inputs: dict, node_id: str) -> str:
        """Replace Heym expressions ($node.field) in Python code with resolved values."""
        import re

        def replace_expr(match: re.Match) -> str:
            expr = match.group(1)
            try:
                resolved = self.resolve_expression("$" + expr, inputs, node_id, preserve_type=True)
                if isinstance(resolved, str):
                    return repr(resolved)
                return repr(resolved)
            except Exception:
                return match.group(0)

        return re.sub(r"\$([a-zA-Z_][a-zA-Z0-9_.]*)", replace_expr, code)

    def _resolve_playwright_auth_state(
        self,
        auth_state_expression: str,
        inputs: dict,
        node_id: str,
    ) -> dict[str, object] | None:
        """Resolve and normalize Playwright auth state from an expression or raw JSON."""
        from app.services.playwright_code_generator import normalize_playwright_auth_state

        if not auth_state_expression or not str(auth_state_expression).strip():
            return None

        expr = str(auth_state_expression).strip()
        if expr.startswith("$") and " " not in expr:
            resolved = self.resolve_expression(expr, inputs, node_id, preserve_type=True)
        else:
            resolved = self._resolve_template(expr, inputs, node_id)
        return normalize_playwright_auth_state(resolved)

    def _playwright_subprocess_inputs(self, inputs: dict) -> dict:
        """Copy of node inputs plus ``vars`` so step fields like ``$vars.searchUrl`` resolve in subprocess.

        Template/expression evaluation uses ``_build_context``, which already exposes ``vars`` from
        ``self.vars``. Generated Playwright code reads a flat ``inputs`` dict only, so variable
        node outputs must be injected under the ``vars`` key before serializing to the runner.
        """
        out = copy.deepcopy(inputs)
        vars_ns = copy.deepcopy(self.vars)
        existing = out.get("vars")
        if isinstance(existing, dict):
            out["vars"] = {**existing, **vars_ns}
        else:
            out["vars"] = vars_ns
        return out

    def _execute_playwright_node(
        self, node_data: dict, inputs: dict, node_id: str, node_label: str
    ) -> dict:
        from app.services.playwright_code_generator import generate_playwright_code
        from app.services.playwright_execution_tokens import create_token

        steps = node_data.get("playwrightSteps") or []
        auth_enabled = node_data.get("playwrightAuthEnabled", False) is True
        playwright_code = node_data.get("playwrightCode", "").strip()
        capture_network = node_data.get("playwrightCaptureNetwork", False)
        auth_state: dict[str, object] | None = None
        auth_check_selector = ""
        auth_check_timeout = 5000
        auth_fallback_steps = node_data.get("playwrightAuthFallbackSteps") or []

        if auth_enabled:
            if not steps:
                raise ValueError(
                    "Playwright auth bootstrap requires step-based execution. Custom code is not supported."
                )
            if steps[0].get("action") != "navigate":
                raise ValueError(
                    "Playwright auth bootstrap requires the first Playwright step to be a navigate action."
                )

            auth_check_selector = self._resolve_template(
                str(node_data.get("playwrightAuthCheckSelector", "") or ""),
                inputs,
                node_id,
            ).strip()
            if not auth_check_selector:
                raise ValueError(
                    "Playwright auth bootstrap requires an authenticated selector to verify login."
                )

            raw_auth_check_timeout = node_data.get("playwrightAuthCheckTimeout", 5000)
            try:
                auth_check_timeout = max(1, int(raw_auth_check_timeout))
            except (TypeError, ValueError):
                auth_check_timeout = 5000

            auth_state_expression = str(node_data.get("playwrightAuthStateExpression", "") or "")
            auth_state = self._resolve_playwright_auth_state(
                auth_state_expression,
                inputs,
                node_id,
            )

        if steps:
            playwright_code = generate_playwright_code(
                steps,
                capture_network=capture_network,
                auth_enabled=auth_enabled,
                auth_state=auth_state,
                auth_check_selector=auth_check_selector,
                auth_check_timeout=auth_check_timeout,
                auth_fallback_steps=auth_fallback_steps,
            )
        elif not playwright_code:
            raise ValueError(
                "Playwright node requires steps. Add at least one step (navigate, click, etc.)."
            )

        headless = node_data.get("playwrightHeadless", True)
        # In Docker/headless environments (no DISPLAY), force headless to avoid "Missing X server" errors
        if not os.environ.get("DISPLAY"):
            headless = True
        timeout_ms = node_data.get("playwrightTimeout", 30000)

        has_ai_steps = any(s.get("action") == "aiStep" for s in steps)
        heym_api_url = ""
        heym_execution_token = ""
        if has_ai_steps:
            if not self.trace_user_id:
                raise ValueError(
                    "Playwright AI step requires workflow execution context (trace_user_id). "
                    "AI steps cannot run in anonymous or cron-triggered workflows without user context."
                )
            heym_api_url = os.environ.get("HEYM_API_URL", "http://localhost:10105")
            heym_execution_token = create_token(str(self.trace_user_id))

        import subprocess
        import sys
        import tempfile

        playwright_inputs = self._playwright_subprocess_inputs(inputs)
        resolved_code = self._resolve_expressions_in_code(
            playwright_code, playwright_inputs, node_id
        )
        script_content = _build_playwright_script(
            resolved_code,
            playwright_inputs,
            headless=headless,
            timeout_ms=timeout_ms,
            capture_network=capture_network,
            heym_api_url=heym_api_url,
            heym_execution_token=heym_execution_token,
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            script_path = f.name
        stdout_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".playwright.out", delete=False)
        stderr_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".playwright.err", delete=False)
        stdout_path = stdout_file.name
        stderr_path = stderr_file.name

        try:
            # playwrightTimeout = total max execution time (ms). Subprocess enforces it strictly.
            subprocess_timeout = max(timeout_ms / 1000, 10)
            popen_kwargs: dict[str, object] = {
                "stdout": stdout_file,
                "stderr": stderr_file,
                "text": True,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True

            process = subprocess.Popen(
                [sys.executable, script_path],
                **popen_kwargs,
            )
            started_at = time.monotonic()
            timed_out = False

            while process.poll() is None:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    self._terminate_subprocess(process)
                    self.check_cancelled()

                if time.monotonic() - started_at >= subprocess_timeout:
                    timed_out = True
                    self._terminate_subprocess(process)
                    break

                time.sleep(0.1)

            stdout_file.flush()
            stderr_file.flush()
            stdout_file.close()
            stderr_file.close()
            stdout = ""
            stderr = ""
            try:
                with open(stdout_path, encoding="utf-8") as stdout_reader:
                    stdout = stdout_reader.read()
            except OSError:
                stdout = ""
            try:
                with open(stderr_path, encoding="utf-8") as stderr_reader:
                    stderr = stderr_reader.read()
            except OSError:
                stderr = ""
            self.check_cancelled()

            if timed_out:
                raise ValueError(
                    f"Playwright script timed out after {subprocess_timeout:.1f} seconds"
                )

            if process.returncode != 0:
                raise ValueError(f"Playwright script failed: {stderr or stdout or 'Unknown error'}")

            output_str = stdout.strip()
            if not output_str:
                return {"status": "ok", "results": {}}

            try:
                output = json.loads(output_str)
            except json.JSONDecodeError:
                return {"status": "ok", "results": {"raw": output_str}}

            return output
        finally:
            for temp_path in (stdout_path, stderr_path, script_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            if not stdout_file.closed:
                stdout_file.close()
            if not stderr_file.closed:
                stderr_file.close()

    def execute_node(
        self,
        node_id: str,
        inputs: dict,
        allow_branch_skip: bool = True,
        on_retry: Callable[[NodeResult, int, int], None] | None = None,
    ) -> NodeResult:
        """Public entry: wrap node execution in an OTel span (no-op when disabled)."""
        if not tracing.is_enabled():
            return self._execute_node_inner(node_id, inputs, allow_branch_skip, on_retry)

        def _run() -> NodeResult:
            tracer = tracing.get_tracer()
            node = self.nodes.get(node_id, {})
            node_data = node.get("data", {}) if isinstance(node, dict) else {}
            with tracer.start_as_current_span("heym.node.execute") as span:
                span.set_attribute("heym.node.id", str(node_id))
                span.set_attribute("heym.node.type", node.get("type", "unknown"))
                span.set_attribute("heym.node.label", node_data.get("label", node_id))
                if self.workflow_id is not None:
                    span.set_attribute("heym.workflow.id", str(self.workflow_id))
                result = self._execute_node_inner(node_id, inputs, allow_branch_skip, on_retry)
                _annotate_node_span(span, result)
                if tracing.capture_node_io_enabled():
                    _attach_node_io(span, inputs, result.output)
                return result

        # Re-attach the workflow root context so node spans nest under the workflow
        # span even when this runs inside a ThreadPoolExecutor worker thread.
        root_ctx = getattr(self, "_otel_root_context", None)
        if root_ctx is not None:
            return tracing.run_with_context(root_ctx, _run)
        return _run()

    def _execute_node_inner(
        self,
        node_id: str,
        inputs: dict,
        allow_branch_skip: bool = True,
        on_retry: Callable[[NodeResult, int, int], None] | None = None,
    ) -> NodeResult:
        start_time = time.time()
        self.check_cancelled()
        node = self.nodes[node_id]
        node_type = node.get("type", "unknown")
        node_data = node.get("data", {})
        node_label = node_data.get("label", node_id)

        retry_enabled = node_data.get("retryEnabled", False)
        retry_max_attempts = node_data.get("retryMaxAttempts", 3) if retry_enabled else 1
        retry_wait_seconds = node_data.get("retryWaitSeconds", 5) if retry_enabled else 0
        on_error_enabled = node_data.get("onErrorEnabled", False)

        last_error = None
        attempt = 0
        pending_retry_result: NodeResult | None = None

        while attempt < retry_max_attempts:
            attempt += 1
            self.check_cancelled()
            if attempt > 1 and on_retry and pending_retry_result is not None:
                on_retry(pending_retry_result, attempt, retry_max_attempts)
                pending_retry_result = None
            attempt_start_time = time.time()
            try:
                return self._execute_node_logic(
                    node_id,
                    inputs,
                    allow_branch_skip,
                    start_time,
                    node,
                    node_type,
                    node_data,
                    node_label,
                )
            except Exception as e:
                if isinstance(e, WorkflowCancelledError):
                    raise
                last_error = e
                # GuardrailViolationError is an intentional block — never retry
                from app.services.guardrails_service import GuardrailViolationError

                if isinstance(e, GuardrailViolationError):
                    break
                if attempt < retry_max_attempts:
                    pending_retry_result = self._record_retry_attempt_result(
                        node_id=node_id,
                        node_label=node_label,
                        node_type=node_type,
                        error=e,
                        attempt=attempt,
                        max_attempts=retry_max_attempts,
                        retry_wait_seconds=retry_wait_seconds,
                        execution_time_ms=(time.time() - attempt_start_time) * 1000,
                    )
                    self.check_cancelled()
                    time.sleep(retry_wait_seconds)
                    continue
                break

        execution_time = (time.time() - start_time) * 1000

        from app.services.guardrails_service import GuardrailViolationError

        output_base = {"error": str(last_error)}
        if isinstance(last_error, GuardrailViolationError):
            output_base["guardrail_violated_categories"] = getattr(last_error, "categories", [])
        error_metadata: dict[str, Any] = {}
        trace_id = getattr(last_error, "trace_id", None)
        if isinstance(trace_id, str) and trace_id:
            error_metadata["trace_id"] = trace_id

        if on_error_enabled:
            output_base["_errorBranch"] = True
            return NodeResult(
                node_id=node_id,
                node_label=node_label,
                node_type=node_type,
                status="success",
                output=output_base,
                execution_time_ms=execution_time,
                metadata=error_metadata,
            )

        return NodeResult(
            node_id=node_id,
            node_label=node_label,
            node_type=node_type,
            status="error",
            output=output_base,
            execution_time_ms=execution_time,
            error=str(last_error),
            metadata=error_metadata,
        )

    def _execute_node_logic(
        self,
        node_id: str,
        inputs: dict,
        allow_branch_skip: bool,
        start_time: float,
        node: dict,
        node_type: str,
        node_data: dict,
        node_label: str,
    ) -> NodeResult:
        try:
            self.check_cancelled()
            if self.test_mode and node_data.get("pinnedData") is not None:
                pinned_output = node_data.get("pinnedData")
                output = (
                    copy.deepcopy(pinned_output)
                    if isinstance(pinned_output, dict)
                    else {"value": pinned_output}
                )
                if allow_branch_skip and node_type == "condition":
                    branch = output.get("branch")
                    true_targets = self.get_downstream_nodes(node_id, "true")
                    false_targets = self.get_downstream_nodes(node_id, "false")
                    if branch == "true":
                        output["_skip_loop_source_handles"] = ["false"]
                        loop_back_targets = self._loop_back_targets_for_source_handle(
                            node_id, "true"
                        )
                        self.skip_branch_targets_preserving_shared_downstream(
                            node_id,
                            active_targets=true_targets,
                            inactive_targets=false_targets,
                            active_exclude_node_ids=loop_back_targets,
                            inactive_stop_node_ids=loop_back_targets,
                        )
                    elif branch == "false":
                        output["_skip_loop_source_handles"] = ["true"]
                        loop_back_targets = self._loop_back_targets_for_source_handle(
                            node_id, "false"
                        )
                        self.skip_branch_targets_preserving_shared_downstream(
                            node_id,
                            active_targets=false_targets,
                            inactive_targets=true_targets,
                            active_exclude_node_ids=loop_back_targets,
                            inactive_stop_node_ids=loop_back_targets,
                        )
                if allow_branch_skip and node_type == "switch":
                    branch = output.get("branch")
                    cases = node_data.get("cases", [])
                    if isinstance(cases, list):
                        handles = [f"case-{index}" for index in range(len(cases))]
                    else:
                        handles = []
                    handles.append("default")
                    if branch:
                        active_targets = self.get_downstream_nodes(node_id, branch)
                        inactive_targets: list[str] = []
                        skipped_handles: list[str] = []
                        for handle_id in handles:
                            if handle_id != branch:
                                skipped_handles.append(handle_id)
                                inactive_targets.extend(
                                    self.get_downstream_nodes(node_id, handle_id)
                                )
                        output["_skip_loop_source_handles"] = skipped_handles
                        loop_back_targets = self._loop_back_targets_for_source_handle(
                            node_id, branch
                        )
                        self.skip_branch_targets_preserving_shared_downstream(
                            node_id,
                            active_targets=active_targets,
                            inactive_targets=inactive_targets,
                            active_exclude_node_ids=loop_back_targets,
                            inactive_stop_node_ids=loop_back_targets,
                        )
                execution_time_ms = (time.time() - start_time) * 1000
                return NodeResult(
                    node_id=node_id,
                    node_label=node_label,
                    node_type=node_type,
                    status="success",
                    output=output,
                    execution_time_ms=execution_time_ms,
                )
            handler_output = execute_node_handler(
                NodeExecutionContext(
                    executor=self,
                    node_id=node_id,
                    inputs=inputs,
                    allow_branch_skip=allow_branch_skip,
                    start_time=start_time,
                    node=node,
                    node_type=node_type,
                    node_data=node_data,
                    node_label=node_label,
                )
            )
            if isinstance(handler_output, NodeResult):
                return handler_output
            output = handler_output

            execution_time = (time.time() - start_time) * 1000
            metadata: dict = {}
            skip_source_handles = output.pop("_skip_source_handles", None)
            if isinstance(skip_source_handles, list):
                metadata["skip_source_handles"] = skip_source_handles
            skip_loop_source_handles = output.pop("_skip_loop_source_handles", None)
            if isinstance(skip_loop_source_handles, list):
                metadata["skip_loop_source_handles"] = skip_loop_source_handles
            trace_id = self._pop_internal_trace_id(output)
            if trace_id:
                metadata["trace_id"] = trace_id

            return NodeResult(
                node_id=node_id,
                node_label=node_label,
                node_type=node_type,
                status="success",
                output=output,
                execution_time_ms=execution_time,
                metadata=metadata,
            )

        except Exception:
            raise

    def execute_error_flow(
        self, error_nodes: set[str], edges: list[dict], error_payload: dict
    ) -> tuple[list[NodeResult], dict | None]:
        pending_count = {node_id: 0 for node_id in error_nodes}
        for edge in edges:
            if edge["target"] in pending_count:
                pending_count[edge["target"]] += 1

        queue = [node_id for node_id, count in pending_count.items() if count == 0]
        results: list[NodeResult] = []
        completed: set[str] = set()
        error_flow_output = None

        output_nodes_with_downstream = set()
        for node_id in error_nodes:
            node = self.nodes.get(node_id, {})
            if node.get("type") == "output" and node.get("data", {}).get("allowDownstream"):
                output_nodes_with_downstream.add(node_id)

        while queue:
            node_id = queue.pop(0)
            if node_id in completed:
                continue
            node = self.nodes.get(node_id, {})
            node_type = node.get("type")
            if node_id in self.skipped_nodes:
                node_label = node.get("data", {}).get("label", node_id)
                results.append(
                    self._stamp_node_result(
                        NodeResult(
                            node_id=node_id,
                            node_label=node_label,
                            node_type=node_type or "unknown",
                            status="skipped",
                            output={},
                            execution_time_ms=0,
                        )
                    )
                )
                completed.add(node_id)
                for edge in edges:
                    if edge["source"] == node_id:
                        target = edge["target"]
                        if target in pending_count:
                            pending_count[target] -= 1
                            if pending_count[target] == 0:
                                queue.append(target)
                continue
            if node_type == "errorHandler":
                inputs = {"error": error_payload}
            else:
                inputs = self.get_node_inputs_for_edges(node_id, edges)
            result = self.execute_node_parallel(node_id, inputs)
            results.append(result)
            completed.add(node_id)

            if node_type == "output" and result.status == "success":
                error_flow_output = {result.node_label: result.output}
                if node_id in output_nodes_with_downstream:
                    remaining_queue = list(queue)
                    remaining_pending = dict(pending_count)
                    remaining_completed = set(completed)
                    for edge in edges:
                        if edge["source"] == node_id:
                            target = edge["target"]
                            if target in remaining_pending:
                                remaining_pending[target] -= 1
                                if remaining_pending[target] == 0:
                                    remaining_queue.append(target)
                    if remaining_queue:

                        def run_downstream():
                            dq = remaining_queue
                            dp = remaining_pending
                            dc = remaining_completed
                            while dq:
                                nid = dq.pop(0)
                                if nid in dc:
                                    continue
                                if nid in self.skipped_nodes:
                                    dc.add(nid)
                                    for e in edges:
                                        if e["source"] == nid and e["target"] in dp:
                                            dp[e["target"]] -= 1
                                            if dp[e["target"]] == 0:
                                                dq.append(e["target"])
                                    continue
                                inp = self.get_node_inputs_for_edges(nid, edges)
                                self.execute_node_parallel(nid, inp)
                                dc.add(nid)
                                for e in edges:
                                    if e["source"] == nid and e["target"] in dp:
                                        dp[e["target"]] -= 1
                                        if dp[e["target"]] == 0:
                                            dq.append(e["target"])

                        _SHARED_EXECUTOR.submit(run_downstream)
                    return results, error_flow_output

            for edge in edges:
                if edge["source"] == node_id:
                    target = edge["target"]
                    if target in pending_count:
                        pending_count[target] -= 1
                        if pending_count[target] == 0:
                            queue.append(target)

        return results, error_flow_output

    def _ensure_execution_id(self) -> None:
        """Assign a runtime execution id once per run (empty in the preview evaluator,
        which never enters a run entry point). Set before nodes run so `$executionId`
        is stable across all nodes. The API layer normally passes the same id it uses
        for the ExecutionHistory row, so `$executionId` is a valid deep-link segment;
        this fallback (canonical UUID string) only applies when no id was supplied."""
        if not self.execution_id:
            self.execution_id = str(uuid.uuid4())

    def execute(self, workflow_id: uuid.UUID, initial_inputs: dict) -> ExecutionResult:
        """Public entry: wrap the whole workflow run in an OTel root span."""
        self._ensure_execution_id()
        if not tracing.is_enabled():
            return self._execute_inner(workflow_id, initial_inputs)

        tracer = tracing.get_tracer()
        from opentelemetry.trace import Status, StatusCode

        with tracer.start_as_current_span("heym.workflow.execute") as span:
            span.set_attribute("heym.workflow.id", str(workflow_id))
            span.set_attribute("heym.node.count", len(self.nodes))
            span.set_attribute("heym.workflow.test_mode", bool(self.test_mode))
            span.set_attribute("heym.sub_workflow.depth", int(self._sub_workflow_invocation_depth))
            # Capture the context (with the root span active) so node spans created in
            # worker threads can re-attach it and nest correctly.
            self._otel_root_context = tracing.capture_context()
            try:
                result = self._execute_inner(workflow_id, initial_inputs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            finally:
                self._otel_root_context = None
            if getattr(result, "status", "") in ("error", "failed"):
                span.set_status(Status(StatusCode.ERROR, "workflow failed"))
            else:
                span.set_attribute("heym.workflow.status", getattr(result, "status", ""))
            return result

    def _execute_inner(self, workflow_id: uuid.UUID, initial_inputs: dict) -> ExecutionResult:
        start_time = time.time()
        self._arm_deadline()
        self.check_cancelled()
        node_results: list[NodeResult] = []
        error_flow_nodes = self.get_error_flow_nodes()
        # Set of node IDs that are connected as tools to an agent (should not run in regular flow)
        tool_node_ids = {
            edge["source"] for edge in self.edges if edge.get("targetHandle") == "tool-input"
        }
        active_edges = [
            edge
            for edge in self.get_active_edges()
            if edge["source"] not in error_flow_nodes
            and edge["target"] not in error_flow_nodes
            and edge.get("targetHandle") != "tool-input"
        ]
        active_nodes = [
            node_id
            for node_id in self.nodes
            if node_id not in error_flow_nodes and node_id not in tool_node_ids
        ]

        for node_id in self.get_input_nodes():
            node = self.nodes[node_id]
            if node.get("type") == "textInput":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
                body = initial_inputs.get("body") if isinstance(initial_inputs, dict) else {}
                if isinstance(body, dict) and "text" in body:
                    node["data"]["value"] = body["text"]
                elif isinstance(initial_inputs, dict) and "text" in initial_inputs:
                    node["data"]["value"] = initial_inputs["text"]
            elif (
                node.get("type") == "rabbitmq"
                and node.get("data", {}).get("rabbitmqOperation") == "receive"
            ):
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
            elif node.get("type") == "imapTrigger":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
            elif node.get("type") == "websocketTrigger":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
            elif node.get("type") == "slackTrigger":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
            elif node.get("type") == "discordTrigger":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
            elif node.get("type") == "telegramTrigger":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs

        pending_count: dict[str, int] = {}
        for node_id in active_nodes:
            node = self.nodes.get(node_id, {})
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
        has_error = False
        error_result = None
        pending_result = None
        pending_lock = Lock()
        early_return_output = None

        output_nodes_with_downstream = set()
        for node_id in active_nodes:
            node = self.nodes.get(node_id, {})
            if (node.get("type") == "output" and node.get("data", {}).get("allowDownstream")) or (
                self.return_on_chart_output and node.get("type") == "chartOutput"
            ):
                output_nodes_with_downstream.add(node_id)

        def schedule_downstream(
            source_node_id: str, source_result: NodeResult | None = None
        ) -> None:
            self.check_cancelled()
            skip_source_handles = (
                set(source_result.metadata.get("skip_source_handles") or [])
                if source_result
                else set()
            )
            skip_loop_source_handles = (
                set(source_result.metadata.get("skip_loop_source_handles") or [])
                if source_result
                else set()
            )
            source_is_skipped = source_result is not None and source_result.status == "skipped"
            source_node = self.nodes.get(source_node_id, {})
            if (
                source_node.get("type") == "loop"
                and source_result is not None
                and source_result.output.get("branch") == "done"
            ):
                self.prepare_branch_targets_for_execution(
                    start_node_ids=self.get_downstream_nodes(source_node_id, "done"),
                    active_edges=active_edges,
                    completed_nodes=completed_nodes,
                    pending_count=pending_count,
                )
            for edge in active_edges:
                if edge["source"] == source_node_id:
                    if self._source_handle_is_skipped(edge, skip_source_handles):
                        continue
                    target = edge["target"]
                    target_handle = edge.get("targetHandle")
                    target_node = self.nodes.get(target, {})

                    if target_node.get("type") == "loop" and target_handle == "loop":
                        if source_is_skipped:
                            continue
                        if self._source_handle_is_skipped(edge, skip_loop_source_handles):
                            continue
                        if self.prepare_loop_for_reexecution(
                            loop_node_id=target,
                            active_edges=active_edges,
                            completed_nodes=completed_nodes,
                            pending_count=pending_count,
                        ):
                            already_running = any(nid == target for nid in running_futures.values())
                            if not already_running:
                                inputs = self.get_node_inputs_for_edges(target, active_edges)
                                new_future = _SHARED_EXECUTOR.submit(
                                    self.execute_node_parallel, target, inputs
                                )
                                running_futures[new_future] = target
                        continue

                    if target not in pending_count:
                        continue
                    if target in completed_nodes:
                        continue
                    pending_count[target] -= 1
                    if pending_count[target] == 0:
                        if target in self.skipped_nodes:
                            node = self.nodes[target]
                            node_label = node.get("data", {}).get("label", target)
                            skipped_result = self._stamp_node_result(
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
                            already_running = any(nid == target for nid in running_futures.values())
                            if not already_running:
                                inputs = self.get_node_inputs_for_edges(target, active_edges)
                                new_future = _SHARED_EXECUTOR.submit(
                                    self.execute_node_parallel, target, inputs
                                )
                                running_futures[new_future] = target

        root_nodes = [nid for nid, count in pending_count.items() if count == 0]
        for node_id in root_nodes:
            self.check_cancelled()
            if node_id in self.skipped_nodes:
                node = self.nodes[node_id]
                node_label = node.get("data", {}).get("label", node_id)
                node_results.append(
                    self._stamp_node_result(
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
                schedule_downstream(node_id)
            else:
                future = _SHARED_EXECUTOR.submit(
                    self.execute_node_parallel,
                    node_id,
                    self.get_node_inputs_for_edges(node_id, active_edges),
                )
                running_futures[future] = node_id

        while (
            running_futures
            and not has_error
            and pending_result is None
            and early_return_output is None
        ):
            self.check_cancelled()
            done, _ = wait(running_futures.keys(), return_when=FIRST_COMPLETED)

            for future in done:
                node_id = running_futures.pop(future)
                self.check_cancelled()
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

                with pending_lock:
                    schedule_downstream(node_id, result)

                if early_return_output is not None:
                    allow_downstream_node_results: list[NodeResult] = []

                    def run_remaining_downstream():
                        nonlocal has_error
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
                                        result_node = self.nodes.get(nid, {})
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
                                            self.prepare_branch_targets_for_execution(
                                                start_node_ids=self.get_downstream_nodes(
                                                    nid, "done"
                                                ),
                                                active_edges=active_edges,
                                                completed_nodes=completed_nodes,
                                                pending_count=pending_count,
                                            )
                                        for edge in active_edges:
                                            if edge["source"] == nid:
                                                if self._source_handle_is_skipped(
                                                    edge, skip_source_handles
                                                ):
                                                    continue
                                                tgt = edge["target"]
                                                tgt_handle = edge.get("targetHandle")
                                                tgt_node = self.nodes.get(tgt, {})
                                                if (
                                                    tgt_node.get("type") == "loop"
                                                    and tgt_handle == "loop"
                                                ):
                                                    if self._source_handle_is_skipped(
                                                        edge, skip_loop_source_handles
                                                    ):
                                                        continue
                                                    if self.prepare_loop_for_reexecution(
                                                        loop_node_id=tgt,
                                                        active_edges=active_edges,
                                                        completed_nodes=completed_nodes,
                                                        pending_count=pending_count,
                                                    ):
                                                        skip_add_to_completed = True
                                                        already = any(
                                                            n == tgt
                                                            for n in remaining_futures.values()
                                                        )
                                                        if not already:
                                                            inp = self.get_node_inputs_for_edges(
                                                                tgt, active_edges
                                                            )
                                                            new_f = _SHARED_EXECUTOR.submit(
                                                                self.execute_node_parallel,
                                                                tgt,
                                                                inp,
                                                            )
                                                            remaining_futures[new_f] = tgt
                                                    continue
                                                if tgt not in pending_count:
                                                    continue
                                                if tgt in completed_nodes:
                                                    continue
                                                pending_count[tgt] -= 1
                                                if pending_count[tgt] == 0:
                                                    if tgt not in self.skipped_nodes:
                                                        already = any(
                                                            n == tgt
                                                            for n in remaining_futures.values()
                                                        )
                                                        if not already:
                                                            inp = self.get_node_inputs_for_edges(
                                                                tgt, active_edges
                                                            )
                                                            new_f = _SHARED_EXECUTOR.submit(
                                                                self.execute_node_parallel,
                                                                tgt,
                                                                inp,
                                                            )
                                                            remaining_futures[new_f] = tgt
                                if not skip_add_to_completed:
                                    completed_nodes.add(nid)
                        self.drain_bg_futures()

                    allow_downstream_future = _SHARED_EXECUTOR.submit(run_remaining_downstream)
                    break

        if pending_result is not None:
            for future in running_futures:
                future.cancel()

            pending_review = _extract_pending_metadata(pending_result)
            resume_snapshot = self.build_resume_snapshot(
                initial_inputs=initial_inputs,
                node_results=node_results,
                pending_count=pending_count,
                completed_nodes=completed_nodes,
                paused_node_id=pending_result.node_id,
                paused_node_label=pending_result.node_label,
            )
            return self._build_execution_result(
                workflow_id=workflow_id,
                status="pending",
                outputs={pending_result.node_label: copy.deepcopy(pending_result.output)},
                start_time=start_time,
                node_results=node_results,
                pending_review=pending_review,
                resume_snapshot=resume_snapshot,
            )

        if early_return_output is not None:
            return self._build_execution_result(
                workflow_id=workflow_id,
                status="success",
                outputs=early_return_output,
                start_time=start_time,
                node_results=node_results,
                allow_downstream_pending=[allow_downstream_future],
                allow_downstream_node_results=allow_downstream_node_results,
            )

        if has_error and error_result:
            error_flow_final_output = None
            if error_flow_nodes:
                error_edges = [
                    edge
                    for edge in self.edges
                    if edge["source"] in error_flow_nodes and edge["target"] in error_flow_nodes
                ]
                error_payload = {
                    "node_id": error_result.node_id,
                    "node_label": error_result.node_label,
                    "node_type": error_result.node_type,
                    "message": error_result.error,
                }
                error_results, error_flow_final_output = self.execute_error_flow(
                    error_flow_nodes, error_edges, error_payload
                )
                node_results.extend(error_results)

            final_outputs = error_flow_final_output or {"error": error_result.error}
            return self._build_execution_result(
                workflow_id=workflow_id,
                status="error",
                outputs=final_outputs,
                start_time=start_time,
                node_results=node_results,
            )

        output_nodes = self.get_output_nodes()
        final_outputs = {}
        for node_id in output_nodes:
            if node_id in self.node_outputs and node_id not in self.skipped_nodes:
                node = self.nodes.get(node_id, {})
                if node.get("type") == "sticky":
                    continue
                node_label = self.get_node_label(node_id)
                final_outputs[node_label] = self.node_outputs[node_id]

        final_outputs = unwrap_single_json_output_terminal_outputs(self, final_outputs)

        return self._build_execution_result(
            workflow_id=workflow_id,
            status="success",
            outputs=final_outputs,
            start_time=start_time,
            node_results=node_results,
        )


def mask_sensitive_output(output: dict, credentials_context: dict[str, str]) -> dict:
    safe_output = _to_json_compatible(output)
    if not credentials_context:
        return safe_output

    output_str = json.dumps(safe_output, ensure_ascii=False)

    for name, value in credentials_context.items():
        if value and len(value) > 7:
            masked = value[:7] + "**"
            output_str = output_str.replace(value, masked)

    return json.loads(output_str)


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
        for node_result in result.node_results:
            if isinstance(node_result, dict):
                node_result["output"] = mask_sensitive_output(
                    node_result["output"], credentials_context
                )

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
    filtered_results: list[NodeResult] = []
    for result in node_results:
        if result.node_id == paused_node_id and result.status == "pending":
            paused_result_ms = result.execution_time_ms
            continue
        filtered_results.append(result)
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
            execution_time_ms=paused_result_ms,
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
                            new_future = _SHARED_EXECUTOR.submit(
                                wf_executor.execute_node_parallel,
                                target,
                                wf_executor.get_node_inputs_for_edges(target, active_edges),
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
                            new_future = _SHARED_EXECUTOR.submit(
                                wf_executor.execute_node_parallel,
                                target,
                                wf_executor.get_node_inputs_for_edges(target, active_edges),
                            )
                            running_futures[new_future] = target

    with pending_lock:
        if hitl_resume_mode in {"rerun_agent", "continue_agent"}:
            rerun_future = _SHARED_EXECUTOR.submit(
                wf_executor.execute_node_parallel,
                paused_node_id,
                wf_executor.get_node_inputs_for_edges(paused_node_id, active_edges),
            )
            running_futures[rerun_future] = paused_node_id
        else:
            schedule_downstream(paused_node_id)

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
                                                        new_future = _SHARED_EXECUTOR.submit(
                                                            wf_executor.execute_node_parallel,
                                                            tgt,
                                                            wf_executor.get_node_inputs_for_edges(
                                                                tgt, active_edges
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
                                                    new_future = _SHARED_EXECUTOR.submit(
                                                        wf_executor.execute_node_parallel,
                                                        tgt,
                                                        wf_executor.get_node_inputs_for_edges(
                                                            tgt, active_edges
                                                        ),
                                                    )
                                                    remaining_futures[new_future] = tgt
                            if not skip_add_to_completed:
                                completed_nodes.add(nid)

                _SHARED_EXECUTOR.submit(run_remaining_downstream)
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
        for node_result in result.node_results:
            if isinstance(node_result, dict):
                node_result["output"] = mask_sensitive_output(
                    node_result["output"], credentials_context
                )

    return result


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
        agent_progress_queue.put(
            {
                "type": "node_start",
                "node_id": node_id,
                "node_label": node_label,
            }
        )

    def _submit_node(node_id: str) -> None:
        already_running = any(
            pending_node_id == node_id for pending_node_id in running_futures.values()
        )
        if already_running:
            return
        _enqueue_start(node_id)
        new_future = _SHARED_EXECUTOR.submit(
            wf_executor.execute_node_parallel,
            node_id,
            wf_executor.get_node_inputs_for_edges(node_id, branch_edges),
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
                    _submit_node(target)
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
                        new_future = _SHARED_EXECUTOR.submit(
                            wf_executor.execute_node_parallel,
                            target,
                            wf_executor.get_node_inputs_for_edges(target, active_edges),
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
                        new_future = _SHARED_EXECUTOR.submit(
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

        yield {
            "type": "node_start",
            "node_id": node_id,
            "node_label": node_label,
        }

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

        if node_type in ("output", "jsonOutputMapper") and result.status == "success":
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
    """Public streaming entry: wrap the run in an OTel root span (no-op when disabled).

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

    def execute_and_report(node_id: str) -> NodeResult:
        wf_executor.check_cancelled()
        node = wf_executor.nodes[node_id]
        node_label = node.get("data", {}).get("label", node_id)

        node_start_event: dict[str, object] = {
            "type": "node_start",
            "node_id": node_id,
            "node_label": node_label,
        }
        start_message = build_node_start_message(node_id, node_label, sse_node_config)
        if start_message is not None:
            node_start_event["message"] = start_message
        event_queue.put(node_start_event)

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
                            new_future = _SHARED_EXECUTOR.submit(execute_and_report, target)
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
                            new_future = _SHARED_EXECUTOR.submit(execute_and_report, target)
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
            future = _SHARED_EXECUTOR.submit(execute_and_report, node_id)
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
            is_json_mapper_final = node_for_final.get("type") == "jsonOutputMapper"
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
