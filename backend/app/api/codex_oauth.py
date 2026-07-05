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
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.db.models import User
from app.services.codex_oauth_service import (
    CodexOAuthError,
    CodexOAuthService,
    generate_pkce_pair,
)
from app.services.encryption import decrypt_config, encrypt_config

router = APIRouter()
logger = logging.getLogger(__name__)

_STATE_TYPE = "codex_oauth_state"
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


def _seal_state(user_id: str, code_verifier: str) -> str:
    return encrypt_config(
        {
            "type": _STATE_TYPE,
            "user_id": user_id,
            "code_verifier": code_verifier,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _open_state(state: str, user_id: str) -> str:
    """Decrypt and validate the sealed OAuth state; return the PKCE ``code_verifier``."""
    try:
        payload = decrypt_config(state)
    except Exception as exc:  # noqa: BLE001 - opaque/invalid state should read as a clean 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired sign-in state; restart the ChatGPT sign-in",
        ) from exc
    if not isinstance(payload, dict) or payload.get("type") != _STATE_TYPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sign-in state")
    if str(payload.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Sign-in state does not match user"
        )
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
