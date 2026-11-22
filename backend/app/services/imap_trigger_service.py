import asyncio
import imaplib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Credential, CredentialType, TriggerPollState, Workflow
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)

logger = logging.getLogger("imap_trigger")

# Seconds a socket operation may block. Without it one silent mailbox stalls the poller.
IMAP_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ImapCursor:
    uidvalidity: str | None = None
    last_uid: int = 0


@dataclass(frozen=True)
class _CursorClaim:
    """Outcome of asking to poll a node. ``due`` with no ``cursor`` means record a baseline."""

    due: bool
    cursor: ImapCursor | None = None


_NOT_DUE = _CursorClaim(due=False)


# Kept under its old name for existing imports; the retry loop below catches it.
ImapDispatchNotStartedError = TriggerDispatchNotStartedError


def _decode_header_value(value: str | None) -> str:
    """Decode MIME-encoded header values into readable Unicode strings."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _serialise_addresses(raw_value: str | None) -> list[dict[str, str]]:
    """Convert RFC822 address strings into a structured list."""
    if not raw_value:
        return []

    addresses: list[dict[str, str]] = []
    for name, email_address in getaddresses([raw_value]):
        addresses.append(
            {
                "name": _decode_header_value(name),
                "email": email_address,
            }
        )
    return addresses


def _walk_body_parts(message: Message) -> Iterator[Message]:
    """Like ``Message.walk()``, but without the inside of an email attached as a file.

    An attached email with a filename (``Invoice.eml``) is an attachment, so its text is not
    this email's body. One without a filename (inline forwards, delivery-status bounces) is
    still read, as before.
    """
    yield message
    if not message.is_multipart():
        return
    if message.get_content_type() == "message/rfc822" and message.get_filename():
        return
    for part in message.get_payload():
        yield from _walk_body_parts(part)


def _extract_email_bodies(message: Message) -> tuple[str, str]:
    """Return plain-text and HTML bodies from a parsed email message."""
    text_parts: list[str] = []
    html_parts: list[str] = []

    for part in _walk_body_parts(message):
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue

        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")

        content_type = part.get_content_type()
        if content_type == "text/plain":
            text_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)

    if not message.is_multipart():
        payload = message.get_payload(decode=True) or b""
        charset = message.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")
        if message.get_content_type() == "text/html" and not html_parts:
            html_parts.append(content)
        elif message.get_content_type() == "text/plain" and not text_parts:
            text_parts.append(content)

    return "\n\n".join(text_parts).strip(), "\n\n".join(html_parts).strip()


@dataclass(frozen=True)
class EmailAttachment:
    """One attachment of a parsed email, with its decoded bytes."""

    filename: str
    content_type: str
    content: bytes


def _attached_email_bytes(part: Message) -> bytes:
    """The bytes of an attached email; it has no transfer-decoded payload of its own.

    Re-serialising can fail on a malformed header (an encoded name with CR/LF); that one
    attachment is then empty instead of failing the whole batch on every poll.
    """
    try:
        return part.get_payload(0).as_bytes()
    except Exception:  # noqa: BLE001 - email's generator raises several types on bad headers
        logger.warning("Could not serialise an attached email", exc_info=True)
        return b""


def _attachment_parts(message: Message) -> list[EmailAttachment]:
    """Every part with a filename, in the order it appears in the email."""
    attachments: list[EmailAttachment] = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        if part.get_content_type() == "message/rfc822":
            content = _attached_email_bytes(part)
        else:
            content = part.get_payload(decode=True) or b""
        attachments.append(
            EmailAttachment(
                filename=_decode_header_value(filename),
                content_type=part.get_content_type(),
                content=content,
            )
        )
    return attachments


def email_attachments(raw_bytes: bytes) -> tuple[str, list[EmailAttachment]]:
    """The Message-ID and the attachments of raw RFC822 bytes."""
    message = message_from_bytes(raw_bytes, policy=policy.default)
    return _decode_header_value(message.get("Message-ID")), _attachment_parts(message)


def _extract_attachment_summaries(message: Message) -> list[dict[str, Any]]:
    """Return lightweight attachment metadata without loading file contents into workflow inputs."""
    return [
        {
            "filename": item.filename,
            "content_type": item.content_type,
            "size_bytes": len(item.content),
        }
        for item in _attachment_parts(message)
    ]


def _extract_raw_message_bytes(fetch_data: list[Any]) -> bytes | None:
    """Pull RFC822 bytes out of imaplib fetch responses."""
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _parse_email_message(
    raw_bytes: bytes, uid: int, uidvalidity: str | None = None
) -> dict[str, Any]:
    """Convert raw RFC822 bytes into the workflow-friendly email payload.

    ``uid`` and ``uidvalidity`` together name the message in its mailbox, so the trigger
    node can fetch it again by UID to save its attachments.
    """
    return {"uid": str(uid), "uidvalidity": uidvalidity, **email_payload(raw_bytes)}


def email_payload(raw_bytes: bytes) -> dict[str, Any]:
    """The email fields every mail trigger hands its run, from raw RFC822 bytes."""
    message = message_from_bytes(raw_bytes, policy=policy.default)
    text_body, html_body = _extract_email_bodies(message)

    parsed_date = message.get("Date")
    parsed_date_iso: str | None = None
    if parsed_date:
        try:
            parsed_date_iso = (
                parsedate_to_datetime(parsed_date).astimezone(timezone.utc).isoformat()
            )
        except Exception:
            parsed_date_iso = None

    headers: dict[str, str] = {}
    for key, value in message.items():
        headers[key] = _decode_header_value(value)

    return {
        "subject": _decode_header_value(message.get("Subject")),
        "from": _decode_header_value(message.get("From")),
        "fromAddresses": _serialise_addresses(message.get("From")),
        "to": _decode_header_value(message.get("To")),
        "toAddresses": _serialise_addresses(message.get("To")),
        "cc": _decode_header_value(message.get("Cc")),
        "ccAddresses": _serialise_addresses(message.get("Cc")),
        "replyTo": _decode_header_value(message.get("Reply-To")),
        "replyToAddresses": _serialise_addresses(message.get("Reply-To")),
        "date": parsed_date_iso or _decode_header_value(parsed_date),
        "messageId": _decode_header_value(message.get("Message-ID")),
        "text": text_body,
        "html": html_body,
        "attachments": _extract_attachment_summaries(message),
        "headers": headers,
    }


@contextmanager
def _open_mailbox(credential_config: dict[str, Any]) -> Iterator[tuple[Any, str | None]]:
    """Log in and select the credential's mailbox read-only, so nothing is marked as read.

    Yields the client and the mailbox UIDVALIDITY, and always closes the connection.
    """
    host = str(credential_config.get("imap_host", "")).strip()
    port = int(credential_config.get("imap_port", 993))
    username = str(credential_config.get("imap_username", "")).strip()
    password = str(credential_config.get("imap_password", "")).strip()
    mailbox = str(credential_config.get("imap_mailbox", "INBOX")).strip() or "INBOX"
    use_ssl = bool(credential_config.get("imap_use_ssl", True))

    client: imaplib.IMAP4 | imaplib.IMAP4_SSL
    if use_ssl:
        client = imaplib.IMAP4_SSL(host, port, timeout=IMAP_TIMEOUT_SECONDS)
    else:
        client = imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT_SECONDS)

    try:
        login_status, _ = client.login(username, password)
        if login_status != "OK":
            raise ValueError("IMAP login failed")

        select_status, _ = client.select(mailbox, readonly=True)
        if select_status != "OK":
            raise ValueError(f"Unable to open mailbox '{mailbox}'")

        _resp_type, uidvalidity_data = client.response("UIDVALIDITY")
        uidvalidity = None
        if uidvalidity_data and uidvalidity_data[0]:
            uidvalidity = uidvalidity_data[0].decode("utf-8", errors="replace")

        yield client, uidvalidity
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass


def fetch_imap_messages(
    credential_config: dict[str, Any],
    cursor: ImapCursor | None = None,
) -> tuple[ImapCursor, list[dict[str, Any]]]:
    """Fetch newly arrived emails using IMAP UIDs, baselining existing inbox contents on first poll."""
    mailbox = str(credential_config.get("imap_mailbox", "INBOX")).strip() or "INBOX"
    with _open_mailbox(credential_config) as (client, uidvalidity):
        search_status, search_data = client.uid("search", None, "ALL")
        if search_status != "OK":
            raise ValueError("IMAP UID search failed")

        raw_uid_list = search_data[0].split() if search_data and search_data[0] else []
        uid_list = sorted(int(item) for item in raw_uid_list)
        latest_uid = uid_list[-1] if uid_list else 0

        if (
            cursor is not None
            and cursor.uidvalidity
            and uidvalidity
            and cursor.uidvalidity != uidvalidity
        ):
            logger.info("IMAP UIDVALIDITY changed for mailbox %s, resetting cursor", mailbox)
            return ImapCursor(uidvalidity=uidvalidity, last_uid=latest_uid), []

        if cursor is None:
            return ImapCursor(uidvalidity=uidvalidity, last_uid=latest_uid), []

        next_last_uid = max(cursor.last_uid, latest_uid)
        next_cursor = ImapCursor(uidvalidity=uidvalidity, last_uid=next_last_uid)

        new_uids = [uid for uid in uid_list if uid > cursor.last_uid]
        emails: list[dict[str, Any]] = []
        for uid in new_uids:
            fetch_status, fetch_data = client.uid("fetch", str(uid), "(RFC822)")
            if fetch_status != "OK" or not isinstance(fetch_data, list):
                # Known limitation: a per-UID fetch failure is skipped rather than
                # retried, so it can still permanently lose that one email.
                logger.warning("Failed to fetch IMAP message uid=%s", uid)
                continue
            raw_bytes = _extract_raw_message_bytes(fetch_data)
            if raw_bytes is None:
                logger.warning("Missing RFC822 payload for IMAP uid=%s", uid)
                continue
            emails.append(_parse_email_message(raw_bytes, uid, uidvalidity))

        return next_cursor, emails


def fetch_imap_message_by_uid(
    credential_config: dict[str, Any], uid: str, uidvalidity: str
) -> bytes | None:
    """The raw RFC822 bytes of one message, or None when it is no longer that message.

    Uses the same login and read-only select as :func:`fetch_imap_messages`. A mailbox whose
    UIDVALIDITY changed since the poll gives None, because the UID may now name another
    message; so does a message that was deleted or moved. ``BODY.PEEK[]`` leaves the message
    unread. Login and network failures raise.
    """
    with _open_mailbox(credential_config) as (client, current_uidvalidity):
        if not uidvalidity or current_uidvalidity != uidvalidity:
            return None
        fetch_status, fetch_data = client.uid("fetch", str(uid), "(BODY.PEEK[])")
        if fetch_status != "OK" or not isinstance(fetch_data, list):
            return None
        return _extract_raw_message_bytes(fetch_data)


# trigger_poll_states row type for an IMAP Trigger's cursor (the Google triggers keep
# their own types there and only ever touch those).
_CURSOR_NODE_TYPE = "imapTrigger"


class ImapTriggerManager:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        # Each node's poll and runs, so a slow workflow holds up only its own trigger.
        self._node_polls: dict[str, asyncio.Task] = {}
        # Each poll holds an IMAP connection and its runs a database connection, so a
        # restart must not open every mailbox and start every run at once.
        self._parallel_polls = asyncio.Semaphore(max(1, settings.imap_max_parallel_polls))
        self._poll_loop_seconds = 15
        self._max_pre_dispatch_attempts = 3

    def _get_node_key(self, workflow_id: uuid.UUID, node_id: str) -> str:
        return f"{workflow_id}_{node_id}"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("IMAP trigger manager started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        node_polls = list(self._node_polls.values())
        for poll in node_polls:
            poll.cancel()
        await asyncio.gather(*node_polls, return_exceptions=True)
        logger.info("IMAP trigger manager stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self._poll_workflows()
            except Exception as exc:
                logger.exception("Error in IMAP trigger loop: %s", exc)
            await asyncio.sleep(self._poll_loop_seconds)

    async def _poll_workflows(self) -> None:
        current_keys: set[str] = set()

        async with async_session_maker() as db:
            workflows = await self._get_workflows_with_imap_trigger(db)

        for workflow in workflows:
            for node in self._find_imap_trigger_nodes(workflow.nodes):
                node_id = str(node.get("id", "")).strip()
                if not node_id:
                    continue

                key = self._get_node_key(workflow.id, node_id)
                current_keys.add(key)

                # The node's claim in trigger_poll_states decides whether it is due.
                if key not in self._node_polls:
                    self._start_node_poll(key, workflow, node)

        await self._forget_inactive_cursors(current_keys)

    def _start_node_poll(self, key: str, workflow: Workflow, node: dict[str, Any]) -> None:
        """Poll one node and run its new emails in order, without holding up the pass."""
        task = asyncio.create_task(self._poll_node_logged(workflow, node))
        self._node_polls[key] = task

        def _forget(done: asyncio.Task) -> None:
            if self._node_polls.get(key) is done:
                del self._node_polls[key]

        task.add_done_callback(_forget)

    async def _poll_node_logged(self, workflow: Workflow, node: dict[str, Any]) -> None:
        try:
            await self._poll_workflow_node(workflow, node)
        except Exception:
            # One unreachable mailbox must not keep the other triggers from polling.
            logger.exception(
                "IMAP trigger poll failed for workflow %s node %s", workflow.id, node.get("id")
            )

    async def wait_for_polls(self) -> None:
        """Wait until every node's started poll and its runs have ended."""
        while self._node_polls:
            await asyncio.gather(*list(self._node_polls.values()), return_exceptions=True)
            # Awaiting finished tasks does not yield, so their done callbacks have not run yet.
            for key, poll in list(self._node_polls.items()):
                if poll.done():
                    del self._node_polls[key]

    async def _forget_inactive_cursors(self, active_keys: set[str]) -> None:
        """Drop stored cursors of IMAP Triggers that were removed or deactivated.

        A trigger turned back on starts from the mailbox as it is then, as it always
        has, instead of running every email that arrived while it was off.
        """
        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(
                        TriggerPollState.id, TriggerPollState.workflow_id, TriggerPollState.node_id
                    ).where(TriggerPollState.node_type == _CURSOR_NODE_TYPE)
                )
            ).all()
            inactive = [
                row.id
                for row in rows
                if self._get_node_key(row.workflow_id, row.node_id) not in active_keys
            ]
            if inactive:
                await db.execute(delete(TriggerPollState).where(TriggerPollState.id.in_(inactive)))
                await db.commit()

    def _get_poll_interval_minutes(self, node: dict[str, Any]) -> int:
        raw_value = node.get("data", {}).get("pollIntervalMinutes", 5)
        try:
            interval = int(raw_value)
        except (TypeError, ValueError):
            return 5
        return max(1, interval)

    async def _get_workflows_with_imap_trigger(self, db: AsyncSession) -> list[Workflow]:
        result = await db.execute(select(Workflow))
        all_workflows = result.scalars().all()
        return [
            workflow for workflow in all_workflows if self._has_imap_trigger_node(workflow.nodes)
        ]

    def _has_imap_trigger_node(self, nodes: list[dict[str, Any]]) -> bool:
        return any(
            node.get("type") == "imapTrigger"
            and node.get("data", {}).get("active", True) is not False
            for node in nodes
        )

    def _find_imap_trigger_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            node
            for node in nodes
            if node.get("type") == "imapTrigger"
            and node.get("data", {}).get("active", True) is not False
        ]

    async def _poll_workflow_node(self, workflow: Workflow, node: dict[str, Any]) -> None:
        """Claim the node for its interval, then fetch and run its new emails in order.

        Leader election keeps the other processes from polling, but during a handoff two
        can briefly both lead, and the old leader's runs may still be going. Correctness
        rests on Postgres instead, as for the Google triggers: one process claims the node
        per interval, and each email is taken by moving the stored cursor onto its UID
        before its run starts, so a restart or a second poller never starts it again.
        """
        node_id = str(node.get("id", "")).strip()
        credential_id = str(node.get("data", {}).get("credentialId", "")).strip()
        if not node_id or not credential_id:
            return

        poll_minutes = self._get_poll_interval_minutes(node)
        claim = await self._claim_cursor(workflow.id, node_id, poll_minutes)
        if not claim.due:
            return

        async with self._parallel_polls:
            credential_config = await self._load_credential_config(credential_id)
            if credential_config is None:
                logger.warning(
                    "Skipping IMAP trigger for workflow %s node %s because credential is "
                    "unavailable",
                    workflow.id,
                    node_id,
                )
                return

            next_cursor, emails = await self._fetch_node_messages(credential_config, claim.cursor)
            if claim.cursor is None:
                await self._insert_baseline(workflow.id, node_id, next_cursor, poll_minutes)
                return

            cursor = claim.cursor
            if emails:
                logger.info(
                    "IMAP trigger found %d new email(s) for workflow %s node %s",
                    len(emails),
                    workflow.id,
                    node_id,
                )
            for email_payload in emails:
                if not lock_service.is_leader:
                    logger.info(
                        "IMAP trigger for workflow %s node %s: no longer the leader, "
                        "leaving the rest of the batch to the next poll",
                        workflow.id,
                        node_id,
                    )
                    return
                taken = ImapCursor(next_cursor.uidvalidity, int(email_payload["uid"]))
                if not await self._advance_cursor(workflow.id, node_id, cursor, taken):
                    logger.info(
                        "IMAP trigger for workflow %s node %s: another process moved on, "
                        "stopping this poll",
                        workflow.id,
                        node_id,
                    )
                    return
                cursor = taken
                await self._process_email_with_retries(workflow, node_id, email_payload)

            # Also carries the UIDVALIDITY reset, and UIDs whose fetch failed.
            await self._advance_cursor(workflow.id, node_id, cursor, next_cursor)

    async def _claim_cursor(
        self, workflow_id: uuid.UUID, node_id: str, poll_minutes: int
    ) -> _CursorClaim:
        """Claim the node for one poll interval and read its stored cursor.

        ``next_poll_at`` moves forward only once it has passed, so one process polls the node
        per interval. A node never polled has no row and is always due.
        """
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    update(TriggerPollState)
                    .where(
                        TriggerPollState.workflow_id == workflow_id,
                        TriggerPollState.node_id == node_id,
                        TriggerPollState.node_type == _CURSOR_NODE_TYPE,
                        TriggerPollState.next_poll_at <= func.now(),
                    )
                    .values(next_poll_at=func.now() + timedelta(minutes=poll_minutes))
                    .returning(TriggerPollState.scope_fingerprint, TriggerPollState.version)
                    .execution_options(synchronize_session=False)
                )
            ).first()
            if row is None:
                exists = (
                    await db.execute(
                        select(TriggerPollState.id).where(
                            TriggerPollState.workflow_id == workflow_id,
                            TriggerPollState.node_id == node_id,
                        )
                    )
                ).first()
                await db.commit()
                return _NOT_DUE if exists else _CursorClaim(due=True)
            await db.commit()
        return _CursorClaim(
            due=True,
            cursor=ImapCursor(uidvalidity=row.scope_fingerprint or None, last_uid=int(row.version)),
        )

    async def _insert_baseline(
        self, workflow_id: uuid.UUID, node_id: str, cursor: ImapCursor, poll_minutes: int
    ) -> None:
        """Record the first cursor: UIDVALIDITY as the scope, the last UID as the version.

        A process that loses the race to record it leaves the other one's cursor alone.
        """
        async with async_session_maker() as db:
            await db.execute(
                pg_insert(TriggerPollState)
                .values(
                    id=uuid.uuid4(),
                    workflow_id=workflow_id,
                    node_id=node_id,
                    node_type=_CURSOR_NODE_TYPE,
                    key_id="imap",
                    scope_fingerprint=(cursor.uidvalidity or "")[:64],
                    version=cursor.last_uid,
                    next_poll_at=func.now() + timedelta(minutes=poll_minutes),
                )
                .on_conflict_do_nothing(constraint="uq_trigger_poll_state_node")
            )
            await db.commit()

    async def _advance_cursor(
        self,
        workflow_id: uuid.UUID,
        node_id: str,
        expected: ImapCursor,
        cursor: ImapCursor,
    ) -> bool:
        """Store ``cursor`` only while the stored one is still ``expected``.

        False when another process has moved it, or the trigger was removed meanwhile.
        """
        async with async_session_maker() as db:
            moved = (
                await db.execute(
                    update(TriggerPollState)
                    .where(
                        TriggerPollState.workflow_id == workflow_id,
                        TriggerPollState.node_id == node_id,
                        TriggerPollState.node_type == _CURSOR_NODE_TYPE,
                        TriggerPollState.scope_fingerprint == (expected.uidvalidity or "")[:64],
                        TriggerPollState.version == expected.last_uid,
                    )
                    .values(
                        scope_fingerprint=(cursor.uidvalidity or "")[:64],
                        version=cursor.last_uid,
                        updated_at=func.now(),
                    )
                    .returning(TriggerPollState.id)
                    .execution_options(synchronize_session=False)
                )
            ).first()
            await db.commit()
        return moved is not None

    async def _process_email_with_retries(
        self, workflow: Workflow, node_id: str, email_payload: dict[str, Any]
    ) -> None:
        """Run one email through the workflow, retrying only failures that happen
        before dispatch_workflow starts. Once a run has started it is never
        retried, since retrying would repeat whatever side effects it already had."""
        uid = email_payload.get("uid")
        for attempt in range(1, self._max_pre_dispatch_attempts + 1):
            try:
                await self._execute_workflow_for_email(workflow, node_id, email_payload)
                return
            except ImapDispatchNotStartedError as exc:
                if attempt >= self._max_pre_dispatch_attempts:
                    logger.error(
                        "IMAP trigger giving up on uid=%s for workflow %s node %s "
                        "after %d attempts: %s",
                        uid,
                        workflow.id,
                        node_id,
                        attempt,
                        exc,
                    )
                    return
                logger.warning(
                    "Retrying IMAP uid=%s for workflow %s node %s (attempt %d/%d): %s",
                    uid,
                    workflow.id,
                    node_id,
                    attempt,
                    self._max_pre_dispatch_attempts,
                    exc,
                )
            except Exception:
                logger.exception(
                    "IMAP trigger workflow execution failed after dispatch started for "
                    "uid=%s (workflow %s node %s); not retrying",
                    uid,
                    workflow.id,
                    node_id,
                )
                return

    async def _load_credential_config(self, credential_id: str) -> dict[str, Any] | None:
        try:
            credential_uuid = uuid.UUID(credential_id)
        except ValueError:
            return None

        async with async_session_maker() as db:
            result = await db.execute(
                select(Credential).where(
                    Credential.id == credential_uuid,
                    Credential.type == CredentialType.imap,
                )
            )
            credential = result.scalar_one_or_none()

        if credential is None:
            return None
        return decrypt_config(credential.encrypted_config)

    async def _fetch_node_messages(
        self,
        credential_config: dict[str, Any],
        cursor: ImapCursor | None,
    ) -> tuple[ImapCursor, list[dict[str, Any]]]:
        return await asyncio.to_thread(fetch_imap_messages, credential_config, cursor)

    async def _execute_workflow_for_email(
        self,
        workflow: Workflow,
        node_id: str,
        email_payload: dict[str, Any],
    ) -> None:
        inputs = {
            "triggered_by": "imap",
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "email": email_payload,
        }

        await run_trigger_workflow(
            workflow_id=workflow.id,
            inputs=inputs,
            trigger_source="imap",
            trigger_label="IMAP trigger",
            log=logger,
        )


imap_trigger_manager = ImapTriggerManager()
