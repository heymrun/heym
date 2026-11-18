"""Exchange Server mailbox for the Outlook Trigger: folders, queries, MIME and after-run actions."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from exchangelib import errors as ews

from app.services.exchange_server import mailbox as ews_mailbox
from app.services.exchange_server.mailbox import FLAG_FLAGGED, EwsMailbox, summary
from app.services.outlook_service import OutlookApiError
from app.services.outlook_trigger.config import parse_outlook_config
from app.services.outlook_trigger.reader import mailbox_scope, read_new_mail

CONFIG = {
    "auth_mode": "ews",
    "ews_email": "ada@heym.run",
    "ews_username": "HEYM\\ada",
    "ews_password": "pw",
    "ews_server": "mail.heym.run",
}
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _folder(
    folder_id: str, name: str, parent: object = None, folder_class: str = "IPF.Note"
) -> SimpleNamespace:
    return SimpleNamespace(
        id=folder_id,
        name=name,
        parent=parent,
        folder_class=folder_class,
        absolute=f"{getattr(parent, 'absolute', '/root/Top of Information Store')}/{name}",
    )


def _item(item_id: str, received: datetime, **extra: object) -> SimpleNamespace:
    values = {
        "id": item_id,
        "message_id": f"<{item_id}@heym.run>",
        "datetime_received": received,
        "conversation_id": SimpleNamespace(id=f"conv-{item_id}"),
        "parent_folder_id": SimpleNamespace(id="inbox"),
        "categories": ["Red category"],
        "importance": "High",
        "is_read": False,
        "web_client_read_form_query_string": f"https://mail.heym.run/owa/?ItemID={item_id}",
        "heym_flag_status": None,
    }
    values.update(extra)
    return SimpleNamespace(**values)


def _account() -> MagicMock:
    account = MagicMock()
    root = SimpleNamespace(id="root", absolute="/root/Top of Information Store", parent=None)
    inbox = _folder("inbox", "Inbox", root)
    sent = _folder("sent", "Sent Items", root)
    trash = _folder("trash", "Deleted Items", root)
    drafts = _folder("drafts", "Drafts", root)
    junk = _folder("junk", "Junk Email", root)
    outbox = _folder("outbox", "Outbox", root)
    clients = _folder("clients", "Clients", inbox)
    old = _folder("old", "Old", trash)
    calendar = _folder("cal", "Calendar", root, "IPF.Appointment")
    archive = _folder("arch", "Arşiv", root)
    account.inbox, account.sent, account.trash = inbox, sent, trash
    account.drafts, account.junk, account.outbox = drafts, junk, outbox
    account.msg_folder_root = MagicMock(absolute=root.absolute)
    account.msg_folder_root.walk.return_value = [
        inbox,
        clients,
        sent,
        trash,
        old,
        drafts,
        junk,
        outbox,
        calendar,
        archive,
    ]
    account.msg_folder_root.children = [inbox, sent, trash, archive]
    account.root.get_folder.side_effect = lambda folder_id: {"clients": clients}.get(folder_id.id)
    return account


class _Query:
    """Records the FindItem query the mailbox builds and serves items for a slice."""

    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.filters: dict = {}
        self.ordered: tuple = ()
        self.fields: tuple = ()
        self.folders: list = []

    def filter(self, **filters: object) -> "_Query":
        self.filters = filters
        return self

    def only(self, *fields: str) -> "_Query":
        self.fields = fields
        return self

    def order_by(self, *fields: str) -> "_Query":
        self.ordered = fields
        return self

    def __getitem__(self, window: slice) -> list[object]:
        return self.items[window]


class MailboxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.account = _account()
        self.mailbox = EwsMailbox(CONFIG)
        self.mailbox._account = self.account
        self.query = _Query([])

        def collection(account: object, folders: list) -> _Query:
            self.query.folders = folders
            return self.query

        patcher = patch.object(ews_mailbox, "FolderCollection", side_effect=collection)
        patcher.start()
        self.addCleanup(patcher.stop)


class SummaryTests(unittest.TestCase):
    def test_an_ews_message_is_summarized_like_graph_with_a_stable_snapshot_key(self) -> None:
        item = _item("AAMk1", NOW, heym_flag_status=FLAG_FLAGGED, is_read=True)
        data = summary(item)
        self.assertEqual(data["id"], "AAMk1")
        self.assertEqual(data["snapshotKey"], "<AAMk1@heym.run>")
        self.assertEqual(data["receivedDateTime"], NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(data["conversationId"], "conv-AAMk1")
        self.assertEqual(data["parentFolderId"], "inbox")
        self.assertEqual(data["importance"], "high")
        self.assertEqual(data["flag"], {"flagStatus": "flagged"})
        self.assertTrue(data["isRead"])
        self.assertIn("owa", data["webLink"])

    def test_a_real_ews_received_time_is_summarized(self) -> None:
        from exchangelib import EWSDateTime, EWSTimeZone

        received = EWSDateTime(2026, 12, 1, 9, 30, tzinfo=EWSTimeZone("Europe/Istanbul"))
        self.assertEqual(summary(_item("m", received))["receivedDateTime"], "2026-12-01T06:30:00Z")

    def test_a_message_without_an_internet_id_keys_on_its_ews_id(self) -> None:
        data = summary(_item("AAMk2", NOW, message_id=None, heym_flag_status=1))
        self.assertEqual(data["snapshotKey"], "AAMk2")
        self.assertEqual(data["flag"], {"flagStatus": "complete"})


class FolderTests(MailboxTestCase):
    def _folders_for(self, **data: object) -> list[str]:
        self.mailbox.received_since(parse_outlook_config(data), NOW, 10)
        return [folder.id for folder in self.query.folders]

    def test_each_mailbox_reads_its_folders(self) -> None:
        self.assertEqual(self._folders_for(), ["inbox"])
        self.assertEqual(self._folders_for(outlookMailbox="sent"), ["sent"])
        self.assertEqual(
            self._folders_for(outlookMailbox="folder", outlookFolderId="clients"), ["clients"]
        )

    def test_all_mail_leaves_out_not_received_folders_and_their_subfolders(self) -> None:
        self.assertEqual(self._folders_for(outlookMailbox="all"), ["inbox", "clients", "arch"])
        self._folders_for(outlookMailbox="important")
        self.assertEqual(self.query.filters["importance"], "High")

    def test_a_missing_folder_and_the_focused_inbox_are_reported(self) -> None:
        for data, status in (
            ({"outlookMailbox": "folder", "outlookFolderId": "gone"}, 404),
            ({"outlookMailbox": "focused"}, 400),
            ({"outlookMailbox": "other"}, 400),
        ):
            with self.subTest(data=data), self.assertRaises(OutlookApiError) as caught:
                self.mailbox.received_since(parse_outlook_config(data), NOW, 10)
            self.assertEqual(caught.exception.status_code, status)


class QueryTests(MailboxTestCase):
    def test_received_mail_is_listed_oldest_first_from_the_cursor(self) -> None:
        self.query.items = [
            _item(f"m{index}", NOW + timedelta(seconds=index)) for index in range(3)
        ]
        listed, complete = self.mailbox.received_since(parse_outlook_config({}), NOW, 2)

        self.assertEqual([item["id"] for item in listed], ["m0", "m1"])
        self.assertFalse(complete)
        self.assertEqual(self.query.filters["datetime_received__gte"], NOW)
        self.assertEqual(self.query.ordered, ("datetime_received",))
        self.assertIn("heym_flag_status", self.query.fields)

    def test_flagged_mail_is_filtered_on_the_follow_up_flag(self) -> None:
        self.query.items = [_item("m1", NOW, heym_flag_status=FLAG_FLAGGED)]
        listed, complete = self.mailbox.flagged(parse_outlook_config({}), 5)

        self.assertEqual(self.query.filters, {"heym_flag_status": FLAG_FLAGGED})
        self.assertTrue(complete)
        self.assertEqual(listed[0]["flag"], {"flagStatus": "flagged"})

    def test_a_failed_item_in_the_listing_fails_the_poll(self) -> None:
        self.query.items = [ews.ErrorAccessDenied("denied")]
        with self.assertRaises(OutlookApiError) as caught:
            self.mailbox.received_since(parse_outlook_config({}), NOW, 5)
        self.assertEqual(caught.exception.status_code, 403)


class ItemTests(MailboxTestCase):
    def test_mime_is_fetched_by_id_and_returned_as_bytes(self) -> None:
        self.account.fetch.return_value = [SimpleNamespace(mime_content=b"Subject: x\r\n")]
        self.assertEqual(self.mailbox.get_mime("AAMk1"), b"Subject: x\r\n")
        self.assertEqual(self.account.fetch.call_args.kwargs["only_fields"], ("mime_content",))
        self.assertEqual(self.account.fetch.call_args.kwargs["ids"][0].id, "AAMk1")

    def test_a_message_deleted_before_its_fetch_is_not_found(self) -> None:
        for result in ([], [ews.ErrorItemNotFound("gone")]):
            with self.subTest(result=result):
                self.account.fetch.return_value = result
                with self.assertRaises(OutlookApiError) as caught:
                    self.mailbox.get_mime("AAMk1")
                self.assertEqual(caught.exception.status_code, 404)

    def test_mark_read_saves_only_the_read_flag(self) -> None:
        item = MagicMock(is_read=False)
        self.account.fetch.return_value = [item]
        self.mailbox.mark_read("AAMk1")
        self.assertTrue(item.is_read)
        item.save.assert_called_once_with(update_fields=["is_read"])

    def test_delete_moves_to_deleted_items_and_archive_finds_the_localized_folder(self) -> None:
        item = MagicMock()
        self.account.fetch.return_value = [item]
        self.mailbox.move("AAMk1", "deleteditems")
        item.move_to_trash.assert_called_once_with()
        item.delete.assert_not_called()

        self.mailbox.move("AAMk1", "archive")
        self.assertEqual(item.move.call_args.args[0].name, "Arşiv")

    def test_a_mailbox_without_an_archive_folder_is_reported(self) -> None:
        self.account.fetch.return_value = [MagicMock()]
        self.account.msg_folder_root.children = [self.account.inbox]
        with self.assertRaises(OutlookApiError) as caught:
            self.mailbox.move("AAMk1", "archive")
        self.assertEqual(caught.exception.status_code, 404)


class PickerTests(MailboxTestCase):
    def test_mail_folders_are_listed_with_their_path(self) -> None:
        folders = self.mailbox.list_folders()
        paths = {folder["path"]: folder["id"] for folder in folders}
        self.assertEqual(paths["Inbox / Clients"], "clients")
        self.assertNotIn("Calendar", paths)
        self.assertEqual(self.mailbox.addresses(), ["ada@heym.run"])


class _MovingMailbox:
    """An EWS-like client whose message changes id when it moves, as EWS ids do."""

    def __init__(self) -> None:
        self.message = summary(_item("id-in-inbox", NOW + timedelta(seconds=5)))

    def account_address(self) -> str:
        return "ada@heym.run"

    def received_since(self, _config: object, _since: datetime, _limit: int) -> tuple:
        return [dict(self.message)], True

    def flagged(self, _config: object, _limit: int) -> tuple:
        return [], True

    def get_mime(self, message_id: str) -> bytes:
        return b"Subject: hello\r\nTo: ada@heym.run\r\nMessage-ID: <x@y>\r\n\r\nbody"


class ReaderOverEwsTests(unittest.TestCase):
    def test_a_message_that_moves_folders_starts_one_run(self) -> None:
        config = parse_outlook_config({"credentialId": "c", "outlookMailbox": "all"})
        client = _MovingMailbox()
        scope = mailbox_scope("ada@heym.run", config)
        stored = {"cursor": {"since": NOW.isoformat()}}

        first = read_new_mail(client, config, scope, stored)
        for write in [email.write for email in first.emails] + first.silent:
            stored[write.item_key] = write.payload
        client.message["id"] = "id-in-clients"
        second = read_new_mail(client, config, scope, stored)

        self.assertEqual(len(first.emails), 1)
        self.assertEqual(second.emails, [])


if __name__ == "__main__":
    unittest.main()
