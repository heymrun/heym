"""Poller adapters: one per Google trigger node type.

Each adapter answers the same questions for the poller: is the node configured, what is
live in Google right now, which scope does that belong to, and what changed. ``fetch``
runs in a worker thread because the Google services are synchronous, and it opens a sync
session so a refreshed OAuth token is saved on the credential.
"""

from __future__ import annotations

from typing import Any

from app.db.models import CredentialType
from app.db.session import SessionLocal
from app.services.google_drive_service import GoogleDriveService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.google_triggers.config import (
    DRIVE_TRIGGER,
    SHEETS_TRIGGER,
    DriveTriggerConfig,
    SheetsTriggerConfig,
    parse_drive_config,
    parse_sheets_config,
)
from app.services.google_triggers.drive_source import diff_drive, drive_items, fetch_drive_entries
from app.services.google_triggers.events import TriggerEvent
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sheets_source import (
    SheetSnapshot,
    build_snapshot,
    diff_sheet,
    header_fingerprint,
    sheet_items,
)

TRIGGER_NODE_TYPES: tuple[str, ...] = (DRIVE_TRIGGER, SHEETS_TRIGGER)


class DriveSource:
    """Google Drive Trigger node, as the poller sees it."""

    node_type = DRIVE_TRIGGER
    trigger_source = "google_drive"
    label = "Google Drive Trigger"
    credential_type = CredentialType.google_drive

    def __init__(self, config: DriveTriggerConfig) -> None:
        self.config = config
        self.credential_id = config.credential_id
        self.poll_minutes = config.poll_minutes
        self.events = config.events

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        return self.config.problem()

    def fetch(self, credential_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Live metadata of the watched folder or file."""
        with SessionLocal() as db:
            service = GoogleDriveService(self.credential_id, credential_config, db)
            return fetch_drive_entries(service, self.config)

    def scope_fingerprint(self, live: list[dict[str, Any]]) -> str:
        """Identity of what is watched."""
        return self.config.scope_fingerprint()

    def items(self, live: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Snapshot items for a baseline."""
        return drive_items(live)

    def diff(
        self, stored: dict[str, dict[str, Any]], live: list[dict[str, Any]]
    ) -> list[TriggerEvent]:
        """Changes since the stored snapshot."""
        return diff_drive(stored, live, self.config)


class SheetsSource:
    """Google Sheets Trigger node, as the poller sees it."""

    node_type = SHEETS_TRIGGER
    trigger_source = "google_sheets"
    label = "Google Sheets Trigger"
    credential_type = CredentialType.google_sheets

    def __init__(self, config: SheetsTriggerConfig, fingerprinter: Fingerprinter) -> None:
        self.config = config
        self.fingerprinter = fingerprinter
        self.credential_id = config.credential_id
        self.poll_minutes = config.poll_minutes
        self.events = config.events

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        return self.config.problem()

    def fetch(self, credential_config: dict[str, Any]) -> SheetSnapshot:
        """The watched tab as it is now."""
        with SessionLocal() as db:
            service = GoogleSheetsService(self.credential_id, credential_config, db)
            values = service.read_sheet_values(self.config.spreadsheet_id, self.config.sheet_name)
        return build_snapshot(values, self.config.has_header)

    def scope_fingerprint(self, live: SheetSnapshot) -> str:
        """Identity of what is watched, including the header row."""
        return self.config.scope_fingerprint(header_fingerprint(live, self.fingerprinter))

    def items(self, live: SheetSnapshot) -> dict[str, dict[str, Any]]:
        """Snapshot items for a baseline."""
        return sheet_items(live, self.fingerprinter, self.config)

    def diff(self, stored: dict[str, dict[str, Any]], live: SheetSnapshot) -> list[TriggerEvent]:
        """Changes since the stored snapshot."""
        return diff_sheet(stored, live, self.fingerprinter, self.config)


def build_source(node: dict[str, Any], fingerprinter: Fingerprinter) -> DriveSource | SheetsSource:
    """Adapter for a Google trigger node. Raises ValueError for any other node type."""
    data = node.get("data") or {}
    node_type = node.get("type")
    if node_type == DRIVE_TRIGGER:
        return DriveSource(parse_drive_config(data))
    if node_type == SHEETS_TRIGGER:
        return SheetsSource(parse_sheets_config(data), fingerprinter)
    raise ValueError(f"not a Google trigger node: {node_type}")
