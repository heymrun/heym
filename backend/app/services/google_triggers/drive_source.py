"""Google Drive Trigger: read a folder or one file and diff it against stored metadata.

Only metadata is kept (id, name, type, size, times, link). File contents are never read.
"""

from __future__ import annotations

from typing import Any

from app.services.google_drive_service import FOLDER_MIME, GoogleDriveService
from app.services.google_triggers.config import DriveTriggerConfig
from app.services.google_triggers.events import ItemWrite, PollSkippedError, TriggerEvent

DRIVE_ENTRY_LIMIT = 5000
_TRACKED_FIELDS = ("name", "modified_time", "size_bytes", "mime_type")


def entry_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Drive API file resource to the metadata a run receives and the snapshot stores."""
    raw_size = raw.get("size")
    mime_type = str(raw.get("mimeType") or "")
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "mime_type": mime_type,
        "size_bytes": int(raw_size) if raw_size is not None else None,
        "created_time": str(raw.get("createdTime") or ""),
        "modified_time": str(raw.get("modifiedTime") or ""),
        "web_view_link": str(raw.get("webViewLink") or ""),
        "is_folder": mime_type == FOLDER_MIME,
    }


def fetch_drive_entries(
    service: GoogleDriveService, config: DriveTriggerConfig
) -> list[dict[str, Any]]:
    """Live metadata for the watched scope. Raises PollSkippedError for an oversized folder."""
    if config.scope == "file":
        raw = service.get_file_entry(config.file_id)
        return [entry_metadata(raw)] if raw else []
    raw_entries = service.list_folder_entries(
        config.folder_id,
        include_folders=config.include_folders,
        max_entries=DRIVE_ENTRY_LIMIT + 1,
    )
    if len(raw_entries) > DRIVE_ENTRY_LIMIT:
        raise PollSkippedError(f"folder has more than {DRIVE_ENTRY_LIMIT} entries")
    return [entry_metadata(raw) for raw in raw_entries]


def drive_items(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Snapshot items keyed by file ID."""
    return {entry["id"]: entry for entry in entries if entry["id"]}


def diff_drive(
    stored: dict[str, dict[str, Any]],
    entries: list[dict[str, Any]],
    config: DriveTriggerConfig,
) -> list[TriggerEvent]:
    """Changes between the stored metadata and the live entries, oldest edit first."""
    live = drive_items(entries)
    folder_id = (config.folder_id or "root") if config.scope == "folder" else None
    changes: list[TriggerEvent] = []

    for key, entry in sorted(live.items(), key=lambda item: (item[1]["modified_time"], item[0])):
        before = stored.get(key)
        if before is None:
            changes.append(
                _event("created", entry, [], folder_id, ItemWrite(key, entry), ItemWrite(key, None))
            )
            continue
        fields = [name for name in _TRACKED_FIELDS if before.get(name) != entry.get(name)]
        if fields:
            changes.append(
                _event(
                    "updated",
                    entry,
                    fields,
                    folder_id,
                    ItemWrite(key, entry),
                    ItemWrite(key, before),
                )
            )

    for key in sorted(set(stored) - set(live)):
        before = stored[key]
        changes.append(
            _event("deleted", before, [], folder_id, ItemWrite(key, None), ItemWrite(key, before))
        )
    return changes


def _event(
    kind: str,
    file: dict[str, Any],
    changed_fields: list[str],
    folder_id: str | None,
    write: ItemWrite,
    revert: ItemWrite,
) -> TriggerEvent:
    payload = {
        "event": kind,
        "file": dict(file),
        "changed_fields": changed_fields,
        "folder_id": folder_id,
    }
    return TriggerEvent(event=kind, payload=payload, write=write, revert=revert)
