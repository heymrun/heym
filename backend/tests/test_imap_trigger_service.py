"""Unit tests for IMAP trigger polling and execution history."""

import asyncio
import socket
import threading
import unittest
import unittest.mock
import uuid
from email import message_from_bytes, policy
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import imap_trigger_service
from app.services.imap_trigger_service import (
    ImapCursor,
    ImapDispatchNotStartedError,
    ImapTriggerManager,
    _CursorClaim,
)


class ImapTriggerManagerPollingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = ImapTriggerManager()
        self.workflow = SimpleNamespace(id=uuid.uuid4())
        self.node = {
            "id": "imap-node",
            "type": "imapTrigger",
            "data": {"credentialId": str(uuid.uuid4()), "pollIntervalMinutes": 5},
        }
        for patcher in (
            patch.object(imap_trigger_service, "lock_service", SimpleNamespace(is_leader=True)),
            patch.object(
                self.manager,
                "_load_credential_config",
                AsyncMock(return_value={"imap_host": "imap.example.com"}),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _poll(self, claim: _CursorClaim, fetched: tuple, advance=True) -> dict:  # noqa: ANN001
        mocks = {
            "_claim_cursor": AsyncMock(return_value=claim),
            "_fetch_node_messages": AsyncMock(return_value=fetched),
            "_execute_workflow_for_email": AsyncMock(),
            "_insert_baseline": AsyncMock(),
            "_advance_cursor": AsyncMock(return_value=advance),
        }
        with patch.multiple(self.manager, **mocks):
            await self.manager._poll_workflow_node(self.workflow, self.node)
        return mocks

    async def test_poll_workflow_node_executes_each_new_email(self) -> None:
        emails = [
            {"uid": "101", "subject": "First"},
            {"uid": "102", "subject": "Second"},
        ]
        stored = ImapCursor(uidvalidity="1", last_uid=100)

        mocks = await self._poll(
            _CursorClaim(due=True, cursor=stored), (ImapCursor("1", 102), emails)
        )

        execute = mocks["_execute_workflow_for_email"]
        self.assertEqual(
            execute.await_args_list,
            [
                unittest.mock.call(self.workflow, "imap-node", emails[0]),
                unittest.mock.call(self.workflow, "imap-node", emails[1]),
            ],
        )
        wf, node = self.workflow.id, "imap-node"
        self.assertEqual(
            mocks["_advance_cursor"].await_args_list,
            [
                unittest.mock.call(wf, node, stored, ImapCursor("1", 101)),
                unittest.mock.call(wf, node, ImapCursor("1", 101), ImapCursor("1", 102)),
                unittest.mock.call(wf, node, ImapCursor("1", 102), ImapCursor("1", 102)),
            ],
        )

    async def test_each_email_is_taken_before_its_run_starts(self) -> None:
        order: list[str] = []
        claim = _CursorClaim(due=True, cursor=ImapCursor("1", 100))
        with patch.multiple(
            self.manager,
            _claim_cursor=AsyncMock(return_value=claim),
            _fetch_node_messages=AsyncMock(return_value=(ImapCursor("1", 101), [{"uid": "101"}])),
            _advance_cursor=AsyncMock(side_effect=lambda *a: order.append("take") or True),
            _execute_workflow_for_email=AsyncMock(side_effect=lambda *a: order.append("run")),
        ):
            await self.manager._poll_workflow_node(self.workflow, self.node)

        self.assertEqual(order, ["take", "run", "take"])

    async def test_a_node_never_polled_records_a_baseline(self) -> None:
        mocks = await self._poll(_CursorClaim(due=True), (ImapCursor("7", 55), []))

        mocks["_fetch_node_messages"].assert_awaited_once_with(
            {"imap_host": "imap.example.com"}, ImapCursor()
        )
        mocks["_insert_baseline"].assert_awaited_once_with(
            self.workflow.id, "imap-node", ImapCursor("7", 55), 5
        )
        mocks["_execute_workflow_for_email"].assert_not_awaited()

    async def test_poll_workflow_node_applies_cursor_on_empty_batch(self) -> None:
        stored = ImapCursor(uidvalidity="7", last_uid=50)

        mocks = await self._poll(_CursorClaim(due=True, cursor=stored), (ImapCursor("8", 3), []))

        mocks["_advance_cursor"].assert_awaited_once_with(
            self.workflow.id, "imap-node", stored, ImapCursor("8", 3)
        )
        mocks["_execute_workflow_for_email"].assert_not_awaited()

    async def test_a_node_claimed_elsewhere_is_not_fetched(self) -> None:
        mocks = await self._poll(_CursorClaim(due=False), (ImapCursor(), []))

        mocks["_fetch_node_messages"].assert_not_awaited()
        mocks["_claim_cursor"].assert_awaited_once_with(self.workflow.id, "imap-node", 5)

    async def test_a_batch_stops_when_another_process_moved_the_cursor(self) -> None:
        emails = [{"uid": "101"}, {"uid": "102"}]
        mocks = await self._poll(
            _CursorClaim(due=True, cursor=ImapCursor("1", 100)),
            (ImapCursor("1", 102), emails),
            advance=False,
        )

        mocks["_execute_workflow_for_email"].assert_not_awaited()
        mocks["_advance_cursor"].assert_awaited_once()

    async def test_a_batch_stops_once_the_process_is_no_longer_the_leader(self) -> None:
        emails = [{"uid": "101"}, {"uid": "102"}]
        with patch.object(imap_trigger_service, "lock_service", SimpleNamespace(is_leader=False)):
            mocks = await self._poll(
                _CursorClaim(due=True, cursor=ImapCursor("1", 100)),
                (ImapCursor("1", 102), emails),
            )

        mocks["_execute_workflow_for_email"].assert_not_awaited()
        mocks["_advance_cursor"].assert_not_awaited()


class ImapParallelPollCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_polls_beyond_the_cap_wait_for_a_free_place(self) -> None:
        with patch.object(imap_trigger_service.settings, "imap_max_parallel_polls", 1):
            manager = ImapTriggerManager()
        release = asyncio.Event()
        fetching: list[str] = []

        async def fetch(config: dict, _cursor: ImapCursor) -> tuple:
            fetching.append(config["name"])
            if config["name"] == "a":
                await release.wait()
            return ImapCursor("1", 1), []

        workflows = [SimpleNamespace(id=uuid.uuid4()) for _ in range(2)]
        nodes = [
            {"id": name, "type": "imapTrigger", "data": {"credentialId": name}}
            for name in ("a", "b")
        ]
        with patch.multiple(
            manager,
            _claim_cursor=AsyncMock(return_value=_CursorClaim(due=True)),
            _load_credential_config=AsyncMock(side_effect=lambda cid: {"name": cid}),
            _fetch_node_messages=AsyncMock(side_effect=fetch),
            _insert_baseline=AsyncMock(),
        ):
            polls = [
                asyncio.create_task(manager._poll_workflow_node(wf, node))
                for wf, node in zip(workflows, nodes, strict=True)
            ]
            for _ in range(10):
                await asyncio.sleep(0)
            self.assertEqual(fetching, ["a"])  # b waits while a's mailbox is open

            release.set()
            await asyncio.wait_for(asyncio.gather(*polls), timeout=5)

        self.assertEqual(fetching, ["a", "b"])


class ImapTriggerPollIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_node_does_not_stop_the_other_nodes(self) -> None:
        manager = ImapTriggerManager()
        failing = SimpleNamespace(
            id=uuid.uuid4(),
            nodes=[{"id": "down", "type": "imapTrigger", "data": {"credentialId": "c1"}}],
        )
        healthy = SimpleNamespace(
            id=uuid.uuid4(),
            nodes=[{"id": "up", "type": "imapTrigger", "data": {"credentialId": "c2"}}],
        )
        polled: list[str] = []

        async def poll(workflow: SimpleNamespace, node: dict) -> None:
            polled.append(node["id"])
            if node["id"] == "down":
                raise TimeoutError("timed out")

        session = AsyncMock()
        session.__aenter__.return_value = session
        with (
            patch("app.services.imap_trigger_service.async_session_maker", return_value=session),
            patch.object(
                manager,
                "_get_workflows_with_imap_trigger",
                AsyncMock(return_value=[failing, healthy]),
            ),
            patch.object(manager, "_poll_workflow_node", side_effect=poll),
            patch.object(manager, "_forget_inactive_cursors", AsyncMock()),
            self.assertLogs("imap_trigger", level="ERROR") as logs,
        ):
            await manager._poll_workflows()
            await manager.wait_for_polls()

        self.assertEqual(polled, ["down", "up"])
        self.assertIn("down", "\n".join(logs.output))


class ImapSlowRunTests(unittest.IsolatedAsyncioTestCase):
    """A slow workflow run holds up only its own IMAP trigger, not the poll pass."""

    async def asyncSetUp(self) -> None:
        self.gate = asyncio.Event()
        self.b_polled = asyncio.Event()
        self.polled: list[str] = []
        self.manager = ImapTriggerManager()
        self._patched = False
        self.workflows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                nodes=[{"id": node_id, "type": "imapTrigger", "data": {"credentialId": "c"}}],
            )
            for node_id in ("a1", "b1")
        ]

    async def _poll_node(self, workflow: SimpleNamespace, node: dict) -> None:
        self.polled.append(node["id"])
        if node["id"] == "a1":
            await self.gate.wait()  # A's workflow is still answering its email
        else:
            self.b_polled.set()

    def _patch(self, *args: object, **kwargs: object) -> None:
        patcher = patch.object(*args, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _pass(self) -> None:
        # Patches stay on for the whole test: the node polls run after the pass returns.
        if not self._patched:
            self._patched = True
            session = AsyncMock()
            session.__aenter__.return_value = session
            self._patch(imap_trigger_service, "async_session_maker", return_value=session)
            self._patch(
                self.manager,
                "_get_workflows_with_imap_trigger",
                AsyncMock(return_value=self.workflows),
            )
            self._patch(self.manager, "_poll_workflow_node", side_effect=self._poll_node)
            self._patch(self.manager, "_forget_inactive_cursors", AsyncMock())
        # Before the fix the pass waited for A's run here, so this timed out.
        await asyncio.wait_for(self.manager._poll_workflows(), timeout=5)

    async def test_another_inbox_is_polled_while_a_slow_run_is_going(self) -> None:
        await self._pass()
        await asyncio.wait_for(self.b_polled.wait(), timeout=5)

        self.assertFalse(self.gate.is_set())
        self.assertEqual(self.polled, ["a1", "b1"])
        self.gate.set()
        await self.manager.wait_for_polls()

    async def test_an_inbox_with_runs_in_flight_is_not_polled_again(self) -> None:
        await self._pass()
        b_key = self.manager._get_node_key(self.workflows[1].id, "b1")
        b_poll = self.manager._node_polls.get(b_key)
        if b_poll is not None:
            await asyncio.wait_for(b_poll, timeout=5)  # B's poll has ended, A's has not
            await asyncio.sleep(0)  # let its done callback drop it
        self.b_polled.clear()

        await self._pass()
        await asyncio.wait_for(self.b_polled.wait(), timeout=5)

        self.assertEqual(self.polled, ["a1", "b1", "b1"])
        self.gate.set()
        await self.manager.wait_for_polls()

    async def test_stop_cancels_polls_in_flight(self) -> None:
        await self._pass()

        await self.manager.stop()

        self.assertEqual(self.manager._node_polls, {})


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


class ForwardedEmailAttachmentTests(unittest.TestCase):
    """An email forwarded as an attachment (.eml) is an attachment, not part of the body."""

    @staticmethod
    def _forwarded() -> EmailMessage:
        forwarded = EmailMessage()
        forwarded["From"] = "billing@vendor.example"
        forwarded["Subject"] = "Invoice 4411"
        forwarded.set_content("Amount due: 1,250.00 EUR by 30 Nov.")
        forwarded.add_attachment(
            b"%PDF-1.4 inner", maintype="application", subtype="pdf", filename="inner.pdf"
        )
        return forwarded

    @classmethod
    def _raw(cls, *, filename: str | None = "Invoice 4411.eml") -> bytes:
        outer = EmailMessage()
        outer["From"] = "colleague@example.com"
        outer["To"] = "ap@example.com"
        outer["Subject"] = "Fwd: Invoice 4411"
        outer["Message-ID"] = "<fwd-1@example.com>"
        outer.set_content("Please book this one.")
        if filename is None:
            outer.add_attachment(cls._forwarded(), disposition="inline")
        else:
            outer.add_attachment(cls._forwarded(), filename=filename)
        return outer.as_bytes()

    def test_the_attached_email_keeps_its_bytes(self) -> None:
        _message_id, attachments = imap_trigger_service.email_attachments(self._raw())

        self.assertEqual([a.filename for a in attachments], ["Invoice 4411.eml", "inner.pdf"])
        self.assertEqual(attachments[0].content_type, "message/rfc822")
        attached = message_from_bytes(attachments[0].content, policy=policy.default)
        self.assertEqual(attached["Subject"], "Invoice 4411")
        self.assertEqual(attachments[1].content, b"%PDF-1.4 inner")

    def test_the_attached_email_body_stays_out_of_the_outer_email(self) -> None:
        payload = imap_trigger_service._parse_email_message(self._raw(), uid=7)

        self.assertEqual(payload["text"], "Please book this one.")
        self.assertEqual(
            [(a["filename"], a["size_bytes"] > 0) for a in payload["attachments"]],
            [("Invoice 4411.eml", True), ("inner.pdf", True)],
        )

    def test_an_inline_forward_without_a_filename_is_still_read(self) -> None:
        payload = imap_trigger_service._parse_email_message(self._raw(filename=None), uid=8)

        self.assertIn("Please book this one.", payload["text"])
        self.assertIn("Amount due: 1,250.00 EUR", payload["text"])
        self.assertEqual([a["filename"] for a in payload["attachments"]], ["inner.pdf"])

    def test_a_malformed_header_in_the_attached_email_does_not_fail_the_poll(self) -> None:
        evil_from = "=?utf-8?q?Evil=0D=0ABcc:_x@y?= <evil-sender-with-a-long-name@example.com>"
        raw = (
            b"From: a@example.com\r\nTo: b@example.com\r\nSubject: Fwd\r\n"
            b"Message-ID: <fwd-2@example.com>\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\nSee attached.\r\n"
            b"--B\r\nContent-Type: message/rfc822\r\n"
            b'Content-Disposition: attachment; filename="x.eml"\r\n\r\n'
            + f"From: {evil_from}\r\nSubject: s\r\n\r\nbody\r\n".encode()
            + b"--B--\r\n"
        )

        payload = imap_trigger_service._parse_email_message(raw, uid=9)
        _message_id, attachments = imap_trigger_service.email_attachments(raw)

        self.assertEqual(payload["text"], "See attached.")
        self.assertEqual([(a.filename, a.content) for a in attachments], [("x.eml", b"")])


if __name__ == "__main__":
    unittest.main()
