"""Reads what entered an Outlook Trigger's mailbox since the last poll.

Synchronous: the poller calls it in a worker thread, with a Microsoft Graph or Exchange
Server mailbox client (see mailbox.py). Neither has an account-wide change cursor like
Gmail's history id, so the trigger keeps a small snapshot in ``trigger_poll_items``:

- By default a message fires when it is received into the watched mailbox. The snapshot
  holds a received-time cursor plus the messages seen within a short look-back window, so
  mail that shows up in a folder a few minutes late still fires, and fires once.
- With ``flagged_only`` the snapshot holds the mailbox's flagged messages. A message fires
  when it is flagged or arrives flagged, and again when it is unflagged and flagged anew.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.google_triggers.events import ItemWrite
from app.services.imap_trigger_service import email_payload
from app.services.outlook_service import OutlookApiError
from app.services.outlook_trigger.config import OutlookTriggerConfig
from app.services.outlook_trigger.mailbox import MailboxClient
from app.services.outlook_trigger.matching import reaches_aliases

logger = logging.getLogger("outlook_trigger")

# Mail received up to this long before the cursor is listed again, in case it was late.
LOOKBACK = timedelta(minutes=10)
# Messages fetched per poll; the rest wait for the next one.
MAX_MESSAGES_PER_POLL = 50
MAX_LISTED = 500
MAX_FLAGGED = 1000
CURSOR_KEY = "cursor"
_MESSAGE_PREFIX = "m:"


@dataclass(frozen=True)
class OutlookEmail:
    """One email to run, with the snapshot write that takes it and the one that undoes it."""

    payload: dict[str, Any]
    write: ItemWrite
    revert: ItemWrite


@dataclass(frozen=True)
class OutlookRead:
    """What one poll found.

    ``silent`` is applied once every email here has run: mail that starts no run, pruning
    and the cursor. With ``baseline`` nothing runs and ``items`` replaces the snapshot: a
    first poll, another account behind the credential, or a changed mailbox.
    """

    scope: str
    emails: list[OutlookEmail] = field(default_factory=list)
    silent: list[ItemWrite] = field(default_factory=list)
    baseline: bool = False
    items: dict[str, dict[str, Any]] = field(default_factory=dict)


def message_key(message_id: str) -> str:
    """Snapshot key of one message; Graph ids are long, so a digest is stored."""
    return _MESSAGE_PREFIX + hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:40]


def mailbox_scope(address: str, config: OutlookTriggerConfig) -> str:
    """Identity of what the snapshot describes; any change records a new baseline."""
    mode = "flagged" if config.flagged_only else "received"
    parts = (address.strip().lower(), config.mailbox, config.folder_id, mode)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _parse_time(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def outlook_payload(message: dict[str, Any], raw_bytes: bytes) -> dict[str, Any]:
    """What the run receives: the mail trigger fields plus Outlook's own."""
    flag = message.get("flag") if isinstance(message.get("flag"), dict) else {}
    return {
        "id": str(message.get("id") or ""),
        "conversationId": str(message.get("conversationId") or ""),
        "folderId": str(message.get("parentFolderId") or ""),
        "categories": [str(item) for item in message.get("categories") or []],
        "importance": str(message.get("importance") or ""),
        "inferenceClassification": str(message.get("inferenceClassification") or ""),
        "flagged": flag.get("flagStatus") == "flagged",
        "isRead": message.get("isRead") is True,
        "webLink": str(message.get("webLink") or ""),
        "snippet": str(message.get("bodyPreview") or ""),
        **email_payload(raw_bytes),
    }


def _identity(message: dict[str, Any]) -> tuple[str, datetime] | None:
    """The snapshot key and received time of a summary, or None when either is missing."""
    message_id = str(message.get("id") or "")
    received = _parse_time(message.get("receivedDateTime"))
    if not message_id or received is None:
        return None
    return message_key(str(message.get("snapshotKey") or message_id)), received


def _fetch_email(
    client: MailboxClient, config: OutlookTriggerConfig, message: dict[str, Any]
) -> dict[str, Any] | None:
    """The run payload, or None when the email is gone or reaches none of the aliases."""
    try:
        raw_bytes = client.get_mime(str(message["id"]))
    except OutlookApiError as exc:
        if exc.status_code == 404:
            return None  # deleted or moved before this poll
        raise
    if not raw_bytes or not reaches_aliases(config, raw_bytes):
        return None
    return outlook_payload(message, raw_bytes)


def _take(
    client: MailboxClient,
    config: OutlookTriggerConfig,
    message: dict[str, Any],
    key: str,
    item: dict[str, Any],
    read: OutlookRead,
) -> None:
    payload = _fetch_email(client, config, message)
    if payload is None:
        read.silent.append(ItemWrite(key, item))
    else:
        read.emails.append(OutlookEmail(payload, ItemWrite(key, item), ItemWrite(key, None)))


def _baseline(client: MailboxClient, config: OutlookTriggerConfig, scope: str) -> OutlookRead:
    """The snapshot of the mailbox as it is now; nothing in it ever starts a run."""
    items: dict[str, dict[str, Any]] = {}
    if config.flagged_only:
        listed, _complete = client.flagged(config, MAX_FLAGGED)
    else:
        now = datetime.now(timezone.utc)
        listed, _complete = client.received_since(config, now - LOOKBACK, MAX_LISTED)
        newest = max((found[1] for found in map(_identity, listed) if found), default=now)
        items[CURSOR_KEY] = {"since": max(now, newest).isoformat()}
    for message in listed:
        found = _identity(message)
        if found:
            items[found[0]] = {"r": found[1].isoformat()}
    return OutlookRead(scope, baseline=True, items=items)


def _read_received(
    client: MailboxClient,
    config: OutlookTriggerConfig,
    scope: str,
    stored: dict[str, dict[str, Any]],
    cursor: datetime,
) -> OutlookRead:
    listed, _complete = client.received_since(config, cursor - LOOKBACK, MAX_LISTED)
    read = OutlookRead(scope)
    reached = cursor
    for message in listed:
        found = _identity(message)
        if found is None:
            continue
        key, received = found
        if key in stored:
            reached = max(reached, received)
            continue
        if len(read.emails) >= MAX_MESSAGES_PER_POLL:
            break  # listed oldest first, so the rest are newer than ``reached``
        _take(client, config, message, key, {"r": received.isoformat()}, read)
        reached = max(reached, received)

    if reached > cursor:
        read.silent.append(ItemWrite(CURSOR_KEY, {"since": reached.isoformat()}))
    keep_after = reached - LOOKBACK
    for key, item in stored.items():
        if not key.startswith(_MESSAGE_PREFIX):
            continue
        seen_at = _parse_time(item.get("r"))
        if seen_at is None or seen_at < keep_after:
            read.silent.append(ItemWrite(key, None))
    return read


def _read_flagged(
    client: MailboxClient,
    config: OutlookTriggerConfig,
    scope: str,
    stored: dict[str, dict[str, Any]],
) -> OutlookRead:
    listed, complete = client.flagged(config, MAX_FLAGGED)
    current: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for message in listed:
        found = _identity(message)
        if found:
            current[found[0]] = (found[1], message)

    read = OutlookRead(scope)
    new_keys = sorted(
        (key for key in current if key not in stored), key=lambda key: current[key][0]
    )
    for key in new_keys[:MAX_MESSAGES_PER_POLL]:
        received, message = current[key]
        _take(client, config, message, key, {"r": received.isoformat()}, read)
    if complete:
        # Unflagged (or gone) since the last poll: flagging it again fires again.
        for key in stored:
            if key.startswith(_MESSAGE_PREFIX) and key not in current:
                read.silent.append(ItemWrite(key, None))
    return read


def read_new_mail(
    client: MailboxClient,
    config: OutlookTriggerConfig,
    stored_scope: str | None,
    stored: dict[str, dict[str, Any]] | None,
) -> OutlookRead:
    """Emails that entered the watched mailbox since the snapshot and reach the aliases."""
    scope = mailbox_scope(client.account_address(), config)
    if stored is None or stored_scope != scope:
        return _baseline(client, config, scope)
    if config.flagged_only:
        return _read_flagged(client, config, scope, stored)
    cursor = _parse_time((stored.get(CURSOR_KEY) or {}).get("since"))
    if cursor is None:
        return _baseline(client, config, scope)
    return _read_received(client, config, scope, stored, cursor)


def apply_after_action(client: MailboxClient, message_id: str, action: str) -> None:
    """Mark read, archive, or move to Deleted Items. ``none`` and unknown actions do nothing."""
    if action in ("markRead", "markReadAndArchive"):
        client.mark_read(message_id)
    if action in ("archive", "markReadAndArchive"):
        client.move(message_id, "archive")
    elif action == "delete":
        client.move(message_id, "deleteditems")
