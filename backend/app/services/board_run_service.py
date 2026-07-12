"""Board chain execution: payload building, sequential chain runner, enqueueing."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_HISTORY_ENTRIES = 200


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


async def enqueue_card_chain(db, *, card, column, board, move: dict | None, rerun: bool) -> bool:
    """Start the column's workflow chain for a card. Returns False if nothing was enqueued."""
    raise NotImplementedError
