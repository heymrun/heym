"""Gmail Trigger node: the email, and its attachments in the run owner's Drive when on."""

import base64
import time
import unittest
import uuid
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.cluster.node_placement import Placement, node_placement
from app.services.gmail_trigger import attachments as gmail_attachments
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import gmail_trigger_node

OWNER = uuid.uuid4()
CREDENTIAL = str(uuid.uuid4())
PDF = ("invoice.pdf", "application/pdf", b"%PDF-1")


def _raw(message_id: str = "<m1@ex>") -> bytes:
    message = EmailMessage()
    message["Subject"] = "Invoice"
    message["From"] = "billing@vendor.example"
    message["To"] = "me@gmail.com"
    message["Message-ID"] = message_id
    message.set_content("Attached.")
    message.add_attachment(PDF[2], maintype="application", subtype="pdf", filename=PDF[0])
    return message.as_bytes()


def _email(**extra: object) -> dict:
    return {
        "id": "gm-1",
        "threadId": "t-1",
        "subject": "Invoice",
        "messageId": "<m1@ex>",
        "attachments": [{"filename": PDF[0], "content_type": PDF[1], "size_bytes": len(PDF[2])}],
        **extra,
    }


class _Executor:
    def __init__(self, credential: object | None) -> None:
        self.trace_user_id = OWNER
        self.workflow_id = str(uuid.uuid4())
        self._base_url = "https://heym.example"
        self.credential = credential

    def _get_accessible_credential(self, _db: object, _credential_id: object) -> object | None:
        return self.credential


def _ctx(data: dict, inputs: dict, credential: object | None = "gmail") -> NodeExecutionContext:
    if credential == "gmail":
        credential = SimpleNamespace(type=CredentialType.gmail, encrypted_config="sealed")
    node_data = {
        "label": "invoiceGmail",
        "credentialId": CREDENTIAL,
        **data,
        "_initial_inputs": inputs,
    }
    return NodeExecutionContext(
        executor=_Executor(credential),
        node_id="gmail-1",
        inputs={},
        allow_branch_skip=False,
        start_time=time.time(),
        node={"id": "gmail-1", "type": "gmailTrigger", "data": node_data},
        node_type="gmailTrigger",
        node_data=node_data,
        node_label="invoiceGmail",
    )


class GmailTriggerNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.__enter__.return_value = MagicMock()
        for patcher in (
            patch("app.db.session.SessionLocal", return_value=session),
            patch("app.services.encryption.decrypt_config", return_value={"client_id": "c"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_without_the_toggle_attachments_mirror_the_metadata_and_nothing_is_fetched(
        self,
    ) -> None:
        with patch.object(gmail_attachments, "_raw_message") as fetch:
            output = gmail_trigger_node.execute(
                _ctx({}, {"email": _email(), "triggered_at": "2026-11-16T10:00:00+00:00"})
            )
        fetch.assert_not_called()
        self.assertEqual(output["email"]["id"], "gm-1")
        self.assertEqual(output["attachments"], _email()["attachments"])
        self.assertEqual(output["file_ids"], [])
        self.assertEqual(output["triggered_at"], "2026-11-16T10:00:00+00:00")

    def test_a_canvas_run_without_an_email_returns_empty_lists(self) -> None:
        output = gmail_trigger_node.execute(_ctx({"gmailDownloadAttachments": True}, {}))
        self.assertEqual((output["attachments"], output["file_ids"]), ([], []))

    def test_attachments_are_fetched_by_gmail_id_and_stored_with_the_trigger_as_context(
        self,
    ) -> None:
        stored = [
            {
                "id": "f1",
                "filename": PDF[0],
                "content_type": PDF[1],
                "size_bytes": 6,
                "download_url": "https://heym.example/dl",
                "skipped_reason": None,
            }
        ]
        with (
            patch.object(gmail_attachments, "_raw_message", return_value=_raw()) as fetch,
            patch.object(gmail_attachments, "store_attachments", return_value=stored) as store,
        ):
            output = gmail_trigger_node.execute(
                _ctx({"gmailDownloadAttachments": True}, {"email": _email()})
            )
        self.assertEqual(fetch.call_args.args, (CREDENTIAL, {"client_id": "c"}, "gm-1"))
        planned = store.call_args.args[1]
        self.assertEqual([(item.filename, item.content) for item in planned], [(PDF[0], PDF[2])])
        self.assertEqual(
            store.call_args.args[2], {"gmail_message_id": "gm-1", "message_id": "<m1@ex>"}
        )
        self.assertEqual(store.call_args.kwargs["context"], "Gmail Trigger")
        self.assertEqual(output["file_ids"], ["f1"])

    def test_a_fetch_failure_or_another_message_saves_nothing_and_keeps_the_run_going(self) -> None:
        for fetched in (RuntimeError("Gmail down"), None, _raw("<other@ex>")):
            with self.subTest(fetched=fetched):
                side_effect = fetched if isinstance(fetched, Exception) else None
                with (
                    patch.object(
                        gmail_attachments,
                        "_raw_message",
                        side_effect=side_effect,
                        return_value=fetched,
                    ),
                    patch.object(gmail_attachments, "store_attachments") as store,
                ):
                    output = gmail_trigger_node.execute(
                        _ctx({"gmailDownloadAttachments": True}, {"email": _email()})
                    )
                store.assert_not_called()
                self.assertEqual(output["attachments"][0]["skipped_reason"], "unavailable")
                self.assertEqual(output["file_ids"], [])

    def test_an_email_without_a_gmail_id_saves_nothing(self) -> None:
        with patch.object(gmail_attachments, "_raw_message") as fetch:
            output = gmail_trigger_node.execute(
                _ctx({"gmailDownloadAttachments": True}, {"email": _email(id="")})
            )
        fetch.assert_not_called()
        self.assertEqual(output["attachments"][0]["skipped_reason"], "unavailable")

    def test_an_inaccessible_or_other_credential_fails_the_step(self) -> None:
        for credential in (None, SimpleNamespace(type=CredentialType.imap, encrypted_config="x")):
            with self.subTest(credential=credential), self.assertRaises(ValueError):
                gmail_trigger_node.execute(
                    _ctx({"gmailDownloadAttachments": True}, {"email": _email()}, credential)
                )

    def test_the_raw_message_is_decoded_from_gmail(self) -> None:
        source = _raw()
        raw = base64.urlsafe_b64encode(source).decode().rstrip("=")
        service = MagicMock()
        service.return_value.get_raw_message.return_value = {"raw": raw}
        with patch("app.services.gmail_service.GmailService", service):
            self.assertEqual(gmail_attachments._raw_message(CREDENTIAL, {}, "gm-1"), source)
        service.return_value.get_raw_message.assert_called_once_with("gm-1")


class GmailTriggerPlacementTests(unittest.TestCase):
    def test_only_a_trigger_that_saves_attachments_stays_on_the_main_instance(self) -> None:
        node = {"type": "gmailTrigger", "data": {"gmailDownloadAttachments": True}}
        self.assertEqual(node_placement(node), Placement.MAIN_ONLY)
        node["data"]["gmailDownloadAttachments"] = False
        self.assertEqual(node_placement(node), Placement.ANYWHERE)


if __name__ == "__main__":
    unittest.main()
