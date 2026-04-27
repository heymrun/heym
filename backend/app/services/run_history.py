"""Record chat/assistant run history for workflow run history and job history."""

import logging
import uuid
from typing import Any

from app.db.models import RunHistory
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def record_run_history(
    user_id: uuid.UUID,
    run_type: str,
    workflow_id: uuid.UUID | None,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    status: str,
    execution_time_ms: float,
    trigger_source: str | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> None:
    """Persist a single chat/assistant run for run history and job history."""
    try:
        with SessionLocal() as db:
            run = RunHistory(
                user_id=user_id,
                run_type=run_type,
                workflow_id=workflow_id,
                trigger_source=trigger_source,
                inputs=inputs,
                outputs=outputs,
                steps=steps or [],
                status=status,
                execution_time_ms=execution_time_ms,
            )
            db.add(run)
            db.commit()
    except Exception:
        logger.exception("Failed to record run history")
