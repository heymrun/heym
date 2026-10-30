"""Settings-free audit formatting shared by Heym and Heym Work."""

from typing import Any

# Any detail key containing one of these loses its value. Over-redaction is
# deliberate: an unhelpful line beats a leaked credential.
_SENSITIVE_KEY_PARTS = (
    "password",
    "passphrase",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "authorization",
    "cookie",
    "credential_data",
    "value",
    "license_key",
)

_REDACTED = "***"
_MAX_VALUE_LEN = 256

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_DENIED = "denied"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in str(value))
    if len(text) > _MAX_VALUE_LEN:
        text = text[:_MAX_VALUE_LEN] + "...(truncated)"
    if text == "" or any(char in text for char in ' ="') or "\n" in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        return f'"{escaped}"'
    return text


def _render(pairs: list[tuple[str, Any]]) -> str:
    return " ".join(f"{key}={_format_value(value)}" for key, value in pairs if value is not None)


def format_audit_line(
    *,
    action: str,
    outcome: str = OUTCOME_SUCCESS,
    actor_id: object = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: object = None,
    target_name: str | None = None,
    **detail: Any,
) -> str:
    """Render the same bounded, redacted, single-line audit record in either service."""
    pairs: list[tuple[str, Any]] = [
        ("action", action),
        ("outcome", outcome),
        ("actor_id", actor_id),
        ("actor_email", actor_email),
    ]
    if target_id is not None or target_name is not None:
        pairs.extend(
            [
                ("target", f"{target_type or 'unknown'}:{target_id}" if target_id else None),
                ("target_name", target_name),
            ]
        )
    elif target_type is not None:
        pairs.append(("target_type", target_type))
    pairs.extend(
        (key, _REDACTED if _is_sensitive(key) and value is not None else value)
        for key, value in detail.items()
    )
    return "audit " + _render(pairs)
