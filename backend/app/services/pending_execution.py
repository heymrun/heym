"""Turn a run that paused into the review request that lets a human resume it.

Every trigger reaches the same fork: a paused run needs its HITL request or its
Codex follow-up minted, its public token issued and its notification branch
fired, while a finished run just needs a history row. This module owns that fork
so no call site has to know which of the two persisters applies.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionHistory, Workflow
from app.services.workflow_executor import ExecutionResult

Redactor = Callable[[Any], Any]


def needs_local_pending_persist(result: Any) -> bool:
    """Whether this caller still has to mint the review request for a paused run.

    An offloaded pause was already minted on the instance that executed it, and
    the summary that crossed the boundary carries none of the pause metadata, so
    a second attempt here would only raise.
    """
    return result.status == "pending" and not getattr(result, "history_written", False)


def _redact_pause(execution_result: ExecutionResult, redact: Redactor) -> None:
    execution_result.outputs = redact(execution_result.outputs)
    execution_result.node_results = redact(execution_result.node_results)
    if execution_result.pending_review is not None:
        execution_result.pending_review = redact(execution_result.pending_review)
    if execution_result.resume_snapshot is not None:
        execution_result.resume_snapshot = redact(execution_result.resume_snapshot)


async def persist_pending_execution(
    *,
    db: AsyncSession,
    workflow: Workflow,
    enriched_inputs: dict,
    execution_result: ExecutionResult,
    trigger_source: str | None,
    credentials_owner_id: uuid.UUID,
    trace_user_id: uuid.UUID | None,
    public_base_url: str,
    history_entry: ExecutionHistory | None = None,
    history_entry_id: uuid.UUID | None = None,
    redact: Redactor | None = None,
) -> tuple[ExecutionHistory, Any]:
    """Mint the pause and write its history row, returning both.

    `redact` is applied on both sides of the mint for triggers that carry a
    request secret: once so the pause metadata never reaches the request row,
    and once after so the notification branch's own results are covered too.
    """
    from app.services.codex_followup_service import (
        is_codex_pending_execution,
        persist_pending_codex_followup_execution,
    )
    from app.services.hitl_service import persist_pending_hitl_execution

    if redact is not None:
        _redact_pause(execution_result, redact)

    mint = (
        persist_pending_codex_followup_execution
        if is_codex_pending_execution(execution_result)
        else persist_pending_hitl_execution
    )
    entry, pending_request = await mint(
        db=db,
        workflow=workflow,
        enriched_inputs=enriched_inputs,
        execution_result=execution_result,
        trigger_source=trigger_source,
        credentials_owner_id=credentials_owner_id,
        trace_user_id=trace_user_id,
        public_base_url=public_base_url,
        history_entry=history_entry,
        history_entry_id=history_entry_id,
    )

    if redact is not None:
        _redact_pause(execution_result, redact)
        entry.inputs = redact(entry.inputs)
        entry.outputs = redact(entry.outputs)
        entry.node_results = redact(entry.node_results)
        pending_request.execution_snapshot = redact(pending_request.execution_snapshot)

    return entry, pending_request
