"""The IMAP Trigger's cursor lives in Postgres: each email runs once across restarts and
leader handoffs, and the cursor is forgotten when the trigger goes."""

import asyncio
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select, update
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import TriggerPollState
from app.db.session import async_session_maker
from app.services import imap_trigger_service
from app.services.imap_trigger_service import ImapCursor, ImapTriggerManager

NODE = {"id": "imap-1", "type": "imapTrigger", "data": {"credentialId": "c1"}}
MAILBOX = [100, 101, 102, 103]


def _mailbox(_config: dict, cursor: ImapCursor) -> tuple[ImapCursor, list[dict]]:
    """Answers like fetch_imap_messages: a baseline first, then the UIDs after the cursor."""
    latest = ImapCursor(uidvalidity="77", last_uid=MAILBOX[-1])
    if cursor.last_uid == 0:
        return latest, []
    return latest, [{"uid": str(uid)} for uid in MAILBOX if uid > cursor.last_uid]


class ImapCursorStorageTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_cursors)
        self.workflow = SimpleNamespace(id=self.workflow_id, nodes=[NODE])
        self.runs: Counter[str] = Counter()
        leader = patch.object(imap_trigger_service, "lock_service", SimpleNamespace(is_leader=True))
        leader.start()
        self.addCleanup(leader.stop)

    async def _drop_cursors(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(TriggerPollState).where(TriggerPollState.workflow_id == self.workflow_id)
            )
            await db.commit()

    async def _record(self, _workflow: object, _node_id: str, email: dict) -> None:
        self.runs[email["uid"]] += 1

    async def _poll(self, manager: ImapTriggerManager, run=None, fetch=None) -> AsyncMock:  # noqa: ANN001
        fetch = fetch or AsyncMock(side_effect=_mailbox)
        with (
            patch.object(manager, "_load_credential_config", AsyncMock(return_value={})),
            patch.object(manager, "_fetch_node_messages", fetch),
            patch.object(manager, "_execute_workflow_for_email", run or self._record),
        ):
            await manager._poll_workflow_node(self.workflow, NODE)
        return fetch

    async def _stored(self) -> ImapCursor | None:
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(TriggerPollState.scope_fingerprint, TriggerPollState.version).where(
                        TriggerPollState.workflow_id == self.workflow_id
                    )
                )
            ).first()
        return None if row is None else ImapCursor(row.scope_fingerprint, int(row.version))

    async def _arrive_and_wait_interval(self, last_uid: int | None = None) -> None:
        """New mail arrived after ``last_uid``, and the node's poll interval has passed."""
        values: dict = {"next_poll_at": func.now()}
        if last_uid is not None:
            values["version"] = last_uid
        async with async_session_maker() as db:
            await db.execute(
                update(TriggerPollState)
                .where(TriggerPollState.workflow_id == self.workflow_id)
                .values(**values)
            )
            await db.commit()

    async def test_the_first_poll_records_a_baseline_and_runs_nothing(self) -> None:
        fetch = await self._poll(ImapTriggerManager())

        self.assertEqual(fetch.await_args.args[1], ImapCursor())
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter())

    async def test_a_new_process_continues_from_the_stored_cursor(self) -> None:
        await self._poll(ImapTriggerManager())
        await self._arrive_and_wait_interval(last_uid=101)

        fetch = await self._poll(ImapTriggerManager())

        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=101))
        self.assertEqual(self.runs, Counter({"102": 1, "103": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))

    async def test_a_node_is_polled_once_per_interval(self) -> None:
        await self._poll(ImapTriggerManager())

        fetch = await self._poll(ImapTriggerManager())

        fetch.assert_not_awaited()

    async def test_a_restart_during_a_batch_does_not_rerun_finished_emails(self) -> None:
        await self._poll(ImapTriggerManager())
        await self._arrive_and_wait_interval(last_uid=100)

        async def stopped_during_102(workflow: object, node_id: str, email: dict) -> None:
            await self._record(workflow, node_id, email)
            if email["uid"] == "102":
                raise asyncio.CancelledError  # the process is stopped during this run

        with self.assertRaises(asyncio.CancelledError):
            await self._poll(ImapTriggerManager(), run=stopped_during_102)
        await self._arrive_and_wait_interval()
        await self._poll(ImapTriggerManager())  # the restarted process

        self.assertEqual(self.runs, Counter({"101": 1, "102": 1, "103": 1}))

    async def test_two_processes_polling_together_run_each_email_once(self) -> None:
        await self._poll(ImapTriggerManager())
        await self._arrive_and_wait_interval(last_uid=100)

        await asyncio.gather(self._poll(ImapTriggerManager()), self._poll(ImapTriggerManager()))

        self.assertEqual(self.runs, Counter({"101": 1, "102": 1, "103": 1}))

    async def test_an_old_leader_stops_once_the_new_one_has_moved_the_cursor(self) -> None:
        await self._poll(ImapTriggerManager())
        await self._arrive_and_wait_interval(last_uid=100)
        running_101 = asyncio.Event()
        release_101 = asyncio.Event()

        async def slow_101(workflow: object, node_id: str, email: dict) -> None:
            await self._record(workflow, node_id, email)
            if email["uid"] == "101":
                running_101.set()
                await release_101.wait()

        old_leader = asyncio.create_task(self._poll(ImapTriggerManager(), run=slow_101))
        await asyncio.wait_for(running_101.wait(), timeout=5)
        # The old leader's run outlasts the interval; the new leader claims the node.
        await self._arrive_and_wait_interval()
        await self._poll(ImapTriggerManager())
        release_101.set()
        await asyncio.wait_for(old_leader, timeout=5)

        self.assertEqual(self.runs, Counter({"101": 1, "102": 1, "103": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))

    async def test_a_process_that_lost_the_lead_leaves_the_rest_to_the_next_poll(self) -> None:
        await self._poll(ImapTriggerManager())
        await self._arrive_and_wait_interval(last_uid=100)
        leadership = SimpleNamespace(is_leader=True)

        async def handoff_during_101(workflow: object, node_id: str, email: dict) -> None:
            await self._record(workflow, node_id, email)
            leadership.is_leader = False

        with patch.object(imap_trigger_service, "lock_service", leadership):
            await self._poll(ImapTriggerManager(), run=handoff_during_101)

        self.assertEqual(self.runs, Counter({"101": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=101))

    async def test_a_changed_uidvalidity_moves_the_cursor_without_runs(self) -> None:
        await self._poll(ImapTriggerManager())
        await self._arrive_and_wait_interval()

        reset = AsyncMock(return_value=(ImapCursor(uidvalidity="78", last_uid=4), []))
        await self._poll(ImapTriggerManager(), fetch=reset)

        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="78", last_uid=4))
        self.assertEqual(self.runs, Counter())

    async def test_a_removed_or_deactivated_trigger_forgets_its_cursor(self) -> None:
        await self._poll(ImapTriggerManager())

        await ImapTriggerManager()._forget_inactive_cursors(active_keys=set())

        self.assertIsNone(await self._stored())

    async def test_an_active_trigger_keeps_its_cursor(self) -> None:
        manager = ImapTriggerManager()
        await self._poll(manager)

        await manager._forget_inactive_cursors(
            active_keys={manager._get_node_key(self.workflow_id, "imap-1")}
        )

        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))
