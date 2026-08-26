"""Instance-wide SSO configuration: the singleton row, its secret, and its allowlist."""

from types import SimpleNamespace

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SSO_SETTINGS_ID, SsoSettings
from app.services.encryption import decrypt_config, encrypt_config
from app.services.instance_admin import is_instance_admin
from app.services.public_url import resolve_public_origin

CALLBACK_PATH = "/api/auth/sso/callback"


def callback_url(request: Request) -> str:
    """The redirect URI the provider must allowlist. Derived, never typed by the admin."""
    return resolve_public_origin(request).rstrip("/") + CALLBACK_PATH


def encrypt_client_secret(secret: str) -> str:
    """Encrypt the OIDC client secret for storage.

    The secret is replayed to the provider's token endpoint, so it cannot be hashed the
    way ``secret_tokens.py`` treats secrets that Heym itself verifies.
    """
    return encrypt_config({"client_secret": secret})


def decrypt_client_secret(stored: str | None) -> str:
    """Return the plaintext client secret, or an empty string when none is stored."""
    if not stored:
        return ""
    return str(decrypt_config(stored).get("client_secret", ""))


def email_domain_allowed(email: str, allowed_domains: str) -> bool:
    """Return True when the address is inside the configured domain allowlist.

    An empty allowlist permits every domain. Matching is on the whole domain label, so
    ``notheym.local`` does not satisfy an allowlist of ``heym.local``.
    """
    allowed = {d.strip().lower() for d in allowed_domains.split(",") if d.strip()}
    if not allowed:
        return True
    _, separator, domain = email.strip().lower().rpartition("@")
    if not separator:
        return False
    return domain in allowed


async def get_sso_settings(db: AsyncSession) -> SsoSettings:
    """Return the singleton settings row, creating the default row on first access."""
    result = await db.execute(select(SsoSettings).where(SsoSettings.id == SSO_SETTINGS_ID))
    row = result.scalar_one_or_none()
    if row is None:
        row = SsoSettings(id=SSO_SETTINGS_ID)
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return row


def password_login_blocked(row: SsoSettings, email: str) -> bool:
    """Return True when this address may not use a password on this instance.

    Instance admins are always exempt. That is the break-glass path: whoever can edit the
    environment file can already recover the instance, so the guarantee belongs in code
    rather than in an operator's memory. It lives here, beside the settings it reads, so
    that every password surface can reach it without importing from the API layer.
    """
    if not (row.enabled and row.issuer and row.client_id and row.password_login_disabled):
        return False
    return not is_instance_admin(SimpleNamespace(email=email))
