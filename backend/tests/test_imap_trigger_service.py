"""Unit tests for IMAP trigger polling and execution history."""

import socket
import threading
import unittest
import unittest.mock
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import imap_trigger_service
from app.services.imap_trigger_service import (
    ImapCursor,
    ImapDispatchNotStartedError,
    ImapTriggerManager,
)


class ImapTriggerManagerPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_poll_respects_interval_minutes(self) -> None:
        manager = ImapTriggerManager()
        now = datetime.now(timezone.utc)
        key = "wf_node"
        node = {"data": {"pollIntervalMinutes": 5}}

        manager._last_poll_at[key] = now - timedelta(minutes=4)
        self.assertFalse(manager._should_poll_node(key, now, node))

        manager._last_poll_at[key] = now - timedelta(minutes=5, seconds=1)
        self.assertTrue(manager._should_poll_node(key, now, node))

    async def test_poll_workflow_node_executes_each_new_email(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4())
        node = {
            "id": "imap-node",
            "type": "imapTrigger",
            "data": {"credentialId": str(uuid.uuid4()), "pollIntervalMinutes": 5},
        }
        emails = [
            {"uid": "101", "subject": "First"},
            {"uid": "102", "subject": "Second"},
        ]

        with (
            patch.object(
                manager,
                "_load_credential_config",
                AsyncMock(return_value={"imap_host": "imap.example.com"}),
            ),
            patch.object(
                manager,
                "_fetch_node_messages",
                AsyncMock(return_value=(ImapCursor(uidvalidity="1", last_uid=102), emails)),
            ),
            patch.object(manager, "_execute_workflow_for_email", AsyncMock()) as mock_execute,
        ):
            await manager._poll_workflow_node(workflow, node)

        self.assertEqual(
            manager._cursors[manager._get_node_key(workflow.id, "imap-node")].last_uid,
            102,
        )
        self.assertEqual(mock_execute.await_count, 2)
        mock_execute.assert_any_await(workflow, "imap-node", emails[0])
        mock_execute.assert_any_await(workflow, "imap-node", emails[1])

    async def test_poll_workflow_node_applies_cursor_on_empty_batch(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4())
        node = {
            "id": "imap-node",
            "type": "imapTrigger",
            "data": {"credentialId": str(uuid.uuid4()), "pollIntervalMinutes": 5},
        }

        with (
            patch.object(
                manager,
                "_load_credential_config",
                AsyncMock(return_value={"imap_host": "imap.example.com"}),
            ),
            patch.object(
                manager,
                "_fetch_node_messages",
                AsyncMock(return_value=(ImapCursor(uidvalidity="7", last_uid=55), [])),
            ),
            patch.object(manager, "_execute_workflow_for_email", AsyncMock()) as mock_execute,
        ):
            await manager._poll_workflow_node(workflow, node)

        key = manager._get_node_key(workflow.id, "imap-node")
        self.assertEqual(manager._cursors[key], ImapCursor(uidvalidity="7", last_uid=55))
        mock_execute.assert_not_awaited()


class ImapTriggerRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_email_retries_pre_dispatch_failure_then_succeeds(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4())
        email_payload = {"uid": "10"}

        execute_mock = AsyncMock(side_effect=[ImapDispatchNotStartedError("db hiccup"), None])
        with patch.object(manager, "_execute_workflow_for_email", execute_mock):
            await manager._process_email_with_retries(workflow, "imap-node", email_payload)

        self.assertEqual(execute_mock.await_count, 2)

    async def test_process_email_gives_up_after_max_pre_dispatch_attempts(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4())
        email_payload = {"uid": "10"}

        execute_mock = AsyncMock(side_effect=ImapDispatchNotStartedError("still broken"))
        with patch.object(manager, "_execute_workflow_for_email", execute_mock):
            await manager._process_email_with_retries(workflow, "imap-node", email_payload)

        self.assertEqual(execute_mock.await_count, manager._max_pre_dispatch_attempts)

    async def test_process_email_does_not_retry_after_dispatch_started(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4())
        email_payload = {"uid": "10"}

        execute_mock = AsyncMock(side_effect=RuntimeError("history write failed"))
        with patch.object(manager, "_execute_workflow_for_email", execute_mock):
            await manager._process_email_with_retries(workflow, "imap-node", email_payload)

        execute_mock.assert_awaited_once()


class ImapTriggerDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_hands_the_email_to_the_shared_dispatch(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())

        with patch("app.services.imap_trigger_service.run_trigger_workflow", AsyncMock()) as run:
            await manager._execute_workflow_for_email(workflow, "imap-node", {"uid": "7"})

        kwargs = run.await_args.kwargs
        self.assertEqual(kwargs["workflow_id"], workflow.id)
        self.assertEqual(kwargs["trigger_source"], "imap")
        self.assertEqual(kwargs["inputs"]["triggered_by"], "imap")
        self.assertEqual(kwargs["inputs"]["trigger_node_id"], "imap-node")
        self.assertEqual(kwargs["inputs"]["email"], {"uid": "7"})


class ImapConnectTimeoutTests(unittest.TestCase):
    """A mailbox that never answers must give up instead of stalling every IMAP trigger."""

    def _open(self, config: dict) -> None:
        with imap_trigger_service._open_mailbox(config):
            pass

    def test_both_clients_are_created_with_a_timeout(self) -> None:
        for use_ssl, name in ((True, "IMAP4_SSL"), (False, "IMAP4")):
            with self.subTest(name=name):
                client_cls = unittest.mock.MagicMock()
                client_cls.return_value.login.return_value = ("NO", [])
                with patch.object(imap_trigger_service.imaplib, name, client_cls):
                    with self.assertRaisesRegex(ValueError, "login failed"):
                        self._open({"imap_host": "h", "imap_use_ssl": use_ssl})
                self.assertEqual(
                    client_cls.call_args.kwargs["timeout"],
                    imap_trigger_service.IMAP_TIMEOUT_SECONDS,
                )

    def test_a_silent_server_raises_instead_of_blocking(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        outcome: list[BaseException] = []

        def attempt() -> None:
            try:
                self._open(
                    {
                        "imap_host": "127.0.0.1",
                        "imap_port": server.getsockname()[1],
                        "imap_use_ssl": False,
                    }
                )
            except BaseException as exc:  # noqa: BLE001
                outcome.append(exc)

        with patch.object(imap_trigger_service, "IMAP_TIMEOUT_SECONDS", 0.2):
            thread = threading.Thread(target=attempt, daemon=True)
            thread.start()
            thread.join(10)

        self.assertFalse(thread.is_alive(), "the IMAP client blocked on a silent server")
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], OSError)


if __name__ == "__main__":
    unittest.main()
