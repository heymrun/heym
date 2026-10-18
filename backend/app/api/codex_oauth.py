"""Codex ChatGPT-subscription sign-in (OAuth PKCE) endpoints.

The Codex node can authenticate with a ChatGPT Plus/Pro subscription instead of a pay-per-token
API key. OpenAI's Codex OAuth client redirects to a fixed ``localhost:1455`` callback that Heym's
server cannot receive, so this uses a paste-back flow:

1. ``POST /start`` returns the OpenAI authorize URL. The PKCE ``code_verifier`` is sealed (encrypted
   with the app key) into the opaque ``state`` so it never leaves the server in the clear and no
   server-side session store is required.
2. The user authorizes in a browser and copies the ``localhost:1455`` redirect URL from the address
   bar back into Heym.
3. ``POST /complete`` decrypts the state, exchanges the code for a ChatGPT token bundle, and returns
   the credential config the client saves. Tokens are never logged.

The device code flow needs no paste-back and is what the credential dialog offers first:

1. ``POST /device/start`` asks OpenAI for a short code the user enters at the returned
   verification URL. OpenAI's ``device_auth_id`` is sealed into ``state`` with the user id and
   expiry, so the browser never holds the handle that would claim the tokens.
2. The client calls ``POST /device/poll`` every ``interval`` seconds. It answers ``pending``
   until the user approves, then ``complete`` with the same credential config as ``/complete``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.db.models import User
from app.services.codex_oauth_service import (
    CodexDeviceCode,
    CodexOAuthError,
    CodexOAuthService,
    generate_pkce_pair,
)
from app.services.encryption import decrypt_config, encrypt_config

router = APIRouter()
logger = logging.getLogger(__name__)

_STATE_TYPE = "codex_oauth_state"
_DEVICE_STATE_TYPE = "codex_device_state"
_STATE_TTL_SECONDS = 900  # 15 minutes to authorize and paste back.


class StartResponse(BaseModel):
    authorize_url: str
    state: str


class CompleteRequest(BaseModel):
    state: str
    redirect_url: str


class CompleteResponse(BaseModel):
    config: dict
    account_id: str


class DeviceStartResponse(BaseModel):
    user_code: str
    verification_url: str
    interval: int
    expires_at: str
    state: str


class DevicePollRequest(BaseModel):
    state: str


class DevicePollResponse(BaseModel):
    status: Literal["pending", "complete"]
    config: dict | None = None
    account_id: str = ""


def _seal_state(user_id: str, code_verifier: str) -> str:
    return encrypt_config(
        {
            "type": _STATE_TYPE,
            "user_id": user_id,
            "code_verifier": code_verifier,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _decrypt_state(state: str, user_id: str, state_type: str) -> dict:
    """Decrypt a sealed sign-in state and check it is the right kind and belongs to the user."""
    try:
        payload = decrypt_config(state)
    except Exception as exc:  # noqa: BLE001 - opaque/invalid state should read as a clean 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired sign-in state; restart the ChatGPT sign-in",
        ) from exc
    if not isinstance(payload, dict) or payload.get("type") != state_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sign-in state")
    if str(payload.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Sign-in state does not match user"
        )
    return payload


def _seal_device_state(user_id: str, device_code: CodexDeviceCode) -> str:
    return encrypt_config(
        {
            "type": _DEVICE_STATE_TYPE,
            "user_id": user_id,
            "device_auth_id": device_code.device_auth_id,
            "user_code": device_code.user_code,
            "expires_at": device_code.expires_at,
        }
    )


def _open_device_state(state: str, user_id: str) -> tuple[str, str]:
    """Validate a sealed device sign-in state; return ``(device_auth_id, user_code)``."""
    payload = _decrypt_state(state, user_id, _DEVICE_STATE_TYPE)
    if _is_past(payload.get("expires_at")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The sign-in code expired; start the ChatGPT sign-in again",
        )
    device_auth_id = str(payload.get("device_auth_id") or "")
    user_code = str(payload.get("user_code") or "")
    if not device_auth_id or not user_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sign-in state")
    return device_auth_id, user_code


def _open_state(state: str, user_id: str) -> str:
    """Decrypt and validate the sealed OAuth state; return the PKCE ``code_verifier``."""
    payload = _decrypt_state(state, user_id, _STATE_TYPE)
    if _state_is_expired(payload.get("issued_at")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-in state expired; restart the ChatGPT sign-in",
        )
    code_verifier = str(payload.get("code_verifier") or "")
    if not code_verifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Sign-in state is missing PKCE data"
        )
    return code_verifier


def _state_is_expired(issued_at: object) -> bool:
    try:
        issued = datetime.fromisoformat(str(issued_at))
    except ValueError:
        return True
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - issued).total_seconds() > _STATE_TTL_SECONDS


def _is_past(moment: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(moment))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= parsed


@router.post("/start", response_model=StartResponse)
async def start(current_user: User = Depends(get_current_user)) -> StartResponse:
    """Begin a ChatGPT sign-in and return the OpenAI authorize URL."""
    code_verifier, code_challenge = generate_pkce_pair()
    state = _seal_state(str(current_user.id), code_verifier)
    authorize_url = CodexOAuthService().build_authorize_url(state, code_challenge)
    return StartResponse(authorize_url=authorize_url, state=state)


@router.post("/complete", response_model=CompleteResponse)
async def complete(
    body: CompleteRequest,
    current_user: User = Depends(get_current_user),
) -> CompleteResponse:
    """Exchange the pasted redirect URL for a ChatGPT token bundle credential config."""
    code_verifier = _open_state(body.state, str(current_user.id))
    service = CodexOAuthService()
    try:
        code = service.extract_code(body.redirect_url, expected_state=body.state)
        bundle = await run_in_threadpool(service.exchange_code, code, code_verifier)
    except CodexOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never leak token internals to the client
        logger.exception("Codex ChatGPT token exchange failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ChatGPT sign-in failed during token exchange",
        ) from exc
    return CompleteResponse(config=bundle.to_config(), account_id=bundle.account_id)


@router.post("/device/start", response_model=DeviceStartResponse)
async def device_start(current_user: User = Depends(get_current_user)) -> DeviceStartResponse:
    """Begin a ChatGPT device code sign-in and return the code the user enters at OpenAI."""
    service = CodexOAuthService()
    try:
        device_code = await run_in_threadpool(service.request_device_code)
    except CodexOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return DeviceStartResponse(
        user_code=device_code.user_code,
        verification_url=service.device_verification_url,
        interval=device_code.interval,
        expires_at=device_code.expires_at,
        state=_seal_device_state(str(current_user.id), device_code),
    )


@router.post("/device/poll", response_model=DevicePollResponse)
async def device_poll(
    body: DevicePollRequest,
    current_user: User = Depends(get_current_user),
) -> DevicePollResponse:
    """Report whether the user approved the code; once they have, return the credential config."""
    device_auth_id, user_code = _open_device_state(body.state, str(current_user.id))
    service = CodexOAuthService()
    try:
        grant = await run_in_threadpool(
            service.poll_device_authorization, device_auth_id, user_code
        )
        if grant is None:
            return DevicePollResponse(status="pending")
        bundle = await run_in_threadpool(service.exchange_device_code, grant)
    except CodexOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never leak token internals to the client
        logger.exception("Codex ChatGPT device sign-in failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ChatGPT sign-in failed during token exchange",
        ) from exc
    return DevicePollResponse(
        status="complete", config=bundle.to_config(), account_id=bundle.account_id
    )
