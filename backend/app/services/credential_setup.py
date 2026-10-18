"""Credential forms the user fills in on Heym's own page, for MCP chat turns.

An MCP client cannot show Heym's credential dialog, and a secret must never pass through it
or the model. The `heym_chat` assistant calls `request_credential_form` instead: Heym opens a
`CredentialSetupRequest`, and the user saves the credential at `/credentials/setup/<id>`,
signed in as the same user. When the client supports URL-mode elicitation, Heym asks it to
open that page and waits for the form, so the turn continues with the new credential.
Otherwise the link goes back in the reply and the user answers once they have saved it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialSetupRequest, CredentialType, DashboardMessage
from app.db.session import async_session_maker
from app.services.mcp_elicitation import (
    ElicitationReply,
    MCPClientChannel,
    elicitation_complete_notification,
    url_elicitation_request,
)

REQUEST_CREDENTIAL_FORM_TOOL = "request_credential_form"

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_DECLINED = "declined"
STATUS_EXPIRED = "expired"

SETUP_REQUEST_TTL = timedelta(hours=24)
# How long one tool call waits for the form before it hands the link back.
FORM_WAIT_SECONDS = 600.0
FORM_POLL_SECONDS = 1.0
# How long a `heym_chat` call with `wait_for_credential_form` waits for the user.
FORM_FOLLOW_UP_WAIT_SECONDS = 300.0
_MAX_FORMS_IN_PROMPT = 10
_MAX_REASON_LENGTH = 500
_MAX_NAME_LENGTH = 100

REQUEST_CREDENTIAL_FORM_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REQUEST_CREDENTIAL_FORM_TOOL,
        "description": (
            "Open Heym's credential form for the user in their browser, to create a credential "
            "or update one they own. The user types the values on Heym's own page; they never "
            "pass through this chat. Waits for the user when their app can open the page, "
            "otherwise returns a link to give them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update"]},
                "credential_type": {
                    "type": "string",
                    "description": "Type of the credential to create, for example github.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Suggested name for a new credential. It must differ from every "
                        "credential name the user has."
                    ),
                },
                "credential_id": {
                    "type": "string",
                    "description": "Id of the credential to update.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "One sentence in the user's language on what the credential is for. "
                        "The form shows it."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


def credential_setup_url(public_base_url: str, request_id: uuid.UUID) -> str:
    """The Heym page where the user fills in one credential form."""
    return f"{public_base_url.rstrip('/')}/credentials/setup/{request_id}"


def _effective_status(status: str, expires_at: datetime, now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if status == STATUS_PENDING and expires_at <= moment:
        return STATUS_EXPIRED
    return status


def setup_request_status(row: CredentialSetupRequest, now: datetime | None = None) -> str:
    """The request's status, with a pending request past its expiry reported as expired."""
    return _effective_status(row.status, row.expires_at, now)


async def record_elicitation_reply(
    db: AsyncSession, user_id: uuid.UUID, reply: ElicitationReply
) -> None:
    """Store the client's answer on the user's pending request; a decline closes it."""
    values: dict[str, Any] = {"client_action": reply.action}
    if reply.action == "decline":
        values["status"] = STATUS_DECLINED
    await db.execute(
        update(CredentialSetupRequest)
        .where(
            CredentialSetupRequest.id == reply.elicitation_id,
            CredentialSetupRequest.user_id == user_id,
            CredentialSetupRequest.status == STATUS_PENDING,
        )
        .values(**values)
    )


def _opened_by(row: CredentialSetupRequest, args: object) -> bool:
    """Whether a `request_credential_form` call with `args` opened this request."""
    if not isinstance(args, dict) or args.get("action") != row.action:
        return False
    if row.action == "update":
        return str(args.get("credential_id") or "").strip().lower() == str(row.credential_id)
    return (
        str(args.get("credential_type") or "").strip() == row.credential_type
        and _text(args.get("name"), _MAX_NAME_LENGTH) == row.suggested_name
    )


async def settle_form_step(db: AsyncSession, row: CredentialSetupRequest, summary: str) -> None:
    """Finish the chat step that opened this form, so the Chat tab stops showing it pending.

    The step only stores the call's arguments, so the newest pending step whose arguments
    opened this request is the one. The caller commits.
    """
    if row.conversation_id is None:
        return
    result = await db.execute(
        select(DashboardMessage)
        .where(
            DashboardMessage.conversation_id == row.conversation_id,
            DashboardMessage.role == "assistant",
        )
        .order_by(DashboardMessage.created_at.desc())
        .limit(_MAX_FORMS_IN_PROMPT)
    )
    for message in result.scalars():
        calls = list(message.tool_calls or [])
        for index, call in enumerate(calls):
            if (
                isinstance(call, dict)
                and call.get("name") == REQUEST_CREDENTIAL_FORM_TOOL
                and call.get("status") == "pending"
                and _opened_by(row, call.get("args"))
            ):
                calls[index] = {**call, "status": "success", "response_summary": summary}
                message.tool_calls = calls
                return


async def wait_for_conversation_forms(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    public_base_url: str,
    session_factory: Callable[[], Any] = async_session_maker,
) -> list[str]:
    """Wait until no form this conversation opened is still open.

    Returns the links of the forms still open when the wait ends, or none once the user has
    saved or declined every one.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + FORM_FOLLOW_UP_WAIT_SECONDS
    while True:
        async with session_factory() as db:
            result = await db.execute(
                select(CredentialSetupRequest.id).where(
                    CredentialSetupRequest.conversation_id == conversation_id,
                    CredentialSetupRequest.user_id == user_id,
                    CredentialSetupRequest.status == STATUS_PENDING,
                    CredentialSetupRequest.expires_at > datetime.now(timezone.utc),
                )
            )
            open_ids = list(result.scalars())
        if not open_ids:
            return []
        if loop.time() >= deadline:
            return [credential_setup_url(public_base_url, request_id) for request_id in open_ids]
        await asyncio.sleep(FORM_POLL_SECONDS)


@dataclass(frozen=True)
class CredentialFormOutcome:
    """One `request_credential_form` call: the result for the model and its step row."""

    result: str
    summary: str
    status: str


@dataclass(frozen=True)
class _FormSpec:
    action: str
    credential_type: str
    name: str | None
    credential_id: uuid.UUID | None
    reason: str | None

    @property
    def message(self) -> str:
        if self.reason:
            return self.reason
        if self.action == "update":
            return (
                f'Update the "{self.name}" credential on Heym\'s page. Its values never pass '
                "through this app."
            )
        return (
            f"Heym needs a {self.credential_type} credential. Enter it on Heym's page; it never "
            "passes through this app."
        )


@dataclass(frozen=True)
class _FormState:
    status: str
    client_action: str | None
    credential: dict[str, str] | None

    @property
    def settled(self) -> bool:
        return self.status != STATUS_PENDING or self.client_action in ("decline", "cancel", "error")


def _outcome(payload: dict[str, Any], summary: str, status: str) -> CredentialFormOutcome:
    return CredentialFormOutcome(result=json.dumps(payload), summary=summary, status=status)


def _error(message: str) -> CredentialFormOutcome:
    return _outcome({"status": "error", "error": message}, f"Error: {message}", "error")


def _text(value: object, limit: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:limit] or None


class CredentialFormTool:
    """`request_credential_form` for one MCP chat turn.

    `waiting_urls` collects the links the user still has to open, so the MCP reply carries
    them even when the model leaves them out.
    """

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        public_base_url: str,
        client: MCPClientChannel | None,
        session_factory: Callable[[], Any] = async_session_maker,
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.public_base_url = public_base_url
        self.client = client
        self._session_factory = session_factory
        self.waiting_urls: list[str] = []

    async def call(
        self, args: dict[str, Any], *, cancel_event: Event | None = None
    ) -> CredentialFormOutcome:
        """Open a form, then wait for it when the client can show it."""
        try:
            spec = await self._spec(args)
        except ValueError as exc:
            return _error(str(exc))
        request_id = await self._open(spec)
        url = credential_setup_url(self.public_base_url, request_id)
        if self.client is None or not self.client.supports_url_elicitation:
            return self._waiting(url)
        try:
            await self.client.send(url_elicitation_request(request_id, url, spec.message))
        except Exception:  # noqa: BLE001 - a client that went away still gets the link
            return self._waiting(url)
        state = await self._wait(request_id, cancel_event)
        if state is None or state.client_action in ("cancel", "error"):
            return self._waiting(url)
        if state.status == STATUS_COMPLETED and state.credential is not None:
            await self._notify_complete(request_id)
            return self._saved(spec, state.credential)
        if state.status == STATUS_DECLINED:
            return _outcome(
                {
                    "status": "declined",
                    "note": (
                        "The user declined the form. Continue without this credential and tell "
                        "them they can add it later."
                    ),
                },
                "Credential form declined",
                "success",
            )
        return self._waiting(url)

    async def conversation_forms_prompt(self) -> str:
        """What became of the forms this conversation opened, as the next turn starts.

        Earlier tool results are not replayed into later turns, so without this the model
        forgets it opened a form and cannot tell a credential the form created from an old one.
        """
        if self.conversation_id is None:
            return ""
        async with self._session_factory() as db:
            result = await db.execute(
                select(
                    CredentialSetupRequest.id,
                    CredentialSetupRequest.action,
                    CredentialSetupRequest.credential_type,
                    CredentialSetupRequest.suggested_name,
                    CredentialSetupRequest.status,
                    CredentialSetupRequest.expires_at,
                    Credential.id,
                    Credential.name,
                    Credential.type,
                )
                .outerjoin(Credential, Credential.id == CredentialSetupRequest.credential_id)
                .where(CredentialSetupRequest.conversation_id == self.conversation_id)
                .order_by(CredentialSetupRequest.created_at.desc())
                .limit(_MAX_FORMS_IN_PROMPT)
            )
            rows = result.all()
        if not rows:
            return ""
        lines = [
            "## Credential forms in this conversation",
            "",
            "The credential forms you opened in this conversation, as of the start of this "
            "turn, newest first. This is the source of truth for them: the id in a form link is "
            "the form's id, never a credential id.",
            "",
        ]
        for row in rows:
            request_id, action, credential_type, suggested_name, status, expires_at = row[:6]
            credential_id, credential_name, saved_type = row[6:]
            form = (
                f'the {credential_type} form for "{suggested_name}"'
                if suggested_name
                else (f"the {credential_type} form")
            )
            current = _effective_status(status, expires_at)
            if current == STATUS_COMPLETED and credential_id is not None:
                verb = "Updated" if action == "update" else "Created"
                lines.append(
                    f'- {verb}: "{credential_name}" ({saved_type.value}), credential id '
                    f"`{credential_id}`. The user saved it on the form and it is in the "
                    "credential list. Use it without asking again."
                )
            elif current == STATUS_PENDING:
                url = credential_setup_url(self.public_base_url, request_id)
                lines.append(f"- Still open: {form}, {url}. The user has not saved it yet.")
            elif current == STATUS_DECLINED:
                lines.append(f"- Declined: {form}. Continue without it unless the user asks again.")
            elif current == STATUS_EXPIRED:
                lines.append(
                    f"- Expired: {form}. Open a new form if the user still wants the credential."
                )
        return "\n\n" + "\n".join(lines) + "\n"

    async def _spec(self, args: dict[str, Any]) -> _FormSpec:
        action = str(args.get("action") or "").strip()
        reason = _text(args.get("reason"), _MAX_REASON_LENGTH)
        if action == "create":
            raw_type = str(args.get("credential_type") or "").strip()
            try:
                credential_type = CredentialType(raw_type).value
            except ValueError as exc:
                raise ValueError(f"Unknown credential type: {raw_type or '(empty)'}") from exc
            return _FormSpec(
                action, credential_type, _text(args.get("name"), _MAX_NAME_LENGTH), None, reason
            )
        if action == "update":
            try:
                credential_id = uuid.UUID(str(args.get("credential_id") or ""))
            except ValueError as exc:
                raise ValueError("Pass the id of the credential to update.") from exc
            async with self._session_factory() as db:
                result = await db.execute(
                    select(Credential.name, Credential.type, Credential.owner_id).where(
                        Credential.id == credential_id
                    )
                )
                row = result.first()
            if row is None or row.owner_id != self.user_id:
                raise ValueError("Only a credential the user owns can be updated.")
            return _FormSpec(action, row.type.value, row.name, credential_id, reason)
        raise ValueError("`action` must be create or update.")

    async def _open(self, spec: _FormSpec) -> uuid.UUID:
        request_id = uuid.uuid4()
        async with self._session_factory() as db:
            db.add(
                CredentialSetupRequest(
                    id=request_id,
                    user_id=self.user_id,
                    conversation_id=self.conversation_id,
                    action=spec.action,
                    credential_type=spec.credential_type,
                    suggested_name=spec.name,
                    credential_id=spec.credential_id,
                    reason=spec.reason,
                    status=STATUS_PENDING,
                    expires_at=datetime.now(timezone.utc) + SETUP_REQUEST_TTL,
                )
            )
            await db.commit()
        return request_id

    async def _state(self, request_id: uuid.UUID) -> _FormState:
        async with self._session_factory() as db:
            result = await db.execute(
                select(
                    CredentialSetupRequest.status,
                    CredentialSetupRequest.client_action,
                    Credential.id,
                    Credential.name,
                    Credential.type,
                )
                .outerjoin(Credential, Credential.id == CredentialSetupRequest.credential_id)
                .where(CredentialSetupRequest.id == request_id)
            )
            row = result.first()
        if row is None:
            return _FormState(STATUS_DECLINED, None, None)
        status, client_action, credential_id, name, credential_type = row
        credential = (
            {"id": str(credential_id), "name": name, "type": credential_type.value}
            if credential_id is not None
            else None
        )
        return _FormState(status, client_action, credential)

    async def _wait(self, request_id: uuid.UUID, cancel_event: Event | None) -> _FormState | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FORM_WAIT_SECONDS
        while loop.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return None
            state = await self._state(request_id)
            if state.settled:
                return state
            await asyncio.sleep(FORM_POLL_SECONDS)
        return None

    async def _notify_complete(self, request_id: uuid.UUID) -> None:
        if self.client is None:
            return
        try:
            await self.client.send(elicitation_complete_notification(request_id))
        except Exception:  # noqa: BLE001 - the notification is optional
            return

    def _saved(self, spec: _FormSpec, credential: dict[str, str]) -> CredentialFormOutcome:
        verb = "updated" if spec.action == "update" else "created"
        return _outcome(
            {
                "status": verb,
                "credential": credential,
                "note": (
                    "Use this credential now without asking again: put its id in the node's "
                    "credential field, or pass its name in credential_choices."
                ),
            },
            f'{verb.capitalize()} credential "{credential["name"]}"',
            "success",
        )

    def _waiting(self, url: str) -> CredentialFormOutcome:
        self.waiting_urls.append(url)
        return _outcome(
            {
                "status": "waiting_for_user",
                "url": url,
                "note": (
                    "The user has not saved the form yet. Give them this url as a markdown "
                    "link, ask them to open it in a browser where they are signed in to Heym, "
                    "save the credential there and then reply. Stop now, and build nothing "
                    "that needs this credential until they reply."
                ),
            },
            "Waiting for the credential form",
            "pending",
        )
