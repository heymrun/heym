"""Polls Outlook Trigger nodes and starts one run per new email.

Runs on the leader worker, like the Gmail and IMAP Triggers. Its snapshot lives in
``trigger_poll_states`` / ``trigger_poll_items`` through the Google triggers' state store:
the poll is claimed per interval, and each email is consumed with a compare-and-swap on the
snapshot version before its run starts, so a restart or a second poller never starts it
again. If the run cannot start, the consume is reverted and the next poll tries again.
After the run has started, the node's after-run action is applied.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Text, cast, select

from app.db.models import CredentialType, Workflow
from app.db.session import SessionLocal, async_session_maker
from app.services.credential_access import get_accessible_credential
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.google_triggers.state_store import ClaimedPoll, TriggerStateStore
from app.services.outlook_service import OutlookApiError, OutlookService
from app.services.outlook_trigger.config import (
    OUTLOOK_TRIGGER,
    OutlookTriggerConfig,
    parse_outlook_config,
)
from app.services.outlook_trigger.reader import OutlookRead, apply_after_action, read_new_mail
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)

logger = logging.getLogger("outlook_trigger")

TICK_SECONDS = 15
PRE_DISPATCH_ATTEMPTS = 3
# Each poll holds Graph requests and its runs a database connection.
MAX_PARALLEL_POLLS = 4
TRIGGER_SOURCE = "outlook"
TRIGGER_LABEL = "Outlook Trigger"
KEY_ID = "outlook"


def _active_nodes(nodes: Any) -> list[dict[str, Any]]:
    return [
        node
        for node in nodes or []
        if isinstance(node, dict)
        and node.get("type") == OUTLOOK_TRIGGER
        and (node.get("data") or {}).get("active", True) is not False
    ]


def _read(
    credential_id: str,
    credential_config: dict[str, Any],
    config: OutlookTriggerConfig,
    poll: ClaimedPoll | None,
) -> OutlookRead:
    with SessionLocal() as db:
        service = OutlookService(credential_id, credential_config, db)
        if poll is None:
            return read_new_mail(service, config, None, None)
        return read_new_mail(service, config, poll.scope_fingerprint, poll.items)


def _act(
    credential_id: str, credential_config: dict[str, Any], message_id: str, action: str
) -> None:
    with SessionLocal() as db:
        apply_after_action(OutlookService(credential_id, credential_config, db), message_id, action)


class OutlookTriggerManager:
    """Leader loop for outlookTrigger nodes."""

    def __init__(self, store: TriggerStateStore | None = None) -> None:
        self._store = store or TriggerStateStore()
        self._running = False
        self._task: asyncio.Task | None = None
        # Each node's poll and runs, so a slow workflow holds up only its own trigger.
        self._node_polls: dict[str, asyncio.Task] = {}
        self._parallel_polls = asyncio.Semaphore(MAX_PARALLEL_POLLS)

    async def start(self) -> None:
        """Start the background loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Outlook trigger manager started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        """Stop the loop and every node poll in flight."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        polls = list(self._node_polls.values())
        for poll in polls:
            poll.cancel()
        await asyncio.gather(*polls, return_exceptions=True)
        logger.info("Outlook trigger manager stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self.poll_once()
            except Exception as exc:
                logger.exception("Error in Outlook trigger loop: %s", exc)
            await asyncio.sleep(TICK_SECONDS)

    async def poll_once(self) -> None:
        """Start a poll for every active node not already polling, then drop stale snapshots."""
        keep: set[tuple[uuid.UUID, str]] = set()
        for workflow in await self._load_workflows():
            for node in _active_nodes(workflow.nodes):
                node_id = str(node.get("id") or "").strip()
                if not node_id:
                    continue
                keep.add((workflow.id, node_id))
                key = f"{workflow.id}_{node_id}"
                if key not in self._node_polls:
                    self._start_node_poll(key, workflow, node)
        # A trigger turned back on starts from the mailbox as it is then.
        await self._store.delete_except((OUTLOOK_TRIGGER,), keep)

    def _start_node_poll(self, key: str, workflow: Any, node: dict[str, Any]) -> None:
        task = asyncio.create_task(self._poll_node_logged(workflow, node))
        self._node_polls[key] = task

        def _forget(done: asyncio.Task) -> None:
            if self._node_polls.get(key) is done:
                del self._node_polls[key]

        task.add_done_callback(_forget)

    async def _poll_node_logged(self, workflow: Any, node: dict[str, Any]) -> None:
        try:
            await self.poll_node(workflow, node)
        except OutlookApiError as exc:
            logger.warning(
                "Outlook Trigger poll for workflow %s node %s failed: %s",
                workflow.id,
                node.get("id"),
                exc,
            )
        except Exception:
            # One broken mailbox must not keep the other triggers from polling.
            logger.exception(
                "Outlook trigger poll failed for workflow %s node %s", workflow.id, node.get("id")
            )

    async def wait_for_polls(self) -> None:
        """Wait until every started node poll and its runs have ended."""
        while self._node_polls:
            await asyncio.gather(*list(self._node_polls.values()), return_exceptions=True)
            for key, poll in list(self._node_polls.items()):
                if poll.done():
                    del self._node_polls[key]

    async def poll_node(self, workflow: Any, node: dict[str, Any]) -> None:
        """Claim the node for its interval, read its new emails and run them in order."""
        node_id = str(node.get("id") or "").strip()
        config = parse_outlook_config(node.get("data") or {})
        problem = config.problem()
        if not node_id or problem:
            if problem:
                logger.debug(
                    "Outlook Trigger for workflow %s node %s: %s", workflow.id, node_id, problem
                )
            return

        claim = await self._store.claim(workflow.id, node_id, config.poll_minutes)
        if not claim.due:
            return

        async with self._parallel_polls:
            credential_config = await self._load_credential(config.credential_id, workflow.owner_id)
            if credential_config is None:
                logger.warning(
                    "Skipping Outlook Trigger for workflow %s node %s: credential unavailable",
                    workflow.id,
                    node_id,
                )
                return

            poll = claim.poll
            read = await asyncio.to_thread(
                _read, config.credential_id, credential_config, config, poll
            )
            if poll is None:
                await self._store.insert_baseline(
                    workflow_id=workflow.id,
                    node_id=node_id,
                    node_type=OUTLOOK_TRIGGER,
                    scope_fingerprint=read.scope,
                    key_id=KEY_ID,
                    items=read.items,
                    poll_minutes=config.poll_minutes,
                )
                return
            if read.baseline:
                await self._store.reset_baseline(
                    poll.state_id,
                    poll.version,
                    scope_fingerprint=read.scope,
                    key_id=KEY_ID,
                    items=read.items,
                )
                return
            if read.emails:
                logger.info(
                    "Outlook trigger found %d new email(s) for workflow %s node %s",
                    len(read.emails),
                    workflow.id,
                    node_id,
                )
            await self._run_emails(workflow, node_id, config, poll, read)

    async def _run_emails(
        self,
        workflow: Any,
        node_id: str,
        config: OutlookTriggerConfig,
        poll: ClaimedPoll,
        read: OutlookRead,
    ) -> None:
        version = poll.version
        for email in read.emails:
            if not lock_service.is_leader:
                logger.info(
                    "Outlook Trigger for workflow %s node %s: no longer the leader, "
                    "leaving the rest of the batch to the next poll",
                    workflow.id,
                    node_id,
                )
                return
            if not await self._store.consume(poll.state_id, version, [email.write]):
                logger.info(
                    "Outlook Trigger for workflow %s node %s: another process moved on, "
                    "stopping this poll",
                    workflow.id,
                    node_id,
                )
                return
            version += 1
            if await self._start_run(workflow, node_id, email.payload):
                await self._after_run(config, workflow.owner_id, email.payload)
                continue
            if await self._store.consume(poll.state_id, version, [email.revert]):
                logger.warning(
                    "Outlook Trigger for workflow %s node %s: run could not start, "
                    "retrying next poll",
                    workflow.id,
                    node_id,
                )
            return
        if read.silent:
            await self._store.consume(poll.state_id, version, read.silent)

    async def _start_run(self, workflow: Any, node_id: str, email: dict[str, Any]) -> bool:
        """Run one email. False only when every attempt failed before dispatch started."""
        inputs = {
            "triggered_by": TRIGGER_SOURCE,
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "email": email,
        }
        for attempt in range(1, PRE_DISPATCH_ATTEMPTS + 1):
            try:
                await run_trigger_workflow(
                    workflow_id=workflow.id,
                    inputs=inputs,
                    trigger_source=TRIGGER_SOURCE,
                    trigger_label=TRIGGER_LABEL,
                    log=logger,
                )
                return True
            except TriggerDispatchNotStartedError as exc:
                logger.warning(
                    "Outlook Trigger for workflow %s node %s: run not started (attempt %d/%d): %s",
                    workflow.id,
                    node_id,
                    attempt,
                    PRE_DISPATCH_ATTEMPTS,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Outlook Trigger for workflow %s node %s: run failed after it started; "
                    "not retrying",
                    workflow.id,
                    node_id,
                )
                return True
        return False

    async def _after_run(
        self, config: OutlookTriggerConfig, owner_id: uuid.UUID, email: dict[str, Any]
    ) -> None:
        """Apply the after-run action; a failure is logged and the next email still runs."""
        message_id = str(email.get("id") or "")
        if config.after_action == "none" or not message_id:
            return
        try:
            # Read again: the run may have refreshed the token, or the access may be gone.
            credential_config = await self._load_credential(config.credential_id, owner_id)
            if credential_config is None:
                raise ValueError("credential unavailable")
            await asyncio.to_thread(
                _act, config.credential_id, credential_config, message_id, config.after_action
            )
        except Exception as exc:
            logger.warning(
                "Outlook Trigger could not apply %s to a message: %s", config.after_action, exc
            )

    async def _load_workflows(self) -> list[Any]:
        """Workflows whose nodes mention the Outlook Trigger; exact checks happen per node."""
        nodes_text = cast(Workflow.nodes, Text)
        async with async_session_maker() as db:
            result = await db.execute(
                select(Workflow.id, Workflow.owner_id, Workflow.nodes).where(
                    nodes_text.contains(f'"{OUTLOOK_TRIGGER}"')
                )
            )
            return list(result.all())

    async def _load_credential(
        self, credential_id: str, owner_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """The credential's config, only if the workflow owner may use it and it is Outlook."""
        try:
            credential_uuid = uuid.UUID(credential_id)
        except ValueError:
            return None
        async with async_session_maker() as db:
            credential = await get_accessible_credential(db, credential_uuid, owner_id)
        if credential is None or credential.type != CredentialType.outlook:
            return None
        return decrypt_config(credential.encrypted_config)


outlook_trigger_manager = OutlookTriggerManager()
