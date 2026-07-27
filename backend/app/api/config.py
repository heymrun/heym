from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.config import settings
from app.constants import RESERVED_VARIABLE_NAMES
from app.db.models import User

router = APIRouter()


@router.get("/reserved-variable-names")
async def get_reserved_variable_names() -> list[str]:
    return RESERVED_VARIABLE_NAMES


class ObservabilityStatus(BaseModel):
    """Read-only OpenTelemetry tracing status. Never exposes exporter secrets."""

    enabled: bool
    endpoint: str
    service_name: str
    sampler_ratio: float
    capture_node_io: bool
    instrumented: list[str]
    spans: list[str]


@router.get("/observability", response_model=ObservabilityStatus)
async def get_observability_status(
    _user: User = Depends(get_current_user),
) -> ObservabilityStatus:
    """Expose how OpenTelemetry tracing is configured for this instance.

    OTLP header values are intentionally omitted so secrets never leave the
    backend. Configuration is read from ``HEYM_OTEL_*`` environment variables.
    """
    enabled = settings.otel_enabled
    return ObservabilityStatus(
        enabled=enabled,
        endpoint=settings.otel_exporter_otlp_endpoint if enabled else "",
        service_name=settings.otel_service_name,
        sampler_ratio=settings.otel_traces_sampler_ratio,
        capture_node_io=settings.otel_capture_node_io,
        instrumented=["fastapi", "httpx"] if enabled else [],
        spans=["workflow", "node", "agent_tool"] if enabled else [],
    )
