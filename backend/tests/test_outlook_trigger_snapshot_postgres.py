"""The Outlook Trigger's snapshot lives in Postgres: each email runs once across restarts and
concurrent pollers, a run that never started is retried, and flagged mail fires on flagging."""

import asyncio
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from outlook_fakes import FakeMessage, FakeOutlook
from sqlalchemy import delete, func, select, update
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import TriggerPollItem, TriggerPollState
from app.db.session import async_session_maker
from app.services.outlook_trigger import poller
from app.services.outlook_trigger.poller import OutlookTriggerManager
from app.services.trigger_run_dispatch import TriggerDispatchNotStartedError


class OutlookSnapshotStorageTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_snapshots)
        self.data: dict = {"credentialId": str(uuid.uuid4())}
        self.node = {"id": "outlook-1", "type": "outlookTrigger", "data": self.data}
        self.workflow = SimpleNamespace(
            id=self.workflow_id, owner_id=uuid.uuid4(), nodes=[self.node]
        )
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mailbox = FakeOutlook()
        self.runs: Counter[str] = Counter()
        self.refuse: set[str] = set()
        session = MagicMock()
        session.__enter__.return_value = MagicMock()
        for patcher in (
            patch.object(poller, "lock_service", SimpleNamespace(is_leader=True)),
            patch.object(poller, "SessionLocal", return_value=session),
            patch.object(poller, "OutlookService", return_value=self.mailbox),
            patch.object(poller, "run_trigger_workflow", side_effect=self._record),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _drop_snapshots(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(TriggerPollState).where(TriggerPollState.workflow_id == self.workflow_id)
            )
            await db.commit()

    async def _record(self, **kwargs: object) -> None:
        await asyncio.sleep(0)
        message_id = kwargs["inputs"]["email"]["id"]  # type: ignore[index]
        if message_id in self.refuse:
            raise TriggerDispatchNotStartedError("queue unavailable")
        self.runs[message_id] += 1

    async def _poll(self, manager: OutlookTriggerManager | None = None) -> None:
        manager = manager or OutlookTriggerManager()
        with patch.object(manager, "_load_credential", AsyncMock(return_value={})):
            await manager.poll_node(self.workflow, self.node)

    async def _interval_passed(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                update(TriggerPollState)
                .where(TriggerPollState.workflow_id == self.workflow_id)
                .values(next_poll_at=func.now())
            )
            await db.commit()

    async def _item_count(self) -> int:
        async with async_session_maker() as db:
            return int(
                (
                    await db.execute(
                        select(func.count(TriggerPollItem.id))
                        .join(TriggerPollState, TriggerPollItem.state_id == TriggerPollState.id)
                        .where(TriggerPollState.workflow_id == self.workflow_id)
                    )
                ).scalar_one()
            )

    def _arrive(self, message_id: str, seconds: int, **extra: object) -> FakeMessage:
        return self.mailbox.add(
            FakeMessage(message_id, self.now + timedelta(seconds=seconds), **extra)
        )

    async def test_mail_before_the_baseline_never_runs_and_new_mail_runs_once(self) -> None:
        self._arrive("before", -60)
        await self._poll()
        self._arrive("a", 1)
        self._arrive("b", 2)

        await self._poll()  # the interval has not passed: nothing is read
        self.assertEqual(self.runs, Counter())

        await self._interval_passed()
        await self._poll()
        await self._interval_passed()
        await self._poll(OutlookTriggerManager())

        self.assertEqual(self.runs, Counter({"a": 1, "b": 1}))

    async def test_two_processes_polling_together_run_each_email_once(self) -> None:
        await self._poll()
        for index in range(5):
            self._arrive(f"m{index}", index + 1)
        await self._interval_passed()

        await asyncio.gather(
            self._poll(OutlookTriggerManager()), self._poll(OutlookTriggerManager())
        )

        self.assertEqual(self.runs, Counter({f"m{index}": 1 for index in range(5)}))

    async def test_a_run_that_never_started_runs_at_the_next_poll(self) -> None:
        await self._poll()
        self._arrive("a", 1)
        self._arrive("b", 2)
        self.refuse.add("a")
        await self._interval_passed()

        with self.assertLogs("outlook_trigger", "WARNING"):
            await self._poll()
        self.assertEqual(self.runs, Counter())

        self.refuse.clear()
        await self._interval_passed()
        await self._poll()

        self.assertEqual(self.runs, Counter({"a": 1, "b": 1}))

    async def test_flagging_runs_once_and_flagging_again_runs_again(self) -> None:
        self.data["outlookFlaggedOnly"] = True
        old = self._arrive("old", -86_400)
        await self._poll()

        old.flagged = True
        await self._interval_passed()
        await self._poll()
        await self._interval_passed()
        await self._poll()
        self.assertEqual(self.runs, Counter({"old": 1}))

        old.flagged = False
        await self._interval_passed()
        await self._poll()
        old.flagged = True
        await self._interval_passed()
        await self._poll()

        self.assertEqual(self.runs, Counter({"old": 2}))

    async def test_switching_to_flagged_only_records_a_new_baseline(self) -> None:
        self._arrive("flagged", -86_400, flagged=True)
        await self._poll()
        self.data["outlookFlaggedOnly"] = True
        await self._interval_passed()

        await self._poll()

        self.assertEqual(self.runs, Counter())
        self.assertEqual(await self._item_count(), 1)

    async def test_a_removed_trigger_forgets_its_snapshot(self) -> None:
        manager = OutlookTriggerManager()
        await self._poll(manager)
        self.assertGreater(await self._item_count(), 0)

        with patch.object(manager, "_load_workflows", AsyncMock(return_value=[])):
            await manager.poll_once()

        self.assertEqual(await self._item_count(), 0)
