"""Gmail Trigger poller: baseline, per-email cursor, runs, after-run actions, isolation."""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from app.db.models import CredentialType
from app.services.gmail_trigger import poller
from app.services.gmail_trigger.poller import GmailTriggerManager, _Claim
from app.services.gmail_trigger.reader import GmailCursor, GmailEmail, GmailRead
from app.services.trigger_run_dispatch import TriggerDispatchNotStartedError

CREDENTIAL = str(uuid.uuid4())
STORED = GmailCursor("scope", 100)


def _email(history_id: int, message_id: str) -> GmailEmail:
    return GmailEmail(history_id, {"id": message_id, "subject": f"Subject {message_id}"})


class GmailPollNodeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = GmailTriggerManager()
        self.workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        self.data = {"credentialId": CREDENTIAL, "pollIntervalMinutes": 2}
        self.node = {"id": "gmail-1", "type": "gmailTrigger", "data": self.data}
        self.run = AsyncMock()
        self.act = unittest.mock.MagicMock()
        for patcher in (
            patch.object(poller, "lock_service", SimpleNamespace(is_leader=True)),
            patch.object(poller, "run_trigger_workflow", self.run),
            patch.object(poller, "_act", self.act),
            patch.object(
                self.manager, "_load_credential", AsyncMock(return_value={"client_id": "c"})
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _poll(self, claim: _Claim, read: GmailRead, advance: bool = True) -> dict:
        mocks = {
            "_claim": AsyncMock(return_value=claim),
            "_insert_baseline": AsyncMock(),
            "_advance": AsyncMock(return_value=advance),
        }
        with (
            patch.multiple(self.manager, **mocks),
            patch.object(poller, "_read", return_value=read) as read_mock,
        ):
            await self.manager.poll_node(self.workflow, self.node)
        mocks["_read"] = read_mock
        return mocks

    async def test_first_poll_records_a_baseline_and_runs_nothing(self) -> None:
        read = GmailRead(GmailCursor("scope", 900), baseline=True)
        mocks = await self._poll(_Claim(due=True), read)

        mocks["_claim"].assert_awaited_once_with(self.workflow.id, "gmail-1", 2)
        mocks["_insert_baseline"].assert_awaited_once_with(
            self.workflow.id, "gmail-1", GmailCursor("scope", 900), 2
        )
        self.assertIsNone(mocks["_read"].call_args.args[3])
        self.run.assert_not_awaited()

    async def test_a_reset_moves_the_stored_cursor_without_runs(self) -> None:
        read = GmailRead(GmailCursor("other", 900), baseline=True)
        mocks = await self._poll(_Claim(due=True, cursor=STORED), read)

        mocks["_advance"].assert_awaited_once_with(
            self.workflow.id, "gmail-1", STORED, GmailCursor("other", 900)
        )
        self.run.assert_not_awaited()

    async def test_each_email_is_taken_before_its_run_then_the_cursor_moves_to_the_end(
        self,
    ) -> None:
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1"), _email(120, "m2")])
        mocks = await self._poll(_Claim(due=True, cursor=STORED), read)

        wf = self.workflow.id
        self.assertEqual(
            mocks["_advance"].await_args_list,
            [
                call(wf, "gmail-1", STORED, GmailCursor("scope", 110)),
                call(wf, "gmail-1", GmailCursor("scope", 110), GmailCursor("scope", 120)),
                call(wf, "gmail-1", GmailCursor("scope", 120), GmailCursor("scope", 150)),
            ],
        )
        self.assertEqual(self.run.await_count, 2)
        first = self.run.await_args_list[0].kwargs
        self.assertEqual(first["workflow_id"], wf)
        self.assertEqual(first["trigger_source"], "gmail")
        self.assertEqual(first["trigger_label"], "Gmail Trigger")
        self.assertEqual(first["inputs"]["triggered_by"], "gmail")
        self.assertEqual(first["inputs"]["trigger_node_id"], "gmail-1")
        self.assertEqual(first["inputs"]["email"]["id"], "m1")
        self.act.assert_not_called()

    async def test_the_after_run_action_follows_each_started_run(self) -> None:
        self.data["gmailAfterAction"] = "markReadAndArchive"
        order: list[str] = []
        self.run.side_effect = lambda **kwargs: order.append(
            f"run {kwargs['inputs']['email']['id']}"
        )
        self.act.side_effect = lambda _cred, _config, message_id, action: order.append(
            f"{action} {message_id}"
        )
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1"), _email(120, "m2")])
        await self._poll(_Claim(due=True, cursor=STORED), read)

        self.assertEqual(
            order,
            ["run m1", "markReadAndArchive m1", "run m2", "markReadAndArchive m2"],
        )
        self.assertEqual(self.act.call_args.args[:2], (CREDENTIAL, {"client_id": "c"}))

    async def test_a_run_that_fails_after_it_started_still_gets_the_action(self) -> None:
        self.data["gmailAfterAction"] = "trash"
        self.run.side_effect = RuntimeError("workflow blew up")
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1")])
        await self._poll(_Claim(due=True, cursor=STORED), read)

        self.assertEqual(self.run.await_count, 1)
        self.act.assert_called_once_with(CREDENTIAL, {"client_id": "c"}, "m1", "trash")

    async def test_a_run_that_never_started_leaves_the_email_alone(self) -> None:
        self.data["gmailAfterAction"] = "trash"
        self.run.side_effect = TriggerDispatchNotStartedError("db down")
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1")])
        await self._poll(_Claim(due=True, cursor=STORED), read)

        self.assertEqual(self.run.await_count, poller.PRE_DISPATCH_ATTEMPTS)
        self.act.assert_not_called()

    async def test_a_failing_action_does_not_stop_the_batch(self) -> None:
        self.data["gmailAfterAction"] = "markRead"
        self.act.side_effect = [RuntimeError("Gmail 500"), None]
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1"), _email(120, "m2")])
        with self.assertLogs("gmail_trigger", level="WARNING"):
            mocks = await self._poll(_Claim(due=True, cursor=STORED), read)

        self.assertEqual(self.run.await_count, 2)
        self.assertEqual(self.act.call_count, 2)
        self.assertEqual(mocks["_advance"].await_args_list[-1].args[3], GmailCursor("scope", 150))

    async def test_an_inaccessible_credential_skips_the_action(self) -> None:
        self.data["gmailAfterAction"] = "markRead"
        self.manager._load_credential.side_effect = [{"client_id": "c"}, None]
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1")])
        with self.assertLogs("gmail_trigger", level="WARNING"):
            await self._poll(_Claim(due=True, cursor=STORED), read)

        self.act.assert_not_called()

    async def test_another_process_moving_the_cursor_stops_the_poll(self) -> None:
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1")])
        mocks = await self._poll(_Claim(due=True, cursor=STORED), read, advance=False)

        mocks["_advance"].assert_awaited_once()
        self.run.assert_not_awaited()

    async def test_losing_leadership_leaves_the_batch_to_the_next_poll(self) -> None:
        read = GmailRead(GmailCursor("scope", 150), [_email(110, "m1")])
        with patch.object(poller, "lock_service", SimpleNamespace(is_leader=False)):
            mocks = await self._poll(_Claim(due=True, cursor=STORED), read)

        mocks["_advance"].assert_not_awaited()
        self.run.assert_not_awaited()

    async def test_a_node_not_due_is_not_read(self) -> None:
        mocks = await self._poll(_Claim(due=False), GmailRead(STORED))
        mocks["_read"].assert_not_called()

    async def test_a_node_without_credential_or_label_is_not_claimed(self) -> None:
        for data in ({}, {"credentialId": CREDENTIAL, "gmailMailbox": "label"}):
            with self.subTest(data=data):
                self.node["data"] = data
                mocks = await self._poll(_Claim(due=True), GmailRead(STORED))
                mocks["_claim"].assert_not_awaited()

    async def test_an_unavailable_credential_reads_nothing(self) -> None:
        self.manager._load_credential.return_value = None
        with self.assertLogs("gmail_trigger", level="WARNING"):
            mocks = await self._poll(_Claim(due=True, cursor=STORED), GmailRead(STORED))
        mocks["_read"].assert_not_called()


class GmailCredentialAccessTests(unittest.IsolatedAsyncioTestCase):
    async def _load(self, credential: object | None) -> object:
        session = AsyncMock()
        session.__aenter__.return_value = session
        owner = uuid.uuid4()
        with (
            patch.object(poller, "async_session_maker", return_value=session),
            patch.object(
                poller, "get_accessible_credential", AsyncMock(return_value=credential)
            ) as access,
            patch.object(poller, "decrypt_config", return_value={"client_id": "c"}),
        ):
            result = await GmailTriggerManager()._load_credential(CREDENTIAL, owner)
        self.assertEqual(access.await_args.args[1:], (uuid.UUID(CREDENTIAL), owner))
        return result

    async def test_the_owner_must_be_able_to_use_a_gmail_credential(self) -> None:
        gmail = SimpleNamespace(type=CredentialType.gmail, encrypted_config="sealed")
        self.assertEqual(await self._load(gmail), {"client_id": "c"})
        self.assertIsNone(await self._load(None))
        drive = SimpleNamespace(type=CredentialType.google_drive, encrypted_config="sealed")
        self.assertIsNone(await self._load(drive))

    async def test_a_malformed_credential_id_is_unavailable(self) -> None:
        self.assertIsNone(await GmailTriggerManager()._load_credential("nope", uuid.uuid4()))


class GmailPollPassTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_failing_mailbox_does_not_stop_the_others(self) -> None:
        manager = GmailTriggerManager()
        workflows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                owner_id=uuid.uuid4(),
                nodes=[{"id": node_id, "type": "gmailTrigger", "data": {"credentialId": "c"}}],
            )
            for node_id in ("down", "up")
        ]
        polled: list[str] = []

        async def poll(_workflow: object, node: dict) -> None:
            polled.append(node["id"])
            if node["id"] == "down":
                raise TimeoutError("Gmail timed out")

        forget = AsyncMock()
        with (
            patch.object(manager, "_load_workflows", AsyncMock(return_value=workflows)),
            patch.object(manager, "poll_node", side_effect=poll),
            patch.object(manager, "_forget_inactive_cursors", forget),
            self.assertLogs("gmail_trigger", level="ERROR"),
        ):
            await manager.poll_once()
            await manager.wait_for_polls()

        self.assertEqual(polled, ["down", "up"])
        forget.assert_awaited_once_with({(workflows[0].id, "down"), (workflows[1].id, "up")})

    async def test_inactive_and_other_nodes_are_not_polled(self) -> None:
        manager = GmailTriggerManager()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[
                {"id": "off", "type": "gmailTrigger", "data": {"active": False}},
                {"id": "imap", "type": "imapTrigger", "data": {}},
                {"id": "on", "type": "gmailTrigger", "data": {"credentialId": "c"}},
            ],
        )
        poll = AsyncMock()
        forget = AsyncMock()
        with (
            patch.object(manager, "_load_workflows", AsyncMock(return_value=[workflow])),
            patch.object(manager, "poll_node", poll),
            patch.object(manager, "_forget_inactive_cursors", forget),
        ):
            await manager.poll_once()
            await manager.wait_for_polls()

        self.assertEqual([c.args[1]["id"] for c in poll.await_args_list], ["on"])
        forget.assert_awaited_once_with({(workflow.id, "on")})

    async def test_a_node_with_a_poll_in_flight_is_not_polled_again(self) -> None:
        manager = GmailTriggerManager()
        gate = asyncio.Event()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "slow", "type": "gmailTrigger", "data": {"credentialId": "c"}}],
        )
        calls: list[str] = []

        async def poll(_workflow: object, node: dict) -> None:
            calls.append(node["id"])
            await gate.wait()

        with (
            patch.object(manager, "_load_workflows", AsyncMock(return_value=[workflow])),
            patch.object(manager, "poll_node", side_effect=poll),
            patch.object(manager, "_forget_inactive_cursors", AsyncMock()),
        ):
            await manager.poll_once()
            await asyncio.sleep(0)
            await manager.poll_once()
            gate.set()
            await manager.wait_for_polls()

        self.assertEqual(calls, ["slow"])


if __name__ == "__main__":
    unittest.main()
