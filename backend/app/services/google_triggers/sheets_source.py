"""Google Sheets Trigger: read one tab and diff its rows against stored fingerprints.

The snapshot keeps, per row, its last row number and one keyed fingerprint per cell
(see fingerprint.py). It never keeps a cell value, so a run gets the row's live values
and the names of the columns that changed, not what they used to say.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.services.google_sheets_service import _column_letter_zero_based
from app.services.google_triggers.config import SheetsTriggerConfig
from app.services.google_triggers.events import MOVED, ItemWrite, PollSkippedError, TriggerEvent
from app.services.google_triggers.fingerprint import Fingerprinter

logger = logging.getLogger("google_triggers")

SHEET_ROW_LIMIT = 10_000
_COLUMN_LETTERS = re.compile(r"[A-Za-z]{1,3}")


@dataclass(frozen=True)
class SheetRow:
    """One non-empty row: its sheet row number and its cells without trailing blanks."""

    row_index: int
    cells: list[str]


@dataclass(frozen=True)
class SheetSnapshot:
    """A tab as read during one poll. ``header`` is empty when the tab has no header row."""

    header: list[str]
    rows: list[SheetRow]


@dataclass(frozen=True)
class LiveRow:
    """A row with its identity and the payload the snapshot would store for it."""

    item_key: str
    row: SheetRow
    key_value: str | None
    payload: dict[str, Any]


def build_snapshot(values: list[list[Any]], has_header: bool) -> SheetSnapshot:
    """Turn Sheets API values into rows, skipping blank rows. Raises PollSkippedError if too big."""
    header: list[str] = []
    first_data_row = 1
    if has_header:
        header = [str(cell) for cell in values[0]] if values else []
        first_data_row = 2

    rows: list[SheetRow] = []
    for offset, raw in enumerate(values[first_data_row - 1 :]):
        cells = [str(cell) for cell in raw]
        while cells and cells[-1] == "":
            cells.pop()
        if not any(cell.strip() for cell in cells):
            continue
        rows.append(SheetRow(row_index=first_data_row + offset, cells=cells))

    if len(rows) > SHEET_ROW_LIMIT:
        raise PollSkippedError(f"sheet has more than {SHEET_ROW_LIMIT} rows")
    return SheetSnapshot(header=header, rows=rows)


def header_fingerprint(snapshot: SheetSnapshot, fingerprinter: Fingerprinter) -> str:
    """Fingerprint of the header row, or empty when there is none."""
    if not snapshot.header:
        return ""
    return fingerprinter.item(json.dumps(snapshot.header))


def key_column_index(key_column: str, snapshot: SheetSnapshot, has_header: bool) -> int | None:
    """Position of the key column, or None for row-number identity.

    Raises PollSkippedError when the column cannot be found.
    """
    if not key_column:
        return None
    if has_header:
        for index, title in enumerate(snapshot.header):
            if title.strip() == key_column:
                return index
        for index, title in enumerate(snapshot.header):
            if title.strip().casefold() == key_column.casefold():
                return index
        raise PollSkippedError(f"key column '{key_column}' is not in the header row")
    if _COLUMN_LETTERS.fullmatch(key_column):
        index = 0
        for char in key_column.upper():
            index = index * 26 + (ord(char) - 64)
        return index - 1
    raise PollSkippedError(f"key column '{key_column}' is not a column letter")


def column_name(index: int, snapshot: SheetSnapshot, has_header: bool) -> str:
    """Header text for a column, or its letter when there is no header text."""
    if has_header and index < len(snapshot.header) and snapshot.header[index]:
        return snapshot.header[index]
    return _column_letter_zero_based(index)


def row_object(row: SheetRow, snapshot: SheetSnapshot, has_header: bool) -> dict[str, Any]:
    """A row in the shape the Google Sheets node's readRange returns."""
    if has_header:
        cells = {
            title: (row.cells[index] if index < len(row.cells) else "")
            for index, title in enumerate(snapshot.header)
        }
    else:
        cells = {_column_letter_zero_based(index): value for index, value in enumerate(row.cells)}
    return {**cells, "rowIndex": row.row_index}


def live_rows(
    snapshot: SheetSnapshot, fingerprinter: Fingerprinter, key_index: int | None
) -> dict[str, LiveRow]:
    """Rows keyed by identity: key fingerprint when a key column is set, else row number."""
    live: dict[str, LiveRow] = {}
    for row in snapshot.rows:
        key_value: str | None = None
        if key_index is None:
            item_key = str(row.row_index)
        else:
            key_value = row.cells[key_index] if key_index < len(row.cells) else ""
            if not key_value.strip():
                continue
            item_key = fingerprinter.item(key_value)
            if item_key in live:
                # Never log the key itself: it is sheet data.
                logger.warning(
                    "Google Sheets Trigger: duplicate key at row %s ignored", row.row_index
                )
                continue
        payload = {"r": row.row_index, "c": [fingerprinter.cell(cell) for cell in row.cells]}
        live[item_key] = LiveRow(item_key, row, key_value, payload)
    return live


def sheet_items(
    snapshot: SheetSnapshot, fingerprinter: Fingerprinter, config: SheetsTriggerConfig
) -> dict[str, dict[str, Any]]:
    """Snapshot items for a baseline."""
    key_index = key_column_index(config.key_column, snapshot, config.has_header)
    return {key: row.payload for key, row in live_rows(snapshot, fingerprinter, key_index).items()}


def diff_sheet(
    stored: dict[str, dict[str, Any]],
    snapshot: SheetSnapshot,
    fingerprinter: Fingerprinter,
    config: SheetsTriggerConfig,
) -> list[TriggerEvent]:
    """Row changes between the stored fingerprints and the live tab, top row first."""
    key_index = key_column_index(config.key_column, snapshot, config.has_header)
    live = live_rows(snapshot, fingerprinter, key_index)
    empty = fingerprinter.cell("")
    base = {"spreadsheet_id": config.spreadsheet_id, "sheet_name": config.sheet_name}
    changes: list[TriggerEvent] = []

    for item_key, current in sorted(live.items(), key=lambda item: item[1].row.row_index):
        before = stored.get(item_key)
        write = ItemWrite(item_key, current.payload)
        row = row_object(current.row, snapshot, config.has_header)
        if before is None:
            columns = [
                column_name(index, snapshot, config.has_header)
                for index, cell in enumerate(current.row.cells)
                if cell.strip()
            ]
            payload = {
                **base,
                "event": "created",
                "row": row,
                "changed_columns": columns,
                "key": current.key_value,
            }
            changes.append(TriggerEvent("created", payload, write, ItemWrite(item_key, None)))
            continue

        old_cells = list(before.get("c") or [])
        new_cells = current.payload["c"]
        width = max(len(old_cells), len(new_cells))
        differing = [
            index
            for index in range(width)
            if (old_cells[index] if index < len(old_cells) else empty)
            != (new_cells[index] if index < len(new_cells) else empty)
        ]
        if differing:
            columns = [column_name(index, snapshot, config.has_header) for index in differing]
            payload = {
                **base,
                "event": "updated",
                "row": row,
                "changed_columns": columns,
                "key": current.key_value,
            }
            changes.append(TriggerEvent("updated", payload, write, ItemWrite(item_key, before)))
        elif before.get("r") != current.payload["r"]:
            changes.append(TriggerEvent(MOVED, {}, write, ItemWrite(item_key, before)))

    gone = sorted(set(stored) - set(live), key=lambda key: stored[key].get("r", 0))
    for item_key in gone:
        before = stored[item_key]
        payload = {
            **base,
            "event": "deleted",
            "row": {"rowIndex": before.get("r")},
            "changed_columns": [],
            "key": None,
        }
        changes.append(
            TriggerEvent("deleted", payload, ItemWrite(item_key, None), ItemWrite(item_key, before))
        )
    return changes
