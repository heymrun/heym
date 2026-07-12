"""Board chain execution: payload building, sequential chain runner, enqueueing."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import (
    Board,
    BoardCard,
    BoardCardActivity,
    BoardCardRun,
    BoardColumn,
    BoardColumnWorkflow,
    ExecutionHistory,
    Workflow,
)
from app.db.session import async_session_maker
from app.services.board_mapper_service import board_mapper_is_configured, build_workflow_inputs
from app.services.execution_cancellation import clear_execution, register_execution
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_default_public_base_url, persist_pending_hitl_execution
from app.services.workflow_executor import _to_json_compatible, execute_workflow

logger = logging.getLogger(__name__)

MAX_HISTORY_ENTRIES = 200
ACTIVE_RUN_STATUSES = ("running", "pending")
_OUTPUT_SNIPPET_LIMIT = 500

# The event loop only keeps weak references to tasks, so a fire-and-forget
# ``create_task`` result can be garbage-collected mid-flight. Hold strong
# references here until each chain task finishes.
_BACKGROUND_CHAIN_TASKS: set[asyncio.Task] = set()


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def build_card_payload(
    *,
    card: Any,
    board: Any,
    from_column_name: str | None,
    to_column_name: str,
    comments: list[Any],
    history: list[Any],
    previous_runs: list[Any],
    chain_position: int,
    chain_length: int,
    previous_workflow_outputs: list[dict],
    rerun: bool,
) -> dict:
    """Build the standard workflow ``inputs`` payload for a board card run."""
    recent_history = history[-MAX_HISTORY_ENTRIES:]
    return {
        "triggered_by": "board",
        "rerun": rerun,
        "card": {
            "id": str(card.id),
            "title": card.title,
            "content": card.content,
            "metadata": card.card_metadata or {},
            "comments": [
                {
                    "author": activity.author_type,
                    "content": activity.content,
                    "created_at": _iso(activity.created_at),
                }
                for activity in comments
            ],
            "history": [
                {
                    "kind": activity.kind,
                    "content": activity.content,
                    "created_at": _iso(activity.created_at),
                }
                for activity in recent_history
            ],
            "previous_outputs": [
                {
                    "workflow_name": run.workflow_name,
                    "output": run.output or {},
                    "finished_at": _iso(run.finished_at),
                }
                for run in previous_runs
            ],
        },
        "board": {"id": str(board.id), "name": board.name},
        "move": (
            {"from_column": from_column_name, "to_column": to_column_name} if not rerun else None
        ),
        "chain": {
            "position": chain_position,
            "length": chain_length,
            "previous_workflow_outputs": previous_workflow_outputs,
        },
    }


def _output_snippet(outputs: dict) -> str:
    text = outputs.get("text") if isinstance(outputs, dict) else None
    if not isinstance(text, str) or not text:
        text = str(outputs)
    return text[:_OUTPUT_SNIPPET_LIMIT]


async def _load_card_context(db, card_id: uuid.UUID) -> dict[str, Any] | None:
    """Load card, board, comments, history and completed previous runs."""
    card = await db.get(BoardCard, card_id)
    if card is None:
        return None
    board = await db.get(Board, card.board_id)
    column = await db.get(BoardColumn, card.column_id)
    activities = (
        (
            await db.execute(
                select(BoardCardActivity)
                .where(BoardCardActivity.card_id == card_id)
                .order_by(BoardCardActivity.created_at)
            )
        )
        .scalars()
        .all()
    )
    previous_runs = (
        (
            await db.execute(
                select(BoardCardRun)
                .where(BoardCardRun.card_id == card_id, BoardCardRun.status == "success")
                .order_by(BoardCardRun.started_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "card": card,
        "board": board,
        "comments": [a for a in activities if a.kind == "comment"],
        "history": list(activities),
        "previous_runs": previous_runs,
        "from_column_name": None,
        "to_column_name": column.name if column is not None else "",
    }


async def _set_card_status(db, card_id: uuid.UUID, run_status: str) -> None:
    card = await db.get(BoardCard, card_id)
    if card is not None:
        card.run_status = run_status


async def _run_chain(
    *,
    card_id: uuid.UUID,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    links: list[dict],
    move: dict | None,
    rerun: bool,
    session_factory=async_session_maker,
) -> None:
    """Execute a column's workflow chain for a card, sequentially, off the request path."""
    chain_outputs: list[dict] = []
    try:
        async with session_factory() as db:
            for index, link in enumerate(links):
                run = BoardCardRun(
                    card_id=card_id,
                    column_id=column_id,
                    workflow_id=link["workflow_id"],
                    workflow_name=link["workflow_name"],
                    chain_position=index,
                    chain_length=len(links),
                    status="running",
                )
                db.add(run)
                await db.flush()

                context = await _load_card_context(db, card_id)
                workflow = await db.get(Workflow, link["workflow_id"])
                if context is None or workflow is None:
                    run.status = "failed"
                    run.error = "Card or workflow no longer exists"
                    run.finished_at = datetime.now(timezone.utc)
                    await _abort_remaining(db, card_id, column_id, links, index + 1)
                    await _set_card_status(db, card_id, "failed")
                    await db.commit()
                    return

                board = context["board"]
                inputs = build_card_payload(
                    card=context["card"],
                    board=board,
                    from_column_name=(move or {}).get("from_column"),
                    to_column_name=(move or {}).get("to_column") or context["to_column_name"],
                    comments=context["comments"],
                    history=context["history"],
                    previous_runs=context["previous_runs"],
                    chain_position=index,
                    chain_length=len(links),
                    previous_workflow_outputs=chain_outputs,
                    rerun=rerun,
                )

                if board_mapper_is_configured(board):
                    mapper_column = await db.get(BoardColumn, column_id)
                    try:
                        inputs = await build_workflow_inputs(
                            db,
                            board=board,
                            column_ai_instructions=(
                                mapper_column.ai_instructions if mapper_column else None
                            ),
                            available_context=inputs,
                            workflow=workflow,
                        )
                    except Exception as exc:  # noqa: BLE001 - a mapper failure fails this link
                        run.status = "failed"
                        run.error = f"Input mapping failed: {exc}"
                        run.finished_at = datetime.now(timezone.utc)
                        db.add(
                            BoardCardActivity(
                                card_id=card_id,
                                kind="event",
                                author_type="system",
                                content=f"{link['workflow_name']} input mapping failed",
                                data={"error": str(exc)},
                                run_id=run.id,
                            )
                        )
                        await _abort_remaining(db, card_id, column_id, links, index + 1)
                        await _set_card_status(db, card_id, "failed")
                        await db.commit()
                        return

                workflow_cache = await collect_referenced_workflows(
                    db, workflow.nodes, actor_user_id=board.owner_id
                )
                credentials_context = await get_credentials_context(db, board.owner_id)
                global_variables_context = await get_global_variables_context(db, board.owner_id)
                public_base_url = build_default_public_base_url()
                execution_id = uuid.uuid4()
                cancel_event = register_execution(
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    inputs=inputs,
                    trigger_source="board",
                    actor_user_id=board.owner_id,
                )
                try:
                    result = await asyncio.to_thread(
                        execute_workflow,
                        workflow_id=workflow.id,
                        nodes=workflow.nodes,
                        edges=workflow.edges,
                        inputs=inputs,
                        workflow_cache=workflow_cache,
                        credentials_context=credentials_context,
                        global_variables_context=global_variables_context,
                        trace_user_id=board.owner_id,
                        actor_user_id=board.owner_id,
                        public_base_url=public_base_url,
                        cancel_event=cancel_event,
                    )
                except Exception as exc:  # noqa: BLE001 - one bad link fails the chain, not the app
                    run.status = "failed"
                    run.error = str(exc)
                    run.finished_at = datetime.now(timezone.utc)
                    db.add(
                        BoardCardActivity(
                            card_id=card_id,
                            kind="event",
                            author_type="system",
                            content=f"{link['workflow_name']} failed",
                            data={"error": str(exc)},
                            run_id=run.id,
                        )
                    )
                    await _abort_remaining(db, card_id, column_id, links, index + 1)
                    await _set_card_status(db, card_id, "failed")
                    await db.commit()
                    return
                finally:
                    clear_execution(execution_id)
                if result.allow_downstream_pending:
                    result.join_allow_downstream()

                if result.status == "pending":
                    history_entry, _ = await persist_pending_hitl_execution(
                        db=db,
                        workflow=workflow,
                        enriched_inputs=inputs,
                        execution_result=result,
                        trigger_source="board",
                        credentials_owner_id=board.owner_id,
                        trace_user_id=board.owner_id,
                        public_base_url=public_base_url,
                    )
                    run.status = "pending"
                    run.execution_history_id = history_entry.id
                    run.finished_at = datetime.now(timezone.utc)
                    await _set_card_status(db, card_id, "pending")
                    await db.commit()
                    return

                history_entry = ExecutionHistory(
                    workflow_id=workflow.id,
                    inputs=_to_json_compatible(inputs),
                    outputs=_to_json_compatible(result.outputs),
                    node_results=_to_json_compatible(result.node_results),
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source="board",
                )
                db.add(history_entry)
                await db.flush()
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=board.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                )
                await _persist_global_variables_from_execution(
                    db,
                    board.owner_id,
                    workflow.nodes,
                    workflow_cache,
                    _to_json_compatible(result.node_results),
                    result.sub_workflow_executions,
                )

                outputs = _to_json_compatible(result.outputs) or {}
                run.execution_history_id = history_entry.id
                run.finished_at = datetime.now(timezone.utc)

                if result.status != "success":
                    run.status = "failed"
                    run.error = f"Workflow finished with status {result.status}"
                    db.add(
                        BoardCardActivity(
                            card_id=card_id,
                            kind="event",
                            author_type="system",
                            content=f"{link['workflow_name']} failed",
                            data={"status": result.status},
                            run_id=run.id,
                        )
                    )
                    await _abort_remaining(db, card_id, column_id, links, index + 1)
                    await _set_card_status(db, card_id, "failed")
                    await db.commit()
                    return

                run.status = "success"
                run.output = outputs
                db.add(
                    BoardCardActivity(
                        card_id=card_id,
                        kind="output",
                        author_type="agent",
                        content=_output_snippet(outputs),
                        data={"workflow_name": link["workflow_name"], "output": outputs},
                        run_id=run.id,
                    )
                )
                chain_outputs.append({"workflow_name": link["workflow_name"], "output": outputs})
                await db.commit()

            await _set_card_status(db, card_id, "success")
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - chain must never crash the server
        logger.exception("Board chain failed for card %s: %s", card_id, exc)
        try:
            async with session_factory() as db:
                await _fail_open_runs(db, card_id, str(exc))
                await _set_card_status(db, card_id, "failed")
                await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record board chain failure for card %s", card_id)


async def _abort_remaining(
    db, card_id: uuid.UUID, column_id: uuid.UUID, links: list[dict], start_index: int
) -> None:
    for index in range(start_index, len(links)):
        db.add(
            BoardCardRun(
                card_id=card_id,
                column_id=column_id,
                workflow_id=links[index]["workflow_id"],
                workflow_name=links[index]["workflow_name"],
                chain_position=index,
                chain_length=len(links),
                status="skipped",
                finished_at=datetime.now(timezone.utc),
            )
        )


async def _fail_open_runs(db, card_id: uuid.UUID, error: str) -> None:
    runs = (
        (
            await db.execute(
                select(BoardCardRun).where(
                    BoardCardRun.card_id == card_id, BoardCardRun.status == "running"
                )
            )
        )
        .scalars()
        .all()
    )
    for run in runs:
        run.status = "failed"
        run.error = error
        run.finished_at = datetime.now(timezone.utc)


async def enqueue_card_chain(db, *, card, column, board, move: dict | None, rerun: bool) -> bool:
    """Start the column's workflow chain for a card.

    Returns False when the column has no chain or the card already has an active run.
    Commits the ``running`` status flip before spawning the background task so the
    task's fresh session sees it.
    """
    active = (
        (
            await db.execute(
                select(BoardCardRun).where(
                    BoardCardRun.card_id == card.id,
                    BoardCardRun.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    if active:
        return False
    link_rows = (
        await db.execute(
            select(BoardColumnWorkflow, Workflow.name)
            .join(Workflow, Workflow.id == BoardColumnWorkflow.workflow_id)
            .where(BoardColumnWorkflow.column_id == column.id)
            .order_by(BoardColumnWorkflow.position)
        )
    ).all()
    if not link_rows:
        return False
    links = [
        {
            "workflow_id": link.workflow_id,
            "workflow_name": workflow_name,
            "position": link.position,
        }
        for link, workflow_name in link_rows
    ]
    card.run_status = "running"
    await db.commit()
    task = asyncio.create_task(
        _run_chain(
            card_id=card.id,
            board_id=board.id,
            column_id=column.id,
            links=links,
            move=move,
            rerun=rerun,
        )
    )
    _BACKGROUND_CHAIN_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_CHAIN_TASKS.discard)
    return True


async def reconcile_orphaned_board_runs() -> None:
    """On startup, fail runs/cards left 'running' by a previous process."""
    try:
        async with async_session_maker() as db:
            runs = (
                (await db.execute(select(BoardCardRun).where(BoardCardRun.status == "running")))
                .scalars()
                .all()
            )
            card_ids = {run.card_id for run in runs}
            for run in runs:
                run.status = "failed"
                run.error = "Server restarted during execution"
                run.finished_at = datetime.now(timezone.utc)
            cards = (
                (
                    await db.execute(
                        select(BoardCard).where(
                            BoardCard.id.in_(card_ids), BoardCard.run_status == "running"
                        )
                    )
                )
                .scalars()
                .all()
                if card_ids
                else []
            )
            for card in cards:
                card.run_status = "failed"
            await db.commit()
            if runs:
                logger.info("Reconciled %d orphaned board runs", len(runs))
    except Exception:  # noqa: BLE001 - reconciliation must never block startup
        logger.exception("Board run reconciliation failed")
