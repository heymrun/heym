"""Linear OAuth authorization and callback endpoints."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from jwt import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.encryption import decrypt_config, encrypt_config
from app.services.public_url import resolve_public_origin

router = APIRouter()
logger = logging.getLogger(__name__)

_LINEAR_AUTH_URL = "https://linear.app/oauth/authorize"
_LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"
_LINEAR_SCOPE = "read,write,issues:create,comments:create"
_STATE_TYPE = "linear_oauth_state"
_STATE_TTL_MINUTES = 10


class AuthorizeRequest(BaseModel):
    credential_id: uuid.UUID


class AuthorizeResponse(BaseModel):
    auth_url: str


def create_oauth_state(user_id: str, credential_id: str, redirect_uri: str) -> str:
    """Encode Linear OAuth state as a signed JWT."""
    payload = {
        "user_id": user_id,
        "credential_id": credential_id,
        "redirect_uri": redirect_uri,
        "type": _STATE_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def handle_callback_state(state: str) -> dict | None:
    """Decode and validate the Linear OAuth state."""
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return payload if payload.get("type") == _STATE_TYPE else None
    except InvalidTokenError:
        return None


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Linear OAuth authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _LINEAR_SCOPE,
        "actor": "user",
        "state": state,
    }
    return f"{_LINEAR_AUTH_URL}?{urlencode(params)}"


def _json_for_inline_script(payload: dict) -> str:
    return (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _popup_html(success: bool, credential_id: str = "", message: str = "") -> str:
    payload = (
        {"type": "linear-oauth-success", "credentialId": credential_id}
        if success
        else {"type": "linear-oauth-error", "message": message.replace("\n", " ")}
    )
    script = f"""
        const message = {_json_for_inline_script(payload)};
        if (window.opener) {{
            window.opener.postMessage(message, window.location.origin);
        }}
        window.close();
    """
    return f"<html><body><script>{script}</script></body></html>"


@router.post("/authorize", response_model=AuthorizeResponse)
async def authorize(
    body: AuthorizeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthorizeResponse:
    """Return the Linear OAuth authorization URL for the popup flow."""
    cred_uuid = body.credential_id
    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.owner_id == current_user.id,
            Credential.type == CredentialType.linear,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    config = decrypt_config(credential.encrypted_config)
    client_id = str(config.get("client_id", "")).strip()
    client_secret = str(config.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential is missing client_id or client_secret",
        )
    redirect_uri = (
        resolve_public_origin(request).rstrip("/") + "/api/credentials/linear/oauth/callback"
    )
    state_token = create_oauth_state(str(current_user.id), str(cred_uuid), redirect_uri)
    return AuthorizeResponse(auth_url=build_auth_url(client_id, redirect_uri, state_token))


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Exchange the Linear authorization code and persist the OAuth token."""
    if error or not code or not state:
        return HTMLResponse(_popup_html(False, message=error or "Authorization cancelled"))
    payload = handle_callback_state(state)
    if not payload:
        return HTMLResponse(_popup_html(False, message="Invalid or expired state"))

    try:
        credential_id = uuid.UUID(payload["credential_id"])
        user_id = uuid.UUID(payload["user_id"])
    except (KeyError, ValueError, TypeError):
        return HTMLResponse(_popup_html(False, message="Invalid OAuth state"))

    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.owner_id == user_id,
            Credential.type == CredentialType.linear,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        return HTMLResponse(_popup_html(False, message="Credential not found"))

    config = decrypt_config(credential.encrypted_config)
    client_id = str(config.get("client_id", "")).strip()
    client_secret = str(config.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        return HTMLResponse(
            _popup_html(False, message="Credential is missing client_id or client_secret")
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _LINEAR_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": payload["redirect_uri"],
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        response.raise_for_status()
        token_data = response.json()
        if not isinstance(token_data, dict):
            raise ValueError("Linear token response must be a JSON object")
        access_token = str(token_data.get("access_token", "")).strip()
        if not access_token:
            raise ValueError("Linear token response is missing access_token")
    except (httpx.HTTPError, ValueError, TypeError):
        logger.exception("Linear OAuth token exchange failed")
        return HTMLResponse(_popup_html(False, message="Token exchange failed"))

    config.pop("api_key", None)
    config.update(
        {
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
            "auth_mode": "oauth",
        }
    )
    if token_data.get("expires_in"):
        try:
            config["token_expiry"] = (
                datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))
            ).isoformat()
        except (TypeError, ValueError):
            config.pop("token_expiry", None)
    credential.encrypted_config = encrypt_config(config)
    await db.commit()
    return HTMLResponse(_popup_html(True, credential_id=str(credential.id)))
