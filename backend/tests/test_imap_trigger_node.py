"""IMAP Trigger node: the email's attachments into the run owner's Drive when the toggle is on."""

import tempfile
import time
import unittest
import uuid
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType, GeneratedFile
from app.services import file_storage, imap_trigger_service
from app.services.imap_trigger_service import ImapCursor, fetch_imap_messages
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import imap_trigger_node

OWNER = uuid.uuid4()
WORKFLOW = uuid.uuid4()
CREDENTIAL = str(uuid.uuid4())
CONFIG = {"imap_host": "imap.example.com", "imap_username": "inbox", "imap_password": "pw"}


def _raw_email(attachments: list[tuple[str, str, bytes]], message_id: str = "<m1@ex>") -> bytes:
    message = EmailMessage()
    message["Subject"] = "Invoice 2026-118"
    message["From"] = "billing@vendor.example"
    message["To"] = "inbox@heym.example"
    message["Message-ID"] = message_id
    message.set_content("Please find the invoice attached.")
    for filename, content_type, content in attachments:
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


class _FakeImap:
    """One IMAP server with one mailbox; records what the client asked for."""

    messages: dict[str, bytes] = {}
    uidvalidity = "42"
    connections: list["_FakeImap"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.selected: tuple[str, bool] | None = None
        self.commands: list[tuple[str, ...]] = []
        self.closed = False
        _FakeImap.connections.append(self)

    def login(self, _username: str, _password: str) -> tuple[str, list[bytes]]:
        return "OK", [b"logged in"]

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.selected = (mailbox, readonly)
        return "OK", [b"1"]

    def response(self, code: str) -> tuple[str, list[bytes | None]]:
        if code == "UIDVALIDITY":
            return code, [self.uidvalidity.encode()]
        return code, [None]

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        self.commands.append((command, *[str(arg) for arg in args]))
        if command == "search":
            uids = b" ".join(uid.encode() for uid in sorted(self.messages, key=int))
            return "OK", [uids]
        uid = str(args[0])
        raw = self.messages.get(uid)
        if raw is None:
            return "OK", [None]
        return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]

    def close(self) -> None:
        self.closed = True

    def logout(self) -> None:
        pass


class _Executor:
    def __init__(self, credential: object | None) -> None:
        self.trace_user_id = OWNER
        self.workflow_id = str(WORKFLOW)
        self._base_url = "https://heym.example"
        self.credential = credential
        self.credential_lookups: list[object] = []

    def _get_accessible_credential(self, _db: object, credential_id: object) -> object | None:
        self.credential_lookups.append(credential_id)
        return self.credential


def _email(uid: str = "4182", uidvalidity: str | None = "42", **extra: object) -> dict:
    raw = _FakeImap.messages.get(uid)
    attachments = []
    if raw is not None:
        _message_id, parts = imap_trigger_service.email_attachments(raw)
        attachments = [
            {
                "filename": part.filename,
                "content_type": part.content_type,
                "size_bytes": len(part.content),
            }
            for part in parts
        ]
    return {
        "uid": uid,
        "uidvalidity": uidvalidity,
        "subject": "Invoice 2026-118",
        "messageId": "<m1@ex>",
        "attachments": attachments,
        **extra,
    }


def _ctx(data: dict, inputs: dict, credential: object | None = "imap") -> NodeExecutionContext:
    if credential == "imap":
        credential = SimpleNamespace(type=CredentialType.imap, encrypted_config="sealed")
    node_data = {"label": "invoiceInbox", "credentialId": CREDENTIAL, **data}
    node_data["_initial_inputs"] = inputs
    return NodeExecutionContext(
        executor=_Executor(credential),
        node_id="imap-1",
        inputs={},
        allow_branch_skip=False,
        start_time=time.time(),
        node={"id": "imap-1", "type": "imapTrigger", "data": node_data},
        node_type="imapTrigger",
        node_data=node_data,
        node_label="invoiceInbox",
    )


class _Harness:
    """Fake IMAP server, Drive storage root and database session for one test."""

    def __init__(self, test: unittest.TestCase, messages: dict[str, bytes]) -> None:
        _FakeImap.messages = messages
        _FakeImap.uidvalidity = "42"
        _FakeImap.connections = []
        self.root = Path(tempfile.mkdtemp())
        self.db = MagicMock()
        session = MagicMock()
        session.__enter__.return_value = self.db
        for patcher in (
            patch.object(imap_trigger_service.imaplib, "IMAP4_SSL", _FakeImap),
            patch.object(imap_trigger_service.imaplib, "IMAP4", _FakeImap),
            patch.object(file_storage, "_storage_root", return_value=self.root),
            patch("app.db.session.SessionLocal", return_value=session),
            patch("app.services.encryption.decrypt_config", return_value=dict(CONFIG)),
        ):
            patcher.start()
            test.addCleanup(patcher.stop)

    def rows(self) -> list[GeneratedFile]:
        return [
            call.args[0]
            for call in self.db.add.call_args_list
            if isinstance(call.args[0], GeneratedFile)
        ]

    def stored_files(self) -> list[Path]:
        return [path for path in self.root.rglob("*") if path.is_file()]


INVOICE = ("invoice-2026-118.pdf", "application/pdf", b"%PDF-invoice")
RECEIPT = ("receipt.png", "image/png", b"\x89PNG-receipt")


class TestDownloadAttachments(unittest.TestCase):
    def test_attachments_land_in_the_owners_drive_with_the_trigger_as_source(self) -> None:
        harness = _Harness(self, {"4182": _raw_email([INVOICE, RECEIPT])})
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": _email()})
        )

        rows = harness.rows()
        self.assertEqual([row.filename for row in rows], ["invoice-2026-118.pdf", "receipt.png"])
        for row in rows:
            self.assertEqual(row.owner_id, OWNER)
            self.assertEqual(row.workflow_id, WORKFLOW)
            self.assertEqual(row.source_node_id, "imap-1")
            self.assertEqual(row.source_node_label, "invoiceInbox")
            self.assertEqual(row.metadata_json, {"imap_uid": "4182", "message_id": "<m1@ex>"})
        harness.db.commit.assert_called_once()
        self.assertEqual(
            sorted(path.read_bytes() for path in harness.stored_files()),
            sorted([INVOICE[2], RECEIPT[2]]),
        )

        first, second = output["attachments"]
        self.assertEqual(first["id"], str(rows[0].id))
        self.assertEqual(first["filename"], "invoice-2026-118.pdf")
        self.assertEqual(first["content_type"], "application/pdf")
        self.assertEqual(first["size_bytes"], len(INVOICE[2]))
        self.assertTrue(first["download_url"].startswith("https://heym.example/api/files/dl/"))
        self.assertIsNone(first["skipped_reason"])
        self.assertEqual(second["filename"], "receipt.png")
        self.assertEqual(output["file_ids"], [str(row.id) for row in rows])
        self.assertEqual(output["email"]["subject"], "Invoice 2026-118")

    def test_the_message_is_fetched_read_only_and_left_unread(self) -> None:
        _Harness(self, {"4182": _raw_email([INVOICE])})
        context = _ctx({"imapDownloadAttachments": True}, {"email": _email()})
        imap_trigger_node.execute(context)

        (connection,) = _FakeImap.connections
        self.assertEqual(connection.selected, ("INBOX", True))
        self.assertEqual(connection.commands, [("fetch", "4182", "(BODY.PEEK[])")])
        self.assertTrue(connection.closed)
        self.assertEqual(context.executor.credential_lookups, [CREDENTIAL])

    def test_an_oversized_attachment_is_skipped_and_the_others_are_saved(self) -> None:
        big = ("site-scan.tiff", "image/tiff", b"x" * (1024 * 1024 + 1))
        harness = _Harness(self, {"4182": _raw_email([INVOICE, big, RECEIPT])})
        with patch("app.config.settings.file_max_size_mb", 1):
            output = imap_trigger_node.execute(
                _ctx({"imapDownloadAttachments": True}, {"email": _email()})
            )

        reasons = [item["skipped_reason"] for item in output["attachments"]]
        self.assertEqual(reasons, [None, "too_large", None])
        skipped = output["attachments"][1]
        self.assertEqual(skipped["filename"], "site-scan.tiff")
        self.assertEqual(skipped["size_bytes"], len(big[2]))
        self.assertIsNone(skipped["id"])
        self.assertIsNone(skipped["download_url"])
        self.assertEqual(len(harness.rows()), 2)
        self.assertEqual(len(output["file_ids"]), 2)

    def test_at_most_ten_attachments_are_saved(self) -> None:
        files = [(f"page-{index:02d}.pdf", "application/pdf", b"%PDF") for index in range(12)]
        harness = _Harness(self, {"4182": _raw_email(files)})
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": _email()})
        )

        reasons = [item["skipped_reason"] for item in output["attachments"]]
        self.assertEqual(reasons, [None] * 10 + ["too_many", "too_many"])
        self.assertEqual(
            [item["filename"] for item in output["attachments"][10:]],
            ["page-10.pdf", "page-11.pdf"],
        )
        self.assertEqual(len(harness.rows()), 10)
        self.assertEqual(len(output["file_ids"]), 10)

    def test_a_changed_uidvalidity_saves_nothing(self) -> None:
        harness = _Harness(self, {"4182": _raw_email([INVOICE, RECEIPT])})
        email = _email()
        _FakeImap.uidvalidity = "43"
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": email})
        )

        self.assertEqual(
            [item["skipped_reason"] for item in output["attachments"]],
            ["unavailable", "unavailable"],
        )
        self.assertEqual(output["attachments"][0]["filename"], "invoice-2026-118.pdf")
        self.assertEqual(output["file_ids"], [])
        self.assertEqual(_FakeImap.connections[0].commands, [])
        self.assertEqual(harness.rows(), [])
        self.assertEqual(harness.stored_files(), [])

    def test_a_missing_message_saves_nothing(self) -> None:
        harness = _Harness(self, {"4182": _raw_email([INVOICE])})
        email = _email()
        _FakeImap.messages = {}
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": email})
        )

        self.assertEqual(
            [item["skipped_reason"] for item in output["attachments"]], ["unavailable"]
        )
        self.assertEqual(output["file_ids"], [])
        self.assertEqual(harness.rows(), [])

    def test_another_message_under_the_same_uid_saves_nothing(self) -> None:
        harness = _Harness(self, {"4182": _raw_email([INVOICE], message_id="<other@ex>")})
        email = _email(messageId="<m1@ex>")
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": email})
        )

        self.assertEqual(
            [item["skipped_reason"] for item in output["attachments"]], ["unavailable"]
        )
        self.assertEqual(harness.rows(), [])

    def test_an_email_without_uidvalidity_saves_nothing_and_opens_no_connection(self) -> None:
        _Harness(self, {"4182": _raw_email([INVOICE])})
        email = _email(uidvalidity=None)
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": email})
        )

        self.assertEqual(
            [item["skipped_reason"] for item in output["attachments"]], ["unavailable"]
        )
        self.assertEqual(_FakeImap.connections, [])

    def test_a_login_failure_keeps_the_run_going(self) -> None:
        _Harness(self, {"4182": _raw_email([INVOICE])})
        email = _email()
        with patch.object(_FakeImap, "login", return_value=("NO", [b"denied"])):
            output = imap_trigger_node.execute(
                _ctx({"imapDownloadAttachments": True}, {"email": email})
            )

        self.assertEqual(
            [item["skipped_reason"] for item in output["attachments"]], ["unavailable"]
        )
        self.assertEqual(output["email"]["uid"], "4182")

    def test_a_storage_error_partway_leaves_no_rows_or_files_behind(self) -> None:
        harness = _Harness(self, {"4182": _raw_email([INVOICE, RECEIPT])})
        real_store = file_storage.store_file_sync
        calls: list[str] = []

        def store_then_fail(db: object, **kwargs: object) -> object:
            calls.append(str(kwargs["filename"]))
            if len(calls) == 2:
                raise OSError("No space left on device")
            return real_store(db, **kwargs)

        with patch.object(file_storage, "store_file_sync", side_effect=store_then_fail):
            with self.assertRaisesRegex(OSError, "No space left"):
                imap_trigger_node.execute(
                    _ctx({"imapDownloadAttachments": True}, {"email": _email()})
                )

        self.assertEqual(calls, ["invoice-2026-118.pdf", "receipt.png"])
        harness.db.rollback.assert_called_once()
        harness.db.commit.assert_not_called()
        self.assertEqual(harness.stored_files(), [])

    def test_an_inaccessible_credential_fails_the_step(self) -> None:
        _Harness(self, {"4182": _raw_email([INVOICE])})
        with self.assertRaisesRegex(ValueError, "not found or not accessible"):
            imap_trigger_node.execute(
                _ctx({"imapDownloadAttachments": True}, {"email": _email()}, credential=None)
            )
        self.assertEqual(_FakeImap.connections, [])

    def test_an_email_without_attachments_opens_no_connection(self) -> None:
        _Harness(self, {"4182": _raw_email([])})
        output = imap_trigger_node.execute(
            _ctx({"imapDownloadAttachments": True}, {"email": _email()})
        )
        self.assertEqual(output["attachments"], [])
        self.assertEqual(output["file_ids"], [])
        self.assertEqual(_FakeImap.connections, [])

    def test_a_canvas_run_without_an_email_returns_empty_lists(self) -> None:
        _Harness(self, {})
        output = imap_trigger_node.execute(_ctx({"imapDownloadAttachments": True}, {}))
        self.assertEqual(output["attachments"], [])
        self.assertEqual(output["file_ids"], [])
        self.assertEqual(output["email"], {})
        self.assertEqual(_FakeImap.connections, [])


class TestToggleOff(unittest.TestCase):
    def test_no_connection_and_attachments_mirror_the_email_metadata(self) -> None:
        harness = _Harness(self, {"4182": _raw_email([INVOICE, RECEIPT])})
        email = _email()
        for data in ({}, {"imapDownloadAttachments": False}):
            output = imap_trigger_node.execute(_ctx(data, {"email": email}))
            self.assertEqual(output["attachments"], email["attachments"])
            self.assertEqual(output["file_ids"], [])
            self.assertEqual(output["email"], email)
        self.assertEqual(_FakeImap.connections, [])
        self.assertEqual(harness.rows(), [])

    def test_output_keeps_triggered_at(self) -> None:
        _Harness(self, {})
        output = imap_trigger_node.execute(
            _ctx({}, {"email": {"uid": "1"}, "triggered_at": "2026-11-14T09:12:03+00:00"})
        )
        self.assertEqual(output["triggered_at"], "2026-11-14T09:12:03+00:00")
        self.assertEqual(output["attachments"], [])


class TestPollerPayload(unittest.TestCase):
    def test_the_trigger_input_carries_uidvalidity_and_no_attachment_bytes(self) -> None:
        _Harness(self, {"7": _raw_email([INVOICE]), "8": _raw_email([INVOICE, RECEIPT])})
        cursor, emails = fetch_imap_messages(CONFIG, ImapCursor(uidvalidity="42", last_uid=7))

        self.assertEqual(cursor, ImapCursor(uidvalidity="42", last_uid=8))
        (email,) = emails
        self.assertEqual(email["uid"], "8")
        self.assertEqual(email["uidvalidity"], "42")
        self.assertEqual(
            email["attachments"],
            [
                {
                    "filename": "invoice-2026-118.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": len(INVOICE[2]),
                },
                {"filename": "receipt.png", "content_type": "image/png", "size_bytes": 12},
            ],
        )

        def walk(value: object) -> None:
            self.assertNotIsInstance(value, bytes)
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(email)


if __name__ == "__main__":
    unittest.main()
