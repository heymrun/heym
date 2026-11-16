"""Polls Gmail Trigger nodes and starts one run per new email.

Runs on the leader worker, like the IMAP Trigger, and keeps its cursor the same way: one
``trigger_poll_states`` row per node, claimed per interval, whose ``version`` is the Gmail
history id. Each email is taken by moving the cursor onto its history record before its
run starts, so a restart or a second poller never starts it again. After the run has
started, the node's after-run action (mark read, archive, Trash) is applied.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Text, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import CredentialType, TriggerPollState, Workflow
from app.db.session import SessionLocal, async_session_maker
from app.services.credential_access import get_accessible_credential
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.gmail_service import GmailService
from app.services.gmail_trigger.config import GMAIL_TRIGGER, GmailTriggerConfig, parse_gmail_config
from app.services.gmail_trigger.reader import (
    GmailCursor,
    GmailRead,
    apply_after_action,
    read_new_mail,
)
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)

logger = logging.getLogger("gmail_trigger")

TICK_SECONDS = 15
PRE_DISPATCH_ATTEMPTS = 3
# Each poll holds Gmail requests and its runs a database connection.
MAX_PARALLEL_POLLS = 4
TRIGGER_SOURCE = "gmail"
TRIGGER_LABEL = "Gmail Trigger"


@dataclass(frozen=True)
class _Claim:
    """``due`` with no ``cursor`` means the node was never polled: record a baseline."""

    due: bool
    cursor: GmailCursor | None = None


_NOT_DUE = _Claim(due=False)


def _active_nodes(nodes: Any) -> list[dict[str, Any]]:
    return [
        node
        for node in nodes or []
        if isinstance(node, dict)
        and node.get("type") == GMAIL_TRIGGER
        and (node.get("data") or {}).get("active", True) is not False
    ]


def _read(
    credential_id: str,
    credential_config: dict[str, Any],
    config: GmailTriggerConfig,
    cursor: GmailCursor | None,
) -> GmailRead:
    with SessionLocal() as db:
        return read_new_mail(GmailService(credential_id, credential_config, db), config, cursor)


def _act(
    credential_id: str, credential_config: dict[str, Any], message_id: str, action: str
) -> None:
    with SessionLocal() as db:
        apply_after_action(GmailService(credential_id, credential_config, db), message_id, action)


class GmailTriggerManager:
    """Leader loop for gmailTrigger nodes."""

    def __init__(self) -> None:
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
        logger.info("Gmail trigger manager started (worker_id=%s)", lock_service.worker_id)

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
        logger.info("Gmail trigger manager stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self.poll_once()
            except Exception as exc:
                logger.exception("Error in Gmail trigger loop: %s", exc)
            await asyncio.sleep(TICK_SECONDS)

    async def poll_once(self) -> None:
        """Start a poll for every active node not already polling, then drop stale cursors."""
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
        await self._forget_inactive_cursors(keep)

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
        except Exception:
            # One broken mailbox must not keep the other triggers from polling.
            logger.exception(
                "Gmail trigger poll failed for workflow %s node %s", workflow.id, node.get("id")
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
        config = parse_gmail_config(node.get("data") or {})
        problem = config.problem()
        if not node_id or problem:
            if problem:
                logger.debug(
                    "Gmail Trigger for workflow %s node %s: %s", workflow.id, node_id, problem
                )
            return

        claim = await self._claim(workflow.id, node_id, config.poll_minutes)
        if not claim.due:
            return

        async with self._parallel_polls:
            credential_config = await self._load_credential(config.credential_id, workflow.owner_id)
            if credential_config is None:
                logger.warning(
                    "Skipping Gmail Trigger for workflow %s node %s: credential unavailable",
                    workflow.id,
                    node_id,
                )
                return

            read = await asyncio.to_thread(
                _read, config.credential_id, credential_config, config, claim.cursor
            )
            if claim.cursor is None:
                await self._insert_baseline(workflow.id, node_id, read.cursor, config.poll_minutes)
                return
            if read.baseline:
                await self._advance(workflow.id, node_id, claim.cursor, read.cursor)
                return
            if read.emails:
                logger.info(
                    "Gmail trigger found %d new email(s) for workflow %s node %s",
                    len(read.emails),
                    workflow.id,
                    node_id,
                )

            cursor = claim.cursor
            for email in read.emails:
                if not lock_service.is_leader:
                    logger.info(
                        "Gmail Trigger for workflow %s node %s: no longer the leader, "
                        "leaving the rest of the batch to the next poll",
                        workflow.id,
                        node_id,
                    )
                    return
                taken = GmailCursor(read.cursor.scope, email.history_id)
                if not await self._advance(workflow.id, node_id, cursor, taken):
                    logger.info(
                        "Gmail Trigger for workflow %s node %s: another process moved on, "
                        "stopping this poll",
                        workflow.id,
                        node_id,
                    )
                    return
                cursor = taken
                if await self._start_run(workflow, node_id, email.payload):
                    await self._after_run(config, workflow.owner_id, email.payload)

            await self._advance(workflow.id, node_id, cursor, read.cursor)

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
                    "Gmail Trigger for workflow %s node %s: run not started (attempt %d/%d): %s",
                    workflow.id,
                    node_id,
                    attempt,
                    PRE_DISPATCH_ATTEMPTS,
                    exc,
                )
            except Exception:
                logger.exception(
                    "Gmail Trigger for workflow %s node %s: run failed after it started; "
                    "not retrying",
                    workflow.id,
                    node_id,
                )
                return True
        return False

    async def _after_run(
        self, config: GmailTriggerConfig, owner_id: uuid.UUID, email: dict[str, Any]
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
                "Gmail Trigger could not apply %s to message %s: %s",
                config.after_action,
                message_id,
                exc,
            )

    async def _load_workflows(self) -> list[Any]:
        """Workflows whose nodes mention the Gmail Trigger; exact checks happen per node."""
        nodes_text = cast(Workflow.nodes, Text)
        async with async_session_maker() as db:
            result = await db.execute(
                select(Workflow.id, Workflow.owner_id, Workflow.nodes).where(
                    nodes_text.contains(f'"{GMAIL_TRIGGER}"')
                )
            )
            return list(result.all())

    async def _load_credential(
        self, credential_id: str, owner_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """The credential's config, only if the workflow owner may use it and it is Gmail."""
        try:
            credential_uuid = uuid.UUID(credential_id)
        except ValueError:
            return None
        async with async_session_maker() as db:
            credential = await get_accessible_credential(db, credential_uuid, owner_id)
        if credential is None or credential.type != CredentialType.gmail:
            return None
        return decrypt_config(credential.encrypted_config)

    async def _claim(self, workflow_id: uuid.UUID, node_id: str, poll_minutes: int) -> _Claim:
        """Claim the node for one interval; ``next_poll_at`` moves only once it has passed."""
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    update(TriggerPollState)
                    .where(
                        TriggerPollState.workflow_id == workflow_id,
                        TriggerPollState.node_id == node_id,
                        TriggerPollState.node_type == GMAIL_TRIGGER,
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
                return _NOT_DUE if exists else _Claim(due=True)
            await db.commit()
        return _Claim(due=True, cursor=GmailCursor(row.scope_fingerprint, int(row.version)))

    async def _insert_baseline(
        self, workflow_id: uuid.UUID, node_id: str, cursor: GmailCursor, poll_minutes: int
    ) -> None:
        """Record the first cursor; a process that loses the race leaves the other one's."""
        async with async_session_maker() as db:
            await db.execute(
                pg_insert(TriggerPollState)
                .values(
                    id=uuid.uuid4(),
                    workflow_id=workflow_id,
                    node_id=node_id,
                    node_type=GMAIL_TRIGGER,
                    key_id="gmail",
                    scope_fingerprint=cursor.scope,
                    version=cursor.history_id,
                    next_poll_at=func.now() + timedelta(minutes=poll_minutes),
                )
                .on_conflict_do_nothing(constraint="uq_trigger_poll_state_node")
            )
            await db.commit()

    async def _advance(
        self,
        workflow_id: uuid.UUID,
        node_id: str,
        expected: GmailCursor,
        cursor: GmailCursor,
    ) -> bool:
        """Store ``cursor`` only while the stored one is still ``expected``."""
        async with async_session_maker() as db:
            moved = (
                await db.execute(
                    update(TriggerPollState)
                    .where(
                        TriggerPollState.workflow_id == workflow_id,
                        TriggerPollState.node_id == node_id,
                        TriggerPollState.node_type == GMAIL_TRIGGER,
                        TriggerPollState.scope_fingerprint == expected.scope,
                        TriggerPollState.version == expected.history_id,
                    )
                    .values(
                        scope_fingerprint=cursor.scope,
                        version=cursor.history_id,
                        updated_at=func.now(),
                    )
                    .returning(TriggerPollState.id)
                    .execution_options(synchronize_session=False)
                )
            ).first()
            await db.commit()
        return moved is not None

    async def _forget_inactive_cursors(self, keep: set[tuple[uuid.UUID, str]]) -> None:
        """Drop cursors of Gmail Triggers that were removed or turned off.

        A trigger turned back on starts from the mailbox as it is then, instead of running
        every email that arrived while it was off.
        """
        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(
                        TriggerPollState.id, TriggerPollState.workflow_id, TriggerPollState.node_id
                    ).where(TriggerPollState.node_type == GMAIL_TRIGGER)
                )
            ).all()
            stale = [row.id for row in rows if (row.workflow_id, row.node_id) not in keep]
            if stale:
                await db.execute(delete(TriggerPollState).where(TriggerPollState.id.in_(stale)))
                await db.commit()


gmail_trigger_manager = GmailTriggerManager()
