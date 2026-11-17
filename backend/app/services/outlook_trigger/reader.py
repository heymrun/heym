"""Reads what entered an Outlook Trigger's mailbox since the last poll.

Synchronous: the poller calls it in a worker thread. Microsoft Graph has no account-wide
change cursor like Gmail's history id, so the trigger keeps a small snapshot in
``trigger_poll_items`` instead:

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
from app.services.outlook_service import OutlookApiError, OutlookService, account_address
from app.services.outlook_trigger.config import OutlookTriggerConfig
from app.services.outlook_trigger.matching import (
    NOT_RECEIVED_FOLDERS,
    MailSource,
    mail_source,
    reaches_aliases,
)

logger = logging.getLogger("outlook_trigger")

# Mail received up to this long before the cursor is listed again, in case it was late.
LOOKBACK = timedelta(minutes=10)
# Messages fetched per poll; the rest wait for the next one.
MAX_MESSAGES_PER_POLL = 50
MAX_LISTED = 500
MAX_FLAGGED = 1000
CURSOR_KEY = "cursor"
_MESSAGE_PREFIX = "m:"
SUMMARY_FIELDS = ",".join(
    (
        "id",
        "receivedDateTime",
        "conversationId",
        "parentFolderId",
        "categories",
        "importance",
        "inferenceClassification",
        "flag",
        "isRead",
        "webLink",
        "bodyPreview",
    )
)


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


def _graph_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _received_listing(
    service: OutlookService, source: MailSource, since: datetime, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    # Graph requires the $orderby property to come first in $filter.
    clauses = [f"receivedDateTime ge {_graph_time(since)}"]
    if source.filter:
        clauses.append(source.filter)
    params = {
        "$filter": " and ".join(clauses),
        "$orderby": "receivedDateTime asc",
        "$select": SUMMARY_FIELDS,
    }
    return service.list_messages(source.path, params, limit)


def _flagged_listing(
    service: OutlookService, source: MailSource
) -> tuple[list[dict[str, Any]], bool]:
    clauses = ["flag/flagStatus eq 'flagged'"]
    if source.filter:
        clauses.append(source.filter)
    params = {"$filter": " and ".join(clauses), "$select": SUMMARY_FIELDS}
    return service.list_messages(source.path, params, MAX_FLAGGED)


def _excluded_folders(service: OutlookService, source: MailSource) -> frozenset[str]:
    if not source.all_folders:
        return frozenset()
    found = (service.folder_id(name) for name in NOT_RECEIVED_FOLDERS)
    return frozenset(folder_id for folder_id in found if folder_id)


def _identity(message: dict[str, Any]) -> tuple[str, datetime] | None:
    message_id = str(message.get("id") or "")
    received = _parse_time(message.get("receivedDateTime"))
    if not message_id or received is None:
        return None
    return message_id, received


def _fetch_email(
    service: OutlookService, config: OutlookTriggerConfig, message: dict[str, Any]
) -> dict[str, Any] | None:
    """The run payload, or None when the email is gone or reaches none of the aliases."""
    try:
        raw_bytes = service.get_mime(str(message["id"]))
    except OutlookApiError as exc:
        if exc.status_code == 404:
            return None  # deleted or moved before this poll
        raise
    if not raw_bytes or not reaches_aliases(config, raw_bytes):
        return None
    return outlook_payload(message, raw_bytes)


def _take(
    service: OutlookService,
    config: OutlookTriggerConfig,
    message: dict[str, Any],
    key: str,
    item: dict[str, Any],
    read: OutlookRead,
) -> None:
    payload = _fetch_email(service, config, message)
    if payload is None:
        read.silent.append(ItemWrite(key, item))
    else:
        read.emails.append(OutlookEmail(payload, ItemWrite(key, item), ItemWrite(key, None)))


def _baseline(
    service: OutlookService, config: OutlookTriggerConfig, source: MailSource, scope: str
) -> OutlookRead:
    """The snapshot of the mailbox as it is now; nothing in it ever starts a run."""
    items: dict[str, dict[str, Any]] = {}
    if config.flagged_only:
        listed, _complete = _flagged_listing(service, source)
    else:
        now = datetime.now(timezone.utc)
        listed, _complete = _received_listing(service, source, now - LOOKBACK, MAX_LISTED)
        newest = max((found[1] for found in map(_identity, listed) if found), default=now)
        items[CURSOR_KEY] = {"since": max(now, newest).isoformat()}
    for message in listed:
        found = _identity(message)
        if found:
            items[message_key(found[0])] = {"r": found[1].isoformat()}
    return OutlookRead(scope, baseline=True, items=items)


def _read_received(
    service: OutlookService,
    config: OutlookTriggerConfig,
    source: MailSource,
    scope: str,
    stored: dict[str, dict[str, Any]],
    cursor: datetime,
) -> OutlookRead:
    listed, _complete = _received_listing(service, source, cursor - LOOKBACK, MAX_LISTED)
    excluded = _excluded_folders(service, source)
    read = OutlookRead(scope)
    reached = cursor
    for message in listed:
        found = _identity(message)
        if found is None:
            continue
        message_id, received = found
        key = message_key(message_id)
        if key in stored or str(message.get("parentFolderId") or "") in excluded:
            reached = max(reached, received)
            continue
        if len(read.emails) >= MAX_MESSAGES_PER_POLL:
            break  # listed oldest first, so the rest are newer than ``reached``
        _take(service, config, message, key, {"r": received.isoformat()}, read)
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
    service: OutlookService,
    config: OutlookTriggerConfig,
    source: MailSource,
    scope: str,
    stored: dict[str, dict[str, Any]],
) -> OutlookRead:
    listed, complete = _flagged_listing(service, source)
    excluded = _excluded_folders(service, source)
    current: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for message in listed:
        found = _identity(message)
        if found and str(message.get("parentFolderId") or "") not in excluded:
            current[message_key(found[0])] = (found[1], message)

    read = OutlookRead(scope)
    new_keys = sorted(
        (key for key in current if key not in stored), key=lambda key: current[key][0]
    )
    for key in new_keys[:MAX_MESSAGES_PER_POLL]:
        received, message = current[key]
        _take(service, config, message, key, {"r": received.isoformat()}, read)
    if complete:
        # Unflagged (or gone) since the last poll: flagging it again fires again.
        for key in stored:
            if key.startswith(_MESSAGE_PREFIX) and key not in current:
                read.silent.append(ItemWrite(key, None))
    return read


def read_new_mail(
    service: OutlookService,
    config: OutlookTriggerConfig,
    stored_scope: str | None,
    stored: dict[str, dict[str, Any]] | None,
) -> OutlookRead:
    """Emails that entered the watched mailbox since the snapshot and reach the aliases."""
    scope = mailbox_scope(account_address(service.get_profile()), config)
    source = mail_source(config)
    if stored is None or stored_scope != scope:
        return _baseline(service, config, source, scope)
    if config.flagged_only:
        return _read_flagged(service, config, source, scope, stored)
    cursor = _parse_time((stored.get(CURSOR_KEY) or {}).get("since"))
    if cursor is None:
        return _baseline(service, config, source, scope)
    return _read_received(service, config, source, scope, stored, cursor)


def apply_after_action(service: OutlookService, message_id: str, action: str) -> None:
    """Mark read, archive, or move to Deleted Items. ``none`` and unknown actions do nothing."""
    if action in ("markRead", "markReadAndArchive"):
        service.mark_read(message_id)
    if action in ("archive", "markReadAndArchive"):
        service.move(message_id, "archive")
    elif action == "delete":
        service.move(message_id, "deleteditems")
