"""Decision model (System One) requests: body construction, transport, tracing.

Decision models answer typed questions about a state instead of generating text.
The canonical contract is TypeSafe's: POST {base_url}/v1/systemone with
{model, state, questions} and back {model, answers, usage}. Everything a provider
knows lives in this module.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.http_identity import merge_outbound_headers
from app.services.llm_trace import LLMTraceContext, record_llm_trace
from app.services.ssrf_guard import build_guarded_http_client, guard_http_url

QUESTION_TYPES = ("noul", "choice", "score")

DEFAULT_ENDPOINT_PATH = "/v1/systemone"


class DecisionRequestError(ValueError):
    """Raised when node configuration cannot be turned into a valid request."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _build_noul_criteria(question: dict) -> dict[str, str] | None:
    true_side = _text(question.get("criteriaTrue"))
    false_side = _text(question.get("criteriaFalse"))
    if not true_side and not false_side:
        return None
    criteria: dict[str, str] = {}
    if true_side:
        criteria["true"] = true_side
    if false_side:
        criteria["false"] = false_side
    return criteria


def _build_choice_criteria(question: dict, question_id: str) -> dict[str, str | None]:
    options = question.get("options") or []
    if not isinstance(options, list) or not options:
        raise DecisionRequestError(
            f"Question '{question_id}' is a choice and needs at least one option"
        )
    criteria: dict[str, str | None] = {}
    for option in options:
        if not isinstance(option, dict):
            raise DecisionRequestError(f"Question '{question_id}' has a malformed option")
        key = _text(option.get("key"))
        if not key:
            raise DecisionRequestError(f"Question '{question_id}' has an option with no name")
        if key in criteria:
            raise DecisionRequestError(f"Question '{question_id}' has a duplicate option '{key}'")
        criteria[key] = _text(option.get("description")) or None
    return criteria


def _build_score_criteria(question: dict, question_id: str) -> list[str]:
    levels = question.get("levels") or []
    if not isinstance(levels, list):
        raise DecisionRequestError(f"Question '{question_id}' has malformed levels")
    cleaned = [_text(level) for level in levels if _text(level)]
    if len(cleaned) < 2:
        raise DecisionRequestError(
            f"Question '{question_id}' is a score and needs at least two levels"
        )
    return cleaned


def build_decision_body(
    *,
    model: str,
    state: Any,
    questions: list[dict],
) -> dict[str, Any]:
    """Turn node configuration into a decision model request body.

    Questions arrive as an ordered list because that is how the panel edits them;
    the wire format is a map keyed by question id, and the answer comes back under
    the same key.
    """
    resolved_model = _text(model)
    if not resolved_model:
        raise DecisionRequestError("Decision node requires a model")
    if not questions:
        raise DecisionRequestError("Decision node requires at least one question")

    built: dict[str, Any] = {}
    for question in questions:
        if not isinstance(question, dict):
            raise DecisionRequestError("Decision node has a malformed question row")
        question_id = _text(question.get("id"))
        if not question_id:
            raise DecisionRequestError("Every decision question needs an id")
        if question_id in built:
            raise DecisionRequestError(f"Duplicate decision question id '{question_id}'")

        question_type = _text(question.get("type"))
        if question_type not in QUESTION_TYPES:
            raise DecisionRequestError(
                f"Question '{question_id}' has an unknown type '{question_type}'"
            )

        instructions = _text(question.get("instructions"))
        if not instructions:
            raise DecisionRequestError(f"Question '{question_id}' needs instructions")

        payload: dict[str, Any] = {"type": question_type, "instructions": instructions}
        if question_type == "noul":
            criteria = _build_noul_criteria(question)
            if criteria is not None:
                payload["criteria"] = criteria
        elif question_type == "choice":
            payload["criteria"] = _build_choice_criteria(question, question_id)
        else:
            payload["criteria"] = _build_score_criteria(question, question_id)

        built[question_id] = payload

    return {"model": resolved_model, "state": state, "questions": built}


class DecisionProviderError(RuntimeError):
    """Raised when the decision model endpoint refuses or fails a request."""


def _endpoint_url(base_url: str) -> str:
    """Join the credential's base URL with the evaluation path exactly once."""
    parts = urlsplit(base_url.strip())
    path = (parts.path or "").rstrip("/")
    if not path.endswith(DEFAULT_ENDPOINT_PATH):
        path = f"{path}{DEFAULT_ENDPOINT_PATH}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _error_message(status_code: int, payload: object, text: str) -> str:
    detail = ""
    if isinstance(payload, dict):
        for key in ("detail", "error", "message"):
            value = payload.get(key)
            if value:
                detail = value if isinstance(value, str) else json.dumps(value)
                break
    if not detail:
        detail = text[:300]
    if status_code == 401:
        return "Decision model rejected the API key on this credential"
    if status_code == 422:
        return f"Decision model rejected the request: {detail}"
    if status_code in (429, 529):
        cause = "rate limited" if status_code == 429 else "overloaded"
        return (
            f"Decision model is {cause} ({status_code}). This is a transient condition; "
            "enable retry on this node to ride it out."
        )
    return f"Decision model returned {status_code}: {detail}"


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def call_decision_model(
    *,
    base_url: str,
    api_key: str,
    body: dict,
    timeout: float,
    trace_context: LLMTraceContext | None = None,
) -> dict:
    """Send one evaluation request and return the provider response unchanged.

    The base URL comes from a credential the user typed, so it is guarded and dialled
    through the pinned client rather than a bare httpx client.
    """
    url = _endpoint_url(base_url)
    guard_http_url(url, "decision model endpoint")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    started = time.monotonic()
    payload: object = None
    error: str | None = None
    text = ""
    try:
        with build_guarded_http_client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, headers=merge_outbound_headers(headers), json=body)
            status_code = response.status_code
            text = response.text
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError):
                payload = None
            if status_code >= 400:
                error = _error_message(status_code, payload, text)
            elif not isinstance(payload, dict):
                error = "Decision model did not return a JSON object"
    except httpx.HTTPError as exc:
        error = f"Decision model request failed: {exc}"
    finally:
        if trace_context is not None:
            usage = payload.get("usage") if isinstance(payload, dict) else None
            usage = usage if isinstance(usage, dict) else {}
            prompt_tokens = _int_or_none(usage.get("input_tokens"))
            completion_tokens = _int_or_none(usage.get("output_tokens"))
            record_llm_trace(
                trace_context,
                request_type="decision.systemone",
                request=body,
                response=payload if isinstance(payload, dict) else {"raw": text[:2000]},
                model=(payload.get("model") if isinstance(payload, dict) else None)
                or str(body.get("model") or ""),
                provider="decision",
                error=error,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=(
                    prompt_tokens + completion_tokens
                    if prompt_tokens is not None and completion_tokens is not None
                    else None
                ),
                elapsed_ms=(time.monotonic() - started) * 1000,
            )

    if error:
        raise DecisionProviderError(error)
    if not isinstance(payload, dict):
        raise DecisionProviderError("Decision model did not return a JSON object")
    return payload


def load_decision_credential(credential_id: str) -> dict:
    """Read and decrypt a decision credential by id.

    Imports sit inside the function so this module stays importable from node
    handlers without pulling the DB layer at import time.
    """
    import uuid as _uuid

    from app.db.models import Credential, CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    try:
        credential_uuid = _uuid.UUID(str(credential_id))
    except ValueError as exc:
        raise DecisionRequestError("Decision credential id is not a valid UUID") from exc

    with SessionLocal() as db:
        credential = db.get(Credential, credential_uuid)
        if credential is None:
            raise DecisionRequestError("Decision credential not found")
        if credential.type != CredentialType.decision:
            raise DecisionRequestError("Node credential is not a decision credential")
        config = decrypt_config(credential.encrypted_config)

    base_url = str(config.get("base_url") or "").strip()
    if not base_url:
        raise DecisionRequestError("Decision credential has no base URL configured")
    return {"base_url": base_url, "api_key": str(config.get("api_key") or "")}
