"""Which A2A version a request speaks, from `A2A-Version` and the method name."""

from __future__ import annotations

from app.services.a2a.errors import VERSION_NOT_SUPPORTED, A2AError

A2A_VERSION_HEADER = "A2A-Version"

# A2A 0.3 method names. A 0.3 client sends these and no version header.
LEGACY_METHODS = frozenset(
    {
        "message/send",
        "message/stream",
        "tasks/get",
        "tasks/list",
        "tasks/cancel",
        "tasks/resubscribe",
        "tasks/pushNotificationConfig/set",
        "tasks/pushNotificationConfig/get",
        "tasks/pushNotificationConfig/list",
        "tasks/pushNotificationConfig/delete",
        "agent/getAuthenticatedExtendedCard",
    }
)


def check_version(value: str | None, method: str) -> None:
    """Accept A2A 1.0. A missing header is 1.0 when the method name is a 1.0 name."""
    if method in LEGACY_METHODS:
        raise A2AError(
            VERSION_NOT_SUPPORTED,
            "This agent speaks A2A 1.0. Use the 1.0 method names (SendMessage, GetTask, "
            "...) and send A2A-Version: 1.0.",
        )
    if value is None or not value.strip():
        return
    major, _, rest = value.strip().partition(".")
    minor = rest.partition(".")[0]
    if major != "1" or minor not in ("", "0"):
        raise A2AError(
            VERSION_NOT_SUPPORTED,
            f"A2A version {value.strip()} is not supported. This agent speaks 1.0.",
        )
