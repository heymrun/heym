"""Inputs for an agent suite's runs: the workflow's last inputs, or ones a model writes."""

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CredentialType, ExecutionHistory
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import build_router_for_credential

MAX_SUITE_RUNS = 20


def unwrap_run_inputs(inputs: Any) -> dict[str, Any]:
    """The input fields of a stored run; webhook-style runs keep them under ``body``."""
    if not isinstance(inputs, dict):
        return {}
    body = inputs.get("body")
    if isinstance(body, dict):
        return dict(body)
    return {key: value for key, value in inputs.items() if key not in ("headers", "query")}


async def previous_run_inputs(
    db: AsyncSession, workflow_id: uuid.UUID
) -> tuple[dict[str, Any] | None, datetime | None]:
    """Inputs of the workflow's most recent run, and when it started."""
    row = (
        await db.execute(
            select(ExecutionHistory.inputs, ExecutionHistory.started_at)
            .where(ExecutionHistory.workflow_id == workflow_id)
            .order_by(ExecutionHistory.started_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None
    return unwrap_run_inputs(row.inputs), row.started_at


def parse_generated_inputs(
    text: str, fields: list[str], example: dict[str, Any], count: int
) -> list[dict[str, Any]]:
    """Read ``{"inputs": [...]}`` from a model's answer, keeping only the workflow's fields.

    A missing field keeps the example's value. Fewer objects than asked are repeated in
    order; none at all is an error, since running with nothing would test nothing.
    """
    start, end = text.find("{"), text.rfind("}")
    try:
        payload = json.loads(text[start : end + 1]) if start >= 0 and end > start else None
    except json.JSONDecodeError:
        payload = None
    items = payload.get("inputs") if isinstance(payload, dict) else None
    generated: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if fields:
            generated.append({key: item.get(key, example.get(key, "")) for key in fields})
        else:
            generated.append(item)
    if not generated:
        raise ValueError("The model returned no usable inputs. Try another model.")
    return [generated[index % len(generated)] for index in range(count)]


MAX_PROMPT_INSTRUCTIONS_CHARS = 6000


def build_generation_prompt(
    *,
    workflow_name: str,
    fields: list[str],
    example: dict[str, Any],
    count: int,
    agent_label: str | None = None,
    agent_instructions: str | None = None,
    agent_message: str | None = None,
) -> str:
    """The request for test inputs: what the agent is for, and the example to stay close to.

    Without the agent's instructions a model only sees the example, so an input such as
    "Frankfurt" comes back as unrelated text instead of other cities.
    """
    keys = ", ".join(fields) if fields else "the same keys as the example"
    parts = [
        f"You write test inputs for an AI agent{f' called {agent_label!r}' if agent_label else ''} "
        f'that runs inside the workflow "{workflow_name}".'
    ]
    if agent_instructions and agent_instructions.strip():
        parts.append(
            "The agent's system instructions:\n<<<\n"
            + agent_instructions.strip()[:MAX_PROMPT_INSTRUCTIONS_CHARS]
            + "\n>>>"
        )
    if agent_message and agent_message.strip():
        parts.append(f"The agent receives the workflow input through this message: {agent_message}")
    parts.append(
        "The user wrote this input as the example to vary:\n"
        + json.dumps(example, ensure_ascii=False, default=str)
    )
    parts.append(
        f"Write {count} new inputs this agent is meant to handle. Stay close to the example in "
        "subject, kind of value, length, format and language: if it is a city name, write other "
        "city names; if it is a customer message, write other customer messages. Vary them so "
        "the runs cover different cases, including a few harder ones.\n"
        f"Each input is a JSON object with exactly these keys: {keys}.\n"
        'Answer with JSON only: {"inputs": [...]}'
    )
    return "\n\n".join(parts)


async def generate_run_inputs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    credential_id: uuid.UUID,
    model: str,
    workflow_name: str,
    fields: list[str],
    example: dict[str, Any],
    count: int,
    session_id: str,
    agent_label: str | None = None,
    agent_instructions: str | None = None,
    agent_message: str | None = None,
) -> list[dict[str, Any]]:
    """Ask a model for ``count`` varied inputs close to ``example``, for what the agent does."""
    credential = await get_accessible_credential(
        db=db, credential_id=credential_id, user_id=user_id
    )
    if credential is None:
        raise ValueError("Credential not found")
    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    prompt = build_generation_prompt(
        workflow_name=workflow_name,
        fields=fields,
        example=example,
        count=count,
        agent_label=agent_label,
        agent_instructions=agent_instructions,
        agent_message=agent_message,
    )
    llm_kwargs: dict[str, Any] = {
        "credential_type": credential.type.value,
        "api_key": config.get("api_key", ""),
        "base_url": config.get("base_url") if credential.type == CredentialType.custom else None,
        "model": model,
        "system_instruction": None,
        "user_message": prompt,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
        "trace_context": LLMTraceContext(
            user_id=user_id,
            credential_id=credential_id,
            source="evals",
            node_label="agent_suite_inputs",
            session_id=session_id,
        ),
        "router": router,
    }
    if is_reasoning_model(model):
        llm_kwargs["reasoning_effort"] = "low"
    else:
        llm_kwargs["temperature"] = 0.9
    result = await execute_llm(**llm_kwargs)
    return parse_generated_inputs(str(result.get("text") or ""), fields, example, count)


def agent_trace_ids(node_results: Any, node_id: str) -> list[str]:
    """Trace ids the agent node recorded during one execution, in run order."""
    ids: list[str] = []
    for result in node_results if isinstance(node_results, list) else []:
        if not isinstance(result, dict) or result.get("node_id") != node_id:
            continue
        metadata = result.get("metadata")
        trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
        if isinstance(trace_id, str) and trace_id:
            ids.append(trace_id)
    return ids
