import asyncio
import imaplib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import Credential, CredentialType, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger("imap_trigger")


@dataclass(frozen=True)
class ImapCursor:
    uidvalidity: str | None = None
    last_uid: int = 0


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


def _extract_email_bodies(message: Message) -> tuple[str, str]:
    """Return plain-text and HTML bodies from a parsed email message."""
    text_parts: list[str] = []
    html_parts: list[str] = []

    for part in message.walk():
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


def _extract_attachment_summaries(message: Message) -> list[dict[str, Any]]:
    """Return lightweight attachment metadata without loading file contents into workflow inputs."""
    attachments: list[dict[str, Any]] = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            {
                "filename": _decode_header_value(filename),
                "content_type": part.get_content_type(),
                "size_bytes": len(payload),
            }
        )
    return attachments


def _extract_raw_message_bytes(fetch_data: list[Any]) -> bytes | None:
    """Pull RFC822 bytes out of imaplib fetch responses."""
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _parse_email_message(raw_bytes: bytes, uid: int) -> dict[str, Any]:
    """Convert raw RFC822 bytes into the workflow-friendly email payload."""
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
        "uid": str(uid),
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


def fetch_imap_messages(
    credential_config: dict[str, Any],
    cursor: ImapCursor,
) -> tuple[ImapCursor, list[dict[str, Any]]]:
    """Fetch newly arrived emails using IMAP UIDs, baselining existing inbox contents on first poll."""
    host = str(credential_config.get("imap_host", "")).strip()
    port = int(credential_config.get("imap_port", 993))
    username = str(credential_config.get("imap_username", "")).strip()
    password = str(credential_config.get("imap_password", "")).strip()
    mailbox = str(credential_config.get("imap_mailbox", "INBOX")).strip() or "INBOX"
    use_ssl = bool(credential_config.get("imap_use_ssl", True))

    client: imaplib.IMAP4 | imaplib.IMAP4_SSL
    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)

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

        search_status, search_data = client.uid("search", None, "ALL")
        if search_status != "OK":
            raise ValueError("IMAP UID search failed")

        raw_uid_list = search_data[0].split() if search_data and search_data[0] else []
        uid_list = [int(item) for item in raw_uid_list]
        latest_uid = uid_list[-1] if uid_list else 0
        next_cursor = ImapCursor(uidvalidity=uidvalidity, last_uid=latest_uid)

        if cursor.uidvalidity and uidvalidity and cursor.uidvalidity != uidvalidity:
            logger.info("IMAP UIDVALIDITY changed for mailbox %s, resetting cursor", mailbox)
            return next_cursor, []

        if cursor.last_uid == 0:
            return next_cursor, []

        new_uids = [uid for uid in uid_list if uid > cursor.last_uid]
        emails: list[dict[str, Any]] = []
        for uid in new_uids:
            fetch_status, fetch_data = client.uid("fetch", str(uid), "(RFC822)")
            if fetch_status != "OK" or not isinstance(fetch_data, list):
                logger.warning("Failed to fetch IMAP message uid=%s", uid)
                continue
            raw_bytes = _extract_raw_message_bytes(fetch_data)
            if raw_bytes is None:
                logger.warning("Missing RFC822 payload for IMAP uid=%s", uid)
                continue
            emails.append(_parse_email_message(raw_bytes, uid))

        return next_cursor, emails
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass


class ImapTriggerManager:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_poll_at: dict[str, datetime] = {}
        self._cursors: dict[str, ImapCursor] = {}
        self._poll_loop_seconds = 15

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
        self._last_poll_at.clear()
        self._cursors.clear()
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
        now = datetime.now(timezone.utc)
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

                if not self._should_poll_node(key, now, node):
                    continue

                self._last_poll_at[key] = now
                await self._poll_workflow_node(workflow, node)

        stale_keys = set(self._last_poll_at.keys()) - current_keys
        for key in stale_keys:
            self._last_poll_at.pop(key, None)
            self._cursors.pop(key, None)

    def _should_poll_node(self, key: str, now: datetime, node: dict[str, Any]) -> bool:
        last_polled_at = self._last_poll_at.get(key)
        if last_polled_at is None:
            return True

        interval_minutes = self._get_poll_interval_minutes(node)
        return now - last_polled_at >= timedelta(minutes=interval_minutes)

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
        node_id = str(node.get("id", "")).strip()
        credential_id = str(node.get("data", {}).get("credentialId", "")).strip()
        if not node_id or not credential_id:
            return

        credential_config = await self._load_credential_config(credential_id)
        if credential_config is None:
            logger.warning(
                "Skipping IMAP trigger for workflow %s node %s because credential is unavailable",
                workflow.id,
                node_id,
            )
            return

        key = self._get_node_key(workflow.id, node_id)
        current_cursor = self._cursors.get(key, ImapCursor())
        next_cursor, emails = await self._fetch_node_messages(credential_config, current_cursor)
        self._cursors[key] = next_cursor

        if not emails:
            return

        logger.info(
            "IMAP trigger found %d new email(s) for workflow %s node %s",
            len(emails),
            workflow.id,
            node_id,
        )
        for email_payload in emails:
            await self._execute_workflow_for_email(workflow, node_id, email_payload)

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
        cursor: ImapCursor,
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

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                logger.warning("Workflow %s disappeared before IMAP execution", workflow.id)
                return

            workflow_cache = await collect_referenced_workflows(db, fresh_workflow.nodes)
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            result = execute_workflow(
                workflow_id=fresh_workflow.id,
                nodes=fresh_workflow.nodes,
                edges=fresh_workflow.edges,
                inputs=inputs,
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=fresh_workflow.owner_id,
            )

            history_entry = ExecutionHistory(
                workflow_id=fresh_workflow.id,
                inputs=inputs,
                outputs=result.outputs,
                node_results=result.node_results,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                trigger_source="imap",
            )
            db.add(history_entry)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=fresh_workflow.id,
                owner_id=fresh_workflow.owner_id,
                workflow_name_snapshot=fresh_workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )

            for sub_exec in result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=sub_exec.inputs,
                    outputs=sub_exec.outputs,
                    node_results=sub_exec.node_results,
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                )
                db.add(sub_history)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                )

            await _persist_global_variables_from_execution(
                db,
                fresh_workflow.owner_id,
                fresh_workflow.nodes,
                workflow_cache,
                result.node_results,
                result.sub_workflow_executions,
            )

            await db.commit()


imap_trigger_manager = ImapTriggerManager()
