"""Gmail Trigger node settings, read from a node's data by the poller.

These fields hold plain values rather than `$` expressions: the poller reads them, never
the executor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

GMAIL_TRIGGER = "gmailTrigger"
DEFAULT_POLL_MINUTES = 1

CATEGORY_LABELS: dict[str, str] = {
    "social": "CATEGORY_SOCIAL",
    "promotions": "CATEGORY_PROMOTIONS",
    "updates": "CATEGORY_UPDATES",
    "forums": "CATEGORY_FORUMS",
}
MAILBOXES: tuple[str, ...] = (
    "inbox",
    "primary",
    *CATEGORY_LABELS,
    "important",
    "starred",
    "sent",
    "all",
    "label",
)
AFTER_ACTIONS: tuple[str, ...] = ("none", "markRead", "archive", "markReadAndArchive", "trash")


def _parse_aliases(raw: Any) -> tuple[str, ...]:
    """Addresses as typed, lowercased and deduplicated; a list or comma/space separated text."""
    if isinstance(raw, str):
        items: list[Any] = re.split(r"[,;\s]+", raw)
    elif isinstance(raw, list):
        items = raw
    else:
        return ()
    aliases: list[str] = []
    for item in items:
        value = str(item or "").strip().lower()
        if "@" in value and value not in aliases:
            aliases.append(value)
    return tuple(aliases)


def _parse_poll_minutes(raw: Any) -> int:
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_POLL_MINUTES


@dataclass(frozen=True)
class GmailTriggerConfig:
    """What one Gmail Trigger node watches and does with each email."""

    credential_id: str
    mailbox: str
    label_id: str
    aliases: tuple[str, ...]
    after_action: str
    poll_minutes: int

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        if not self.credential_id:
            return "no credential selected"
        if self.mailbox == "label" and not self.label_id:
            return "no label selected"
        return None


def parse_gmail_config(data: dict[str, Any]) -> GmailTriggerConfig:
    """Read a gmailTrigger node's data; unknown values fall back to the defaults."""
    mailbox = str(data.get("gmailMailbox") or "inbox")
    after_action = str(data.get("gmailAfterAction") or "none")
    return GmailTriggerConfig(
        credential_id=str(data.get("credentialId") or "").strip(),
        mailbox=mailbox if mailbox in MAILBOXES else "inbox",
        label_id=str(data.get("gmailLabelId") or "").strip() if mailbox == "label" else "",
        aliases=_parse_aliases(data.get("gmailAliases")),
        after_action=after_action if after_action in AFTER_ACTIONS else "none",
        poll_minutes=_parse_poll_minutes(data.get("pollIntervalMinutes")),
    )
