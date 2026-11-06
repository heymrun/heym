"""Turn a labelled Secret into a SecretCredential, or say why it can't be one."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from app.db.models import CredentialType
from app.services.k8s_credentials.store import SecretCredential

LABEL = "heym.run/credential"
ANNOTATION_PREFIX = "heym.run/"
CONFIG_JSON_KEY = "config.json"

# Heym writes refreshed tokens back to these, so they can't be read-only. The write
# guard on the model would refuse the write anyway; rejecting them here says why up
# front instead of failing on the first refresh.
_WRITE_BACK_TYPES = frozenset(
    {
        CredentialType.codex,
        CredentialType.google_sheets,
        CredentialType.google_drive,
        CredentialType.google_meet,
        CredentialType.bigquery,
    }
)
_WRITE_BACK_WHEN_OAUTH = frozenset({CredentialType.linear, CredentialType.notion})


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(",") if part.strip())


def _decode_data(data: dict[str, Any]) -> dict[str, Any]:
    decoded = {}
    for key, raw in data.items():
        try:
            decoded[key] = base64.b64decode(str(raw), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(f"data key {key!r} is not UTF-8 text") from exc
    if CONFIG_JSON_KEY not in decoded:
        return decoded
    if len(decoded) > 1:
        raise ValueError(f"{CONFIG_JSON_KEY} must be the only data key when present")
    try:
        config = json.loads(decoded[CONFIG_JSON_KEY])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CONFIG_JSON_KEY} is not valid JSON: {exc.msg}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"{CONFIG_JSON_KEY} must hold a JSON object")
    return config


def _validation_problem(credential_type: CredentialType, config: dict[str, Any]) -> str | None:
    """The same checks the create endpoint applies, as a message rather than a 400."""
    from fastapi import HTTPException

    from app.api.credentials import validate_credential_config

    try:
        validate_credential_config(credential_type, config)
    except HTTPException as exc:
        return str(exc.detail)
    return None


def parse_secret(secret: dict[str, Any]) -> SecretCredential:
    """Decode one Secret. Problems are recorded on the result, never raised."""
    metadata = secret.get("metadata") or {}
    annotations = metadata.get("annotations") or {}
    namespace = str(metadata.get("namespace") or "")
    secret_name = str(metadata.get("name") or "")

    def annotation(key: str) -> str:
        return str(annotations.get(f"{ANNOTATION_PREFIX}{key}") or "").strip()

    base = {
        "namespace": namespace,
        "secret_name": secret_name,
        "name": annotation("name"),
        "type": annotation("type"),
        "owner_email": annotation("owner").lower(),
        "share_users": tuple(email.lower() for email in _split(annotation("share-users"))),
        "share_teams": _split(annotation("share-teams")),
    }

    def invalid(problem: str) -> SecretCredential:
        return SecretCredential(**base, problem=problem)

    missing = [key for key in ("name", "type", "owner") if not annotation(key)]
    if missing:
        return invalid("missing annotation " + ", ".join(f"heym.run/{k}" for k in missing))
    if len(base["name"]) > 100:
        return invalid("heym.run/name is longer than 100 characters")
    try:
        credential_type = CredentialType(base["type"])
    except ValueError:
        return invalid(f"heym.run/type {base['type']!r} is not a credential type")
    if credential_type in _WRITE_BACK_TYPES:
        return invalid(
            f"type {credential_type.value} stores refreshed tokens, so it can't be read-only"
        )
    try:
        config = _decode_data(secret.get("data") or {})
    except ValueError as exc:
        return invalid(str(exc))
    if credential_type in _WRITE_BACK_WHEN_OAUTH and str(config.get("auth_mode") or "") == "oauth":
        return invalid(f"{credential_type.value} in OAuth mode stores refreshed tokens")
    problem = _validation_problem(credential_type, config)
    if problem:
        return invalid(problem)
    return SecretCredential(**base, config=config)
