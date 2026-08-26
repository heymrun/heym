"""Who administers this instance. Identity comes from the environment, not the database."""

from typing import Protocol

from app.config import settings


class _HasEmail(Protocol):
    email: str


def admin_emails() -> set[str]:
    """The configured instance administrators, lowercased. Empty means nobody."""
    return {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}


def is_admin_email(email: str) -> bool:
    """Return True when this address is listed in HEYM_ADMIN_EMAILS."""
    allowed = admin_emails()
    return bool(allowed) and email.strip().lower() in allowed


def is_instance_admin(user: _HasEmail) -> bool:
    """Return True when the user is listed in HEYM_ADMIN_EMAILS."""
    return is_admin_email(user.email)
