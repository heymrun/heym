"""Capability secrets in a run's inputs, kept out of the rows a queued run leaves behind.

A trigger can hand a run a value that grants access on its own, such as Discord's
interaction token. The run itself may still need it, so the dispatcher cannot drop it,
but a run that goes through the queue is written to more rows than the trigger's own
history write: the queue row (kept after the run ends), the held-runs list, the
registry, and every history row the dispatcher, the worker or the queue writes.

So the dispatcher seals each declared secret before the run is queued: the queue row's
inputs hold a placeholder and its run options hold the value encrypted like a
credential. The worker unseals it in memory to execute, and redacts the value from
everything it persists.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Any

from app.services.encryption import decrypt_text, encrypt_text

REDACTED = "[redacted]"
# The run option that carries the sealed values from the dispatcher to the worker.
SEALED_SECRETS_OPTION = "sealed_input_secrets"

# Returns the same shape it is given, so callers keep their own types.
Redactor = Callable[[Any], Any]
InputPath = Sequence[str]


def redact_values(value: object, secrets: Sequence[str]) -> object:
    """Replace every occurrence of each secret, including inside longer strings.

    New containers are returned, so the caller's structure is left as it was.
    """
    if not secrets:
        return value
    if isinstance(value, dict):
        return {key: redact_values(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_values(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, REDACTED)
    return value


def redactor_for(secrets: Sequence[str]) -> Redactor:
    """One redactor for a run; the identity when the run carries no secret."""
    values = tuple(secret for secret in secrets if secret)
    if not values:
        return lambda value: value
    return lambda value: redact_values(value, values)


def _read(inputs: dict, path: InputPath) -> object:
    current: object = inputs
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _write(inputs: dict, path: InputPath, value: str) -> None:
    current: Any = inputs
    for key in path[:-1]:
        current = current.get(key) if isinstance(current, dict) else None
    if isinstance(current, dict) and path[-1] in current:
        current[path[-1]] = value


def seal_input_secrets(
    inputs: dict, paths: Sequence[InputPath]
) -> tuple[dict, list[dict[str, Any]] | None]:
    """The inputs to store, with each secret at `paths` replaced, and the sealed values.

    With no secret found the caller's own inputs come back unchanged and the sealed list
    is None, so a run that declares nothing is queued exactly as before.
    """
    found = [
        (list(path), value)
        for path in paths
        if path and isinstance(value := _read(inputs, path), str) and value
    ]
    if not found:
        return inputs, None
    stored = copy.deepcopy(inputs)
    for path, _value in found:
        _write(stored, path, REDACTED)
    return stored, [{"path": path, "value": encrypt_text(value)} for path, value in found]


def unseal_input_secrets(inputs: dict, sealed: object) -> tuple[dict, list[str]]:
    """The inputs the run executes with, and the secret values to redact from its rows.

    Rows queued before sealing existed carry no sealed list; they come back unchanged.
    """
    if not isinstance(sealed, list) or not sealed:
        return inputs, []
    restored = copy.deepcopy(inputs)
    secrets: list[str] = []
    for entry in sealed:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        value = decrypt_text(str(entry.get("value") or ""))
        _write(restored, [str(key) for key in entry["path"]], value)
        secrets.append(value)
    return restored, secrets
