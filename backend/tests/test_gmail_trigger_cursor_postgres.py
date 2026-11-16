"""The Gmail Trigger's cursor lives in Postgres: each email runs once across restarts and
concurrent pollers, and the cursor is forgotten when the trigger goes."""

import asyncio
import uuid
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select, update
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import TriggerPollState
from app.db.session import async_session_maker
from app.services.gmail_trigger import poller
from app.services.gmail_trigger.poller import GmailTriggerManager
from app.services.gmail_trigger.reader import GmailCursor, GmailEmail, GmailRead

NODE = {"id": "gmail-1", "type": "gmailTrigger", "data": {"credentialId": str(uuid.uuid4())}}
HISTORY = [110, 120, 130]
SCOPE = "a" * 64


def _mailbox(_credential_id: str, _config: dict, _node: object, cursor: GmailCursor | None):  # noqa: ANN202
    """Answers like read_new_mail: a baseline first, then the emails after the cursor."""
    if cursor is None:
        return GmailRead(GmailCursor(SCOPE, 100), baseline=True)
    emails = [
        GmailEmail(history_id, {"id": f"m{history_id}"})
        for history_id in HISTORY
        if history_id > cursor.history_id
    ]
    return GmailRead(GmailCursor(SCOPE, 140), emails)


class GmailCursorStorageTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_cursors)
        self.workflow = SimpleNamespace(id=self.workflow_id, owner_id=uuid.uuid4(), nodes=[NODE])
        self.runs: Counter[str] = Counter()
        for patcher in (
            patch.object(poller, "lock_service", SimpleNamespace(is_leader=True)),
            patch.object(poller, "_read", side_effect=_mailbox),
            patch.object(poller, "run_trigger_workflow", side_effect=self._record),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _drop_cursors(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(TriggerPollState).where(TriggerPollState.workflow_id == self.workflow_id)
            )
            await db.commit()

    async def _record(self, **kwargs: object) -> None:
        await asyncio.sleep(0)
        self.runs[kwargs["inputs"]["email"]["id"]] += 1  # type: ignore[index]

    async def _poll(self, manager: GmailTriggerManager) -> None:
        with patch.object(manager, "_load_credential", AsyncMock(return_value={})):
            await manager.poll_node(self.workflow, NODE)

    async def _stored(self) -> GmailCursor | None:
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(TriggerPollState.scope_fingerprint, TriggerPollState.version).where(
                        TriggerPollState.workflow_id == self.workflow_id
                    )
                )
            ).first()
        return None if row is None else GmailCursor(row.scope_fingerprint, int(row.version))

    async def _interval_passed(self, history_id: int | None = None) -> None:
        values: dict = {"next_poll_at": func.now()}
        if history_id is not None:
            values["version"] = history_id
        async with async_session_maker() as db:
            await db.execute(
                update(TriggerPollState)
                .where(TriggerPollState.workflow_id == self.workflow_id)
                .values(**values)
            )
            await db.commit()

    async def test_the_first_poll_records_a_baseline_and_runs_nothing(self) -> None:
        await self._poll(GmailTriggerManager())

        self.assertEqual(await self._stored(), GmailCursor(SCOPE, 100))
        self.assertEqual(self.runs, Counter())

    async def test_a_new_process_continues_from_the_stored_cursor(self) -> None:
        await self._poll(GmailTriggerManager())
        await self._interval_passed(history_id=110)

        await self._poll(GmailTriggerManager())

        self.assertEqual(self.runs, Counter({"m120": 1, "m130": 1}))
        self.assertEqual(await self._stored(), GmailCursor(SCOPE, 140))

    async def test_a_node_is_polled_once_per_interval(self) -> None:
        await self._poll(GmailTriggerManager())
        await self._interval_passed()
        await self._poll(GmailTriggerManager())
        await self._poll(GmailTriggerManager())

        self.assertEqual(self.runs, Counter({"m110": 1, "m120": 1, "m130": 1}))

    async def test_two_processes_polling_together_run_each_email_once(self) -> None:
        await self._poll(GmailTriggerManager())
        await self._interval_passed()

        await asyncio.gather(self._poll(GmailTriggerManager()), self._poll(GmailTriggerManager()))

        self.assertEqual(self.runs, Counter({"m110": 1, "m120": 1, "m130": 1}))

    async def test_a_removed_trigger_forgets_its_cursor_and_an_active_one_keeps_it(self) -> None:
        manager = GmailTriggerManager()
        await self._poll(manager)

        await manager._forget_inactive_cursors({(self.workflow_id, "gmail-1")})
        self.assertEqual(await self._stored(), GmailCursor(SCOPE, 100))

        await manager._forget_inactive_cursors(set())
        self.assertIsNone(await self._stored())
