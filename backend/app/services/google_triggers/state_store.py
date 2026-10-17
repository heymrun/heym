"""Snapshot storage for polling triggers, with the claims that make each change fire once.

Leader election keeps the other workers from polling Google, but correctness does not
rely on it: during a leader handoff two processes can briefly both believe they lead.
Two statements carry the guarantee instead:

- ``claim`` moves ``next_poll_at`` forward only when it is due, so one worker polls a
  node per interval.
- ``consume`` bumps ``version`` only while it still holds the expected value, so each
  change is consumed, and its run started, by exactly one worker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TriggerPollItem, TriggerPollState
from app.db.session import async_session_maker
from app.services.google_triggers.events import ItemWrite


@dataclass(frozen=True)
class ClaimedPoll:
    """A node this worker may poll now, with its stored snapshot."""

    state_id: uuid.UUID
    version: int
    scope_fingerprint: str
    key_id: str
    items: dict[str, dict[str, Any]] = field(repr=False)


@dataclass(frozen=True)
class Claim:
    """Outcome of asking to poll a node. ``due`` with no ``poll`` means record a baseline."""

    due: bool
    poll: ClaimedPoll | None = None


NOT_DUE = Claim(due=False)


class TriggerStateStore:
    """Async access to ``trigger_poll_states`` and ``trigger_poll_items``."""

    def __init__(
        self, session_maker: async_sessionmaker[AsyncSession] = async_session_maker
    ) -> None:
        self._session_maker = session_maker

    async def claim(self, workflow_id: uuid.UUID, node_id: str, poll_minutes: int) -> Claim:
        """Claim the node for this interval. Only one concurrent caller gets a ClaimedPoll."""
        async with self._session_maker() as db:
            row = (
                await db.execute(
                    update(TriggerPollState)
                    .where(
                        TriggerPollState.workflow_id == workflow_id,
                        TriggerPollState.node_id == node_id,
                        TriggerPollState.next_poll_at <= func.now(),
                    )
                    .values(next_poll_at=func.now() + timedelta(minutes=poll_minutes))
                    .returning(
                        TriggerPollState.id,
                        TriggerPollState.version,
                        TriggerPollState.scope_fingerprint,
                        TriggerPollState.key_id,
                    )
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
                return NOT_DUE if exists else Claim(due=True)

            item_rows = await db.execute(
                select(TriggerPollItem.item_key, TriggerPollItem.payload).where(
                    TriggerPollItem.state_id == row.id
                )
            )
            items = {item.item_key: item.payload for item in item_rows}
            await db.commit()
        return Claim(
            due=True,
            poll=ClaimedPoll(row.id, row.version, row.scope_fingerprint, row.key_id, items),
        )

    async def insert_baseline(
        self,
        *,
        workflow_id: uuid.UUID,
        node_id: str,
        node_type: str,
        scope_fingerprint: str,
        key_id: str,
        items: dict[str, dict[str, Any]],
        poll_minutes: int,
    ) -> bool:
        """Record the first snapshot. False when another worker recorded it first."""
        async with self._session_maker() as db:
            state_id = (
                await db.execute(
                    pg_insert(TriggerPollState)
                    .values(
                        id=uuid.uuid4(),
                        workflow_id=workflow_id,
                        node_id=node_id,
                        node_type=node_type,
                        scope_fingerprint=scope_fingerprint,
                        key_id=key_id,
                        version=0,
                        next_poll_at=func.now() + timedelta(minutes=poll_minutes),
                    )
                    .on_conflict_do_nothing(constraint="uq_trigger_poll_state_node")
                    .returning(TriggerPollState.id)
                )
            ).scalar_one_or_none()
            if state_id is None:
                await db.rollback()
                return False
            await self._insert_items(db, state_id, items)
            await db.commit()
            return True

    async def consume(
        self, state_id: uuid.UUID, expected_version: int, writes: list[ItemWrite]
    ) -> bool:
        """Apply writes and bump the version, only if no one else has moved it."""
        async with self._session_maker() as db:
            if not await self._bump(db, state_id, expected_version):
                await db.rollback()
                return False
            for write in writes:
                await self._apply(db, state_id, write)
            await db.commit()
            return True

    async def reset_baseline(
        self,
        state_id: uuid.UUID,
        expected_version: int,
        *,
        scope_fingerprint: str,
        key_id: str,
        items: dict[str, dict[str, Any]],
    ) -> bool:
        """Replace the whole snapshot after a scope or key change. No events fire for it."""
        async with self._session_maker() as db:
            if not await self._bump(
                db,
                state_id,
                expected_version,
                scope_fingerprint=scope_fingerprint,
                key_id=key_id,
            ):
                await db.rollback()
                return False
            await db.execute(delete(TriggerPollItem).where(TriggerPollItem.state_id == state_id))
            await self._insert_items(db, state_id, items)
            await db.commit()
            return True

    async def delete_except(
        self, node_types: tuple[str, ...], keep: set[tuple[uuid.UUID, str]]
    ) -> int:
        """Drop snapshots of nodes that are gone or inactive. Returns how many were dropped."""
        async with self._session_maker() as db:
            rows = (
                await db.execute(
                    select(
                        TriggerPollState.id,
                        TriggerPollState.workflow_id,
                        TriggerPollState.node_id,
                    ).where(TriggerPollState.node_type.in_(node_types))
                )
            ).all()
            stale = [row.id for row in rows if (row.workflow_id, row.node_id) not in keep]
            if stale:
                await db.execute(delete(TriggerPollState).where(TriggerPollState.id.in_(stale)))
            await db.commit()
            return len(stale)

    async def _bump(
        self, db: AsyncSession, state_id: uuid.UUID, expected_version: int, **values: Any
    ) -> bool:
        bumped = (
            await db.execute(
                update(TriggerPollState)
                .where(
                    TriggerPollState.id == state_id,
                    TriggerPollState.version == expected_version,
                )
                .values(version=TriggerPollState.version + 1, updated_at=func.now(), **values)
                .returning(TriggerPollState.id)
                .execution_options(synchronize_session=False)
            )
        ).first()
        return bumped is not None

    async def _apply(self, db: AsyncSession, state_id: uuid.UUID, write: ItemWrite) -> None:
        if write.payload is None:
            await db.execute(
                delete(TriggerPollItem).where(
                    TriggerPollItem.state_id == state_id,
                    TriggerPollItem.item_key == write.item_key,
                )
            )
            return
        await db.execute(
            pg_insert(TriggerPollItem)
            .values(
                id=uuid.uuid4(),
                state_id=state_id,
                item_key=write.item_key,
                payload=write.payload,
            )
            .on_conflict_do_update(
                constraint="uq_trigger_poll_item_key", set_={"payload": write.payload}
            )
        )

    async def _insert_items(
        self, db: AsyncSession, state_id: uuid.UUID, items: dict[str, dict[str, Any]]
    ) -> None:
        if not items:
            return
        await db.execute(
            insert(TriggerPollItem),
            [
                {"id": uuid.uuid4(), "state_id": state_id, "item_key": key, "payload": payload}
                for key, payload in items.items()
            ],
        )
