import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.db.models import LLMTrace
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMTraceContext:
    user_id: uuid.UUID
    credential_id: uuid.UUID
    workflow_id: uuid.UUID | None = None
    node_id: str | None = None
    node_label: str | None = None
    source: str = "workflow"
    trace_ids: list[uuid.UUID] = field(default_factory=list, compare=False, repr=False)


def record_llm_trace(
    context: LLMTraceContext,
    request_type: str,
    request: dict[str, Any] | None,
    response: dict[str, Any] | None,
    model: str | None = None,
    provider: str | None = None,
    error: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    elapsed_ms: float | None = None,
) -> uuid.UUID | None:
    """Persist a single LLM trace entry for later inspection."""
    try:
        with SessionLocal() as db:
            trace = LLMTrace(
                user_id=context.user_id,
                credential_id=context.credential_id,
                workflow_id=context.workflow_id,
                source=context.source,
                request_type=request_type,
                provider=provider,
                model=model,
                node_id=context.node_id,
                node_label=context.node_label,
                request=request or {},
                response=response or {},
                error=error,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                elapsed_ms=elapsed_ms,
            )
            db.add(trace)
            db.commit()
            context.trace_ids.append(trace.id)
            return trace.id
    except Exception:
        logger.exception("Failed to record LLM trace")
    return None
