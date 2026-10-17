"""Google trigger node settings, read from a node's data.

These fields are read by the poller, never by the executor, so they hold plain values
rather than `$` expressions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.services.google_drive_service import parse_drive_id
from app.services.google_sheets_service import GoogleSheetsService

DRIVE_TRIGGER = "googleDriveTrigger"
SHEETS_TRIGGER = "googleSheetsTrigger"
TRIGGER_EVENTS: tuple[str, ...] = ("created", "updated", "deleted")
DEFAULT_POLL_MINUTES = 1


def parse_poll_minutes(raw: Any) -> int:
    """Poll interval in whole minutes; missing or invalid means 1, and never below 1."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_POLL_MINUTES
    return max(1, value)


def parse_events(raw: Any, allowed: tuple[str, ...]) -> frozenset[str]:
    """Events that start a run. A missing value means all of them; unknown names are dropped."""
    if not isinstance(raw, list):
        return frozenset(allowed)
    return frozenset(str(item) for item in raw if str(item) in allowed)


def _fingerprint(parts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DriveTriggerConfig:
    """What one Google Drive Trigger node watches."""

    credential_id: str
    scope: str
    folder_id: str
    file_id: str
    events: frozenset[str]
    include_folders: bool
    poll_minutes: int

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        if not self.credential_id:
            return "no credential selected"
        if self.scope == "file" and not self.file_id:
            return "no file selected"
        return None

    def scope_fingerprint(self) -> str:
        """Changes when what is watched changes; events and interval are left out."""
        return _fingerprint(
            {
                "type": DRIVE_TRIGGER,
                "credential": self.credential_id,
                "scope": self.scope,
                "folder": self.folder_id,
                "file": self.file_id,
                "include_folders": self.include_folders,
            }
        )


def parse_drive_config(data: dict[str, Any]) -> DriveTriggerConfig:
    """Read a googleDriveTrigger node's data."""
    scope = "file" if data.get("gdtScope") == "file" else "folder"
    allowed = ("updated", "deleted") if scope == "file" else TRIGGER_EVENTS
    return DriveTriggerConfig(
        credential_id=str(data.get("credentialId") or "").strip(),
        scope=scope,
        folder_id=parse_drive_id(str(data.get("gdtFolderId") or "")) if scope == "folder" else "",
        file_id=parse_drive_id(str(data.get("gdtFileId") or "")) if scope == "file" else "",
        events=parse_events(data.get("gdtEvents"), allowed),
        include_folders=scope == "folder" and data.get("gdtIncludeFolders") is True,
        poll_minutes=parse_poll_minutes(data.get("pollIntervalMinutes")),
    )


@dataclass(frozen=True)
class SheetsTriggerConfig:
    """What one Google Sheets Trigger node watches."""

    credential_id: str
    spreadsheet_id: str
    sheet_name: str
    has_header: bool
    key_column: str
    events: frozenset[str]
    poll_minutes: int

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        if not self.credential_id:
            return "no credential selected"
        if not self.spreadsheet_id:
            return "no spreadsheet selected"
        if not self.sheet_name:
            return "no sheet name"
        return None

    def scope_fingerprint(self, header_fingerprint: str) -> str:
        """Changes when the watched tab, row identity, or header row changes."""
        return _fingerprint(
            {
                "type": SHEETS_TRIGGER,
                "credential": self.credential_id,
                "spreadsheet": self.spreadsheet_id,
                "sheet": self.sheet_name,
                "has_header": self.has_header,
                "key_column": self.key_column,
                "header": header_fingerprint,
            }
        )


def parse_sheets_config(data: dict[str, Any]) -> SheetsTriggerConfig:
    """Read a googleSheetsTrigger node's data."""
    raw_id = str(data.get("gstSpreadsheetId") or "").strip()
    return SheetsTriggerConfig(
        credential_id=str(data.get("credentialId") or "").strip(),
        spreadsheet_id=GoogleSheetsService.parse_spreadsheet_id(raw_id) if raw_id else "",
        sheet_name=str(data.get("gstSheetName") or "Sheet1"),
        has_header=data.get("gstHasHeader") is not False,
        key_column=str(data.get("gstKeyColumn") or "").strip(),
        events=parse_events(data.get("gstEvents"), TRIGGER_EVENTS),
        poll_minutes=parse_poll_minutes(data.get("pollIntervalMinutes")),
    )
