"""The rows of an Excel (.xlsx) workbook, as a vector store reads them.

Every worksheet is read. Its first non-empty row names the columns, and every row after it
becomes "Column: value | Column: value", as a CSV row does. A column without a name is called
by its letter. Formulas read as the value Excel last saved with the file.
"""

from __future__ import annotations

import datetime
import io
from dataclasses import dataclass

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.services.office_archive import ensure_unpacked_size


@dataclass(frozen=True)
class SheetRow:
    """One row of a worksheet; `row` is its number as Excel shows it."""

    sheet: str
    row: int
    text: str


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime.datetime):
        if value.time() == datetime.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return str(value).strip()


def _column_name(header: list[str], index: int) -> str:
    name = header[index] if index < len(header) else ""
    return name or get_column_letter(index + 1)


def _sheet_rows(title: str, rows: list[tuple[int, list[str]]]) -> list[SheetRow]:
    if not rows:
        return []
    header_number, header = rows[0]
    if len(rows) == 1:
        return [SheetRow(title, header_number, " | ".join(cell for cell in header if cell))]
    result: list[SheetRow] = []
    for number, cells in rows[1:]:
        pairs = [
            f"{_column_name(header, index)}: {cell}" for index, cell in enumerate(cells) if cell
        ]
        result.append(SheetRow(title, number, " | ".join(pairs)))
    return result


def xlsx_rows(data: bytes) -> list[SheetRow]:
    """The rows of every worksheet in workbook order, header rows excepted.

    A worksheet with a single row gives that row as it is, so it is not lost.

    Raises zipfile.BadZipFile, KeyError, OSError or ValueError for a file that is not a
    readable .xlsx, and office_archive.ArchiveTooLargeError for one that unpacks too far.
    """
    ensure_unpacked_size(data)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        result: list[SheetRow] = []
        for sheet in workbook.worksheets:
            # Read-only mode trusts the stored dimension, which some writers leave stale;
            # without the reset, cells outside it are dropped.
            sheet.reset_dimensions()
            rows = []
            for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = [_cell_text(value) for value in values]
                if any(cells):
                    rows.append((number, cells))
            result.extend(_sheet_rows(sheet.title, rows))
        return result
    finally:
        workbook.close()
