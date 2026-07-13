"""Board chain execution: payload building, sequential chain runner, enqueueing."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

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
from app.services.board_attachment_service import load_card_attachments
from app.services.board_mapper_service import (
    board_mapper_is_configured,
    build_workflow_inputs,
    humanize_output,
)
from app.services.codex_followup_service import (
    is_codex_pending_execution,
    persist_pending_codex_followup_execution,
)
from app.services.execution_cancellation import clear_execution, register_execution
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_default_public_base_url, persist_pending_hitl_execution
from app.services.workflow_executor import _to_json_compatible, execute_workflow

logger = logging.getLogger(__name__)

MAX_HISTORY_ENTRIES = 200
ACTIVE_RUN_STATUSES = ("running", "pending")
_OUTPUT_SNIPPET_LIMIT = 500

# Cards only auto-advance once they are past the planning gate. Index 0 (Backlog) and
# index 1 (Planning) run their chain but wait there for a human answer; from index 2 on
# a successful column cascades the card to the right.
GATE_COLUMN_INDEX = 2

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
    attachments: list[dict] | None = None,
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
            # Resolved at run time: documents carry their extracted text, images their URL.
            "attachments": attachments or [],
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
        "attachments": await load_card_attachments(db, card),
        "from_column_name": None,
        "to_column_name": column.name if column is not None else "",
    }


async def _set_card_status(db, card_id: uuid.UUID, run_status: str) -> None:
    card = await db.get(BoardCard, card_id)
    if card is not None:
        card.run_status = run_status


async def _column_links(db, column_id: uuid.UUID) -> list[dict]:
    """The column's workflow chain, in run order."""
    rows = (
        await db.execute(
            select(BoardColumnWorkflow, Workflow.name)
            .join(Workflow, Workflow.id == BoardColumnWorkflow.workflow_id)
            .where(BoardColumnWorkflow.column_id == column_id)
            .order_by(BoardColumnWorkflow.position)
        )
    ).all()
    return [
        {"workflow_id": link.workflow_id, "workflow_name": name, "position": link.position}
        for link, name in rows
    ]


async def _record_output_activity(
    db,
    *,
    card_id: uuid.UUID,
    run: BoardCardRun,
    board: Any,
    workflow: Any,
    workflow_name: str,
    outputs: dict,
    column_instructions: str | None,
) -> None:
    """Add the run's output as a card activity.

    The activity shows readable prose/markdown (the board mapper humanizes it), not a raw
    JSON dump. The raw output stays on the run row and in the activity's ``data``.
    """
    activity_text = _output_snippet(outputs)
    if board_mapper_is_configured(board):
        humanized = await humanize_output(
            db,
            board=board,
            workflow=workflow,
            outputs=outputs,
            column_ai_instructions=column_instructions,
        )
        if humanized:
            activity_text = humanized
    db.add(
        BoardCardActivity(
            card_id=card_id,
            kind="output",
            author_type="agent",
            content=activity_text,
            data={"workflow_name": workflow_name, "output": outputs},
            run_id=run.id,
        )
    )


async def _run_chain(
    *,
    card_id: uuid.UUID,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    links: list[dict],
    move: dict | None,
    rerun: bool,
    allow_advance: bool = True,
    session_factory=async_session_maker,
    start_index: int = 0,
    chain_length: int | None = None,
    initial_outputs: list[dict] | None = None,
) -> None:
    """Execute a column's workflow chain for a card, sequentially, off the request path.

    ``links`` may be the tail of a chain (when resuming after a HITL/Codex pause), in which
    case ``start_index`` is the position of its first link and ``chain_length`` the length of
    the full chain, so run rows keep reporting "step n of m" over the original chain.
    """
    total = chain_length if chain_length is not None else len(links)
    chain_outputs: list[dict] = list(initial_outputs or [])
    try:
        async with session_factory() as db:
            chain_column = await db.get(BoardColumn, column_id)
            column_instructions = getattr(chain_column, "ai_instructions", None)
            for index, link in enumerate(links):
                position = start_index + index
                run = BoardCardRun(
                    card_id=card_id,
                    column_id=column_id,
                    workflow_id=link["workflow_id"],
                    workflow_name=link["workflow_name"],
                    chain_position=position,
                    chain_length=total,
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
                    await _abort_remaining(
                        db, card_id, column_id, links, index + 1, start_index, total
                    )
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
                    chain_position=position,
                    chain_length=total,
                    previous_workflow_outputs=chain_outputs,
                    rerun=rerun,
                    attachments=context.get("attachments") or [],
                )

                if board_mapper_is_configured(board):
                    try:
                        inputs = await build_workflow_inputs(
                            db,
                            board=board,
                            column_ai_instructions=column_instructions,
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
                        await _abort_remaining(
                            db, card_id, column_id, links, index + 1, start_index, total
                        )
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
                    await _abort_remaining(
                        db, card_id, column_id, links, index + 1, start_index, total
                    )
                    await _set_card_status(db, card_id, "failed")
                    await db.commit()
                    return
                finally:
                    clear_execution(execution_id)
                if result.allow_downstream_pending:
                    result.join_allow_downstream()

                if result.status == "pending":
                    # A Codex question and a HITL review are different pauses with different
                    # answer UIs and resume paths; persist each as its own kind.
                    persist_pending = (
                        persist_pending_codex_followup_execution
                        if is_codex_pending_execution(result)
                        else persist_pending_hitl_execution
                    )
                    history_entry, _ = await persist_pending(
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
                    db.add(
                        BoardCardActivity(
                            card_id=card_id,
                            kind="event",
                            author_type="system",
                            content=f"{link['workflow_name']} is waiting for a human answer",
                            data={"execution_history_id": str(history_entry.id)},
                            run_id=run.id,
                        )
                    )
                    # The chain resumes from the next link once the human answers; see
                    # ``resume_card_chain``.
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
                    await _abort_remaining(
                        db, card_id, column_id, links, index + 1, start_index, total
                    )
                    await _set_card_status(db, card_id, "failed")
                    await db.commit()
                    return

                run.status = "success"
                run.output = outputs
                await _record_output_activity(
                    db,
                    card_id=card_id,
                    run=run,
                    board=board,
                    workflow=workflow,
                    workflow_name=link["workflow_name"],
                    outputs=outputs,
                    column_instructions=column_instructions,
                )
                chain_outputs.append({"workflow_name": link["workflow_name"], "output": outputs})
                await db.commit()

            await _set_card_status(db, card_id, "success")
            await db.commit()
        if allow_advance:
            # A follow-up round means the human already answered, so it releases the
            # planning gate and the card flows on.
            await _auto_advance(
                card_id=card_id,
                board_id=board_id,
                from_column_id=column_id,
                session_factory=session_factory,
                ignore_gate=rerun,
            )
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
    db,
    card_id: uuid.UUID,
    column_id: uuid.UUID,
    links: list[dict],
    start_index: int,
    position_offset: int = 0,
    chain_length: int | None = None,
) -> None:
    total = chain_length if chain_length is not None else len(links)
    for index in range(start_index, len(links)):
        db.add(
            BoardCardRun(
                card_id=card_id,
                column_id=column_id,
                workflow_id=links[index]["workflow_id"],
                workflow_name=links[index]["workflow_name"],
                chain_position=position_offset + index,
                chain_length=total,
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


async def resume_card_chain(
    execution_history_id: uuid.UUID, *, session_factory=async_session_maker
) -> None:
    """Continue a board chain that paused on a HITL review or a Codex question.

    Called by the HITL / Codex follow-up resume paths once they finish re-running the
    execution. Finds the paused ``BoardCardRun`` by its execution history, records the
    outcome on the card, then runs the rest of that column's chain and auto-advances.
    A no-op for executions that no board started. Never raises.
    """
    try:
        async with session_factory() as db:
            run = (
                (
                    await db.execute(
                        select(BoardCardRun).where(
                            BoardCardRun.execution_history_id == execution_history_id,
                            BoardCardRun.status == "pending",
                        )
                    )
                )
                .scalars()
                .first()
            )
            if run is None:
                return
            history = await db.get(ExecutionHistory, execution_history_id)
            card = await db.get(BoardCard, run.card_id)
            column = await db.get(BoardColumn, run.column_id)
            if history is None or card is None or column is None:
                return
            if history.status == "pending":
                # The resume hit another question; the card keeps waiting.
                return

            board = await db.get(Board, card.board_id)
            workflow = await db.get(Workflow, run.workflow_id)
            links = await _column_links(db, column.id)
            remaining = links[run.chain_position + 1 :]
            run.finished_at = datetime.now(timezone.utc)

            if history.status != "success":
                run.status = "failed"
                run.error = f"Workflow finished with status {history.status}"
                db.add(
                    BoardCardActivity(
                        card_id=card.id,
                        kind="event",
                        author_type="system",
                        content=f"{run.workflow_name} failed",
                        data={"status": history.status},
                        run_id=run.id,
                    )
                )
                await _abort_remaining(
                    db, card.id, column.id, remaining, 0, run.chain_position + 1, run.chain_length
                )
                card.run_status = "failed"
                await db.commit()
                return

            outputs = history.outputs or {}
            run.status = "success"
            run.output = outputs
            await _record_output_activity(
                db,
                card_id=card.id,
                run=run,
                board=board,
                workflow=workflow,
                workflow_name=run.workflow_name,
                outputs=outputs,
                column_instructions=getattr(column, "ai_instructions", None),
            )

            if remaining:
                card.run_status = "running"
                await db.commit()
                _spawn_chain(
                    card_id=card.id,
                    board_id=card.board_id,
                    column_id=column.id,
                    links=remaining,
                    move=None,
                    rerun=False,
                    start_index=run.chain_position + 1,
                    chain_length=run.chain_length,
                    initial_outputs=[{"workflow_name": run.workflow_name, "output": outputs}],
                )
                return

            card.run_status = "success"
            board_id = card.board_id
            column_id = column.id
            card_id = card.id
            await db.commit()

        await _auto_advance(
            card_id=card_id,
            board_id=board_id,
            from_column_id=column_id,
            session_factory=session_factory,
        )
    except Exception:  # noqa: BLE001 - a resume must never crash the answering request
        logger.exception("Board chain resume failed for execution %s", execution_history_id)


async def answer_card_comment(db, *, card, column, board) -> bool:
    """A user comment on a card waiting at the planning gate is its answer.

    The gate column's chain has already run and asked its questions, so the answer does not
    re-run it: it releases the gate and the card flows on to the right. No-op for cards past
    the gate, for cards whose chain never completed here, or while a run is still active.
    """
    columns = (
        (
            await db.execute(
                select(BoardColumn.id)
                .where(BoardColumn.board_id == board.id)
                .order_by(BoardColumn.position)
            )
        )
        .scalars()
        .all()
    )
    if column.id not in columns or columns.index(column.id) >= GATE_COLUMN_INDEX:
        return False

    active = (
        (
            await db.execute(
                select(BoardCardRun.id).where(
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

    # Only a card whose gate chain actually finished is waiting for an answer.
    answered = (
        await db.execute(
            select(BoardCardRun.id).where(
                BoardCardRun.card_id == card.id,
                BoardCardRun.column_id == column.id,
                BoardCardRun.status == "success",
            )
        )
    ).first()
    if answered is None:
        return False

    # Flip to running before the response returns so the board shows the card as active
    # right away; the next column's chain takes over from there.
    card.run_status = "running"
    await db.commit()
    await _auto_advance(
        card_id=card.id, board_id=board.id, from_column_id=column.id, ignore_gate=True
    )
    return True


async def enqueue_card_chain(
    db, *, card, column, board, move: dict | None, rerun: bool, allow_advance: bool = True
) -> bool:
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
    links = await _column_links(db, column.id)
    if not links:
        # No chain on this column. A card moved forward must still keep flowing right,
        # so pass it through to the next column (and the last one).
        if allow_advance and not rerun:
            await _auto_advance(card_id=card.id, board_id=board.id, from_column_id=column.id)
        return False
    card.run_status = "running"
    await db.commit()
    _spawn_chain(
        card_id=card.id,
        board_id=board.id,
        column_id=column.id,
        links=links,
        move=move,
        rerun=rerun,
        allow_advance=allow_advance,
    )
    return True


def _spawn_chain(
    *,
    card_id: uuid.UUID,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    links: list[dict],
    move: dict | None,
    rerun: bool,
    allow_advance: bool = True,
    start_index: int = 0,
    chain_length: int | None = None,
    initial_outputs: list[dict] | None = None,
) -> None:
    """Start a chain run as a background task, holding a strong reference to it."""
    task = asyncio.create_task(
        _run_chain(
            card_id=card_id,
            board_id=board_id,
            column_id=column_id,
            links=links,
            move=move,
            rerun=rerun,
            allow_advance=allow_advance,
            start_index=start_index,
            chain_length=chain_length,
            initial_outputs=initial_outputs,
        )
    )
    _BACKGROUND_CHAIN_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_CHAIN_TASKS.discard)


async def _reindex_column(db, column_id: uuid.UUID) -> None:
    result = await db.execute(
        select(BoardCard)
        .where(BoardCard.column_id == column_id)
        .order_by(BoardCard.position, BoardCard.updated_at)
    )
    for index, card in enumerate(result.scalars().all()):
        card.position = index


async def _auto_advance(
    *,
    card_id: uuid.UUID,
    board_id: uuid.UUID,
    from_column_id: uuid.UUID,
    session_factory=async_session_maker,
    ignore_gate: bool = False,
) -> None:
    """After a successful chain, move the card to the next column (to the right) and run
    that column's chain. Empty columns are passed through; the cascade continues until the
    last column. Never raises (best-effort automation).

    The planning gate: a card sitting in the first two columns (index 0 = Backlog,
    index 1 = Planning) never cascades on its own. Planning runs its chain automatically,
    but the card waits there for a human answer. Auto-advance only applies from index 2 on.
    """
    try:
        async with session_factory() as db:
            columns = (
                (
                    await db.execute(
                        select(BoardColumn)
                        .where(BoardColumn.board_id == board_id)
                        .order_by(BoardColumn.position)
                    )
                )
                .scalars()
                .all()
            )
            ids = [c.id for c in columns]
            if from_column_id not in ids:
                return
            from_index = ids.index(from_column_id)
            if not ignore_gate and from_index < GATE_COLUMN_INDEX:
                # Backlog/Planning: run, then wait for the human. No cascade.
                return
            prev_name = columns[from_index].name
            for target in columns[from_index + 1 :]:
                card = await db.get(BoardCard, card_id)
                if card is None:
                    return
                old_column_id = card.column_id
                count = (
                    await db.execute(
                        select(func.count(BoardCard.id)).where(
                            BoardCard.column_id == target.id, BoardCard.id != card_id
                        )
                    )
                ).scalar() or 0
                card.column_id = target.id
                card.position = count
                await _reindex_column(db, old_column_id)
                await _reindex_column(db, target.id)
                db.add(
                    BoardCardActivity(
                        card_id=card_id,
                        kind="event",
                        author_type="system",
                        content=f"Auto-advanced from {prev_name} to {target.name}",
                        data={
                            "from_column_id": str(old_column_id),
                            "to_column_id": str(target.id),
                            "auto": True,
                        },
                    )
                )

                link_rows = (
                    await db.execute(
                        select(BoardColumnWorkflow, Workflow.name)
                        .join(Workflow, Workflow.id == BoardColumnWorkflow.workflow_id)
                        .where(BoardColumnWorkflow.column_id == target.id)
                        .order_by(BoardColumnWorkflow.position)
                    )
                ).all()
                if link_rows:
                    links = [
                        {
                            "workflow_id": link.workflow_id,
                            "workflow_name": name,
                            "position": link.position,
                        }
                        for link, name in link_rows
                    ]
                    card.run_status = "running"
                    await db.commit()
                    _spawn_chain(
                        card_id=card_id,
                        board_id=board_id,
                        column_id=target.id,
                        links=links,
                        move={"from_column": prev_name, "to_column": target.name},
                        rerun=False,
                    )
                    return
                await db.commit()
                prev_name = target.name

            # The cascade ran out of columns without finding a chain to start, so the card
            # is not executing anything and must not stay marked as running.
            settled = await db.get(BoardCard, card_id)
            if settled is not None and settled.run_status == "running":
                settled.run_status = "success"
                await db.commit()
    except Exception:  # noqa: BLE001 - auto-advance must never break a completed chain
        logger.exception("Board auto-advance failed for card %s", card_id)


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
