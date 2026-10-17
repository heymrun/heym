"""Polls Google Drive and Google Sheets trigger nodes and starts one run per change.

Runs on the leader worker only, like the IMAP trigger, but its correctness does not
depend on that: polls are claimed and changes consumed through the state store's
compare-and-swap, so a change starts at most one run across all workers and instances.

A change is consumed before its run starts. If preparing the run fails before dispatch
begins, the consume is reverted and the next poll fires the change again. Once a run has
started it is never retried. A crash between the consume and the dispatch loses that one
change; it never duplicates it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Text, cast, or_, select

from app.config import settings
from app.db.models import Workflow
from app.db.session import async_session_maker
from app.services.credential_access import get_accessible_credential
from app.services.distributed_lock import lock_service
from app.services.encryption import decrypt_config
from app.services.google_triggers.events import TriggerEvent
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sources import (
    TRIGGER_NODE_TYPES,
    DriveSource,
    SheetsSource,
    build_source,
)
from app.services.google_triggers.state_store import ClaimedPoll, TriggerStateStore
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)

logger = logging.getLogger("google_triggers")

MAX_RUNS_PER_POLL = 50
TICK_SECONDS = 15
PRE_DISPATCH_ATTEMPTS = 3

Dispatch = Callable[..., Awaitable[None]]
Source = DriveSource | SheetsSource


@dataclass(frozen=True)
class _LiveRead:
    scope_fingerprint: str
    items: dict[str, dict[str, Any]]
    changes: list[TriggerEvent]


def _active_trigger_nodes(nodes: Any) -> list[dict[str, Any]]:
    return [
        node
        for node in nodes or []
        if isinstance(node, dict)
        and node.get("type") in TRIGGER_NODE_TYPES
        and (node.get("data") or {}).get("active", True) is not False
    ]


def _read_live(
    source: Source,
    credential_config: dict[str, Any],
    stored: dict[str, dict[str, Any]] | None,
) -> _LiveRead:
    """Fetch and diff in one worker-thread call; HMAC over a large sheet is CPU work."""
    live = source.fetch(credential_config)
    return _LiveRead(
        scope_fingerprint=source.scope_fingerprint(live),
        items=source.items(live),
        changes=source.diff(stored, live) if stored is not None else [],
    )


class GoogleTriggerPoller:
    """Leader loop for googleDriveTrigger and googleSheetsTrigger nodes."""

    def __init__(
        self,
        *,
        store: TriggerStateStore | None = None,
        dispatch: Dispatch = run_trigger_workflow,
        secret: str | None = None,
    ) -> None:
        self._store = store or TriggerStateStore()
        self._dispatch = dispatch
        self._secret = secret
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Google trigger poller started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Google trigger poller stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            try:
                if lock_service.is_leader:
                    await self.poll_once()
            except Exception as exc:
                logger.exception("Error in Google trigger loop: %s", exc)
            await asyncio.sleep(TICK_SECONDS)

    async def poll_once(self) -> None:
        """Poll every due node once, then drop snapshots of nodes that are gone or inactive."""
        workflows = await self._load_workflows()
        keep: set[tuple[uuid.UUID, str]] = set()
        for workflow in workflows:
            for node in _active_trigger_nodes(workflow.nodes):
                node_id = str(node.get("id") or "").strip()
                if not node_id:
                    continue
                keep.add((workflow.id, node_id))
                try:
                    await self.poll_node(workflow, node)
                except Exception:
                    logger.exception(
                        "Google trigger poll failed for workflow %s node %s", workflow.id, node_id
                    )
        await self._store.delete_except(TRIGGER_NODE_TYPES, keep)

    async def poll_node(self, workflow: Any, node: dict[str, Any]) -> None:
        """Claim, read, diff and dispatch for one trigger node."""
        node_id = str(node.get("id") or "").strip()
        fingerprinter = Fingerprinter.for_node(
            self._secret or settings.secret_key, str(workflow.id), node_id
        )
        source = build_source(node, fingerprinter)
        problem = source.problem()
        if problem:
            logger.debug(
                "%s for workflow %s node %s: %s", source.label, workflow.id, node_id, problem
            )
            return

        claim = await self._store.claim(workflow.id, node_id, source.poll_minutes)
        if not claim.due:
            return

        credential_config = await self._load_credential(source, workflow.owner_id)
        if credential_config is None:
            logger.warning(
                "Skipping %s for workflow %s node %s: credential unavailable",
                source.label,
                workflow.id,
                node_id,
            )
            return

        stored = claim.poll.items if claim.poll is not None else None
        try:
            read = await asyncio.to_thread(_read_live, source, credential_config, stored)
        except Exception as exc:
            logger.warning(
                "Skipping %s poll for workflow %s node %s: %s",
                source.label,
                workflow.id,
                node_id,
                exc,
            )
            return

        if claim.poll is None:
            await self._store.insert_baseline(
                workflow_id=workflow.id,
                node_id=node_id,
                node_type=source.node_type,
                scope_fingerprint=read.scope_fingerprint,
                key_id=fingerprinter.key_id,
                items=read.items,
                poll_minutes=source.poll_minutes,
            )
            return

        poll = claim.poll
        if poll.scope_fingerprint != read.scope_fingerprint or poll.key_id != fingerprinter.key_id:
            await self._store.reset_baseline(
                poll.state_id,
                poll.version,
                scope_fingerprint=read.scope_fingerprint,
                key_id=fingerprinter.key_id,
                items=read.items,
            )
            return

        await self._consume_and_dispatch(workflow, node_id, source, poll, read.changes)

    async def _consume_and_dispatch(
        self,
        workflow: Any,
        node_id: str,
        source: Source,
        poll: ClaimedPoll,
        changes: list[TriggerEvent],
    ) -> None:
        version = poll.version
        silent = [change for change in changes if change.event not in source.events]
        loud = [change for change in changes if change.event in source.events]

        if silent:
            if not await self._store.consume(
                poll.state_id, version, [change.write for change in silent]
            ):
                return
            version += 1

        for change in loud[:MAX_RUNS_PER_POLL]:
            if not await self._store.consume(poll.state_id, version, [change.write]):
                logger.info(
                    "%s for workflow %s node %s: another worker moved on, stopping this poll",
                    source.label,
                    workflow.id,
                    node_id,
                )
                return
            version += 1
            if await self._start_run(workflow, node_id, source, change):
                continue
            if await self._store.consume(poll.state_id, version, [change.revert]):
                logger.warning(
                    "%s for workflow %s node %s: run could not start, retrying next poll",
                    source.label,
                    workflow.id,
                    node_id,
                )
            return

        if len(loud) > MAX_RUNS_PER_POLL:
            logger.info(
                "%s for workflow %s node %s: %d more changes wait for the next poll",
                source.label,
                workflow.id,
                node_id,
                len(loud) - MAX_RUNS_PER_POLL,
            )

    async def _start_run(
        self, workflow: Any, node_id: str, source: Source, change: TriggerEvent
    ) -> bool:
        """Start one run. False only when every attempt failed before dispatch started."""
        inputs = {
            "triggered_by": source.trigger_source,
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "change": change.payload,
        }
        for attempt in range(1, PRE_DISPATCH_ATTEMPTS + 1):
            try:
                await self._dispatch(
                    workflow_id=workflow.id,
                    inputs=inputs,
                    trigger_source=source.trigger_source,
                    trigger_label=source.label,
                    log=logger,
                )
                return True
            except TriggerDispatchNotStartedError as exc:
                logger.warning(
                    "%s for workflow %s node %s: run not started (attempt %d/%d): %s",
                    source.label,
                    workflow.id,
                    node_id,
                    attempt,
                    PRE_DISPATCH_ATTEMPTS,
                    exc,
                )
            except Exception:
                logger.exception(
                    "%s for workflow %s node %s: run failed after it started; not retrying",
                    source.label,
                    workflow.id,
                    node_id,
                )
                return True
        return False

    async def _load_workflows(self) -> list[Any]:
        """Workflows whose nodes mention a Google trigger type; exact checks happen per node."""
        nodes_text = cast(Workflow.nodes, Text)
        async with async_session_maker() as db:
            result = await db.execute(
                select(Workflow.id, Workflow.owner_id, Workflow.nodes).where(
                    or_(
                        *(nodes_text.contains(f'"{node_type}"') for node_type in TRIGGER_NODE_TYPES)
                    )
                )
            )
            return list(result.all())

    async def _load_credential(self, source: Source, owner_id: uuid.UUID) -> dict[str, Any] | None:
        """The credential's config, only if the workflow owner may use it and its type fits."""
        try:
            credential_uuid = uuid.UUID(source.credential_id)
        except ValueError:
            return None
        async with async_session_maker() as db:
            credential = await get_accessible_credential(db, credential_uuid, owner_id)
        if credential is None or credential.type != source.credential_type:
            return None
        return decrypt_config(credential.encrypted_config)


google_trigger_poller = GoogleTriggerPoller()
