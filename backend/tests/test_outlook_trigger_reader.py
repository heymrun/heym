"""Outlook Trigger reader: baselines, received mail, look-back, flagged mail, aliases."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from outlook_fakes import FakeMessage, FakeOutlook, apply_read

from app.services.outlook_service import OutlookApiError
from app.services.outlook_trigger import reader
from app.services.outlook_trigger.config import parse_outlook_config
from app.services.outlook_trigger.mailbox import GraphMailbox
from app.services.outlook_trigger.reader import (
    CURSOR_KEY,
    LOOKBACK,
    MAX_MESSAGES_PER_POLL,
    apply_after_action,
    mailbox_scope,
    message_key,
    read_new_mail,
)


def _config(**data: object):  # noqa: ANN202
    return parse_outlook_config({"credentialId": "cred", **data})


class ReceivedMailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mailbox = FakeOutlook()
        self.config = _config()

    def _poll(self, stored: dict | None, config=None):  # noqa: ANN001, ANN202
        config = config or self.config
        scope = mailbox_scope(self.mailbox.address, config) if stored is not None else None
        read = read_new_mail(GraphMailbox(self.mailbox), config, scope, stored)
        return read, apply_read(stored, read)

    def test_the_first_poll_records_a_baseline_of_recent_mail_and_runs_nothing(self) -> None:
        self.mailbox.add(FakeMessage("recent", self.now - timedelta(minutes=2)))
        self.mailbox.add(FakeMessage("old", self.now - timedelta(days=2)))

        read, stored = self._poll(None)

        self.assertTrue(read.baseline)
        self.assertEqual(read.emails, [])
        self.assertIn(message_key("recent"), stored)
        self.assertNotIn(message_key("old"), stored)
        self.assertGreaterEqual(datetime.fromisoformat(stored[CURSOR_KEY]["since"]), self.now)
        self.assertEqual(self.mailbox.fetched, [])

    def test_mail_received_after_the_baseline_runs_once(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("new", self.now + timedelta(seconds=30)))

        read, stored = self._poll(stored)
        again, _stored = self._poll(stored)

        self.assertEqual([email.payload["id"] for email in read.emails], ["new"])
        self.assertEqual(again.emails, [])

    def test_mail_that_shows_up_late_within_the_look_back_still_runs(self) -> None:
        _read, stored = self._poll(None)
        stored[CURSOR_KEY] = {"since": (self.now + timedelta(minutes=5)).isoformat()}
        self.mailbox.add(FakeMessage("late", self.now + timedelta(minutes=1)))
        self.mailbox.add(FakeMessage("too-old", self.now - LOOKBACK - timedelta(minutes=1)))

        read, _stored = self._poll(stored)

        self.assertEqual([email.payload["id"] for email in read.emails], ["late"])

    def test_the_cursor_moves_to_the_newest_mail_and_old_entries_are_pruned(self) -> None:
        _read, stored = self._poll(None)
        stored[message_key("ancient")] = {"r": (self.now - timedelta(hours=1)).isoformat()}
        newest = self.now + timedelta(minutes=20)
        self.mailbox.add(FakeMessage("new", newest))

        read, stored = self._poll(stored)

        self.assertEqual(datetime.fromisoformat(stored[CURSOR_KEY]["since"]), newest)
        self.assertNotIn(message_key("ancient"), stored)
        self.assertIn(message_key("new"), stored)
        self.assertEqual(len(read.emails), 1)

    def test_a_large_batch_runs_in_order_across_polls(self) -> None:
        _read, stored = self._poll(None)
        for index in range(MAX_MESSAGES_PER_POLL + 10):
            self.mailbox.add(FakeMessage(f"m{index:03}", self.now + timedelta(seconds=index + 1)))

        first, stored = self._poll(stored)
        second, stored = self._poll(stored)
        third, _stored = self._poll(stored)

        self.assertEqual(len(first.emails), MAX_MESSAGES_PER_POLL)
        self.assertEqual(first.emails[0].payload["id"], "m000")
        self.assertEqual([email.payload["id"] for email in second.emails][-1], "m059")
        self.assertEqual(len(second.emails), 10)
        self.assertEqual(third.emails, [])

    def test_aliases_keep_only_mail_sent_to_them_and_others_are_never_fetched_again(
        self,
    ) -> None:
        config = _config(outlookAliases=["support@contoso.com"])
        _read, stored = self._poll(None, config)
        self.mailbox.add(FakeMessage("other", self.now + timedelta(seconds=5)))
        self.mailbox.add(
            FakeMessage("support", self.now + timedelta(seconds=6), to="Support@Contoso.com")
        )

        read, stored = self._poll(stored, config)
        self.mailbox.fetched.clear()
        again, _stored = self._poll(stored, config)

        self.assertEqual([email.payload["id"] for email in read.emails], ["support"])
        self.assertIn(message_key("other"), stored)
        self.assertEqual((again.emails, self.mailbox.fetched), ([], []))

    def test_all_mail_leaves_out_sent_drafts_deleted_junk_and_outbox(self) -> None:
        config = _config(outlookMailbox="all")
        _read, stored = self._poll(None, config)
        for index, folder in enumerate(
            ("F-INBOX", "F-ARCHIVE", "F-SENT", "F-DRAFTS", "F-DELETED", "F-JUNK", "F-OUTBOX")
        ):
            self.mailbox.add(FakeMessage(folder, self.now + timedelta(seconds=index + 1), folder))

        read, _stored = self._poll(stored, config)

        self.assertEqual([email.payload["id"] for email in read.emails], ["F-INBOX", "F-ARCHIVE"])

    def test_focused_and_other_filter_the_inbox_with_the_received_time_first(self) -> None:
        for mailbox in ("focused", "other"):
            with self.subTest(mailbox=mailbox):
                self.mailbox = FakeOutlook()
                config = _config(outlookMailbox=mailbox)
                _read, stored = self._poll(None, config)
                self.mailbox.add(FakeMessage("f", self.now + timedelta(seconds=1)))
                self.mailbox.add(
                    FakeMessage("o", self.now + timedelta(seconds=2), inference="other")
                )

                read, _stored = self._poll(stored, config)

                self.assertEqual([email.payload["id"] for email in read.emails], [mailbox[0]])
                path, params = self.mailbox.listings[-1]
                self.assertEqual(path, "mailFolders/inbox/messages")
                self.assertTrue(params["$filter"].startswith("receivedDateTime ge "))
                self.assertIn(f"inferenceClassification eq '{mailbox}'", params["$filter"])
                self.assertEqual(params["$orderby"], "receivedDateTime asc")

    def test_a_folder_is_listed_by_its_id(self) -> None:
        config = _config(outlookMailbox="folder", outlookFolderId="AAMk/x=")
        _read, _stored = self._poll(None, config)

        self.assertEqual(self.mailbox.listings[-1][0], "mailFolders/AAMk%2Fx%3D/messages")

    def test_a_message_deleted_before_its_fetch_is_skipped_and_remembered(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("gone", self.now + timedelta(seconds=1)))
        self.mailbox.get_mime = MagicMock(side_effect=OutlookApiError(404, "Outlook: not found"))

        read, stored = self._poll(stored)

        self.assertEqual(read.emails, [])
        self.assertIn(message_key("gone"), stored)

    def test_other_fetch_errors_fail_the_poll(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("m", self.now + timedelta(seconds=1)))
        self.mailbox.get_mime = MagicMock(side_effect=OutlookApiError(429, "Outlook: rate limit"))

        with self.assertRaises(OutlookApiError):
            self._poll(stored)

    def test_another_account_mailbox_or_mode_records_a_new_baseline(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("new", self.now + timedelta(seconds=1)))
        for config, address in (
            (self.config, "someone-else@contoso.com"),
            (_config(outlookMailbox="focused"), self.mailbox.address),
            (_config(outlookFlaggedOnly=True), self.mailbox.address),
        ):
            with self.subTest(config=config, address=address):
                scope = mailbox_scope(self.mailbox.address, self.config)
                self.mailbox.address = address
                read = read_new_mail(GraphMailbox(self.mailbox), config, scope, stored)
                self.mailbox.address = "me@contoso.com"
                self.assertTrue(read.baseline)
                self.assertEqual(read.emails, [])

    def test_the_payload_carries_the_mail_fields_and_outlooks_own(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("m1", self.now + timedelta(seconds=1), flagged=True))

        read, _stored = self._poll(stored)

        payload = read.emails[0].payload
        self.assertEqual(payload["id"], "m1")
        self.assertEqual(payload["subject"], "Subject m1")
        self.assertEqual(payload["messageId"], "<m1@example.com>")
        self.assertEqual(payload["conversationId"], "conv-m1")
        self.assertEqual(payload["folderId"], "F-INBOX")
        self.assertEqual(payload["categories"], ["Blue category"])
        self.assertTrue(payload["flagged"])
        self.assertFalse(payload["isRead"])
        self.assertEqual(payload["snippet"], "Preview m1")
        self.assertEqual(payload["webLink"], "https://outlook.office.com/mail/m1")


class FlaggedMailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mailbox = FakeOutlook()
        self.config = _config(outlookFlaggedOnly=True)
        self.old = self.mailbox.add(FakeMessage("old", self.now - timedelta(days=30)))

    def _poll(self, stored: dict | None):  # noqa: ANN202
        scope = mailbox_scope(self.mailbox.address, self.config) if stored is not None else None
        read = read_new_mail(GraphMailbox(self.mailbox), self.config, scope, stored)
        return read, apply_read(stored, read)

    def test_mail_flagged_before_the_baseline_never_runs(self) -> None:
        self.old.flagged = True
        read, stored = self._poll(None)
        again, _stored = self._poll(stored)

        self.assertTrue(read.baseline)
        self.assertEqual(stored, {message_key("old"): stored[message_key("old")]})
        self.assertEqual(again.emails, [])

    def test_flagging_old_mail_runs_it_at_the_next_poll_and_only_once(self) -> None:
        _read, stored = self._poll(None)
        self.old.flagged = True

        read, stored = self._poll(stored)
        again, _stored = self._poll(stored)

        self.assertEqual([email.payload["id"] for email in read.emails], ["old"])
        self.assertTrue(read.emails[0].payload["flagged"])
        self.assertEqual(again.emails, [])

    def test_unflagging_and_flagging_again_runs_again(self) -> None:
        self.old.flagged = True
        _read, stored = self._poll(None)
        self.old.flagged = False
        _read, stored = self._poll(stored)
        self.assertNotIn(message_key("old"), stored)

        self.old.flagged = True
        read, _stored = self._poll(stored)

        self.assertEqual([email.payload["id"] for email in read.emails], ["old"])

    def test_unflagged_mail_never_runs(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("plain", self.now + timedelta(seconds=1)))

        read, _stored = self._poll(stored)

        self.assertEqual(read.emails, [])
        self.assertIn("flag/flagStatus eq 'flagged'", self.mailbox.listings[-1][1]["$filter"])

    def test_an_incomplete_listing_never_forgets_flagged_mail(self) -> None:
        self.old.flagged = True
        _read, stored = self._poll(None)
        self.old.flagged = False
        listing = self.mailbox.list_messages
        self.mailbox.list_messages = lambda path, params, limit: (
            listing(path, params, limit)[0],
            False,
        )

        read, stored = self._poll(stored)

        self.assertEqual(read.silent, [])
        self.assertIn(message_key("old"), stored)

    def test_the_oldest_newly_flagged_mail_runs_first(self) -> None:
        _read, stored = self._poll(None)
        self.mailbox.add(FakeMessage("newer", self.now - timedelta(days=1), flagged=True))
        self.old.flagged = True

        read, _stored = self._poll(stored)

        self.assertEqual([email.payload["id"] for email in read.emails], ["old", "newer"])


class AfterActionTests(unittest.TestCase):
    def test_each_action_marks_read_or_moves_and_none_does_nothing(self) -> None:
        cases = {
            "none": ([], []),
            "markRead": (["m"], []),
            "archive": ([], [("m", "archive")]),
            "markReadAndArchive": (["m"], [("m", "archive")]),
            "delete": ([], [("m", "deleteditems")]),
            "unknown": ([], []),
        }
        for action, (marked, moved) in cases.items():
            with self.subTest(action=action):
                mailbox = FakeOutlook()
                apply_after_action(mailbox, "m", action)
                self.assertEqual((mailbox.marked_read, mailbox.moved), (marked, moved))

    def test_delete_moves_to_deleted_items_and_never_deletes_permanently(self) -> None:
        service = MagicMock()
        apply_after_action(service, "m", "delete")
        service.move.assert_called_once_with("m", "deleteditems")
        self.assertNotIn("delete", [name for name, *_ in service.method_calls])


class ScopeTests(unittest.TestCase):
    def test_scope_changes_with_account_mailbox_folder_and_mode(self) -> None:
        base = mailbox_scope("Me@Contoso.com", _config())
        self.assertEqual(base, mailbox_scope("me@contoso.com", _config()))
        for other in (
            mailbox_scope("other@contoso.com", _config()),
            mailbox_scope("me@contoso.com", _config(outlookMailbox="sent")),
            mailbox_scope("me@contoso.com", _config(outlookMailbox="folder", outlookFolderId="a")),
            mailbox_scope("me@contoso.com", _config(outlookFlaggedOnly=True)),
        ):
            self.assertNotEqual(base, other)

    def test_message_keys_are_short_digests(self) -> None:
        key = message_key("A" * 200)
        self.assertTrue(key.startswith("m:"))
        self.assertEqual(len(key), 42)
        self.assertNotEqual(reader.CURSOR_KEY, key)


if __name__ == "__main__":
    unittest.main()
