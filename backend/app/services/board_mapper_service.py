"""Board agentic mapper: translate a card's full context into a target workflow's inputs.

When a board has a mapper model + credential configured, the board calls each column
workflow through this service instead of passing the fixed ``build_card_payload`` shape.
A single structured LLM call (using the board's model/credential) inspects the target
workflow and the card's full context and returns the ``inputs`` object for that specific
workflow. The mapper decides, as its own business logic, how much context/history to
carry (deterministic transforms usually need little; agentic workflows benefit from more).

Trace source is ``kanban_ai_mapper``. Errors are strict: any failure raises, and the
caller (``board_run_service._run_chain``) fails that chain link.
"""

import json
import logging
from typing import Any

from sqlalchemy import select

from app.db.models import Board, Credential
from app.services.encryption import decrypt_config
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext

logger = logging.getLogger(__name__)

_AGENTIC_NODE_TYPES = {"agent", "llm", "codex"}

MAPPER_SYSTEM_PROMPT = (
    "You map a kanban task into the inputs of one specific workflow. You are given the "
    "workflow's input field keys, a summary of what the workflow does, an optional column "
    "instruction, and the full available task context. Decide how much of the task context "
    "to include based on the workflow: deterministic transforms usually need only the "
    "latest relevant value; agentic workflows (agent/llm/codex) benefit from history, "
    "notes and comments. Return ONLY a JSON object whose keys are the workflow's input "
    "field keys with the values you mapped. Do not use 'board' as a key; it is reserved. "
    "If there are no declared input fields, return a small JSON object with the fields the "
    "workflow most likely needs."
)


def board_mapper_is_configured(board: Board) -> bool:
    """True when the board has both a mapper model and a credential set."""
    return bool(getattr(board, "mapper_model", None)) and (
        getattr(board, "mapper_credential_id", None) is not None
    )


def _input_field_keys(nodes: list[dict]) -> list[str]:
    keys: list[str] = []
    for node in nodes or []:
        data = node.get("data") or {}
        for field in data.get("inputFields") or []:
            key = field.get("key") if isinstance(field, dict) else None
            if key and key not in keys:
                keys.append(key)
    return keys


def _workflow_summary(workflow: Any) -> dict:
    nodes = workflow.nodes or []
    node_types = [n.get("type") for n in nodes if n.get("type")]
    labels = [(n.get("data") or {}).get("label") or n.get("type") for n in nodes]
    return {
        "name": workflow.name,
        "description": getattr(workflow, "description", None),
        "node_types": node_types,
        "node_labels": labels,
        "is_agentic": any(t in _AGENTIC_NODE_TYPES for t in node_types),
    }


def _reserved_board_block(available_context: dict, board: Board) -> dict:
    card = available_context.get("card") or {}
    move = available_context.get("move")
    return {
        "board_id": str(board.id),
        "board_name": board.name,
        "card_id": card.get("id"),
        "card_title": card.get("title"),
        "rerun": bool(available_context.get("rerun")),
        "move": move,
    }


async def build_workflow_inputs(
    db,
    *,
    board: Board,
    column_ai_instructions: str | None,
    available_context: dict,
    workflow: Any,
) -> dict:
    """Return the ``inputs`` dict for ``workflow`` mapped from ``available_context``.

    ``available_context`` is the full fixed payload (from ``build_card_payload``); it is
    the complete context the mapper may draw from. Raises on any failure (strict).
    """
    credential = (
        await db.execute(
            select(Credential).where(
                Credential.id == board.mapper_credential_id,
                Credential.owner_id == board.owner_id,
            )
        )
    ).scalar_one_or_none()
    if credential is None:
        raise ValueError("Board mapper credential not found")

    config = decrypt_config(credential.encrypted_config)
    api_key = config.get("api_key", "")
    base_url = config.get("base_url") if credential.type.value == "custom" else None

    input_fields = _input_field_keys(workflow.nodes)
    payload_for_llm = {
        "workflow": _workflow_summary(workflow),
        "input_fields": input_fields,
        "column_instruction": column_ai_instructions or "",
        "available_context": available_context,
    }

    trace_context = LLMTraceContext(
        user_id=board.owner_id,
        credential_id=credential.id,
        workflow_id=getattr(workflow, "id", None),
        node_label="board_mapper",
        source="kanban_ai_mapper",
    )

    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=api_key,
        base_url=base_url,
        model=board.mapper_model,
        system_instruction=MAPPER_SYSTEM_PROMPT,
        user_message=json.dumps(payload_for_llm, default=str),
        response_format={"type": "json_object"},
        content_only=True,
        trace_context=trace_context,
    )

    text = (result.get("text") or "").strip()
    if not text:
        raise ValueError("Mapper returned an empty response")
    try:
        inputs = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Mapper returned invalid JSON: {exc}") from exc
    if not isinstance(inputs, dict):
        raise ValueError("Mapper output must be a JSON object")

    # Always convey task detail, regardless of what the mapper chose to include.
    inputs["board"] = _reserved_board_block(available_context, board)
    return inputs
