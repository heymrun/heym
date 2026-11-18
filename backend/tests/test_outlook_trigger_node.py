"""Outlook Trigger node: the email, and its attachments in the run owner's Drive when on."""

import time
import unittest
import uuid
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.cluster.node_placement import Placement, node_placement
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import outlook_trigger_node
from app.services.outlook_trigger import attachments as outlook_attachments
from app.services.outlook_trigger.config import parse_outlook_config
from app.services.outlook_trigger.matching import mail_source, reaches_aliases

OWNER = uuid.uuid4()
CREDENTIAL = str(uuid.uuid4())
PDF = ("invoice.pdf", "application/pdf", b"%PDF-1")


def _raw(message_id: str = "<m1@ex>", to: str = "me@contoso.com") -> bytes:
    message = EmailMessage()
    message["Subject"] = "Invoice"
    message["From"] = "billing@vendor.example"
    message["To"] = to
    message["Message-ID"] = message_id
    message.set_content("Attached.")
    message.add_attachment(PDF[2], maintype="application", subtype="pdf", filename=PDF[0])
    return message.as_bytes()


def _email(**extra: object) -> dict:
    return {
        "id": "ol-1",
        "conversationId": "c-1",
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


def _ctx(data: dict, inputs: dict, credential: object | None = "outlook") -> NodeExecutionContext:
    if credential == "outlook":
        credential = SimpleNamespace(type=CredentialType.outlook, encrypted_config="sealed")
    node_data = {
        "label": "invoiceOutlook",
        "credentialId": CREDENTIAL,
        **data,
        "_initial_inputs": inputs,
    }
    return NodeExecutionContext(
        executor=_Executor(credential),
        node_id="outlook-1",
        inputs={},
        allow_branch_skip=False,
        start_time=time.time(),
        node={"id": "outlook-1", "type": "outlookTrigger", "data": node_data},
        node_type="outlookTrigger",
        node_data=node_data,
        node_label="invoiceOutlook",
    )


class OutlookTriggerNodeTests(unittest.TestCase):
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
        with patch.object(outlook_attachments, "_raw_message") as fetch:
            output = outlook_trigger_node.execute(
                _ctx({}, {"email": _email(), "triggered_at": "2026-11-17T10:00:00+00:00"})
            )
        fetch.assert_not_called()
        self.assertEqual(output["email"]["id"], "ol-1")
        self.assertEqual(output["attachments"], _email()["attachments"])
        self.assertEqual(output["file_ids"], [])
        self.assertEqual(output["triggered_at"], "2026-11-17T10:00:00+00:00")

    def test_a_canvas_run_without_an_email_returns_empty_lists(self) -> None:
        output = outlook_trigger_node.execute(_ctx({"outlookDownloadAttachments": True}, {}))
        self.assertEqual((output["attachments"], output["file_ids"]), ([], []))

    def test_attachments_are_fetched_by_graph_id_and_stored_with_the_trigger_as_context(
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
            patch.object(outlook_attachments, "_raw_message", return_value=_raw()) as fetch,
            patch.object(outlook_attachments, "store_attachments", return_value=stored) as store,
        ):
            output = outlook_trigger_node.execute(
                _ctx({"outlookDownloadAttachments": True}, {"email": _email()})
            )
        self.assertEqual(fetch.call_args.args, (CREDENTIAL, {"client_id": "c"}, "ol-1"))
        planned = store.call_args.args[1]
        self.assertEqual([(item.filename, item.content) for item in planned], [(PDF[0], PDF[2])])
        self.assertEqual(
            store.call_args.args[2], {"outlook_message_id": "ol-1", "message_id": "<m1@ex>"}
        )
        self.assertEqual(store.call_args.kwargs["context"], "Outlook Trigger")
        self.assertEqual(output["file_ids"], ["f1"])

    def test_a_fetch_failure_or_another_message_saves_nothing_and_keeps_the_run_going(self) -> None:
        for fetched in (RuntimeError("Graph down"), None, _raw("<other@ex>")):
            with self.subTest(fetched=fetched):
                side_effect = fetched if isinstance(fetched, Exception) else None
                with (
                    patch.object(
                        outlook_attachments,
                        "_raw_message",
                        side_effect=side_effect,
                        return_value=fetched,
                    ),
                    patch.object(outlook_attachments, "store_attachments") as store,
                ):
                    output = outlook_trigger_node.execute(
                        _ctx({"outlookDownloadAttachments": True}, {"email": _email()})
                    )
                store.assert_not_called()
                self.assertEqual(output["attachments"][0]["skipped_reason"], "unavailable")
                self.assertEqual(output["file_ids"], [])

    def test_an_inaccessible_or_other_credential_fails_the_step(self) -> None:
        for credential in (None, SimpleNamespace(type=CredentialType.gmail, encrypted_config="x")):
            with self.subTest(credential=credential), self.assertRaises(ValueError):
                outlook_trigger_node.execute(
                    _ctx({"outlookDownloadAttachments": True}, {"email": _email()}, credential)
                )

    def test_the_raw_message_comes_from_the_graph_mime_endpoint(self) -> None:
        source = _raw()
        service = MagicMock()
        service.return_value.get_mime.return_value = source
        with patch("app.services.outlook_trigger.poller.OutlookService", service):
            self.assertEqual(outlook_attachments._raw_message(CREDENTIAL, {}, "ol-1"), source)
        service.return_value.get_mime.assert_called_once_with("ol-1")


class OutlookTriggerConfigTests(unittest.TestCase):
    def test_unknown_values_fall_back_to_the_defaults(self) -> None:
        config = parse_outlook_config(
            {
                "credentialId": " c ",
                "outlookMailbox": "spam",
                "outlookAfterAction": "purge",
                "outlookFlaggedOnly": "yes",
                "pollIntervalMinutes": "0",
                "outlookFolderId": "ignored",
            }
        )
        self.assertEqual(
            (config.credential_id, config.mailbox, config.after_action, config.folder_id),
            ("c", "inbox", "none", ""),
        )
        self.assertFalse(config.flagged_only)
        self.assertEqual(config.poll_minutes, 1)

    def test_a_folder_mailbox_needs_a_folder_and_every_trigger_a_credential(self) -> None:
        self.assertEqual(parse_outlook_config({}).problem(), "no credential selected")
        folder = parse_outlook_config({"credentialId": "c", "outlookMailbox": "folder"})
        self.assertEqual(folder.problem(), "no folder selected")
        aliases = parse_outlook_config({"credentialId": "c", "outlookAliases": "A@x.com, b@x.com"})
        self.assertEqual(aliases.aliases, ("a@x.com", "b@x.com"))
        self.assertIsNone(aliases.problem())

    def test_each_mailbox_lists_the_right_folder(self) -> None:
        cases = {
            "inbox": ("mailFolders/inbox/messages", None, False),
            "focused": (
                "mailFolders/inbox/messages",
                "inferenceClassification eq 'focused'",
                False,
            ),
            "other": ("mailFolders/inbox/messages", "inferenceClassification eq 'other'", False),
            "important": ("messages", "importance eq 'high'", True),
            "sent": ("mailFolders/sentitems/messages", None, False),
            "all": ("messages", None, True),
        }
        for mailbox, expected in cases.items():
            with self.subTest(mailbox=mailbox):
                source = mail_source(parse_outlook_config({"outlookMailbox": mailbox}))
                self.assertEqual((source.path, source.filter, source.all_folders), expected)

    def test_aliases_match_to_cc_and_delivery_headers_case_insensitively(self) -> None:
        config = parse_outlook_config({"outlookAliases": ["Sales@Contoso.com"]})
        self.assertTrue(reaches_aliases(config, _raw(to="sales@contoso.com")))
        self.assertFalse(reaches_aliases(config, _raw(to="me@contoso.com")))
        self.assertTrue(reaches_aliases(parse_outlook_config({}), _raw()))


class OutlookTriggerPlacementTests(unittest.TestCase):
    def test_only_a_trigger_that_saves_attachments_stays_on_the_main_instance(self) -> None:
        node = {"type": "outlookTrigger", "data": {"outlookDownloadAttachments": True}}
        self.assertEqual(node_placement(node), Placement.MAIN_ONLY)
        node["data"]["outlookDownloadAttachments"] = False
        self.assertEqual(node_placement(node), Placement.ANYWHERE)


if __name__ == "__main__":
    unittest.main()
