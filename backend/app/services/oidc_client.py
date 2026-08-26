"""A minimal OpenID Connect relying-party client.

Every endpoint is derived from the provider's discovery document, so no provider is named
here. The module knows nothing about Heym's users or database.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

# Asymmetric signatures only. A symmetric algorithm would let anyone holding the client
# secret mint an ID token, and `none` would let anyone at all.
_ALLOWED_SIGNING_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256")
_DISCOVERY_TTL_SECONDS = 300
_HTTP_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 512 * 1024

_discovery_cache: dict[str, tuple[float, "OidcDiscovery"]] = {}


class OidcError(Exception):
    """A provider response could not be used."""


@dataclass(frozen=True)
class OidcDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    signing_algorithms: list[str]
    token_auth_method: str


def parse_discovery_document(document: dict[str, Any]) -> OidcDiscovery:
    """Validate a discovery document and reduce it to the fields the flow needs."""
    required = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
    missing = [key for key in required if not document.get(key)]
    if missing:
        raise OidcError(f"Discovery document is missing: {', '.join(missing)}")

    advertised = document.get("id_token_signing_alg_values_supported") or ["RS256"]
    algorithms = [alg for alg in advertised if alg in _ALLOWED_SIGNING_ALGORITHMS]
    if not algorithms:
        raise OidcError("Provider offers no supported ID token signing algorithm")

    methods = document.get("token_endpoint_auth_methods_supported") or ["client_secret_post"]
    auth_method = "client_secret_post" if "client_secret_post" in methods else "client_secret_basic"

    return OidcDiscovery(
        issuer=str(document["issuer"]),
        authorization_endpoint=str(document["authorization_endpoint"]),
        token_endpoint=str(document["token_endpoint"]),
        jwks_uri=str(document["jwks_uri"]),
        userinfo_endpoint=(
            str(document["userinfo_endpoint"]) if document.get("userinfo_endpoint") else None
        ),
        signing_algorithms=algorithms,
        token_auth_method=auth_method,
    )


def discovery_url(issuer: str) -> str:
    """Return the well-known discovery URL for an issuer."""
    if not issuer.startswith(("http://", "https://")):
        raise OidcError("Issuer must be an http or https URL")
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


async def fetch_discovery(issuer: str, *, use_cache: bool = True) -> OidcDiscovery:
    """Fetch and cache the provider's discovery document."""
    cached = _discovery_cache.get(issuer)
    if use_cache and cached and cached[0] > time.monotonic():
        return cached[1]

    url = discovery_url(issuer)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise OidcError(f"Discovery request failed with HTTP {response.status_code}")
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise OidcError("Discovery document is implausibly large")

    discovery = parse_discovery_document(response.json())
    _discovery_cache[issuer] = (time.monotonic() + _DISCOVERY_TTL_SECONDS, discovery)
    return discovery


def make_pkce_pair() -> tuple[str, str]:
    """Return a fresh (code_verifier, code_challenge) pair using S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorization_url(
    discovery: OidcDiscovery,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    """Build the authorization-code request URL. The verifier is never included."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    separator = "&" if "?" in discovery.authorization_endpoint else "?"
    return f"{discovery.authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_code(
    discovery: OidcDiscovery,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Trade an authorization code for tokens, using the provider's advertised auth method."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": client_id,
    }
    auth: tuple[str, str] | None = None
    if discovery.token_auth_method == "client_secret_basic":
        auth = (client_id, client_secret)
    else:
        form["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.post(discovery.token_endpoint, data=form, auth=auth)

    if response.status_code != 200:
        raise OidcError(f"Token exchange failed with HTTP {response.status_code}")
    payload = response.json()
    if not payload.get("id_token"):
        raise OidcError("Token response contained no id_token")
    return dict(payload)


def get_signing_key(discovery: OidcDiscovery, id_token: str) -> Any:
    """Resolve the provider's signing key for this token. PyJWKClient caches the key set."""
    try:
        return PyJWKClient(discovery.jwks_uri).get_signing_key_from_jwt(id_token).key
    except Exception as exc:  # noqa: BLE001 - any JWKS failure is one failure to the caller
        raise OidcError(f"Could not resolve the provider signing key: {exc}") from exc


def verify_id_token(
    id_token: str,
    *,
    signing_key: Any,
    discovery: OidcDiscovery,
    client_id: str,
    expected_nonce: str,
) -> dict[str, Any]:
    """Verify signature, audience, issuer, expiry, and nonce, then return the claims."""
    try:
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=discovery.signing_algorithms,
            audience=client_id,
            issuer=discovery.issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"ID token rejected: {exc}") from exc

    if not claims.get("sub"):
        raise OidcError("ID token carries no subject")
    # The nonce ties this token to the login this browser started; without it a token
    # captured from another session would be replayable here.
    if claims.get("nonce") != expected_nonce:
        raise OidcError("ID token nonce does not match this login attempt")
    return dict(claims)


async def fetch_userinfo(discovery: OidcDiscovery, access_token: str) -> dict[str, Any]:
    """Fetch userinfo claims. Used only when the ID token carries no email."""
    if not discovery.userinfo_endpoint:
        return {}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.get(
            discovery.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        return {}
    return dict(response.json())
