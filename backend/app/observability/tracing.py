"""OpenTelemetry tracing bootstrap for Heym.

Tracing is a no-op unless ``HEYM_OTEL_ENABLED=true``. When enabled, a global
``TracerProvider`` exports spans over OTLP/HTTP and FastAPI + httpx are
instrumented so W3C trace context propagates across webhooks, outbound HTTP
calls, and (in-process) sub-workflows.

Design rules:
- Disabled by default, so there is no runtime cost unless opted in.
- A misconfiguration degrades to "tracing off"; it never breaks app startup.
- Exporter/collector errors are swallowed by the batch processor and never
  propagate into workflow execution.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Tracer

from app.config import settings

logger = logging.getLogger(__name__)

_provider: Any = None
T = TypeVar("T")


def _sanitize_span_text(value: str, *, max_chars: int) -> str:
    """Return bounded, redacted span text without letting sanitization fail tracing."""
    try:
        from app.services.agent_tool_observability import sanitize_tool_payload

        sanitized = sanitize_tool_payload(
            value,
            max_chars=max_chars,
            max_depth=1,
            max_total_chars=max_chars,
        )
        return sanitized if isinstance(sanitized, str) else "[REDACTED]"
    except Exception:  # noqa: BLE001 - tracing must never break execution
        return "[REDACTED]"


def set_span_attribute(span: Any, key: str, value: Any) -> None:
    """Set an OTel attribute without allowing observability to affect execution."""
    if span is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception:  # noqa: BLE001 - tracing must never break workflows
        logger.debug("Failed to set OTel span attribute %s", key, exc_info=True)


def set_span_status(span: Any, status_code: Any, description: str | None = None) -> None:
    """Set an OTel span status without allowing observability to affect execution."""
    if span is None:
        return
    try:
        from opentelemetry.trace import Status

        safe_description = _sanitize_span_text(description, max_chars=512) if description else None
        span.set_status(
            Status(status_code, safe_description) if safe_description else Status(status_code)
        )
    except Exception:  # noqa: BLE001 - tracing must never break workflows
        logger.debug("Failed to set OTel span status", exc_info=True)


@contextmanager
def agent_tool_span(
    *,
    tool_name: str,
    tool_call_id: str | None,
    source: str | None,
    mcp_server: str | None = None,
    workflow_id: str | None = None,
    node_id: str | None = None,
    node_label: str | None = None,
    iteration: int | None = None,
) -> Any:
    """Create an opt-in span for one Agent tool invocation."""
    if not is_enabled():
        yield None
        return

    span = get_tracer().start_as_current_span("heym.agent.tool.execute")
    with span:
        current = trace.get_current_span()
        set_span_attribute(current, "heym.agent.tool.name", tool_name)
        if tool_call_id:
            set_span_attribute(current, "heym.agent.tool.call_id", tool_call_id)
        if source:
            set_span_attribute(current, "heym.agent.tool.source", source)
        if mcp_server:
            set_span_attribute(current, "heym.agent.tool.mcp_server", mcp_server)
        if workflow_id:
            set_span_attribute(current, "heym.workflow.id", workflow_id)
        if node_id:
            set_span_attribute(current, "heym.node.id", node_id)
        if node_label:
            set_span_attribute(current, "heym.node.label", node_label)
        if iteration is not None:
            set_span_attribute(current, "heym.agent.tool.iteration", iteration)
        try:
            yield current
        except Exception as exc:  # noqa: BLE001 - observability must never break execution
            record_agent_tool_exception(current, exc)
            raise


def record_agent_tool_exception(span: Any, exc: BaseException) -> None:
    """Record a caught Agent tool exception without affecting tool execution."""
    if span is None:
        return
    try:
        from opentelemetry.trace import StatusCode

        error_text = _sanitize_span_text(str(exc), max_chars=512)
        stacktrace = _sanitize_span_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            max_chars=4096,
        )
        span.add_event(
            "exception",
            {
                "exception.type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "exception.message": error_text,
                "exception.stacktrace": stacktrace,
                "exception.escaped": False,
            },
        )
        set_span_status(span, StatusCode.ERROR, error_text)
    except Exception:  # noqa: BLE001 - observability must never break execution
        pass


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse a comma-separated ``key=value`` header string for the OTLP exporter."""
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            headers[key] = value
    return headers


def setup_tracing(app: Any) -> None:
    """Configure the global tracer provider. Safe to call once at startup.

    No-op when ``settings.otel_enabled`` is false. Any failure is logged and
    leaves tracing disabled rather than raising.
    """
    global _provider
    if not settings.otel_enabled:
        return
    if _provider is not None:
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        resource = Resource.create(
            {
                "service.name": settings.otel_service_name or "heym",
                "service.version": settings.resolved_version,
            }
        )
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sampler_ratio)),
        )

        endpoint = settings.otel_exporter_otlp_endpoint.strip()
        exporter_kwargs: dict[str, Any] = {
            "headers": _parse_headers(settings.otel_exporter_otlp_headers)
        }
        if endpoint:
            # OTLP/HTTP traces are posted to the /v1/traces path of the base endpoint.
            exporter_kwargs["endpoint"] = endpoint.rstrip("/") + "/v1/traces"
        exporter = OTLPSpanExporter(**exporter_kwargs)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _provider = provider

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()

        logger.info(
            "OpenTelemetry tracing enabled (endpoint=%s, service=%s)",
            endpoint or "<default>",
            settings.otel_service_name,
        )
    except Exception:  # noqa: BLE001 - tracing must never break startup
        logger.exception("Failed to initialize OpenTelemetry; tracing disabled")
        _provider = None


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider on app shutdown."""
    global _provider
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # noqa: BLE001
            logger.exception("Error shutting down tracing provider")
        finally:
            _provider = None


def is_enabled() -> bool:
    """Return True when a real tracer provider is active."""
    return _provider is not None


def get_tracer() -> Tracer:
    """Return the Heym workflow tracer (no-op when tracing is disabled)."""
    return trace.get_tracer("heym.workflow")


def capture_node_io_enabled() -> bool:
    """Whether node input/output payloads should be attached to node spans.

    Off by default for privacy; payloads can contain user data or secrets.
    """
    return is_enabled() and settings.otel_capture_node_io


def capture_context() -> object:
    """Snapshot the active OTel context for re-attachment in a worker thread."""
    return otel_context.get_current()


def run_with_context(ctx: object, fn: Callable[[], T]) -> T:
    """Run ``fn`` with ``ctx`` attached as the active OTel context.

    Used to carry the workflow span context into ``ThreadPoolExecutor`` workers
    so node spans nest under the workflow span even when run in parallel.
    """
    token = otel_context.attach(ctx)  # type: ignore[arg-type]
    try:
        return fn()
    finally:
        otel_context.detach(token)
