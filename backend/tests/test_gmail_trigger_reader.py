"""Gmail Trigger history reads: baseline, mailbox entry, aliases, caps and after-run actions."""

import base64
import unittest
from email.message import EmailMessage
from unittest.mock import patch

from app.services.gmail_service import GmailApiError, decode_raw_message
from app.services.gmail_trigger import reader
from app.services.gmail_trigger.config import parse_gmail_config
from app.services.gmail_trigger.reader import (
    GmailCursor,
    account_scope,
    apply_after_action,
    read_new_mail,
)

ACCOUNT = "me@gmail.com"
SCOPE = account_scope(ACCOUNT)


def _raw(subject: str = "Hello", to: str = "me@gmail.com") -> str:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "Ada <ada@example.com>"
    message["To"] = to
    message["Message-ID"] = f"<{subject}@example.com>"
    message.set_content(f"Body of {subject}")
    return base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")


def _added(history_id: int, message_id: str, labels: list[str] | None) -> dict:
    message: dict = {"id": message_id, "threadId": f"t-{message_id}"}
    if labels is not None:
        message["labelIds"] = labels
    return {"id": str(history_id), "messagesAdded": [{"message": message}]}


def _labelled(history_id: int, message_id: str, added: list[str], labels: list[str]) -> dict:
    return {
        "id": str(history_id),
        "labelsAdded": [{"message": {"id": message_id, "labelIds": labels}, "labelIds": added}],
    }


class _FakeGmail:
    def __init__(
        self,
        pages: list[dict] | None = None,
        messages: dict[str, dict] | None = None,
        history_id: int = 500,
        email: str = ACCOUNT,
    ) -> None:
        self.pages = pages or [{"historyId": str(history_id)}]
        self.messages = messages or {}
        self.profile = {"emailAddress": email, "historyId": str(history_id)}
        self.history_calls: list[tuple[int, str | None]] = []
        self.fetched: list[str] = []
        self.history_error: GmailApiError | None = None
        self.modified: list[tuple[str, list[str] | None, list[str] | None]] = []
        self.trashed: list[str] = []

    def get_profile(self) -> dict:
        return self.profile

    def list_history(self, start: int, page_token: str | None = None) -> dict:
        self.history_calls.append((start, page_token))
        if self.history_error:
            raise self.history_error
        index = int(page_token) if page_token else 0
        return self.pages[index]

    def get_raw_message(self, message_id: str) -> dict:
        self.fetched.append(message_id)
        if message_id not in self.messages:
            raise GmailApiError(404, "Gmail: not found")
        return self.messages[message_id]

    def modify_labels(self, message_id: str, add=None, remove=None) -> None:  # noqa: ANN001
        self.modified.append((message_id, add, remove))

    def trash_message(self, message_id: str) -> None:
        self.trashed.append(message_id)


def _message(message_id: str, labels: list[str], **raw: str) -> dict:
    return {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "labelIds": labels,
        "snippet": f"snippet {message_id}",
        "raw": _raw(**raw),
    }


def _config(**data: object):  # noqa: ANN202
    return parse_gmail_config({"credentialId": "cred", **data})


class ReadNewMailTests(unittest.TestCase):
    def test_first_poll_records_a_baseline_and_reads_no_history(self) -> None:
        gmail = _FakeGmail(history_id=900)
        read = read_new_mail(gmail, _config(), None)

        self.assertTrue(read.baseline)
        self.assertEqual(read.cursor, GmailCursor(SCOPE, 900))
        self.assertEqual(read.emails, [])
        self.assertEqual(gmail.history_calls, [])

    def test_another_account_behind_the_credential_starts_over(self) -> None:
        gmail = _FakeGmail(history_id=900, email="other@gmail.com")
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertTrue(read.baseline)
        self.assertEqual(read.cursor, GmailCursor(account_scope("other@gmail.com"), 900))
        self.assertEqual(gmail.history_calls, [])

    def test_history_gmail_no_longer_keeps_starts_over(self) -> None:
        gmail = _FakeGmail(history_id=900)
        gmail.history_error = GmailApiError(404, "Gmail: not found")
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertTrue(read.baseline)
        self.assertEqual(read.cursor.history_id, 900)

    def test_other_history_errors_raise(self) -> None:
        gmail = _FakeGmail()
        gmail.history_error = GmailApiError(429, "Gmail: rate limit")
        with self.assertRaises(GmailApiError):
            read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

    def test_new_inbox_mail_is_read_in_history_order_with_gmail_fields(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [
                        _added(120, "m2", ["INBOX", "UNREAD"]),
                        _added(110, "m1", ["INBOX", "UNREAD", "CATEGORY_PERSONAL"]),
                    ],
                    "historyId": "130",
                }
            ],
            messages={
                "m1": _message("m1", ["INBOX", "UNREAD"], subject="First"),
                "m2": _message("m2", ["INBOX", "UNREAD"], subject="Second"),
            },
        )
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertFalse(read.baseline)
        self.assertEqual(read.cursor, GmailCursor(SCOPE, 130))
        self.assertEqual([email.history_id for email in read.emails], [110, 120])
        first = read.emails[0].payload
        self.assertEqual(first["id"], "m1")
        self.assertEqual(first["threadId"], "t-m1")
        self.assertEqual(first["labelIds"], ["INBOX", "UNREAD"])
        self.assertEqual(first["snippet"], "snippet m1")
        self.assertEqual(first["subject"], "First")
        self.assertEqual(first["fromAddresses"], [{"name": "Ada", "email": "ada@example.com"}])
        self.assertEqual(first["text"], "Body of First")
        self.assertNotIn("uid", first)
        self.assertEqual(gmail.history_calls, [(100, None)])

    def test_records_at_or_below_the_cursor_are_ignored(self) -> None:
        gmail = _FakeGmail(
            pages=[{"history": [_added(100, "old", ["INBOX"])], "historyId": "105"}],
            messages={"old": _message("old", ["INBOX"])},
        )
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual(read.emails, [])
        self.assertEqual(gmail.fetched, [])
        self.assertEqual(read.cursor.history_id, 105)

    def test_mail_outside_the_mailbox_is_not_fetched(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [
                        _added(110, "promo", ["INBOX", "CATEGORY_PROMOTIONS"]),
                        _added(111, "draft", ["DRAFT"]),
                        _added(112, "personal", ["INBOX", "CATEGORY_PERSONAL"]),
                    ],
                    "historyId": "120",
                }
            ],
            messages={"personal": _message("personal", ["INBOX", "CATEGORY_PERSONAL"])},
        )
        read = read_new_mail(gmail, _config(gmailMailbox="primary"), GmailCursor(SCOPE, 100))

        self.assertEqual([email.payload["id"] for email in read.emails], ["personal"])
        self.assertEqual(gmail.fetched, ["personal"])

    def test_a_label_added_later_brings_the_message_in_once(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [
                        _labelled(110, "m1", ["Label_7"], ["Label_7", "INBOX"]),
                        _labelled(111, "m1", ["Label_7"], ["Label_7", "INBOX"]),
                        _labelled(112, "m2", ["STARRED"], ["STARRED", "Label_7"]),
                    ],
                    "historyId": "120",
                }
            ],
            messages={"m1": _message("m1", ["Label_7", "INBOX"])},
        )
        config = _config(gmailMailbox="label", gmailLabelId="Label_7")
        read = read_new_mail(gmail, config, GmailCursor(SCOPE, 100))

        self.assertEqual([email.payload["id"] for email in read.emails], ["m1"])
        self.assertEqual(gmail.fetched, ["m1"])

    def test_a_message_added_and_moved_in_the_same_window_runs_once(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [
                        _added(110, "m1", ["INBOX"]),
                        _labelled(115, "m1", ["INBOX"], ["INBOX"]),
                    ],
                    "historyId": "120",
                }
            ],
            messages={"m1": _message("m1", ["INBOX"])},
        )
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual(
            [(email.history_id, email.payload["id"]) for email in read.emails], [(110, "m1")]
        )

    def test_labels_missing_from_history_are_checked_after_the_fetch(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [_added(110, "in", None), _added(111, "out", None)],
                    "historyId": "120",
                }
            ],
            messages={
                "in": _message("in", ["INBOX"]),
                "out": _message("out", ["SENT"]),
            },
        )
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual([email.payload["id"] for email in read.emails], ["in"])
        self.assertEqual(gmail.fetched, ["in", "out"])

    def test_aliases_filter_after_the_fetch(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [_added(110, "sales", ["INBOX"]), _added(111, "other", ["INBOX"])],
                    "historyId": "120",
                }
            ],
            messages={
                "sales": _message("sales", ["INBOX"], to="sales@example.com"),
                "other": _message("other", ["INBOX"], to="me@gmail.com"),
            },
        )
        read = read_new_mail(
            gmail, _config(gmailAliases=["Sales@example.com"]), GmailCursor(SCOPE, 100)
        )

        self.assertEqual([email.payload["id"] for email in read.emails], ["sales"])
        self.assertEqual(read.cursor.history_id, 120)

    def test_a_message_deleted_before_the_poll_is_skipped(self) -> None:
        gmail = _FakeGmail(
            pages=[{"history": [_added(110, "gone", ["INBOX"])], "historyId": "120"}]
        )
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual(read.emails, [])
        self.assertEqual(read.cursor.history_id, 120)

    def test_history_pages_are_followed(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {"history": [_added(110, "m1", ["INBOX"])], "nextPageToken": "1"},
                {"history": [_added(130, "m2", ["INBOX"])], "historyId": "140"},
            ],
            messages={"m1": _message("m1", ["INBOX"]), "m2": _message("m2", ["INBOX"])},
        )
        read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual([email.payload["id"] for email in read.emails], ["m1", "m2"])
        self.assertEqual(gmail.history_calls, [(100, None), (100, "1")])
        self.assertEqual(read.cursor.history_id, 140)

    def test_too_many_pages_hand_over_after_the_last_record_read(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {"history": [_added(110, "m1", ["INBOX"])], "nextPageToken": "1"},
                {"history": [_added(130, "m2", ["INBOX"])], "nextPageToken": "2"},
            ],
            messages={"m1": _message("m1", ["INBOX"]), "m2": _message("m2", ["INBOX"])},
        )
        with patch.object(reader, "MAX_HISTORY_PAGES", 2):
            read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual(read.cursor.history_id, 130)
        self.assertEqual(len(read.emails), 2)

    def test_a_large_batch_stops_between_history_records(self) -> None:
        gmail = _FakeGmail(
            pages=[
                {
                    "history": [
                        _added(110, "m1", ["INBOX"]),
                        {
                            "id": "120",
                            "messagesAdded": [
                                {"message": {"id": "m2", "labelIds": ["INBOX"]}},
                                {"message": {"id": "m3", "labelIds": ["INBOX"]}},
                            ],
                        },
                        _added(130, "m4", ["INBOX"]),
                    ],
                    "historyId": "140",
                }
            ],
            messages={name: _message(name, ["INBOX"]) for name in ("m1", "m2", "m3", "m4")},
        )
        with patch.object(reader, "MAX_MESSAGES_PER_POLL", 2):
            read = read_new_mail(gmail, _config(), GmailCursor(SCOPE, 100))

        self.assertEqual([email.payload["id"] for email in read.emails], ["m1", "m2", "m3"])
        self.assertEqual(read.cursor.history_id, 120)
        self.assertNotIn("m4", gmail.fetched)


class AfterActionTests(unittest.TestCase):
    def test_each_action(self) -> None:
        cases = {
            "markRead": [("m1", None, ["UNREAD"])],
            "archive": [("m1", None, ["INBOX"])],
            "markReadAndArchive": [("m1", None, ["UNREAD", "INBOX"])],
        }
        for action, expected in cases.items():
            with self.subTest(action=action):
                gmail = _FakeGmail()
                apply_after_action(gmail, "m1", action)
                self.assertEqual(gmail.modified, expected)
                self.assertEqual(gmail.trashed, [])

    def test_trash_moves_to_trash_and_never_deletes(self) -> None:
        gmail = _FakeGmail()
        apply_after_action(gmail, "m1", "trash")
        self.assertEqual(gmail.trashed, ["m1"])
        self.assertEqual(gmail.modified, [])

    def test_none_and_unknown_actions_do_nothing(self) -> None:
        for action in ("none", "delete"):
            gmail = _FakeGmail()
            apply_after_action(gmail, "m1", action)
            self.assertEqual((gmail.modified, gmail.trashed), ([], []))


class RawMessageTests(unittest.TestCase):
    def test_unpadded_base64url_decodes(self) -> None:
        raw = _raw(subject="Padding?")
        self.assertIn(b"Subject: Padding?", decode_raw_message(raw))


if __name__ == "__main__":
    unittest.main()
