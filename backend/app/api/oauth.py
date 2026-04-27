import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.config import settings
from app.db.models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, User
from app.db.session import get_db
from app.services.auth import verify_password
from app.services.auth_rate_limiter import oauth_register_limiter

router = APIRouter()

_CSRF_MAX_AGE_SECONDS = 600  # 10-minute window


def _generate_csrf_token(client_id: str) -> str:
    """Generate a time-bound HMAC CSRF token for the consent form."""
    ts = int(time.time())
    msg = f"{client_id}:{ts}".encode()
    sig = hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()
    return f"{ts}:{sig}"


def _verify_csrf_token(client_id: str, token: str) -> bool:
    """Verify a CSRF token; returns False if invalid or expired."""
    try:
        ts_str, sig = token.split(":", 1)
        ts = int(ts_str)
    except (ValueError, AttributeError):
        return False
    if int(time.time()) - ts > _CSRF_MAX_AGE_SECONDS:
        return False
    expected_msg = f"{client_id}:{ts}".encode()
    expected_sig = hmac.new(settings.secret_key.encode(), expected_msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _h(value: str) -> str:
    """HTML-escape a value for safe embedding in HTML attributes and text."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _render_consent_page(
    *,
    client_name: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    csrf_token: str,
    error: str | None,
) -> str:
    error_html = ""
    if error:
        error_html = f'<div class="error">{_h(error)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Authorize — Heym</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0a0a; color: #e5e5e5;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 1rem;
  }}
  .card {{
    background: #171717; border: 1px solid #262626; border-radius: 12px;
    padding: 2rem; width: 100%; max-width: 400px;
  }}
  .logo {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #a3a3a3; font-size: 0.875rem; margin-bottom: 1.5rem; }}
  .client-name {{ color: #fafafa; font-weight: 600; }}
  label {{ display: block; font-size: 0.875rem; color: #a3a3a3; margin-bottom: 0.375rem; }}
  input {{
    width: 100%; padding: 0.625rem 0.75rem; background: #0a0a0a;
    border: 1px solid #262626; border-radius: 8px; color: #fafafa;
    font-size: 0.875rem; outline: none; transition: border-color 0.15s;
  }}
  input:focus {{ border-color: #525252; }}
  .field {{ margin-bottom: 1rem; }}
  .error {{
    background: #450a0a; border: 1px solid #7f1d1d; border-radius: 8px;
    padding: 0.625rem 0.75rem; font-size: 0.875rem; color: #fca5a5;
    margin-bottom: 1rem;
  }}
  button {{
    width: 100%; padding: 0.625rem; background: #fafafa; color: #0a0a0a;
    border: none; border-radius: 8px; font-size: 0.875rem; font-weight: 600;
    cursor: pointer; transition: background 0.15s;
  }}
  button:hover {{ background: #d4d4d4; }}
  .scope-info {{
    font-size: 0.75rem; color: #737373; margin-top: 1rem; text-align: center;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Heym</div>
  <div class="subtitle">
    <span class="client-name">{_h(client_name)}</span> wants to access your Heym workflows.
  </div>
  {error_html}
  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id" value="{_h(client_id)}" />
    <input type="hidden" name="redirect_uri" value="{_h(redirect_uri)}" />
    <input type="hidden" name="scope" value="{_h(scope)}" />
    <input type="hidden" name="state" value="{_h(state)}" />
    <input type="hidden" name="code_challenge" value="{_h(code_challenge)}" />
    <input type="hidden" name="code_challenge_method" value="{_h(code_challenge_method)}" />
    <input type="hidden" name="csrf_token" value="{_h(csrf_token)}" />
    <div class="field">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" required autocomplete="email" />
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input type="password" id="password" name="password" required autocomplete="current-password" />
    </div>
    <button type="submit">Authorize</button>
  </form>
  <div class="scope-info">Scope: {_h(scope)}</div>
</div>
</body>
</html>"""


async def _get_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    result = await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))
    return result.scalar_one_or_none()


async def _authenticate_client(form: dict, request: Request, db: AsyncSession) -> OAuthClient:
    """Authenticate the OAuth client from form data or Basic auth header."""
    client_id = form.get("client_id", "")
    client_secret = form.get("client_secret")

    # Check Basic auth header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            client_id, client_secret = decoded.split(":", 1)
        except Exception:
            raise HTTPException(400, detail={"error": "invalid_client"})

    client = await _get_client(db, client_id)
    if client is None:
        raise HTTPException(400, detail={"error": "invalid_client"})

    # Confidential clients must provide a valid secret
    if client.is_confidential:
        if not client_secret:
            raise HTTPException(400, detail={"error": "invalid_client"})
        if not bcrypt.checkpw(client_secret.encode(), client.client_secret_hash.encode()):
            raise HTTPException(400, detail={"error": "invalid_client"})

    return client


def _verify_pkce(code_challenge: str, code_verifier: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == code_challenge


async def _issue_tokens(db: AsyncSession, client_id: str, user_id, scope: str) -> dict:
    access_token = secrets.token_urlsafe(40)
    refresh_token = secrets.token_urlsafe(40)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.oauth_access_token_expire_seconds
    )
    refresh_expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.oauth_refresh_token_expire_days
    )

    token = OAuthAccessToken(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        user_id=user_id,
        scope=scope,
        expires_at=expires_at,
        refresh_token_expires_at=refresh_expires_at,
    )
    db.add(token)
    await db.flush()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.oauth_access_token_expire_seconds,
        "refresh_token": refresh_token,
        "scope": scope,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server")
async def oauth_server_metadata(request: Request) -> dict:
    base = (
        settings.oauth_issuer.rstrip("/")
        if settings.oauth_issuer
        else str(request.base_url).rstrip("/")
    )
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
            "none",
        ],
    }


@router.post("/register", status_code=201)
async def register_client(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    ip = get_client_ip(request)
    allowed, retry_after = oauth_register_limiter.is_allowed(ip)
    if not allowed:
        raise HTTPException(
            400,
            detail={"error": "rate_limited", "retry_after": retry_after},
        )

    body = await request.json()
    client_name = body.get("client_name", "MCP Client")
    redirect_uris = body.get("redirect_uris", [])

    if not redirect_uris:
        raise HTTPException(400, detail="redirect_uris required")

    client_id = secrets.token_urlsafe(24)
    client_secret = None
    client_secret_hash = None
    is_confidential = False

    token_auth_method = body.get("token_endpoint_auth_method", "none")
    if token_auth_method in ("client_secret_post", "client_secret_basic"):
        client_secret = secrets.token_urlsafe(32)
        client_secret_hash = bcrypt.hashpw(client_secret.encode(), bcrypt.gensalt()).decode()
        is_confidential = True

    client = OAuthClient(
        client_id=client_id,
        client_secret_hash=client_secret_hash,
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=body.get("grant_types", ["authorization_code"]),
        response_types=body.get("response_types", ["code"]),
        scope=body.get("scope", "mcp"),
        is_confidential=is_confidential,
    )
    db.add(client)
    await db.flush()

    response = {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": client.grant_types,
        "response_types": client.response_types,
        "scope": client.scope,
        "token_endpoint_auth_method": token_auth_method,
    }
    if client_secret:
        response["client_secret"] = client_secret

    return response


@router.get("/authorize")
async def authorize_get(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    scope: str = "mcp",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if response_type != "code":
        raise HTTPException(400, detail="Only response_type=code is supported")

    client = await _get_client(db, client_id)
    if client is None or redirect_uri not in client.redirect_uris:
        raise HTTPException(400, detail="Invalid client_id or redirect_uri")

    csrf_token = _generate_csrf_token(client_id)
    return HTMLResponse(
        _render_consent_page(
            client_name=client.client_name,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            csrf_token=csrf_token,
            error=None,
        )
    )


@router.post("/authorize")
async def authorize_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()

    email = str(form.get("email", ""))
    password = str(form.get("password", ""))
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    scope = str(form.get("scope", "mcp"))
    state = str(form.get("state", ""))
    code_challenge = str(form.get("code_challenge", "")) or ""
    code_challenge_method = str(form.get("code_challenge_method", "")) or ""
    csrf_token = str(form.get("csrf_token", ""))

    # Validate client
    client = await _get_client(db, client_id)
    if client is None or redirect_uri not in client.redirect_uris:
        raise HTTPException(400, detail="Invalid client")

    # Verify CSRF token
    if not _verify_csrf_token(client_id, csrf_token):
        raise HTTPException(
            400, detail="Invalid or expired form token. Please reload and try again."
        )

    # Authenticate user
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()

    if user is None or not verify_password(password, user.hashed_password):
        new_csrf = _generate_csrf_token(client_id)
        return HTMLResponse(
            _render_consent_page(
                client_name=client.client_name,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                csrf_token=new_csrf,
                error="Invalid email or password",
            ),
            status_code=400,
        )

    # Generate authorization code
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.oauth_auth_code_expire_minutes
    )

    auth_code = OAuthAuthorizationCode(
        code=code,
        client_id=client_id,
        user_id=user.id,
        redirect_uri=redirect_uri,
        scope=scope,
        code_challenge=code_challenge or None,
        code_challenge_method=code_challenge_method or None,
        expires_at=expires_at,
    )
    db.add(auth_code)
    await db.flush()

    params: dict[str, str] = {"code": code}
    if state:
        params["state"] = state
    redirect_url = redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(params)
    return RedirectResponse(redirect_url, status_code=302)


@router.post("/token")
async def token_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    grant_type = form.get("grant_type")

    if grant_type == "authorization_code":
        result = await _handle_auth_code_grant(request, dict(form), db)
    elif grant_type == "refresh_token":
        result = await _handle_refresh_token_grant(request, dict(form), db)
    else:
        raise HTTPException(400, detail={"error": "unsupported_grant_type"})

    return JSONResponse(
        content=result,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


async def _handle_auth_code_grant(request: Request, form: dict, db: AsyncSession) -> dict:
    code_str = form.get("code", "")
    redirect_uri = form.get("redirect_uri", "")
    code_verifier = form.get("code_verifier")

    client = await _authenticate_client(form, request, db)

    result = await db.execute(
        select(OAuthAuthorizationCode).where(
            OAuthAuthorizationCode.code == code_str,
            OAuthAuthorizationCode.used.is_(False),
        )
    )
    auth_code = result.scalar_one_or_none()

    if auth_code is None:
        raise HTTPException(400, detail={"error": "invalid_grant"})
    if auth_code.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            400, detail={"error": "invalid_grant", "error_description": "Code expired"}
        )
    if auth_code.redirect_uri != redirect_uri:
        raise HTTPException(400, detail={"error": "invalid_grant"})
    if auth_code.client_id != client.client_id:
        raise HTTPException(400, detail={"error": "invalid_grant"})

    # PKCE verification
    if auth_code.code_challenge:
        if not code_verifier:
            raise HTTPException(
                400,
                detail={
                    "error": "invalid_grant",
                    "error_description": "code_verifier required",
                },
            )
        if not _verify_pkce(auth_code.code_challenge, str(code_verifier)):
            raise HTTPException(
                400,
                detail={
                    "error": "invalid_grant",
                    "error_description": "PKCE verification failed",
                },
            )

    # Mark code as used
    auth_code.used = True
    await db.flush()

    return await _issue_tokens(db, client.client_id, auth_code.user_id, auth_code.scope)


async def _handle_refresh_token_grant(request: Request, form: dict, db: AsyncSession) -> dict:
    refresh_token_str = form.get("refresh_token", "")

    client = await _authenticate_client(form, request, db)

    result = await db.execute(
        select(OAuthAccessToken).where(
            OAuthAccessToken.refresh_token == refresh_token_str,
            OAuthAccessToken.revoked.is_(False),
        )
    )
    token_record = result.scalar_one_or_none()

    if token_record is None:
        raise HTTPException(400, detail={"error": "invalid_grant"})

    if token_record.client_id != client.client_id:
        raise HTTPException(400, detail={"error": "invalid_grant"})

    now = datetime.now(timezone.utc)
    refresh_expires = token_record.refresh_token_expires_at
    if refresh_expires and refresh_expires.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(
            400,
            detail={"error": "invalid_grant", "error_description": "Refresh token expired"},
        )

    # Revoke old token (rotation)
    token_record.revoked = True
    await db.flush()

    return await _issue_tokens(db, client.client_id, token_record.user_id, token_record.scope)
