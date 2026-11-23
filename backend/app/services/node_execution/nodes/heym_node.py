from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.db.models import Board, BoardCard, BoardColumn
from app.services.board_access import accessible_board_ids
from app.services.board_card_fields import read_fields
from app.services.node_execution.base import NodeExecutionContext

# An empty limit, a zero, or anything unparseable means "every workflow". There is
# no ceiling on top of that: a cap the user can step around by clearing the field
# would only be theatre.
NO_LIST_LIMIT = 0

# `heymWorkflowId` value that reads the history of every workflow the run's user can reach.
ALL_WORKFLOWS = "all"

BOARD_OPERATIONS = {
    "getBoard": ("heymBoardId", "Board", Board),
    "getBoardColumn": ("heymBoardColumnId", "Board column", BoardColumn),
    "getBoardCardId": ("heymBoardCardId", "Board card", BoardCard),
}


def _resolve(ctx: NodeExecutionContext, key: str) -> str:
    """Resolve one node field through the executor's expression engine."""
    raw = ctx.node_data.get(key)
    if raw in (None, ""):
        return ""
    return str(ctx.executor.evaluate_message_template(raw, ctx.inputs)).strip()


def _parse_int(value: str, fallback: int) -> int:
    """A whole number from a field; "2.0" (a float from an expression) is 2, not the fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return int(number) if math.isfinite(number) else fallback


def _workflow_summary(workflow: Any) -> dict[str, Any]:
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "description": workflow.description,
        "active": bool(getattr(workflow, "active", True)),
        "folder_id": str(workflow.folder_id) if workflow.folder_id else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        "node_count": len(workflow.nodes or []),
    }


def _execution_summary(entry: Any) -> dict[str, Any]:
    """Summarise one execution-history row.

    ``inputs`` and ``outputs`` are what the run received and what it answered, so
    both travel. ``node_results`` does not: it is the full per-node trace, the
    largest column in the table, and it would dwarf everything downstream.
    """
    started_at = getattr(entry, "started_at", None)
    return {
        "id": str(entry.id),
        "status": entry.status,
        "started_at": started_at.isoformat() if started_at else None,
        "execution_time_ms": entry.execution_time_ms,
        "trigger_source": entry.trigger_source,
        "recovered": bool(getattr(entry, "recovered", False)),
        "inputs": entry.inputs or {},
        "outputs": entry.outputs or {},
    }


def _workflow_detail(workflow: Any) -> dict[str, Any]:
    """Return the workflow's full structure, node configuration included.

    ``data`` carries every configured field, which is what makes scanning
    possible: a workflow cannot be audited for a hardcoded API key or token that
    the node refuses to show. This grants no new reach - the read is already
    scoped to workflows the run's user can open in the editor - and stored credential
    secrets still are not here, since node data holds only credential ids while
    the secrets themselves live encrypted in the credentials table.
    """
    detail = _workflow_summary(workflow)
    detail["nodes"] = [
        {
            "id": node.get("id"),
            "type": node.get("type"),
            "label": node.get("data", {}).get("label", ""),
            "position": node.get("position", {}),
            "data": node.get("data", {}),
        }
        for node in workflow.nodes or []
    ]
    detail["edges"] = [
        {
            "id": edge.get("id"),
            "source": edge.get("source"),
            "target": edge.get("target"),
            "sourceHandle": edge.get("sourceHandle"),
            "targetHandle": edge.get("targetHandle"),
        }
        for edge in workflow.edges or []
    ]
    return detail


def _run_user_id(ctx: NodeExecutionContext, db: Any, workflow_model: Any) -> uuid.UUID:
    """Return the user whose reach this run reads with.

    That is the run's actor, the same user its credentials and global variables
    resolve for: whoever ran it from the canvas, the API, an execution token, chat
    or MCP, and the workflow owner for cron, portal, event and other triggered runs,
    which their entry points start as the owner. Only a run that carries no actor
    at all falls back to the owner of the workflow this node lives in.
    """
    actor_user_id = ctx.executor.actor_user_id
    if actor_user_id is not None:
        return actor_user_id

    owning = None
    try:
        owning = db.execute(
            select(workflow_model).where(
                workflow_model.id == uuid.UUID(str(ctx.executor.workflow_id))
            )
        ).scalar_one_or_none()
    except (TypeError, ValueError):
        # An unsaved workflow has no persisted id to look the owner up by.
        owning = None
    if owning is None:
        raise ValueError(
            "Heym node cannot resolve which user's workflows to read. "
            "Save the workflow before running this node."
        )
    return owning.owner_id


def _require_workflow(ctx: NodeExecutionContext, db: Any, workflow_model: Any, access: Any) -> Any:
    """Load the selected workflow or refuse in a way that leaks nothing.

    A workflow that does not exist and a workflow the run's user cannot reach produce
    the same message, so the node cannot be used to probe for workflow ids.
    """
    from sqlalchemy import select

    raw_id = _resolve(ctx, "heymWorkflowId")
    if not raw_id:
        raise ValueError("Heym node requires a target workflow")
    try:
        workflow_uuid = uuid.UUID(raw_id)
    except ValueError:
        raise ValueError(f"Workflow not found or not accessible: {raw_id}") from None

    workflow = db.execute(
        select(workflow_model).where(workflow_model.id == workflow_uuid).where(access)
    ).scalar_one_or_none()
    if workflow is None:
        raise ValueError(f"Workflow not found or not accessible: {raw_id}")
    return workflow


def _column_summary(column: BoardColumn) -> dict[str, Any]:
    return {
        "id": str(column.id),
        "board_id": str(column.board_id),
        "name": column.name,
        "position": column.position,
        "color": column.color,
    }


def _card_summary(card: BoardCard) -> dict[str, Any]:
    return {
        "id": str(card.id),
        "board_id": str(card.board_id),
        "column_id": str(card.column_id),
        "title": card.title,
        "position": card.position,
        "run_status": card.run_status,
        "path": f"/b/{card.board_id}/cards/{card.id}",
    }


def _read_board_data(
    ctx: NodeExecutionContext, db: Session, user_id: uuid.UUID, operation: str
) -> dict[str, Any]:
    field, label, model = BOARD_OPERATIONS[operation]
    raw_id = _resolve(ctx, field)
    if not raw_id:
        raise HTTPException(400, f"{label} ID is required")
    not_found = f"{label} not found or not accessible"
    try:
        target_id = uuid.UUID(raw_id)
    except ValueError:
        raise HTTPException(404, not_found) from None

    board_id = Board.id if model is Board else model.board_id
    target = db.execute(
        select(model).where(model.id == target_id, board_id.in_(accessible_board_ids(user_id)))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, not_found)

    if isinstance(target, Board):
        columns = db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == target.id)
            .order_by(BoardColumn.position, BoardColumn.id)
        )
        return {
            "id": str(target.id),
            "name": target.name,
            "description": target.description,
            "auto_advance": target.auto_advance,
            "columns": [_column_summary(column) for column in columns],
        }

    if isinstance(target, BoardColumn):
        cards = db.scalars(
            select(BoardCard)
            .options(
                load_only(
                    BoardCard.id,
                    BoardCard.board_id,
                    BoardCard.column_id,
                    BoardCard.title,
                    BoardCard.position,
                    BoardCard.run_status,
                )
            )
            .where(BoardCard.board_id == target.board_id, BoardCard.column_id == target.id)
            .order_by(BoardCard.position, BoardCard.id)
        )
        return {
            **_column_summary(target),
            "ai_instructions": target.ai_instructions,
            "cards": [_card_summary(card) for card in cards],
        }

    fields = read_fields(target.card_metadata)
    return {
        **_card_summary(target),
        "content": target.content,
        "card_metadata": target.card_metadata or {},
        "fields": {
            "assignee_user_id": str(fields.assignee_user_id) if fields.assignee_user_id else None,
            "priority": fields.priority,
            "due_date": fields.due_date.isoformat() if fields.due_date else None,
            "labels": list(fields.labels),
        },
        "created_at": target.created_at.isoformat(),
        "updated_at": target.updated_at.isoformat(),
    }


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the heym node."""
    from sqlalchemy import func
    from sqlalchemy.orm import defer

    from app.db import session as db_session
    from app.db.models import ExecutionHistory, Workflow
    from app.services.run_history_encryption import not_encrypted
    from app.services.workflow_access import workflow_access_clause

    operation = str(ctx.node_data.get("heymOperation", "")).strip()
    if not operation:
        raise ValueError("Heym node requires an operation")

    with db_session.SessionLocal() as db:
        user_id = _run_user_id(ctx, db, Workflow)
        if operation in BOARD_OPERATIONS:
            return _read_board_data(ctx, db, user_id, operation)

        access = workflow_access_clause(user_id)
        limit = _parse_int(_resolve(ctx, "heymLimit"), NO_LIST_LIMIT)

        if operation == "listWorkflows":
            rows = (
                db.execute(
                    select(Workflow)
                    .where(access)
                    .where(Workflow.kind == "workflow")
                    .order_by(Workflow.updated_at.desc())
                )
                .scalars()
                .all()
            )
            selected = rows if limit <= NO_LIST_LIMIT else rows[:limit]
            return {
                "workflows": [_workflow_summary(row) for row in selected],
                "total": len(rows),
            }

        if operation in ("getWorkflow", "getExecutionHistory"):
            all_workflows = (
                operation == "getExecutionHistory"
                and _resolve(ctx, "heymWorkflowId").lower() == ALL_WORKFLOWS
            )
            workflow = None if all_workflows else _require_workflow(ctx, db, Workflow, access)

            if operation == "getWorkflow":
                return _workflow_detail(workflow)

            since_days = _parse_int(_resolve(ctx, "heymSinceDays"), 0)
            since = (
                datetime.now(timezone.utc) - timedelta(days=since_days) if since_days > 0 else None
            )
            status_filter = _resolve(ctx, "heymStatus")

            if all_workflows:
                # Same set `listWorkflows` returns, so "all" means what the list shows.
                reachable = select(Workflow.id).where(access).where(Workflow.kind == "workflow")
                filters = [ExecutionHistory.workflow_id.in_(reachable)]
            else:
                filters = [ExecutionHistory.workflow_id == workflow.id]
            if since is not None:
                filters.append(ExecutionHistory.started_at >= since)
            if status_filter:
                filters.append(ExecutionHistory.status == status_filter)

            # The breakdown is counted in SQL. Loading every row just to tally it
            # pulls the inputs/outputs/node_results JSON of the workflow's entire
            # history into memory, which is what used to take the backend down on
            # workflows with a long history.
            count_rows = db.execute(
                select(ExecutionHistory.status, func.count())
                .where(*filters)
                .group_by(ExecutionHistory.status)
            ).all()
            by_status: dict[str, int] = {status: int(count) for status, count in count_rows}
            total = sum(by_status.values())

            # Encrypted runs are counted above but never listed: only an audited unlock
            # in the History dialog reads them.
            encrypted_skipped = int(
                db.execute(
                    select(func.count())
                    .select_from(ExecutionHistory)
                    .where(*filters, ~not_encrypted())
                ).scalar_one()
                or 0
            )

            # Only the requested slice is fetched, and never the node_results trace.
            if all_workflows:
                query = (
                    select(ExecutionHistory, Workflow.name)
                    .join(Workflow, Workflow.id == ExecutionHistory.workflow_id)
                    .options(
                        defer(ExecutionHistory.node_results),
                        defer(ExecutionHistory.encrypted_payload),
                    )
                    .where(*filters, not_encrypted())
                    .order_by(ExecutionHistory.started_at.desc())
                )
            else:
                query = (
                    select(ExecutionHistory)
                    .options(
                        defer(ExecutionHistory.node_results),
                        defer(ExecutionHistory.encrypted_payload),
                    )
                    .where(*filters, not_encrypted())
                    .order_by(ExecutionHistory.started_at.desc())
                )
            if limit > NO_LIST_LIMIT:
                query = query.limit(limit)

            if all_workflows:
                executions = [
                    {
                        **_execution_summary(entry),
                        "workflow_id": str(entry.workflow_id),
                        "workflow_name": workflow_name,
                    }
                    for entry, workflow_name in db.execute(query).all()
                ]
            else:
                executions = [_execution_summary(row) for row in db.execute(query).scalars().all()]

            return {
                "workflow_id": None if workflow is None else str(workflow.id),
                "workflow_name": None if workflow is None else workflow.name,
                "executions": executions,
                "total": total,
                "by_status": by_status,
                "encrypted_skipped": encrypted_skipped,
                "since": since.isoformat() if since else None,
            }

    raise ValueError(f"Unknown Heym operation: {operation}")
