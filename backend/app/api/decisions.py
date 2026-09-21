"""AI-assisted drafting of decision model questions.

An LLM writes the questions; the decision model answers them at run time. The two
are different kinds of model, so they use different credentials.
"""

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.models.schemas import (
    CredentialType,
    DecisionQuestionsGenerateRequest,
    DecisionQuestionsSuggestionResponse,
)
from app.services.decision_models import QUESTION_TYPES
from app.services.encryption import decrypt_config
from app.services.llm_provider import is_reasoning_model
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext

router = APIRouter()

_SYSTEM_PROMPT = """You design questions for a decision model.

A decision model reads a `state` and answers typed questions about it. It does not
generate prose. There are exactly three question types:

- "noul": whether a condition holds. Returns the probability of yes.
- "choice": picks one option from a set you define. Returns the option and a distribution.
- "score": rates the state along an ordered rubric you define, two to ten levels.

Rules you must follow:
- Each question id is used only by code and is NEVER shown to the model, so the whole
  meaning must live in "instructions". Never write an instruction that depends on the id.
- Ask one narrow, coherent judgment per question. Split independent dimensions into
  separate questions instead of combining them.
- For "choice", include an option that covers "none of these" whenever nothing may fit.
- "score" levels must describe concrete situations and stand on their own, ordered from
  lowest to highest.
- Criteria describe what each answer means, not how to answer.

Respond with JSON only, no prose, in exactly this shape:

{
  "state": "a template describing what the model should read, may use $input.text",
  "questions": [
    {"id": "snake_case_id", "type": "noul", "instructions": "...",
     "criteria": {"true": "...", "false": "..."}},
    {"id": "...", "type": "choice", "instructions": "...",
     "criteria": {"option_key": "what this option means"}},
    {"id": "...", "type": "score", "instructions": "...",
     "criteria": ["lowest level", "middle level", "highest level"]}
  ]
}
"""


def extract_questions_payload(content: str) -> dict | None:
    """Pull the JSON object out of a model response that may be fenced or padded."""
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _slug(value: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "question"


def normalize_generated_questions(
    raw_questions: Any, existing_ids: set[str]
) -> list[dict[str, Any]]:
    """Turn model output into panel rows, dropping anything unusable.

    Ids are slugged and de-duplicated against what the node already holds, because an
    answer comes back keyed by its id and a collision would silently overwrite one.
    """
    if not isinstance(raw_questions, list):
        return []
    taken = set(existing_ids)
    rows: list[dict[str, Any]] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        question_type = str(raw.get("type") or "").strip()
        if question_type not in QUESTION_TYPES:
            continue
        instructions = str(raw.get("instructions") or "").strip()
        if not instructions:
            continue

        base_id = _slug(raw.get("id"))
        candidate = base_id
        suffix = 2
        while candidate in taken:
            candidate = f"{base_id}_{suffix}"
            suffix += 1

        row: dict[str, Any] = {
            "id": candidate,
            "type": question_type,
            "instructions": instructions,
        }
        criteria = raw.get("criteria")
        if question_type == "noul":
            if isinstance(criteria, dict):
                row["criteriaTrue"] = str(criteria.get("true") or "").strip()
                row["criteriaFalse"] = str(criteria.get("false") or "").strip()
        elif question_type == "choice":
            if not isinstance(criteria, dict) or not criteria:
                continue
            row["options"] = [
                {"key": _slug(key), "description": str(value or "").strip()}
                for key, value in criteria.items()
            ]
        else:
            if not isinstance(criteria, list):
                continue
            levels = [str(level).strip() for level in criteria if str(level).strip()]
            if len(levels) < 2:
                continue
            row["levels"] = levels

        taken.add(candidate)
        rows.append(row)
    return rows


@router.post("/generate-questions", response_model=DecisionQuestionsSuggestionResponse)
async def generate_decision_questions(
    request: DecisionQuestionsGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DecisionQuestionsSuggestionResponse:
    """Draft decision questions from a plain-language intent."""
    # Imported lazily to avoid a circular import, matching data_tables.py.
    from app.api.ai_assistant import get_credential_for_user

    credential = await get_credential_for_user(request.credential_id, current_user, db)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LLM credential not found"
        )
    if credential.type not in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.custom,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    raw_base_url = config.get("base_url")

    user_message = f"Intent: {request.prompt.strip()}"
    if request.state_sample:
        user_message += f"\n\nExample state the node will receive:\n{request.state_sample}"
    if request.existing_question_ids:
        user_message += "\n\nThese question ids already exist and must not be reused: " + ", ".join(
            request.existing_question_ids
        )

    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=str(config.get("api_key") or ""),
        base_url=str(raw_base_url) if raw_base_url else None,
        model=request.model,
        system_instruction=_SYSTEM_PROMPT,
        user_message=user_message,
        temperature=None if is_reasoning_model(request.model) else 0.2,
        extra_body={"disable_reasoning": True},
        trace_context=LLMTraceContext(
            user_id=current_user.id,
            credential_id=credential.id,
            source="decision_ai",
            node_label="AI Decision Questions",
        ),
        content_only=True,
    )

    payload = extract_questions_payload(str(result.get("text") or ""))
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse decision questions from the model response",
        )

    questions = normalize_generated_questions(
        payload.get("questions"), set(request.existing_question_ids)
    )
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The model did not return any usable decision questions",
        )

    state = str(payload.get("state") or "").strip() or None
    return DecisionQuestionsSuggestionResponse(state=state, questions=questions)
