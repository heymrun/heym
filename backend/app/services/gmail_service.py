"""Gmail API client for the Gmail Trigger and Gmail Send, with OAuth2 token refresh."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.db.models import Credential
from app.services.encryption import encrypt_config

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
# Media upload takes the RFC 5322 message as is, up to Gmail's 35 MB limit.
GMAIL_UPLOAD_BASE = "https://gmail.googleapis.com/upload/gmail/v1/users/me"
# Read mail, send mail, change labels and move to Trash. Never permanent deletion.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_TIMEOUT_SECONDS = 30
# An upload with attachments can take longer than a read.
_SEND_TIMEOUT_SECONDS = 120
_PROVIDER_MESSAGE_LIMIT = 200

_STATUS_DETAIL = {
    401: "credential expired; reconnect it in Credentials",
    403: "Gmail access denied; check the Gmail API and OAuth permissions",
    404: "not found",
    413: "the message is larger than Gmail accepts (35 MB)",
    429: "Gmail rate limit reached; retry later",
}


class GmailApiError(Exception):
    """A Gmail request failed. ``status_code`` is Google's HTTP status, or 502."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _rejection_reason(response: httpx.Response) -> str:
    """Google's own reason for refusing a message, such as "Invalid To header"."""
    try:
        message = response.json().get("error", {}).get("message")
    except (ValueError, AttributeError):
        return ""
    return str(message or "").strip()[:_PROVIDER_MESSAGE_LIMIT]


def decode_raw_message(raw: str) -> bytes:
    """RFC822 bytes from Gmail's base64url ``raw`` field, which may lack padding."""
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


class GmailService:
    """Synchronous Gmail v1 client; a refreshed token is saved on the credential."""

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
            raise GmailApiError(401, "Gmail: reconnect the credential in Credentials")
        try:
            response = httpx.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._config["refresh_token"],
                    "client_id": self._config["client_id"],
                    "client_secret": self._config["client_secret"],
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            tokens = response.json()
            self._config["access_token"] = tokens["access_token"]
            self._config["token_expiry"] = (
                datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
            ).isoformat()
            if tokens.get("refresh_token"):
                self._config["refresh_token"] = tokens["refresh_token"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise GmailApiError(
                401, "Gmail: token refresh failed; reconnect the credential"
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
            raise GmailApiError(401, "Gmail: reconnect the credential in Credentials")
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{GMAIL_BASE}/{path}",
                headers={"Authorization": f"Bearer {self.access_token()}"},
                params=params,
                json=json,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GmailApiError(502, "Gmail: Google could not be reached") from exc
        if response.is_error:
            # Provider bodies can echo addresses or tokens, so only the status is kept.
            detail = _STATUS_DETAIL.get(response.status_code, "Gmail rejected the request")
            raise GmailApiError(response.status_code, f"Gmail: {detail}")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise GmailApiError(502, "Gmail: invalid response from Google") from exc
        if not isinstance(data, dict):
            raise GmailApiError(502, "Gmail: invalid response from Google")
        return data

    def get_profile(self) -> dict[str, Any]:
        """The account address and its current ``historyId``."""
        return self._request("GET", "profile")

    def list_history(self, start_history_id: int, page_token: str | None = None) -> dict[str, Any]:
        """One page of messages added to the mailbox or given a label since the history id."""
        params: list[tuple[str, str]] = [
            ("startHistoryId", str(start_history_id)),
            ("historyTypes", "messageAdded"),
            ("historyTypes", "labelAdded"),
            ("maxResults", "500"),
        ]
        if page_token:
            params.append(("pageToken", page_token))
        return self._request("GET", "history", params=params)

    def get_raw_message(self, message_id: str) -> dict[str, Any]:
        """The message with its RFC822 source in ``raw``."""
        return self._request(
            "GET", f"messages/{quote(message_id, safe='')}", params={"format": "raw"}
        )

    def list_labels(self) -> list[dict[str, Any]]:
        """Every label of the account, system and user labels alike."""
        labels = self._request("GET", "labels").get("labels")
        return [label for label in labels or [] if isinstance(label, dict)]

    def list_send_as(self) -> list[dict[str, Any]]:
        """The account's addresses: the primary one and its Send mail as aliases."""
        items = self._request("GET", "settings/sendAs").get("sendAs")
        return [item for item in items or [] if isinstance(item, dict)]

    def modify_labels(
        self, message_id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> None:
        """Add and remove labels on one message."""
        self._request(
            "POST",
            f"messages/{quote(message_id, safe='')}/modify",
            json={"addLabelIds": add or [], "removeLabelIds": remove or []},
        )

    def send_message(self, mime: bytes) -> dict[str, Any]:
        """Send an RFC 5322 message as the account; Gmail returns its ``id`` and ``threadId``.

        Gmail delivers to every To, Cc and Bcc address in the headers and leaves the Bcc
        header out of what the other recipients receive. The sent copy lands in Sent.
        """
        try:
            response = httpx.post(
                f"{GMAIL_UPLOAD_BASE}/messages/send",
                params={"uploadType": "media"},
                headers={
                    "Authorization": f"Bearer {self.access_token()}",
                    "Content-Type": "message/rfc822",
                },
                content=mime,
                timeout=_SEND_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GmailApiError(502, "Gmail: Google could not be reached") from exc
        if response.status_code == 400:
            # A refused message says why (a malformed address, no recipient); that names
            # only what the node itself sent.
            reason = _rejection_reason(response) or "Gmail refused the message"
            raise GmailApiError(400, f"Gmail: {reason}")
        if response.is_error:
            detail = _STATUS_DETAIL.get(response.status_code, "Gmail rejected the request")
            raise GmailApiError(response.status_code, f"Gmail: {detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise GmailApiError(502, "Gmail: invalid response from Google") from exc
        return data if isinstance(data, dict) else {}

    def trash_message(self, message_id: str) -> None:
        """Move one message to Trash, where Gmail keeps it for 30 days."""
        self._request("POST", f"messages/{quote(message_id, safe='')}/trash")
