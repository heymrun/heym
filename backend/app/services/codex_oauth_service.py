"""ChatGPT-subscription OAuth (PKCE) for the Codex node.

Implements the OpenAI ChatGPT sign-in flow directly (no dependency on the ``codex`` CLI) so a
Codex credential can use a ChatGPT Plus/Pro subscription instead of a pay-per-token API key.

The flow is Authorization Code + PKCE (S256):

1. ``create_authorization`` returns an authorize URL plus the ``state`` and ``code_verifier`` the
   caller must retain for the exchange step.
2. The user authorizes in a browser and is redirected to the configured redirect URI
   (``http://localhost:1455/auth/callback`` by default) which carries ``code`` and ``state``.
3. ``exchange_code`` swaps the code + verifier for the ChatGPT token bundle.
4. ``refresh_tokens`` renews an expired bundle using the stored refresh token.

The device code variant (what ``codex login --device-auth`` uses) needs no redirect at all:
``request_device_code`` returns a short code the user enters at ``{issuer}/codex/device``,
``poll_device_authorization`` returns the authorization code once they approve, and
``exchange_device_code`` swaps it for the same token bundle.

Endpoints and the client id default to the public OpenAI Codex CLI values and are overridable via
``HEYM_CODEX_OAUTH_*`` env vars so deployments can adapt without code changes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.config import settings
from app.http_identity import merge_outbound_headers

OAUTH_SCOPE = "openid profile email offline_access"
DEVICE_CODE_TTL_SECONDS = 15 * 60
DEFAULT_DEVICE_POLL_INTERVAL_SECONDS = 5
# OpenAI answers 403 (deviceauth_authorization_pending) until the user approves; the Codex CLI
# also treats 404 as "not yet".
_DEVICE_PENDING_STATUSES = frozenset({403, 404})


@dataclass(frozen=True)
class CodexAuthorization:
    """Values returned when starting a Codex ChatGPT sign-in."""

    authorize_url: str
    state: str
    code_verifier: str


@dataclass(frozen=True)
class CodexTokenBundle:
    """Normalized ChatGPT token bundle stored in a Codex credential."""

    access_token: str
    refresh_token: str
    id_token: str
    account_id: str
    expires_at: str | None

    def to_config(self) -> dict:
        return {
            "auth_mode": "chatgpt",
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "account_id": self.account_id,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class CodexDeviceCode:
    """A pending device code sign-in: the user enters ``user_code`` at the verification URL."""

    device_auth_id: str
    user_code: str
    interval: int
    expires_at: str


@dataclass(frozen=True)
class CodexDeviceGrant:
    """What OpenAI returns once the user approves a device code."""

    authorization_code: str
    code_verifier: str


class CodexOAuthError(ValueError):
    """Raised when the Codex ChatGPT OAuth flow cannot be completed."""


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` using the S256 method."""
    code_verifier = _b64url_no_pad(secrets.token_bytes(64))
    challenge = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return code_verifier, _b64url_no_pad(challenge)


class CodexOAuthService:
    """Drive the OpenAI ChatGPT OAuth PKCE flow for Codex credentials."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._issuer = settings.codex_oauth_issuer.rstrip("/")
        self._client_id = settings.codex_oauth_client_id
        self._redirect_uri = settings.codex_oauth_redirect_uri
        self._client = client

    @property
    def authorize_endpoint(self) -> str:
        return f"{self._issuer}/oauth/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self._issuer}/oauth/token"

    @property
    def device_verification_url(self) -> str:
        return f"{self._issuer}/codex/device"

    @property
    def device_redirect_uri(self) -> str:
        return f"{self._issuer}/deviceauth/callback"

    def build_authorize_url(self, state: str, code_challenge: str) -> str:
        """Build the OpenAI authorize URL for a caller-controlled ``state``/PKCE challenge."""
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": OAUTH_SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
        }
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    def create_authorization(self) -> CodexAuthorization:
        """Generate the authorize URL plus the PKCE ``state`` and ``code_verifier``."""
        code_verifier, code_challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(32)
        return CodexAuthorization(
            authorize_url=self.build_authorize_url(state, code_challenge),
            state=state,
            code_verifier=code_verifier,
        )

    def extract_code(self, redirect_url: str, expected_state: str) -> str:
        """Pull the authorization ``code`` from a pasted redirect URL and validate ``state``.

        Accepts either a full redirect URL (``http://localhost:1455/auth/callback?code=...&state=...``)
        or a bare ``code`` value with the state supplied separately.
        """
        raw = (redirect_url or "").strip()
        if not raw:
            raise CodexOAuthError("Paste the redirect URL from your browser to finish sign-in")

        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        error = (query.get("error") or [""])[0]
        if error:
            description = (query.get("error_description") or [""])[0]
            raise CodexOAuthError(description or f"Authorization failed: {error}")

        code = (query.get("code") or [""])[0]
        if not code:
            # Allow pasting only the code when there is no query string.
            code = raw if not parsed.query and "://" not in raw else ""
        if not code:
            raise CodexOAuthError("Redirect URL is missing the authorization code")

        returned_state = (query.get("state") or [""])[0]
        if returned_state and expected_state and returned_state != expected_state:
            raise CodexOAuthError("OAuth state mismatch; restart the sign-in and try again")
        return code

    def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str | None = None
    ) -> CodexTokenBundle:
        """Exchange an authorization code + PKCE verifier for a ChatGPT token bundle."""
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or self._redirect_uri,
            "client_id": self._client_id,
            "code_verifier": code_verifier,
        }
        return self._token_request(payload)

    def request_device_code(self) -> CodexDeviceCode:
        """Start a device code sign-in and return the code the user enters at OpenAI."""
        response = self._post(
            f"{self._issuer}/api/accounts/deviceauth/usercode",
            json_body={"client_id": self._client_id},
        )
        if response.status_code == 404:
            raise CodexOAuthError(
                "OpenAI does not offer device code sign-in right now; use the redirect URL instead"
            )
        if response.status_code >= 400:
            raise CodexOAuthError(_summarize_token_error(response))
        data = _json_object(response)
        device_auth_id = str(data.get("device_auth_id") or "").strip()
        user_code = str(data.get("user_code") or data.get("usercode") or "").strip()
        if not device_auth_id or not user_code:
            raise CodexOAuthError("OpenAI did not return a device sign-in code")
        return CodexDeviceCode(
            device_auth_id=device_auth_id,
            user_code=user_code,
            interval=_poll_interval_from(data.get("interval")),
            expires_at=_device_expires_at_from(data.get("expires_at")),
        )

    def poll_device_authorization(
        self, device_auth_id: str, user_code: str
    ) -> CodexDeviceGrant | None:
        """Return the grant once the user approved the code, or None while it is still pending."""
        response = self._post(
            f"{self._issuer}/api/accounts/deviceauth/token",
            json_body={"device_auth_id": device_auth_id, "user_code": user_code},
        )
        if response.status_code in _DEVICE_PENDING_STATUSES:
            return None
        if response.status_code >= 400:
            raise CodexOAuthError(_summarize_token_error(response))
        data = _json_object(response)
        authorization_code = str(data.get("authorization_code") or "").strip()
        code_verifier = str(data.get("code_verifier") or "").strip()
        if not authorization_code or not code_verifier:
            raise CodexOAuthError("OpenAI approved the sign-in but returned no authorization code")
        return CodexDeviceGrant(authorization_code=authorization_code, code_verifier=code_verifier)

    def exchange_device_code(self, grant: CodexDeviceGrant) -> CodexTokenBundle:
        """Exchange an approved device code grant for a ChatGPT token bundle."""
        return self.exchange_code(
            grant.authorization_code, grant.code_verifier, redirect_uri=self.device_redirect_uri
        )

    def refresh_tokens(self, refresh_token: str) -> CodexTokenBundle:
        """Renew a ChatGPT token bundle from its refresh token."""
        if not str(refresh_token or "").strip():
            raise CodexOAuthError("Codex credential is missing a refresh token")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "scope": OAUTH_SCOPE,
        }
        bundle = self._token_request(payload)
        # Refresh responses may omit the refresh token; keep the existing one.
        if not bundle.refresh_token:
            bundle = CodexTokenBundle(
                access_token=bundle.access_token,
                refresh_token=refresh_token,
                id_token=bundle.id_token,
                account_id=bundle.account_id,
                expires_at=bundle.expires_at,
            )
        return bundle

    def _token_request(self, payload: dict) -> CodexTokenBundle:
        response = self._post(self.token_endpoint, form=payload)
        if response.status_code >= 400:
            raise CodexOAuthError(_summarize_token_error(response))
        return _bundle_from_token_response(_json_object(response))

    def _post(
        self, url: str, *, form: dict | None = None, json_body: dict | None = None
    ) -> httpx.Response:
        """POST a form or JSON body to OpenAI; transport failures read as ``CodexOAuthError``."""
        client = self._client or httpx.Client(headers=merge_outbound_headers(), timeout=30.0)
        should_close = self._client is None
        try:
            if json_body is not None:
                return client.post(url, json=json_body)
            return client.post(
                url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise CodexOAuthError(f"Could not reach the OpenAI sign-in service: {exc}") from exc
        finally:
            if should_close:
                client.close()


def _json_object(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise CodexOAuthError("OpenAI sign-in service returned an invalid response") from exc
    if not isinstance(data, dict):
        raise CodexOAuthError("OpenAI sign-in service returned an invalid response")
    return data


def _summarize_token_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = ""
    if isinstance(body, dict):
        error = body.get("error")
        # Token errors are OAuth-shaped; the device endpoints nest {"error": {"message": ...}}.
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "").strip()
        else:
            detail = str(body.get("error_description") or error or "").strip()
    return detail or f"OpenAI sign-in service returned HTTP {response.status_code}"


def _poll_interval_from(value: object) -> int:
    """OpenAI sends the poll interval as a string ("5"); keep it within a sane range."""
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_DEVICE_POLL_INTERVAL_SECONDS
    return min(max(seconds, 1), 30)


def _device_expires_at_from(value: object) -> str:
    """Use OpenAI's expiry when it parses and is not past our own 15-minute limit."""
    limit = datetime.now(timezone.utc) + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)
    try:
        expires_at = datetime.fromisoformat(str(value))
    except ValueError:
        return limit.isoformat()
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return min(expires_at, limit).isoformat()


def _bundle_from_token_response(data: dict) -> CodexTokenBundle:
    access_token = str(data.get("access_token") or "").strip()
    id_token = str(data.get("id_token") or "").strip()
    if not access_token and not id_token:
        raise CodexOAuthError("OpenAI token response did not include an access token")
    refresh_token = str(data.get("refresh_token") or "").strip()
    expires_at = _expires_at_from(data.get("expires_in"))
    account_id = _account_id_from_id_token(id_token)
    return CodexTokenBundle(
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        account_id=account_id,
        expires_at=expires_at,
    )


def _expires_at_from(expires_in: object) -> str | None:
    try:
        seconds = int(expires_in)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _account_id_from_id_token(id_token: str) -> str:
    """Best-effort extraction of the ChatGPT account id from the id_token JWT payload."""
    claims = _decode_jwt_payload(id_token)
    auth_claim = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        account_id = str(auth_claim.get("chatgpt_account_id") or "").strip()
        if account_id:
            return account_id
    return str(claims.get("chatgpt_account_id") or claims.get("account_id") or "").strip()


def _decode_jwt_payload(token: str) -> dict:
    parts = (token or "").split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        parsed = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def bundle_is_expired(expires_at: str | None, *, skew_seconds: int = 120) -> bool:
    """Return True when a stored ChatGPT token bundle is at/near expiry."""
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + timedelta(seconds=skew_seconds) >= expiry
