"""The IMAP Trigger's cursor lives in Postgres: each email runs once across restarts and
leader handoffs, and the cursor is forgotten when the trigger goes."""

import asyncio
import uuid
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import TriggerPollState
from app.db.session import async_session_maker
from app.services import imap_trigger_service
from app.services.imap_trigger_service import (
    ImapCursor,
    ImapTriggerManager,
    mailbox_fingerprint,
)

NODE = {"id": "imap-1", "type": "imapTrigger", "data": {"credentialId": "c1"}}
MAILBOX = [100, 101, 102, 103]


def _mailbox(_config: dict, cursor: ImapCursor | None) -> tuple[ImapCursor, list[dict]]:
    """Answers like fetch_imap_messages: a baseline first, then the UIDs after the cursor."""
    latest_uid = MAILBOX[-1] if MAILBOX else 0
    if cursor is None:
        return ImapCursor(uidvalidity="77", last_uid=latest_uid), []
    last_uid = max(cursor.last_uid, latest_uid)
    return (
        ImapCursor(uidvalidity="77", last_uid=last_uid),
        [{"uid": str(uid)} for uid in MAILBOX if uid > cursor.last_uid],
    )


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

    async def _poll(
        self,
        manager: ImapTriggerManager,
        run=None,  # noqa: ANN001
        fetch=None,  # noqa: ANN001
        node: dict | None = None,
        config: dict | None = None,
    ) -> AsyncMock:
        fetch = fetch or AsyncMock(side_effect=_mailbox)
        target_node = node or NODE
        target_config = config if config is not None else {}
        with (
            patch.object(manager, "_load_credential_config", AsyncMock(return_value=target_config)),
            patch.object(manager, "_fetch_node_messages", fetch),
            patch.object(manager, "_execute_workflow_for_email", run or self._record),
        ):
            await manager._poll_workflow_node(self.workflow, target_node)
        return fetch

    async def _stored(self) -> ImapCursor | None:
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(
                        TriggerPollState.scope_fingerprint,
                        TriggerPollState.version,
                        TriggerPollState.key_id,
                    ).where(TriggerPollState.workflow_id == self.workflow_id)
                )
            ).first()
        return (
            None if row is None else ImapCursor(row.scope_fingerprint, int(row.version), row.key_id)
        )

    async def _stored_key_id(self) -> str | None:
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(TriggerPollState.key_id).where(
                        TriggerPollState.workflow_id == self.workflow_id
                    )
                )
            ).first()
        return None if row is None else row.key_id

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

        self.assertIsNone(fetch.await_args.args[1])
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter())

    async def test_a_baseline_on_an_empty_mailbox_runs_subsequent_new_emails(self) -> None:
        with patch(f"{__name__}.MAILBOX", []):
            fetch = await self._poll(ImapTriggerManager())

        self.assertIsNone(fetch.await_args.args[1])
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=0))
        self.assertEqual(self.runs, Counter())

        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", [1, 2]):
            fetch = await self._poll(ImapTriggerManager())

        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=0))
        self.assertEqual(self.runs, Counter({"1": 1, "2": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=2))

    async def test_an_emptied_mailbox_keeps_its_cursor_and_runs_future_emails(self) -> None:
        await self._poll(ImapTriggerManager())
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))

        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", []):
            await self._poll(ImapTriggerManager())

        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter())

        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", [104, 105]):
            fetch = await self._poll(ImapTriggerManager())

        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter({"104": 1, "105": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=105))

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

    async def test_switching_mailbox_with_zero_cursor_takes_new_baseline(self) -> None:
        # Mailbox A starts empty, establishing a baseline with last_uid=0
        with patch(f"{__name__}.MAILBOX", []):
            await self._poll(ImapTriggerManager(), config={"imap_mailbox": "INBOX"})

        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=0))
        self.assertEqual(self.runs, Counter())

        # Switch the node to mailbox B which already has emails [100, 101, 102, 103]
        # and shares the same UIDVALIDITY ("77").
        await self._arrive_and_wait_interval()
        fetch = await self._poll(ImapTriggerManager(), config={"imap_mailbox": "Archive"})

        # Establishing a new baseline fetches with cursor=None and runs no emails
        self.assertIsNone(fetch.await_args.args[1])
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter())

        # The next poll on mailbox B runs only newly arrived email
        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", [100, 101, 102, 103, 104]):
            fetch = await self._poll(ImapTriggerManager(), config={"imap_mailbox": "Archive"})

        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter({"104": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=104))

    async def test_switching_mailbox_with_non_zero_cursor_takes_new_baseline(self) -> None:
        # Mailbox A establishes baseline at 103
        await self._poll(ImapTriggerManager(), config={"imap_mailbox": "INBOX"})
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))

        # Switch to mailbox B which has emails [200, 201] and shares UIDVALIDITY ("77")
        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", [200, 201]):
            fetch = await self._poll(ImapTriggerManager(), config={"imap_mailbox": "Archive"})

        self.assertIsNone(fetch.await_args.args[1])
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=201))
        self.assertEqual(self.runs, Counter())

        # Next poll runs only new emails
        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", [200, 201, 202]):
            fetch = await self._poll(ImapTriggerManager(), config={"imap_mailbox": "Archive"})

        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=201))
        self.assertEqual(self.runs, Counter({"202": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=202))

    async def test_legacy_cursor_adopts_current_mailbox_without_reset(self) -> None:
        # Simulate a row saved before this change with key_id="imap" and last_uid=101
        async with async_session_maker() as db:
            await db.execute(
                pg_insert(TriggerPollState).values(
                    id=uuid.uuid4(),
                    workflow_id=self.workflow_id,
                    node_id="imap-1",
                    node_type="imapTrigger",
                    key_id="imap",
                    scope_fingerprint="77",
                    version=101,
                    next_poll_at=func.now(),
                )
            )
            await db.commit()

        # First poll after upgrade should process pending emails 102 and 103 without reset
        fetch = await self._poll(ImapTriggerManager())

        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=101))
        self.assertEqual(self.runs, Counter({"102": 1, "103": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))

        # And key_id should now be adopted (no longer "imap")
        key_id = await self._stored_key_id()
        self.assertNotEqual(key_id, "imap")
        self.assertEqual(key_id, mailbox_fingerprint("c1", {}))

    async def test_case_difference_in_username_or_inbox_does_not_take_new_baseline(self) -> None:
        # Establish baseline on INBOX with uppercase username
        await self._poll(
            ImapTriggerManager(),
            config={"imap_username": "User@Example.com", "imap_mailbox": "INBOX"},
        )
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=103))

        # Next poll: new email arrives, and credential was edited to lowercase username and inbox
        await self._arrive_and_wait_interval()
        with patch(f"{__name__}.MAILBOX", [100, 101, 102, 103, 104]):
            fetch = await self._poll(
                ImapTriggerManager(),
                config={"imap_username": "user@example.com", "imap_mailbox": "inbox"},
            )

        # It must NOT take a new baseline; it must fetch new email 104
        self.assertEqual(fetch.await_args.args[1], ImapCursor(uidvalidity="77", last_uid=103))
        self.assertEqual(self.runs, Counter({"104": 1}))
        self.assertEqual(await self._stored(), ImapCursor(uidvalidity="77", last_uid=104))
