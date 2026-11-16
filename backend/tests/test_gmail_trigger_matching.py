"""Gmail Trigger settings, mailbox rules and alias matching."""

import unittest
from email.message import EmailMessage

from app.services.gmail_trigger.config import parse_gmail_config
from app.services.gmail_trigger.matching import (
    entry_labels,
    in_mailbox,
    normalize_address,
    reaches_aliases,
    recipient_addresses,
)


def _config(**data: object):  # noqa: ANN202
    return parse_gmail_config({"credentialId": "cred", **data})


def _raw(**headers: str | list[str]) -> bytes:
    message = EmailMessage()
    message["Subject"] = "Hello"
    message["From"] = "sender@example.com"
    for name, value in headers.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            message[name.replace("_", "-")] = item
    message.set_content("Body")
    return message.as_bytes()


class GmailTriggerConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = parse_gmail_config({"credentialId": " cred "})

        self.assertEqual(config.credential_id, "cred")
        self.assertEqual(config.mailbox, "inbox")
        self.assertEqual(config.label_id, "")
        self.assertEqual(config.aliases, ())
        self.assertEqual(config.after_action, "none")
        self.assertEqual(config.poll_minutes, 1)
        self.assertIsNone(config.problem())

    def test_unknown_values_fall_back_to_the_defaults(self) -> None:
        config = _config(
            gmailMailbox="spam", gmailAfterAction="deleteForever", pollIntervalMinutes="x"
        )

        self.assertEqual(config.mailbox, "inbox")
        self.assertEqual(config.after_action, "none")
        self.assertEqual(config.poll_minutes, 1)

    def test_poll_interval_is_never_below_one_minute(self) -> None:
        self.assertEqual(_config(pollIntervalMinutes=0).poll_minutes, 1)
        self.assertEqual(_config(pollIntervalMinutes="15").poll_minutes, 15)

    def test_a_label_mailbox_needs_a_label(self) -> None:
        self.assertEqual(_config(gmailMailbox="label").problem(), "no label selected")
        config = _config(gmailMailbox="label", gmailLabelId="Label_7")
        self.assertIsNone(config.problem())
        self.assertEqual(config.label_id, "Label_7")

    def test_the_label_is_ignored_for_other_mailboxes(self) -> None:
        self.assertEqual(_config(gmailMailbox="inbox", gmailLabelId="Label_7").label_id, "")

    def test_no_credential_is_a_problem(self) -> None:
        self.assertEqual(parse_gmail_config({}).problem(), "no credential selected")

    def test_aliases_from_a_list_or_text_are_lowercased_and_deduplicated(self) -> None:
        self.assertEqual(
            _config(
                gmailAliases=["Sales@Example.com", "sales@example.com", "", "not-an-email"]
            ).aliases,
            ("sales@example.com",),
        )
        self.assertEqual(
            _config(gmailAliases="a@x.com, b@x.com;c@x.com\nA@X.com").aliases,
            ("a@x.com", "b@x.com", "c@x.com"),
        )
        self.assertEqual(_config(gmailAliases=None).aliases, ())


class GmailMailboxTests(unittest.TestCase):
    def test_inbox(self) -> None:
        config = _config(gmailMailbox="inbox")
        self.assertTrue(in_mailbox(config, ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"]))
        self.assertFalse(in_mailbox(config, ["CATEGORY_PERSONAL"]))

    def test_primary_is_inbox_mail_outside_the_other_tabs(self) -> None:
        config = _config(gmailMailbox="primary")
        self.assertTrue(in_mailbox(config, ["INBOX", "CATEGORY_PERSONAL"]))
        self.assertTrue(in_mailbox(config, ["INBOX"]))
        for tab in (
            "CATEGORY_SOCIAL",
            "CATEGORY_PROMOTIONS",
            "CATEGORY_UPDATES",
            "CATEGORY_FORUMS",
        ):
            with self.subTest(tab=tab):
                self.assertFalse(in_mailbox(config, ["INBOX", tab]))
        self.assertFalse(in_mailbox(config, ["CATEGORY_PERSONAL"]))

    def test_category_tabs_hold_inbox_mail_of_that_category(self) -> None:
        config = _config(gmailMailbox="promotions")
        self.assertTrue(in_mailbox(config, ["INBOX", "CATEGORY_PROMOTIONS"]))
        self.assertFalse(in_mailbox(config, ["CATEGORY_PROMOTIONS"]))
        self.assertFalse(in_mailbox(config, ["INBOX", "CATEGORY_SOCIAL"]))

    def test_system_mailboxes(self) -> None:
        self.assertTrue(in_mailbox(_config(gmailMailbox="important"), ["IMPORTANT"]))
        self.assertTrue(in_mailbox(_config(gmailMailbox="starred"), ["STARRED"]))
        self.assertTrue(in_mailbox(_config(gmailMailbox="sent"), ["SENT"]))
        self.assertFalse(in_mailbox(_config(gmailMailbox="sent"), ["INBOX"]))

    def test_a_custom_label(self) -> None:
        config = _config(gmailMailbox="label", gmailLabelId="Label_7")
        self.assertTrue(in_mailbox(config, ["Label_7"]))
        self.assertFalse(in_mailbox(config, ["Label_8", "INBOX"]))

    def test_all_mail_is_received_mail_including_archived_but_not_own_sent_mail(self) -> None:
        config = _config(gmailMailbox="all")
        self.assertTrue(in_mailbox(config, ["INBOX"]))
        self.assertTrue(in_mailbox(config, ["Label_7"]))
        self.assertTrue(in_mailbox(config, ["SENT", "INBOX"]))
        self.assertFalse(in_mailbox(config, ["SENT"]))

    def test_drafts_spam_and_trash_never_fire(self) -> None:
        for label in ("DRAFT", "SPAM", "TRASH"):
            for mailbox in ("inbox", "all", "sent"):
                with self.subTest(label=label, mailbox=mailbox):
                    self.assertFalse(
                        in_mailbox(_config(gmailMailbox=mailbox), ["INBOX", "SENT", label])
                    )

    def test_entry_labels(self) -> None:
        self.assertEqual(entry_labels(_config()), {"INBOX"})
        self.assertEqual(
            entry_labels(_config(gmailMailbox="primary")), {"INBOX", "CATEGORY_PERSONAL"}
        )
        self.assertEqual(entry_labels(_config(gmailMailbox="social")), {"INBOX", "CATEGORY_SOCIAL"})
        self.assertEqual(entry_labels(_config(gmailMailbox="starred")), {"STARRED"})
        self.assertEqual(
            entry_labels(_config(gmailMailbox="label", gmailLabelId="Label_7")), {"Label_7"}
        )
        self.assertEqual(entry_labels(_config(gmailMailbox="all")), set())


class GmailAliasTests(unittest.TestCase):
    def test_gmail_ignores_dots_but_keeps_the_plus_tag(self) -> None:
        self.assertEqual(
            normalize_address("Jane.Doe+Invoices@GMail.com"), "janedoe+invoices@gmail.com"
        )
        self.assertEqual(normalize_address("j.doe@googlemail.com"), "jdoe@googlemail.com")
        self.assertEqual(normalize_address("Jane.Doe@Example.com"), "jane.doe@example.com")

    def test_recipients_come_from_every_delivery_header(self) -> None:
        raw = _raw(
            To="Team <team@example.com>",
            Cc="cc@example.com",
            Delivered_To=["me@gmail.com", "sales@example.com"],
            X_Original_To="orig@example.com",
        )
        self.assertEqual(
            recipient_addresses(raw),
            {
                "team@example.com",
                "cc@example.com",
                "me@gmail.com",
                "sales@example.com",
                "orig@example.com",
            },
        )

    def test_no_aliases_lets_every_email_through(self) -> None:
        self.assertTrue(reaches_aliases(_config(), _raw(To="anyone@example.com")))

    def test_an_alias_matches_any_recipient_header(self) -> None:
        config = _config(gmailAliases=["sales@example.com"])
        self.assertTrue(reaches_aliases(config, _raw(To="Sales <SALES@example.com>")))
        self.assertTrue(reaches_aliases(config, _raw(To="x@y.com", Cc="sales@example.com")))
        self.assertTrue(
            reaches_aliases(config, _raw(To="x@y.com", Delivered_To="sales@example.com"))
        )
        self.assertFalse(reaches_aliases(config, _raw(To="support@example.com")))

    def test_a_plus_address_matches_only_itself(self) -> None:
        config = _config(gmailAliases=["jane.doe+invoices@gmail.com"])
        self.assertTrue(reaches_aliases(config, _raw(To="janedoe+invoices@gmail.com")))
        self.assertFalse(reaches_aliases(config, _raw(To="janedoe@gmail.com")))
        self.assertFalse(
            reaches_aliases(
                _config(gmailAliases=["janedoe@gmail.com"]), _raw(To="janedoe+invoices@gmail.com")
            )
        )


if __name__ == "__main__":
    unittest.main()
