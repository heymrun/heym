"""Reading the rows of an Excel workbook (xlsx_rows)."""

import datetime
import io
import re
import unittest
import zipfile
from unittest.mock import patch

from openpyxl import Workbook

from app.services.office_archive import ArchiveTooLargeError
from app.services.xlsx_rows import SheetRow, xlsx_rows


def _save(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _with_stale_dimension(data: bytes) -> bytes:
    """The same workbook, its first sheet claiming to cover A1 only."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                content = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1"', content)
            target.writestr(info, content)
    return out.getvalue()


class XlsxRowsTests(unittest.TestCase):
    def test_header_names_the_columns_of_every_row_after_it(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Prices"
        sheet.append([])
        sheet.append([None, "Product", "Price", None])
        sheet.append([None, "Apple", 5.5, "organic"])
        sheet.append([])
        sheet.append([None, "Pear", None, None, "late"])

        self.assertEqual(
            xlsx_rows(_save(workbook)),
            [
                SheetRow("Prices", 3, "Product: Apple | Price: 5.5 | D: organic"),
                SheetRow("Prices", 5, "Product: Pear | E: late"),
            ],
        )

    def test_values_read_as_excel_shows_them(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Count", "Day", "At", "Time", "Paid", "Formula"])
        sheet.append(
            [
                3.0,
                datetime.datetime(2026, 11, 18),
                datetime.datetime(2026, 11, 18, 9, 30),
                datetime.time(9, 30),
                True,
                "=A2*2",
            ]
        )

        self.assertEqual(
            xlsx_rows(_save(workbook))[0].text,
            "Count: 3 | Day: 2026-11-18 | At: 2026-11-18 09:30:00 | Time: 09:30:00 | Paid: TRUE",
        )

    def test_every_sheet_in_order_and_a_single_row_sheet_is_kept(self) -> None:
        workbook = Workbook()
        workbook.active.title = "Notes"
        workbook.active.append(["Quarterly targets", None, "draft"])
        workbook.create_sheet("Empty")
        data = workbook.create_sheet("Data")
        data.append(["Region", "Target"])
        data.append(["EMEA", 120])

        self.assertEqual(
            xlsx_rows(_save(workbook)),
            [
                SheetRow("Notes", 1, "Quarterly targets | draft"),
                SheetRow("Data", 2, "Region: EMEA | Target: 120"),
            ],
        )

    def test_rows_outside_a_stale_dimension_are_read(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Name", "Team"])
        sheet.append(["Ada", "Platform"])
        sheet.append(["Lin", "Data"])

        rows = xlsx_rows(_with_stale_dimension(_save(workbook)))

        self.assertEqual(
            [row.text for row in rows], ["Name: Ada | Team: Platform", "Name: Lin | Team: Data"]
        )

    def test_empty_workbook_has_no_rows(self) -> None:
        self.assertEqual(xlsx_rows(_save(Workbook())), [])

    def test_archive_that_unpacks_too_far_is_refused_before_parsing(self) -> None:
        data = _save(Workbook())

        with patch("app.services.office_archive.MAX_UNPACKED_BYTES", 1024):
            with patch("app.services.xlsx_rows.load_workbook") as parse:
                with self.assertRaises(ArchiveTooLargeError):
                    xlsx_rows(data)

        parse.assert_not_called()
