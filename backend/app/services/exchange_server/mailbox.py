"""An Exchange Server mailbox for the Outlook Trigger and its pickers, over EWS.

Messages are summarized in the Graph shape the trigger's reader uses. EWS ids change when
a message moves between folders, so the snapshot keys on the Internet message id instead.
Exchange Server has no Focused Inbox.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from exchangelib import EWSDateTime, ExtendedProperty, Message
from exchangelib.folders import (
    Conflicts,
    ConversationHistory,
    FolderCollection,
    LocalFailures,
    ServerFailures,
    SyncIssues,
)
from exchangelib.properties import FolderId, ItemId

from app.services.exchange_server.connection import (
    LABEL,
    ews_account,
    ews_errors,
    ews_settings,
    raise_failed,
    to_utc,
)
from app.services.outlook_service import OutlookApiError
from app.services.outlook_trigger.config import OutlookTriggerConfig

# Outlook's follow-up flag (PidTagFlagStatus): 1 complete, 2 flagged.
FLAG_FLAGGED = 2
_FLAG_STATUS = {1: "complete", 2: "flagged"}
_SUMMARY_FIELDS = (
    "datetime_received",
    "message_id",
    "conversation_id",
    "parent_folder_id",
    "categories",
    "importance",
    "is_read",
    "web_client_read_form_query_string",
    "heym_flag_status",
)
# The one-click Archive folder has no well-known EWS name; Outlook names it per language.
ARCHIVE_NAMES = frozenset(
    {"archive", "arşiv", "archiv", "archives", "archivio", "archivo", "arquivo", "archief"}
)
_NOT_MAIL = (SyncIssues, Conflicts, LocalFailures, ServerFailures, ConversationHistory)
MAX_FOLDERS = 500


class FlagStatus(ExtendedProperty):
    """MAPI PidTagFlagStatus; exchangelib has no field for Outlook's follow-up flag."""

    property_tag = 0x1090
    property_type = "Integer"


if "heym_flag_status" not in {field.name for field in Message.FIELDS}:
    Message.register("heym_flag_status", FlagStatus)


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    return to_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id_of(value: Any) -> str:
    return str(getattr(value, "id", value) or "") if value else ""


def summary(item: Any) -> dict[str, Any]:
    """One EWS message in the Graph summary shape the reader works on."""
    message_id = str(item.id or "")
    flag = _FLAG_STATUS.get(getattr(item, "heym_flag_status", None) or 0, "notFlagged")
    return {
        "id": message_id,
        "snapshotKey": str(item.message_id or "") or message_id,
        "receivedDateTime": _iso(item.datetime_received),
        "conversationId": _id_of(item.conversation_id),
        "parentFolderId": _id_of(item.parent_folder_id),
        "categories": [str(category) for category in item.categories or []],
        "importance": str(item.importance or "").lower(),
        "inferenceClassification": "",
        "flag": {"flagStatus": flag},
        "isRead": item.is_read is True,
        "webLink": str(item.web_client_read_form_query_string or ""),
        "bodyPreview": "",
    }


def _under(folder: Any, folder_ids: set[str]) -> bool:
    """Whether the folder is one of ``folder_ids`` or sits below one of them."""
    current, depth = folder, 0
    while current is not None and depth < 32:
        if getattr(current, "id", None) in folder_ids:
            return True
        current, depth = getattr(current, "parent", None), depth + 1
    return False


class EwsMailbox:
    """The credential's own Exchange Server mailbox."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._account: Any = None

    @property
    def account(self) -> Any:
        if self._account is None:
            with ews_errors():
                self._account = ews_account(self._config)
        return self._account

    def account_address(self) -> str:
        return ews_settings(self._config).email

    def _excluded_ids(self) -> set[str]:
        account = self.account
        folders = (account.sent, account.drafts, account.trash, account.junk, account.outbox)
        return {folder.id for folder in folders if folder is not None and folder.id}

    def mail_folders(self) -> list[Any]:
        """Every mail folder under the message root, the not-received ones included."""
        return [
            folder
            for folder in self.account.msg_folder_root.walk()
            if not isinstance(folder, _NOT_MAIL)
            and str(folder.folder_class or "IPF.Note").startswith("IPF.Note")
        ]

    def _source_folders(self, config: OutlookTriggerConfig) -> list[Any]:
        account = self.account
        mailbox = config.mailbox
        if mailbox in ("focused", "other"):
            raise OutlookApiError(
                400, f"{LABEL}: Focused and Other need a Microsoft 365 or Outlook.com account"
            )
        if mailbox == "sent":
            return [account.sent]
        if mailbox == "folder":
            folder = account.root.get_folder(FolderId(id=config.folder_id))
            if folder is None:
                raise OutlookApiError(404, f"{LABEL}: the watched folder no longer exists")
            return [folder]
        if mailbox in ("all", "important"):
            excluded = self._excluded_ids()
            return [folder for folder in self.mail_folders() if not _under(folder, excluded)]
        return [account.inbox]

    def _query(self, config: OutlookTriggerConfig, **filters: Any) -> Any:
        if config.mailbox == "important":
            filters["importance"] = "High"
        folders = FolderCollection(account=self.account, folders=self._source_folders(config))
        return folders.filter(**filters).only(*_SUMMARY_FIELDS)

    def _listing(self, query: Any, limit: int) -> tuple[list[dict[str, Any]], bool]:
        with ews_errors():
            items = [raise_failed(item) for item in query[: limit + 1]]
        return [summary(item) for item in items[:limit]], len(items) <= limit

    def received_since(
        self, config: OutlookTriggerConfig, since: datetime, limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        with ews_errors():
            start = EWSDateTime.from_datetime(since.astimezone(timezone.utc))
            query = self._query(config, datetime_received__gte=start).order_by("datetime_received")
        return self._listing(query, limit)

    def flagged(
        self, config: OutlookTriggerConfig, limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        with ews_errors():
            query = self._query(config, heym_flag_status=FLAG_FLAGGED)
        return self._listing(query, limit)

    def _item(self, message_id: str, *fields: str) -> Any:
        with ews_errors():
            found = list(self.account.fetch(ids=[ItemId(id=message_id)], only_fields=fields))
            return raise_failed(found[0]) if found else None

    def get_mime(self, message_id: str) -> bytes:
        item = self._item(message_id, "mime_content")
        if item is None:
            raise OutlookApiError(404, f"{LABEL}: not found")
        content = item.mime_content or b""
        return content.encode("utf-8") if isinstance(content, str) else bytes(content)

    def mark_read(self, message_id: str) -> None:
        item = self._item(message_id, "is_read")
        with ews_errors():
            item.is_read = True
            item.save(update_fields=["is_read"])

    def _archive_folder(self) -> Any:
        for folder in self.account.msg_folder_root.children:
            if str(folder.name or "").strip().lower() in ARCHIVE_NAMES:
                return folder
        raise OutlookApiError(404, f"{LABEL}: this mailbox has no Archive folder")

    def move(self, message_id: str, destination: str) -> None:
        item = self._item(message_id, "parent_folder_id")
        with ews_errors():
            if destination == "deleteditems":
                item.move_to_trash()
            elif destination == "archive":
                item.move(self._archive_folder())
            else:
                raise OutlookApiError(400, f"{LABEL}: unknown destination")

    def list_folders(self) -> list[dict[str, Any]]:
        """Every mail folder as ``{"id", "path"}``, nested ones as ``Parent / Child``."""
        with ews_errors():
            root = self.account.msg_folder_root
            prefix = f"{root.absolute}/"
            folders = []
            for folder in self.mail_folders()[:MAX_FOLDERS]:
                path = str(folder.absolute or folder.name or "")
                path = path[len(prefix) :] if path.startswith(prefix) else str(folder.name or "")
                folders.append({"id": str(folder.id), "path": path.replace("/", " / ")})
        return sorted(folders, key=lambda folder: folder["path"].lower())

    def addresses(self) -> list[str]:
        """The mailbox's own address; Exchange Server keeps aliases in Active Directory."""
        return [self.account_address()]
