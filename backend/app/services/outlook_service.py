"""Microsoft Graph mail client for the Outlook Trigger, with OAuth2 token refresh."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.db.models import Credential
from app.services.encryption import encrypt_config

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_BASE = f"{GRAPH_ROOT}/me"
LOGIN_BASE = "https://login.microsoftonline.com"
# Read mail, mark it read and move it between folders. Heym never deletes permanently.
OUTLOOK_SCOPES: tuple[str, ...] = ("offline_access", "User.Read", "Mail.ReadWrite")
DEFAULT_TENANT = "common"
_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,99}$")
_TIMEOUT_SECONDS = 30
# Immutable ids stay the same when a message moves between folders.
_PREFER_IMMUTABLE_IDS = 'IdType="ImmutableId"'
PAGE_SIZE = 100

_STATUS_DETAIL = {
    401: "credential expired; reconnect it in Credentials",
    403: "Outlook access denied; check the app's Mail.ReadWrite permission",
    404: "not found",
    429: "Microsoft Graph rate limit reached; retry later",
}


class OutlookApiError(Exception):
    """A Graph request failed. ``status_code`` is Microsoft's HTTP status, or 502."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def oauth_tenant(config: dict[str, Any]) -> str:
    """The credential's sign-in tenant: common, organizations, consumers, an id or a domain."""
    tenant = str(config.get("tenant") or "").strip() or DEFAULT_TENANT
    if not _TENANT_PATTERN.match(tenant):
        raise ValueError("Tenant must be common, organizations, consumers, a tenant id or a domain")
    return tenant


def token_url(tenant: str) -> str:
    return f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/token"


def has_mail_scope(scope: str) -> bool:
    """Whether a granted scope string includes Mail.ReadWrite, short or full form."""
    return any(
        item.rsplit("/", 1)[-1].lower() == "mail.readwrite" for item in str(scope or "").split()
    )


def account_address(profile: dict[str, Any]) -> str:
    """The signed-in account's address; personal accounts often have no ``mail``."""
    return str(profile.get("mail") or profile.get("userPrincipalName") or "").strip()


class OutlookService:
    """Synchronous Graph v1.0 client for the signed-in mailbox; refreshed tokens are saved."""

    def __init__(self, credential_id: str, config: dict[str, Any], db: Session) -> None:
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

    def _token_expired(self) -> bool:
        try:
            expiry = datetime.fromisoformat(str(self._config.get("token_expiry") or ""))
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expiry - timedelta(seconds=60)

    def _refresh(self) -> None:
        if not all(
            self._config.get(key) for key in ("refresh_token", "client_id", "client_secret")
        ):
            raise OutlookApiError(401, "Outlook: reconnect the credential in Credentials")
        try:
            response = httpx.post(
                token_url(oauth_tenant(self._config)),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._config["refresh_token"],
                    "client_id": self._config["client_id"],
                    "client_secret": self._config["client_secret"],
                    "scope": " ".join(OUTLOOK_SCOPES),
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            tokens = response.json()
            self._config["access_token"] = tokens["access_token"]
            self._config["token_expiry"] = (
                datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
            ).isoformat()
            # Microsoft rotates refresh tokens; keep the newest one.
            if tokens.get("refresh_token"):
                self._config["refresh_token"] = tokens["refresh_token"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise OutlookApiError(
                401, "Outlook: token refresh failed; reconnect the credential"
            ) from exc
        credential = self._db.query(Credential).filter(Credential.id == self._credential_id).first()
        if credential:
            credential.encrypted_config = encrypt_config(self._config)
            self._db.commit()

    def access_token(self) -> str:
        """A valid access token, refreshed and saved when it is about to expire."""
        if self._token_expired():
            self._refresh()
        token = str(self._config.get("access_token") or "").strip()
        if not token:
            raise OutlookApiError(401, "Outlook: reconnect the credential in Credentials")
        return token

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if not url.startswith(f"{GRAPH_ROOT}/"):
            raise OutlookApiError(502, "Outlook: unexpected Microsoft Graph address")
        try:
            response = httpx.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token()}",
                    "Prefer": _PREFER_IMMUTABLE_IDS,
                },
                params=params,
                json=json,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise OutlookApiError(502, "Outlook: Microsoft Graph could not be reached") from exc
        if response.is_error:
            # Provider bodies can echo addresses or tokens, so only the status is kept.
            detail = _STATUS_DETAIL.get(
                response.status_code, "Microsoft Graph rejected the request"
            )
            raise OutlookApiError(response.status_code, f"Outlook: {detail}")
        return response

    def _json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._send(method, url, params=params, json=json)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise OutlookApiError(502, "Outlook: invalid response from Microsoft Graph") from exc
        if not isinstance(data, dict):
            raise OutlookApiError(502, "Outlook: invalid response from Microsoft Graph")
        return data

    def get_profile(self) -> dict[str, Any]:
        """The signed-in account: ``mail``, ``userPrincipalName`` and ``proxyAddresses``."""
        return self._json(
            "GET",
            GRAPH_BASE,
            params={"$select": "displayName,mail,userPrincipalName,proxyAddresses"},
        )

    def list_messages(
        self, path: str, params: dict[str, Any], limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Messages under ``path`` (relative to /me), following pages up to ``limit``.

        Returns the messages and whether the listing is complete.
        """
        messages: list[dict[str, Any]] = []
        url: str | None = f"{GRAPH_BASE}/{path}"
        query: dict[str, Any] | None = {**params, "$top": str(PAGE_SIZE)}
        while url:
            page = self._json("GET", url, params=query)
            messages.extend(item for item in page.get("value") or [] if isinstance(item, dict))
            if len(messages) >= limit:
                return messages[:limit], not page.get("@odata.nextLink") and len(messages) == limit
            next_link = page.get("@odata.nextLink")
            url = str(next_link) if next_link else None
            query = None  # the next link carries the query
        return messages, True

    def get_mime(self, message_id: str) -> bytes:
        """The message's RFC822 source."""
        response = self._send("GET", f"{GRAPH_BASE}/messages/{quote(message_id, safe='')}/$value")
        return response.content

    def folder_id(self, well_known_name: str) -> str | None:
        """The id of a well-known folder (inbox, sentitems, ...), or None when it is absent."""
        try:
            folder = self._json(
                "GET",
                f"{GRAPH_BASE}/mailFolders/{quote(well_known_name, safe='')}",
                params={"$select": "id"},
            )
        except OutlookApiError as exc:
            if exc.status_code == 404:
                return None
            raise
        return str(folder.get("id") or "") or None

    def list_folders(self, max_folders: int = 500, max_depth: int = 6) -> list[dict[str, Any]]:
        """Every mail folder, children after their parent, with a ``path`` like ``Inbox / Clients``."""
        folders: list[dict[str, Any]] = []
        select = {"$select": "id,displayName,childFolderCount", "$top": "250"}

        def visit(url: str, prefix: str, depth: int) -> None:
            next_url: str | None = url
            query: dict[str, Any] | None = select
            while next_url and len(folders) < max_folders:
                page = self._json("GET", next_url, params=query)
                for item in page.get("value") or []:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    if len(folders) >= max_folders:
                        return
                    name = str(item.get("displayName") or item["id"])
                    path = f"{prefix} / {name}" if prefix else name
                    folders.append({"id": str(item["id"]), "path": path})
                    if int(item.get("childFolderCount") or 0) > 0 and depth < max_depth:
                        folder_id = quote(str(item["id"]), safe="")
                        visit(f"{GRAPH_BASE}/mailFolders/{folder_id}/childFolders", path, depth + 1)
                next_link = page.get("@odata.nextLink")
                next_url = str(next_link) if next_link else None
                query = None

        visit(f"{GRAPH_BASE}/mailFolders", "", 1)
        return folders

    def mark_read(self, message_id: str) -> None:
        """Mark one message as read."""
        self._json(
            "PATCH", f"{GRAPH_BASE}/messages/{quote(message_id, safe='')}", json={"isRead": True}
        )

    def move(self, message_id: str, destination: str) -> None:
        """Move one message to a folder id or a well-known name (archive, deleteditems)."""
        self._json(
            "POST",
            f"{GRAPH_BASE}/messages/{quote(message_id, safe='')}/move",
            json={"destinationId": destination},
        )
