"""Outlook Trigger poller: baselines, consumes per email, reverts, after-run actions."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.db.models import CredentialType
from app.services.google_triggers.events import ItemWrite
from app.services.google_triggers.state_store import NOT_DUE, Claim, ClaimedPoll
from app.services.outlook_service import OutlookApiError
from app.services.outlook_trigger import poller
from app.services.outlook_trigger.poller import OutlookTriggerManager
from app.services.outlook_trigger.reader import OutlookEmail, OutlookRead
from app.services.trigger_run_dispatch import TriggerDispatchNotStartedError

CREDENTIAL = str(uuid.uuid4())
STATE = uuid.uuid4()


def _email(message_id: str) -> OutlookEmail:
    key = f"m:{message_id}"
    return OutlookEmail(
        {"id": message_id, "subject": f"Subject {message_id}"},
        ItemWrite(key, {"r": "2026-11-17T10:00:00+00:00"}),
        ItemWrite(key, None),
    )


def _claim(version: int = 7) -> Claim:
    return Claim(due=True, poll=ClaimedPoll(STATE, version, "scope", "outlook", {"cursor": {}}))


class OutlookPollNodeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = MagicMock()
        self.store.claim = AsyncMock(return_value=_claim())
        self.store.insert_baseline = AsyncMock(return_value=True)
        self.store.reset_baseline = AsyncMock(return_value=True)
        self.store.consume = AsyncMock(return_value=True)
        self.store.delete_except = AsyncMock(return_value=0)
        self.manager = OutlookTriggerManager(store=self.store)
        self.workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        self.data = {"credentialId": CREDENTIAL, "pollIntervalMinutes": 3}
        self.node = {"id": "outlook-1", "type": "outlookTrigger", "data": self.data}
        self.run = AsyncMock()
        self.act = MagicMock()
        self.read = MagicMock()
        for patcher in (
            patch.object(poller, "lock_service", SimpleNamespace(is_leader=True)),
            patch.object(poller, "run_trigger_workflow", self.run),
            patch.object(poller, "_act", self.act),
            patch.object(poller, "_read", self.read),
            patch.object(
                self.manager, "_load_credential", AsyncMock(return_value={"client_id": "c"})
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_the_first_poll_stores_a_baseline_and_runs_nothing(self) -> None:
        self.store.claim.return_value = Claim(due=True)
        self.read.return_value = OutlookRead("scope-1", baseline=True, items={"cursor": {}})

        await self.manager.poll_node(self.workflow, self.node)

        self.store.claim.assert_awaited_once_with(self.workflow.id, "outlook-1", 3)
        self.store.insert_baseline.assert_awaited_once_with(
            workflow_id=self.workflow.id,
            node_id="outlook-1",
            node_type="outlookTrigger",
            scope_fingerprint="scope-1",
            key_id="outlook",
            items={"cursor": {}},
            poll_minutes=3,
        )
        self.assertIsNone(self.read.call_args.args[3])
        self.run.assert_not_awaited()

    async def test_a_new_scope_replaces_the_snapshot_without_runs(self) -> None:
        self.read.return_value = OutlookRead("scope-2", baseline=True, items={"m:a": {}})

        await self.manager.poll_node(self.workflow, self.node)

        self.store.reset_baseline.assert_awaited_once_with(
            STATE, 7, scope_fingerprint="scope-2", key_id="outlook", items={"m:a": {}}
        )
        self.store.consume.assert_not_awaited()
        self.run.assert_not_awaited()

    async def test_each_email_is_consumed_before_its_run_and_housekeeping_comes_last(
        self,
    ) -> None:
        silent = [ItemWrite("cursor", {"since": "later"})]
        self.read.return_value = OutlookRead("scope", [_email("a"), _email("b")], silent)

        await self.manager.poll_node(self.workflow, self.node)

        self.assertEqual(
            self.store.consume.await_args_list,
            [
                call(STATE, 7, [_email("a").write]),
                call(STATE, 8, [_email("b").write]),
                call(STATE, 9, silent),
            ],
        )
        sent = [kwargs["inputs"]["email"]["id"] for _, kwargs in self.run.await_args_list]
        self.assertEqual(sent, ["a", "b"])
        inputs = self.run.await_args.kwargs["inputs"]
        self.assertEqual(inputs["triggered_by"], "outlook")
        self.assertEqual(inputs["trigger_node_id"], "outlook-1")
        self.assertEqual(self.run.await_args.kwargs["trigger_label"], "Outlook Trigger")
        self.act.assert_not_called()

    async def test_the_after_run_action_follows_each_started_run(self) -> None:
        self.data["outlookAfterAction"] = "markReadAndArchive"
        self.read.return_value = OutlookRead("scope", [_email("a"), _email("b")])

        await self.manager.poll_node(self.workflow, self.node)

        self.assertEqual(
            [c.args[2:] for c in self.act.call_args_list],
            [("a", "markReadAndArchive"), ("b", "markReadAndArchive")],
        )

    async def test_a_failing_after_run_action_does_not_stop_the_next_email(self) -> None:
        self.data["outlookAfterAction"] = "delete"
        self.act.side_effect = [OutlookApiError(404, "Outlook: not found"), None]
        self.read.return_value = OutlookRead("scope", [_email("a"), _email("b")])

        with self.assertLogs("outlook_trigger", "WARNING"):
            await self.manager.poll_node(self.workflow, self.node)

        self.assertEqual(self.run.await_count, 2)
        self.assertEqual(self.act.call_count, 2)

    async def test_a_run_that_never_started_is_reverted_and_retried_next_poll(self) -> None:
        self.data["outlookAfterAction"] = "delete"
        self.run.side_effect = TriggerDispatchNotStartedError("queue full")
        silent = [ItemWrite("cursor", {"since": "later"})]
        self.read.return_value = OutlookRead("scope", [_email("a"), _email("b")], silent)

        await self.manager.poll_node(self.workflow, self.node)

        self.assertEqual(self.run.await_count, poller.PRE_DISPATCH_ATTEMPTS)
        self.assertEqual(
            self.store.consume.await_args_list,
            [call(STATE, 7, [_email("a").write]), call(STATE, 8, [_email("a").revert])],
        )
        self.act.assert_not_called()

    async def test_a_run_that_failed_after_starting_is_not_retried(self) -> None:
        self.data["outlookAfterAction"] = "markRead"
        self.run.side_effect = RuntimeError("node failed")
        self.read.return_value = OutlookRead("scope", [_email("a")])

        await self.manager.poll_node(self.workflow, self.node)

        self.assertEqual(self.run.await_count, 1)
        self.assertEqual(self.store.consume.await_count, 1)
        self.act.assert_called_once()

    async def test_another_process_taking_the_email_stops_this_poll(self) -> None:
        self.store.consume.return_value = False
        self.read.return_value = OutlookRead("scope", [_email("a"), _email("b")])

        await self.manager.poll_node(self.workflow, self.node)

        self.run.assert_not_awaited()
        self.assertEqual(self.store.consume.await_count, 1)

    async def test_a_lost_leadership_leaves_the_batch_to_the_next_poll(self) -> None:
        self.read.return_value = OutlookRead("scope", [_email("a")])
        with patch.object(poller, "lock_service", SimpleNamespace(is_leader=False)):
            await self.manager.poll_node(self.workflow, self.node)

        self.run.assert_not_awaited()
        self.store.consume.assert_not_awaited()

    async def test_nothing_is_read_when_not_due_unconfigured_or_without_access(self) -> None:
        self.store.claim.return_value = NOT_DUE
        await self.manager.poll_node(self.workflow, self.node)

        self.store.claim.return_value = _claim()
        unconfigured = {"id": "outlook-2", "type": "outlookTrigger", "data": {}}
        folder = {
            "id": "outlook-3",
            "type": "outlookTrigger",
            "data": {"credentialId": CREDENTIAL, "outlookMailbox": "folder"},
        }
        await self.manager.poll_node(self.workflow, unconfigured)
        await self.manager.poll_node(self.workflow, folder)

        self.manager._load_credential.return_value = None
        await self.manager.poll_node(self.workflow, self.node)

        self.read.assert_not_called()
        self.assertEqual(self.store.claim.await_count, 2)

    async def test_a_graph_error_is_logged_without_a_traceback(self) -> None:
        self.read.side_effect = OutlookApiError(401, "Outlook: credential expired")

        with self.assertLogs("outlook_trigger", "WARNING") as logs:
            await self.manager._poll_node_logged(self.workflow, self.node)

        self.assertIn("credential expired", logs.output[0])
        self.store.consume.assert_not_awaited()


EWS_CONFIG = {
    "auth_mode": "ews",
    "ews_email": "ada@heym.run",
    "ews_username": "HEYM\\ada",
    "ews_password": "pw",
    "ews_server": "mail.heym.run",
}


class ExchangeSignInTests(unittest.IsolatedAsyncioTestCase):
    """A refused Exchange sign-in is not retried until the credential changes."""

    setUp = OutlookPollNodeTests.setUp

    def _credential(self, updated_at: str) -> None:
        self.manager._load_credential.return_value = {
            **EWS_CONFIG,
            poller.CREDENTIAL_MARKER: updated_at,
        }

    async def test_a_refused_first_sign_in_records_a_block_instead_of_a_baseline(self) -> None:
        self._credential("2026-11-18T10:00:00+00:00")
        self.store.claim.return_value = Claim(due=True)
        self.read.side_effect = OutlookApiError(401, "Exchange Server: sign-in failed")

        with self.assertLogs("outlook_trigger", "WARNING"):
            await self.manager.poll_node(self.workflow, self.node)

        kwargs = self.store.insert_baseline.await_args.kwargs
        self.assertEqual(kwargs["scope_fingerprint"], poller.BLOCKED_SCOPE)
        self.assertEqual(
            kwargs["items"], {poller.AUTH_BLOCK_KEY: {"credential": "2026-11-18T10:00:00+00:00"}}
        )

    async def test_a_refused_sign_in_on_a_running_trigger_is_remembered(self) -> None:
        self._credential("v1")
        self.read.side_effect = OutlookApiError(401, "Exchange Server: sign-in failed")

        with self.assertLogs("outlook_trigger", "WARNING"):
            await self.manager.poll_node(self.workflow, self.node)

        self.store.consume.assert_awaited_once_with(
            STATE, 7, [ItemWrite(poller.AUTH_BLOCK_KEY, {"credential": "v1"})]
        )

    async def test_a_blocked_credential_is_not_tried_again_until_it_changes(self) -> None:
        self._credential("v1")
        blocked = ClaimedPoll(
            STATE, 7, "scope", "outlook", {poller.AUTH_BLOCK_KEY: {"credential": "v1"}}
        )
        self.store.claim.return_value = Claim(due=True, poll=blocked)

        await self.manager.poll_node(self.workflow, self.node)
        self.read.assert_not_called()

        self._credential("v2")
        self.read.return_value = OutlookRead("scope", [], [])
        await self.manager.poll_node(self.workflow, self.node)
        self.read.assert_called_once()
        self.store.consume.assert_awaited_once_with(
            STATE, 7, [ItemWrite(poller.AUTH_BLOCK_KEY, None)]
        )

    async def test_a_microsoft_account_error_is_not_blocked(self) -> None:
        self.read.side_effect = OutlookApiError(401, "Outlook: credential expired")
        with self.assertRaises(OutlookApiError):
            await self.manager.poll_node(self.workflow, self.node)
        self.store.consume.assert_not_awaited()
        self.store.insert_baseline.assert_not_awaited()


class MailboxClientTests(unittest.TestCase):
    def test_the_credential_mode_picks_the_client_and_the_marker_is_dropped(self) -> None:
        ews_client = poller.mailbox_client("c", {**EWS_CONFIG, poller.CREDENTIAL_MARKER: "v"}, None)
        self.assertEqual(type(ews_client).__name__, "EwsMailbox")
        self.assertNotIn(poller.CREDENTIAL_MARKER, ews_client._config)

        with patch.object(poller, "OutlookService") as service:
            graph_client = poller.mailbox_client(
                "c", {"client_id": "x", poller.CREDENTIAL_MARKER: "v"}, None
            )
        self.assertEqual(type(graph_client).__name__, "GraphMailbox")
        self.assertEqual(service.call_args.args[1], {"client_id": "x"})


class OutlookPollOnceTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_nodes_are_polled_and_only_outlook_snapshots_are_pruned(self) -> None:
        store = MagicMock(delete_except=AsyncMock(return_value=0))
        manager = OutlookTriggerManager(store=store)
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[
                {"id": "on", "type": "outlookTrigger", "data": {}},
                {"id": "off", "type": "outlookTrigger", "data": {"active": False}},
                {"id": "gmail", "type": "gmailTrigger", "data": {}},
            ],
        )
        polled: list[str] = []

        async def poll_node(_workflow: object, node: dict) -> None:
            polled.append(node["id"])

        with (
            patch.object(manager, "_load_workflows", AsyncMock(return_value=[workflow])),
            patch.object(manager, "poll_node", poll_node),
        ):
            await manager.poll_once()
            await manager.wait_for_polls()

        self.assertEqual(polled, ["on"])
        store.delete_except.assert_awaited_once_with(("outlookTrigger",), {(workflow.id, "on")})

    async def test_only_an_accessible_outlook_credential_is_loaded(self) -> None:
        manager = OutlookTriggerManager(store=MagicMock())
        owner = uuid.uuid4()
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=MagicMock())
        session.__aexit__ = AsyncMock(return_value=False)
        for credential, expected in (
            (
                SimpleNamespace(type=CredentialType.outlook, encrypted_config="x"),
                {"ok": 1, poller.CREDENTIAL_MARKER: ""},
            ),
            (SimpleNamespace(type=CredentialType.gmail, encrypted_config="x"), None),
            (None, None),
        ):
            with (
                self.subTest(credential=credential),
                patch.object(poller, "async_session_maker", return_value=session),
                patch.object(
                    poller, "get_accessible_credential", AsyncMock(return_value=credential)
                ) as access,
                patch.object(poller, "decrypt_config", return_value={"ok": 1}),
            ):
                self.assertEqual(await manager._load_credential(CREDENTIAL, owner), expected)
                self.assertEqual(access.await_args.args[1:], (uuid.UUID(CREDENTIAL), owner))
        self.assertIsNone(await manager._load_credential("not-a-uuid", owner))


if __name__ == "__main__":
    unittest.main()
