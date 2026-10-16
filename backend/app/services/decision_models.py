"""Decision model (System One) requests: body construction, transport, tracing.

Decision models answer typed questions about a state instead of generating text.
The canonical contract is TypeSafe's: POST {base_url}/v1/systemone with
{model, state, questions} and back {model, answers, usage}. Everything a provider
knows lives in this module.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.http_identity import merge_outbound_headers
from app.services.llm_trace import LLMTraceContext, record_llm_trace
from app.services.ssrf_guard import build_guarded_http_client, guard_http_url

if TYPE_CHECKING:
    from app.services.decision_images import PreparedImage

QUESTION_TYPES = ("noul", "choice", "score", "box")

DEFAULT_ENDPOINT_PATH = "/v1/systemone"

# TypeSafe's opt-in for images and Box questions. Without it such a request is a 400.
IMAGES_HEADER = "TypeSafe-Danger-Zone-Images"

# Non-object state is placed under this key when images join it.
CONTEXT_STATE_KEY = "context"

_IMAGE_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def _validate_image_names(images: list[PreparedImage]) -> None:
    seen: set[str] = set()
    for image in images:
        if not _IMAGE_NAME_PATTERN.fullmatch(image.name):
            raise DecisionRequestError(
                f"Image name '{image.name}' must start with a letter or underscore and "
                "contain only letters, digits and underscores"
            )
        if image.name in seen:
            raise DecisionRequestError(f"Duplicate image name '{image.name}'")
        seen.add(image.name)


def _merge_images_into_state(state: Any, references: dict[str, str]) -> dict[str, Any]:
    """Place each image reference in the state under its name.

    Questions refer to an image by that name in backticks, the way TypeSafe refers to
    any state field. A non-object state keeps its value under `context`.
    """
    if state is None or (isinstance(state, str) and not state.strip()):
        merged: dict[str, Any] = {}
    elif isinstance(state, dict):
        merged = dict(state)
    else:
        merged = {CONTEXT_STATE_KEY: state}
    for name, reference in references.items():
        if name in merged:
            raise DecisionRequestError(
                f"Image '{name}' collides with a state field of the same name"
            )
        merged[name] = reference
    return merged


def build_decision_body(
    *,
    model: str,
    state: Any,
    questions: list[dict],
    images: list[PreparedImage] | None = None,
) -> dict[str, Any]:
    """Turn node configuration into a decision model request body.

    Questions arrive as an ordered list because that is how the panel edits them;
    the wire format is a map keyed by question id, and the answer comes back under
    the same key.

    Each image is listed once in `assets` under a fresh reference, and the reference
    is placed in the state under the image's name.
    """
    images = images or []
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
        elif question_type == "score":
            payload["criteria"] = _build_score_criteria(question, question_id)
        elif not images:
            # A box locates something in an image and takes no criteria.
            raise DecisionRequestError(
                f"Question '{question_id}' is a box and needs an image: turn on Images and add one"
            )

        built[question_id] = payload

    if not images:
        return {"model": resolved_model, "state": state, "questions": built}

    _validate_image_names(images)
    # A fresh UUID per image per request cannot match the user's text by accident.
    references = {image.name: str(uuid.uuid4()) for image in images}
    assets = {
        references[image.name]: {
            "type": "image",
            "format": image.format,
            "data_base64": base64.b64encode(image.data).decode("ascii"),
        }
        for image in images
    }
    return {
        "model": resolved_model,
        "state": _merge_images_into_state(state, references),
        "assets": assets,
        "questions": built,
    }


def needs_images_header(body: dict) -> bool:
    """True when the body carries an asset or asks a Box question."""
    if body.get("assets"):
        return True
    questions = body.get("questions")
    if not isinstance(questions, dict):
        return False
    return any(
        isinstance(question, dict) and question.get("type") == "box"
        for question in questions.values()
    )


def redact_assets(body: dict) -> dict:
    """A copy of the body safe to store in a trace: image data replaced by its size."""
    assets = body.get("assets")
    if not isinstance(assets, dict) or not assets:
        return body
    redacted: dict[str, Any] = {}
    for reference, asset in assets.items():
        if isinstance(asset, dict) and isinstance(asset.get("data_base64"), str):
            encoded = asset["data_base64"]
            size = len(encoded) * 3 // 4 - encoded[-2:].count("=")
            redacted[reference] = {**asset, "data_base64": f"[base64 image, {size} bytes]"}
        else:
            redacted[reference] = asset
    return {**body, "assets": redacted}


class DecisionProviderError(RuntimeError):
    """Raised when the decision model endpoint refuses or fails a request.

    `status_code` is the HTTP status the endpoint answered with, and None when no
    response arrived, so a caller can retry the transient ones without parsing text.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    if status_code == 413:
        return (
            f"Decision model rejected the request as too large: {detail}. "
            "Send fewer or smaller images."
        )
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
    if needs_images_header(body):
        headers[IMAGES_HEADER] = "true"

    started = time.monotonic()
    payload: object = None
    error: str | None = None
    failed_status: int | None = None
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
                failed_status = status_code
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
                # Base64 images would put megabytes into the traces table per call.
                request=redact_assets(body),
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
        raise DecisionProviderError(error, status_code=failed_status)
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
