"""Run history encryption: AES-256-GCM under a key of the workflow owner's.

While a workflow has ``encrypt_run_history`` on, every history row written for it keeps
placeholders in ``inputs``, ``outputs`` and ``node_results`` (a node skeleton without
inputs, outputs, errors or metadata) and the real values in ``encrypted_payload``.
Sub-workflow runs started by such a run are encrypted too.

The key is not the owner's user id, which other users see through shares and teams. Each
user gets a random 32-byte secret in ``user_history_keys``, wrapped under ENCRYPTION_KEY,
that no API returns. The AES key is derived from it with HKDF, and the row id and workflow
id are the associated data, so a ciphertext only opens on the row it was written for.

Rows are sealed in one place for the ORM (the ``before_flush`` hook in ``app.db.models``)
and through ``seal_insert_values`` for Core inserts. Nothing decrypts implicitly: readers
get placeholders, and decryption happens on the server in ``open_run_payload``, for the
unlock endpoint (which audits) and for run continuations that need the real values.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, attributes
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import ExecutionHistory, UserHistoryKey, Workflow

PAYLOAD_FIELDS = ("inputs", "outputs", "node_results")
SUB_RUN_TRIGGER = "SUB_WORKFLOW"
# Set on a session once it has written an encrypted run, so its sub-workflow rows follow.
SEAL_SUB_RUNS_FLAG = "heym_seal_sub_runs"

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "v1."
_NONCE_BYTES = 12
_HKDF_INFO = b"heym run history v1"
_SKELETON_KEYS = ("node_id", "node_label", "node_type", "status")
_SKELETON_METADATA_KEYS = ("started_at_ms", "sequence")


class RunHistoryUnavailableError(Exception):
    """An encrypted run that can no longer be decrypted (its key or ciphertext is gone)."""


@dataclass(frozen=True)
class RunPayload:
    """A run's real inputs, outputs and node results."""

    inputs: dict
    outputs: dict
    node_results: list


def not_encrypted() -> ColumnElement[bool]:
    """WHERE clause for history rows whose data a reader may use."""
    return ExecutionHistory.encrypted.is_(False)


def node_results_skeleton(node_results: Any) -> list[dict[str, Any]]:
    """Which nodes ran, their status and timing; no inputs, outputs, errors or metadata."""
    if not isinstance(node_results, list):
        return []
    skeleton: list[dict[str, Any]] = []
    for item in node_results:
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            item = dataclasses.asdict(item)
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {key: item.get(key) or "" for key in _SKELETON_KEYS}
        row["execution_time_ms"] = item.get("execution_time_ms") or 0.0
        row["output"] = {}
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            kept = {key: metadata[key] for key in _SKELETON_METADATA_KEYS if key in metadata}
            if kept:
                row["metadata"] = kept
        skeleton.append(row)
    return skeleton


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _derive_key(secret: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(secret)


def _aad(row_id: uuid.UUID, workflow_id: uuid.UUID, purpose: str) -> bytes:
    return f"{purpose}:{row_id}:{workflow_id}".encode()


def seal_payload(
    key: bytes,
    row_id: uuid.UUID,
    workflow_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    purpose: str = "history",
) -> str:
    """Encrypt one run's payload for one row; `purpose` keeps history and queue apart."""
    nonce = os.urandom(_NONCE_BYTES)
    plaintext = json.dumps(payload, default=_json_default, separators=(",", ":")).encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _aad(row_id, workflow_id, purpose))
    return _TOKEN_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def open_payload(
    key: bytes,
    row_id: uuid.UUID,
    workflow_id: uuid.UUID,
    token: str,
    *,
    purpose: str = "history",
) -> dict:
    """Decrypt a payload sealed for this row; raises RunHistoryUnavailableError otherwise."""
    if not token or not token.startswith(_TOKEN_PREFIX):
        raise RunHistoryUnavailableError("Unknown run history ciphertext format")
    try:
        blob = base64.urlsafe_b64decode(token[len(_TOKEN_PREFIX) :].encode())
        plaintext = AESGCM(key).decrypt(
            blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], _aad(row_id, workflow_id, purpose)
        )
    except (InvalidTag, ValueError, binascii.Error) as exc:
        raise RunHistoryUnavailableError("Run history ciphertext does not decrypt") from exc
    payload = json.loads(plaintext.decode())
    return payload if isinstance(payload, dict) else {}


def user_key(connection: Connection, user_id: uuid.UUID, *, create: bool) -> bytes | None:
    """The user's AES key, minting their secret first when `create` is set."""
    from app.services.encryption import decrypt_text, encrypt_text

    def stored() -> str | None:
        return connection.execute(
            select(UserHistoryKey.wrapped_key).where(UserHistoryKey.user_id == user_id)
        ).scalar_one_or_none()

    wrapped = stored()
    if wrapped is None:
        if not create:
            return None
        secret = base64.b64encode(os.urandom(32)).decode()
        connection.execute(
            pg_insert(UserHistoryKey)
            .values(user_id=user_id, wrapped_key=encrypt_text(secret))
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        wrapped = stored()
        if wrapped is None:
            raise RunHistoryUnavailableError("Run history key could not be created")
    try:
        return _derive_key(base64.b64decode(decrypt_text(wrapped)))
    except (InvalidToken, ValueError, binascii.Error) as exc:
        raise RunHistoryUnavailableError("Run history key does not decrypt") from exc


async def ensure_user_key(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Mint the user's key ahead of the first encrypted run."""
    await db.run_sync(lambda session: user_key(session.connection(), user_id, create=True))


def _payload_changed(row: ExecutionHistory) -> bool:
    return any(attributes.get_history(row, name).has_changes() for name in PAYLOAD_FIELDS)


def _place_holders(row: ExecutionHistory, node_results: Any) -> None:
    row.inputs = {}
    row.outputs = {}
    row.node_results = node_results_skeleton(node_results)


def _seal_row(
    connection: Connection,
    row: ExecutionHistory,
    key_user_id: uuid.UUID,
    keys: dict[uuid.UUID, bytes],
) -> None:
    if row.id is None:
        row.id = uuid.uuid4()
    if row.encrypted and row.encrypted_payload and row.encryption_key_user_id is not None:
        # A sealed row being updated (a resumed or finished run): fields not assigned in
        # this flush keep what the ciphertext holds.
        key_user_id = row.encryption_key_user_id
        if key_user_id not in keys:
            existing = user_key(connection, key_user_id, create=False)
            if existing is None:
                raise RunHistoryUnavailableError("Run history key is missing")
            keys[key_user_id] = existing
        base = open_payload(keys[key_user_id], row.id, row.workflow_id, row.encrypted_payload)
        changed = {
            name for name in PAYLOAD_FIELDS if attributes.get_history(row, name).has_changes()
        }
        payload = {
            name: getattr(row, name) if name in changed else base.get(name)
            for name in PAYLOAD_FIELDS
        }
    else:
        payload = {name: getattr(row, name) for name in PAYLOAD_FIELDS}
    if key_user_id not in keys:
        keys[key_user_id] = user_key(connection, key_user_id, create=True) or b""
    payload = {
        "inputs": payload.get("inputs") or {},
        "outputs": payload.get("outputs") or {},
        "node_results": payload.get("node_results") or [],
    }
    row.encrypted_payload = seal_payload(keys[key_user_id], row.id, row.workflow_id, payload)
    row.encrypted = True
    row.encryption_key_user_id = key_user_id
    _place_holders(row, payload["node_results"])


def seal_session_rows(session: Session) -> None:
    """Seal the history rows this flush writes. Called from the ``before_flush`` hook."""
    rows = [obj for obj in session.new if isinstance(obj, ExecutionHistory)]
    rows += [
        obj
        for obj in session.dirty
        if isinstance(obj, ExecutionHistory) and obj not in session.deleted
        if _payload_changed(obj)
    ]
    if not rows:
        return
    connection = session.connection()
    workflow_ids = {row.workflow_id for row in rows if row.workflow_id is not None}
    settings: dict[uuid.UUID, tuple[bool, uuid.UUID]] = {
        workflow_id: (bool(enabled), owner_id)
        for workflow_id, enabled, owner_id in connection.execute(
            select(Workflow.id, Workflow.encrypt_run_history, Workflow.owner_id).where(
                Workflow.id.in_(workflow_ids)
            )
        )
    }

    def sealed_by_own_setting(row: ExecutionHistory) -> bool:
        return bool(row.encrypted) or settings.get(row.workflow_id, (False, None))[0]

    if any(sealed_by_own_setting(row) and row.trigger_source != SUB_RUN_TRIGGER for row in rows):
        session.info[SEAL_SUB_RUNS_FLAG] = True
    elif any(
        isinstance(obj, ExecutionHistory)
        and obj.encrypted
        and obj.trigger_source != SUB_RUN_TRIGGER
        for obj in session.identity_map.values()
    ):
        session.info[SEAL_SUB_RUNS_FLAG] = True
    seal_sub_runs = bool(session.info.get(SEAL_SUB_RUNS_FLAG))

    keys: dict[uuid.UUID, bytes] = {}
    for row in rows:
        owner_id = settings.get(row.workflow_id, (False, None))[1]
        sub_run = row.trigger_source == SUB_RUN_TRIGGER and seal_sub_runs
        if not (sealed_by_own_setting(row) or sub_run):
            continue
        key_user_id = row.encryption_key_user_id or owner_id
        if key_user_id is None:
            continue
        _seal_row(connection, row, key_user_id, keys)


def _seal_values(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    connection = session.connection()
    found = connection.execute(
        select(Workflow.encrypt_run_history, Workflow.owner_id).where(
            Workflow.id == values["workflow_id"]
        )
    ).first()
    sub_run = values.get("trigger_source") == SUB_RUN_TRIGGER
    if found is None or not (found[0] or (sub_run and session.info.get(SEAL_SUB_RUNS_FLAG))):
        return values
    key = user_key(connection, found[1], create=True) or b""
    payload = {
        "inputs": values.get("inputs") or {},
        "outputs": values.get("outputs") or {},
        "node_results": values.get("node_results") or [],
    }
    if not sub_run:
        session.info[SEAL_SUB_RUNS_FLAG] = True
    return {
        **values,
        "inputs": {},
        "outputs": {},
        "node_results": node_results_skeleton(payload["node_results"]),
        "encrypted": True,
        "encrypted_payload": seal_payload(key, values["id"], values["workflow_id"], payload),
        "encryption_key_user_id": found[1],
    }


async def seal_insert_values(db: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    """The values of a Core history INSERT, sealed when the workflow encrypts its runs.

    `values` must carry ``id`` and ``workflow_id``. Every Core insert into
    ``execution_history`` goes through here; ORM writes are sealed by the flush hook.
    """
    return await db.run_sync(lambda session: _seal_values(session, dict(values)))


def stored_run_payload(row: ExecutionHistory) -> RunPayload:
    """What the row itself holds: placeholders for an encrypted run."""
    return _stored_payload(row)


def _stored_payload(row: ExecutionHistory) -> RunPayload:
    return RunPayload(
        inputs=getattr(row, "inputs", None) or {},
        outputs=getattr(row, "outputs", None) or {},
        node_results=getattr(row, "node_results", None) or [],
    )


def _open_row(session: Session, row: ExecutionHistory) -> RunPayload:
    if not row.encrypted:
        return _stored_payload(row)
    if not row.encrypted_payload or row.encryption_key_user_id is None:
        raise RunHistoryUnavailableError("Run history ciphertext is missing")
    key = user_key(session.connection(), row.encryption_key_user_id, create=False)
    if key is None:
        raise RunHistoryUnavailableError("Run history key is missing")
    payload = open_payload(key, row.id, row.workflow_id, row.encrypted_payload)
    return RunPayload(
        inputs=payload.get("inputs") or {},
        outputs=payload.get("outputs") or {},
        node_results=payload.get("node_results") or [],
    )


async def open_run_payload(db: AsyncSession, row: ExecutionHistory) -> RunPayload:
    """A run's real values, decrypted on the server when the row is encrypted.

    Callers outside the unlock endpoint use this only to continue the run itself (a
    resume, a board chain); they never return the values to a user.
    """
    if not getattr(row, "encrypted", False):
        return _stored_payload(row)
    return await db.run_sync(lambda session: _open_row(session, row))


async def open_run_payload_or_placeholders(db: AsyncSession, row: ExecutionHistory) -> RunPayload:
    """`open_run_payload`, falling back to the row's placeholders when it can't decrypt."""
    try:
        return await open_run_payload(db, row)
    except RunHistoryUnavailableError:
        logger.warning("Run history %s could not be decrypted", row.id)
        return _stored_payload(row)


async def unseal_in_place(db: AsyncSession, row: ExecutionHistory) -> None:
    """Put a row's real values on the object before code that reads and rewrites them.

    The next flush seals the row again, so the database never holds the plaintext.
    """
    if not getattr(row, "encrypted", False):
        return
    payload = await open_run_payload(db, row)
    row.inputs = payload.inputs
    row.outputs = payload.outputs
    row.node_results = payload.node_results


# A queued run's row (workflow_run_queue) is kept after the run ends, so its inputs and the
# outputs part of its result are sealed the same way, under a purpose of their own.
QUEUE_SEALED = "__heym_sealed__"
QUEUE_KEY_USER = "__heym_key_user__"
_QUEUE_RESULT_FIELDS = ("outputs", "failed_node", "error")


def is_sealed_queue_value(value: Any) -> bool:
    """Whether a queue row's inputs or result carry sealed values."""
    return isinstance(value, dict) and QUEUE_SEALED in value


def queue_inputs_for_display(inputs: Any) -> dict:
    """A queue row's inputs for a listing: sealed inputs show as empty."""
    if not isinstance(inputs, dict) or is_sealed_queue_value(inputs):
        return {}
    return inputs


def _encrypting_owner(connection: Connection, workflow_id: uuid.UUID) -> uuid.UUID | None:
    found = connection.execute(
        select(Workflow.encrypt_run_history, Workflow.owner_id).where(Workflow.id == workflow_id)
    ).first()
    return found[1] if found is not None and found[0] else None


def _seal_queue(
    session: Session,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    purpose: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    connection = session.connection()
    owner_id = _encrypting_owner(connection, workflow_id)
    if owner_id is None:
        return None
    key = user_key(connection, owner_id, create=True) or b""
    return {
        QUEUE_SEALED: seal_payload(key, execution_id, workflow_id, payload, purpose=purpose),
        QUEUE_KEY_USER: str(owner_id),
    }


def _open_queue(
    session: Session,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    purpose: str,
    sealed: dict[str, Any],
) -> dict:
    try:
        key_user_id = uuid.UUID(str(sealed.get(QUEUE_KEY_USER)))
    except ValueError as exc:
        raise RunHistoryUnavailableError("Queued run key owner is missing") from exc
    key = user_key(session.connection(), key_user_id, create=False)
    if key is None:
        raise RunHistoryUnavailableError("Run history key is missing")
    return open_payload(
        key, execution_id, workflow_id, str(sealed.get(QUEUE_SEALED)), purpose=purpose
    )


async def seal_queue_inputs(
    db: AsyncSession, *, workflow_id: uuid.UUID, execution_id: uuid.UUID, inputs: Any
) -> Any:
    """A queued run's inputs as its row stores them: sealed when the workflow encrypts."""
    sealed = await db.run_sync(
        lambda session: _seal_queue(
            session, workflow_id, execution_id, "queue-inputs", {"inputs": inputs or {}}
        )
    )
    return sealed if sealed is not None else inputs


async def open_queue_inputs(
    db: AsyncSession, *, workflow_id: uuid.UUID, execution_id: uuid.UUID, inputs: Any
) -> Any:
    """A queued run's real inputs, for the instance that runs it or writes its history."""
    if not is_sealed_queue_value(inputs):
        return inputs
    payload = await db.run_sync(
        lambda session: _open_queue(session, workflow_id, execution_id, "queue-inputs", inputs)
    )
    return payload.get("inputs") or {}


async def seal_queue_result(
    db: AsyncSession, *, workflow_id: uuid.UUID, execution_id: uuid.UUID, result: Any
) -> Any:
    """A finished run's queue result with its outputs, failing node and error sealed.

    Status, timing and the other fields stay readable: cancellation and the status URL
    branch on them.
    """
    if not isinstance(result, dict):
        return result
    payload = {field: result.get(field) for field in _QUEUE_RESULT_FIELDS}
    sealed = await db.run_sync(
        lambda session: _seal_queue(session, workflow_id, execution_id, "queue-result", payload)
    )
    if sealed is None:
        return result
    return {**result, "outputs": {}, "failed_node": None, "error": None, **sealed}


async def open_queue_result(
    db: AsyncSession, *, workflow_id: uuid.UUID, execution_id: uuid.UUID, result: Any
) -> Any:
    """A queue result with its sealed fields put back; unsealed results come back as they are."""
    if not is_sealed_queue_value(result):
        return result
    payload = await db.run_sync(
        lambda session: _open_queue(session, workflow_id, execution_id, "queue-result", result)
    )
    opened = {k: v for k, v in result.items() if k not in (QUEUE_SEALED, QUEUE_KEY_USER)}
    opened.update({field: payload.get(field) for field in _QUEUE_RESULT_FIELDS})
    return opened


def redacted_queue_result(result: Any) -> Any:
    """A sealed queue result as a reader without the run token sees it."""
    if not is_sealed_queue_value(result):
        return result
    return {k: v for k, v in result.items() if k not in (QUEUE_SEALED, QUEUE_KEY_USER)}


# A running execution's registry row (active_workflow_executions) is rewritten on every
# heartbeat, so the workflow's setting and the owner's key are cached briefly here.
_OWNER_CACHE_SECONDS = 10.0
_owner_cache: dict[uuid.UUID, tuple[float, uuid.UUID | None]] = {}
_key_cache: dict[uuid.UUID, bytes] = {}
_UNSET: Any = object()


def _cached_owner(connection: Connection, workflow_id: uuid.UUID) -> uuid.UUID | None:
    now = time.monotonic()
    hit = _owner_cache.get(workflow_id)
    if hit is not None and hit[0] > now:
        return hit[1]
    owner_id = _encrypting_owner(connection, workflow_id)
    _owner_cache[workflow_id] = (now + _OWNER_CACHE_SECONDS, owner_id)
    return owner_id


def _cached_key(connection: Connection, owner_id: uuid.UUID) -> bytes:
    key = _key_cache.get(owner_id)
    if key is None:
        key = user_key(connection, owner_id, create=True) or b""
        _key_cache[owner_id] = key
    return key


def _seal_active(
    session: Session,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    inputs: Any,
    node_results: Any,
) -> dict[str, Any]:
    connection = session.connection()
    owner_id = _cached_owner(connection, workflow_id)
    values: dict[str, Any] = {}
    if owner_id is None:
        if inputs is not _UNSET:
            values["inputs"] = inputs
        if node_results is not _UNSET:
            values["node_results"] = node_results
            values["encrypted_node_results"] = None
        return values
    key = _cached_key(connection, owner_id)
    if inputs is not _UNSET:
        values["inputs"] = {
            QUEUE_SEALED: seal_payload(
                key, execution_id, workflow_id, {"inputs": inputs or {}}, purpose="active-inputs"
            ),
            QUEUE_KEY_USER: str(owner_id),
        }
    if node_results is not _UNSET:
        values["node_results"] = node_results_skeleton(node_results)
        values["encrypted_node_results"] = (
            f"{owner_id}:"
            + seal_payload(
                key,
                execution_id,
                workflow_id,
                {"node_results": node_results},
                purpose="active-node-results",
            )
            if node_results
            else None
        )
    return values


async def seal_active_values(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    inputs: Any = _UNSET,
    node_results: Any = _UNSET,
) -> dict[str, Any]:
    """Registry row values for the given fields, sealed when the workflow encrypts.

    Returns ``inputs``, and ``node_results`` with ``encrypted_node_results``, for the
    fields passed.
    """
    return await db.run_sync(
        lambda session: _seal_active(session, workflow_id, execution_id, inputs, node_results)
    )


async def open_active_inputs(
    db: AsyncSession, *, workflow_id: uuid.UUID, execution_id: uuid.UUID, inputs: Any
) -> dict:
    """A registry row's real inputs, for recovery or an audited live view."""
    if not is_sealed_queue_value(inputs):
        return inputs if isinstance(inputs, dict) else {}
    payload = await db.run_sync(
        lambda session: _open_queue(session, workflow_id, execution_id, "active-inputs", inputs)
    )
    return payload.get("inputs") or {}


async def open_active_node_results(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    node_results: Any,
    sealed: str | None,
) -> list:
    """A registry row's real node results, for an audited live view."""
    if not sealed:
        return list(node_results or [])
    owner_text, _, token = sealed.partition(":")

    def _open(session: Session) -> dict:
        envelope = {QUEUE_SEALED: token, QUEUE_KEY_USER: owner_text}
        return _open_queue(session, workflow_id, execution_id, "active-node-results", envelope)

    return list((await db.run_sync(_open)).get("node_results") or [])
