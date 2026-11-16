"""Which Gmail messages belong to a trigger's mailbox, and which reach its aliases."""

from __future__ import annotations

from collections.abc import Iterable
from email import message_from_bytes, policy
from email.utils import getaddresses

from app.services.gmail_trigger.config import CATEGORY_LABELS, GmailTriggerConfig

# Mail in these never starts a run, whatever the mailbox.
_NEVER_FIRES = frozenset({"DRAFT", "SPAM", "TRASH", "CHAT"})
_OTHER_TABS = frozenset(CATEGORY_LABELS.values())
_SYSTEM_MAILBOX_LABELS = {"important": "IMPORTANT", "starred": "STARRED", "sent": "SENT"}
# Gmail delivers these domains to one mailbox whatever dots the local part has.
_DOTLESS_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
_RECIPIENT_HEADERS = ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To")


def in_mailbox(config: GmailTriggerConfig, labels: Iterable[str]) -> bool:
    """Whether a message with these labels is in the mailbox the trigger watches."""
    label_set = set(labels)
    if label_set & _NEVER_FIRES:
        return False
    mailbox = config.mailbox
    if mailbox == "inbox":
        return "INBOX" in label_set
    if mailbox == "primary":
        return "INBOX" in label_set and not label_set & _OTHER_TABS
    if mailbox in CATEGORY_LABELS:
        return "INBOX" in label_set and CATEGORY_LABELS[mailbox] in label_set
    if mailbox in _SYSTEM_MAILBOX_LABELS:
        return _SYSTEM_MAILBOX_LABELS[mailbox] in label_set
    if mailbox == "label":
        return bool(config.label_id) and config.label_id in label_set
    # All mail: everything received, archived included, but not the account's own sent mail.
    return "INBOX" in label_set or "SENT" not in label_set


def entry_labels(config: GmailTriggerConfig) -> frozenset[str]:
    """Labels whose later addition brings a message into the mailbox."""
    mailbox = config.mailbox
    if mailbox == "inbox":
        return frozenset({"INBOX"})
    if mailbox == "primary":
        return frozenset({"INBOX", "CATEGORY_PERSONAL"})
    if mailbox in CATEGORY_LABELS:
        return frozenset({"INBOX", CATEGORY_LABELS[mailbox]})
    if mailbox in _SYSTEM_MAILBOX_LABELS:
        return frozenset({_SYSTEM_MAILBOX_LABELS[mailbox]})
    if mailbox == "label" and config.label_id:
        return frozenset({config.label_id})
    return frozenset()


def normalize_address(address: str) -> str:
    """Lowercase, and without the dots Gmail ignores in gmail.com local parts."""
    value = str(address or "").strip().lower()
    local, sep, domain = value.rpartition("@")
    if not sep:
        return value
    if domain in _DOTLESS_DOMAINS:
        name, plus, tag = local.partition("+")
        local = name.replace(".", "") + plus + tag
    return f"{local}@{domain}"


def recipient_addresses(raw_bytes: bytes) -> set[str]:
    """Every address the email was sent or delivered to, normalized."""
    message = message_from_bytes(raw_bytes, policy=policy.compat32)
    values: list[str] = []
    for header in _RECIPIENT_HEADERS:
        values.extend(str(value) for value in message.get_all(header, []))
    return {normalize_address(email) for _name, email in getaddresses(values) if "@" in email}


def reaches_aliases(config: GmailTriggerConfig, raw_bytes: bytes) -> bool:
    """True with no aliases set, else when one of them is among the email's recipients."""
    if not config.aliases:
        return True
    wanted = {normalize_address(alias) for alias in config.aliases}
    return bool(wanted & recipient_addresses(raw_bytes))
