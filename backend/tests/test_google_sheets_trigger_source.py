"""Google Sheets Trigger diff over keyed fingerprints; cell values are never stored."""

import json
import unittest

from app.services.google_triggers.config import parse_sheets_config
from app.services.google_triggers.events import MOVED, PollSkippedError
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sheets_source import (
    SHEET_ROW_LIMIT,
    build_snapshot,
    diff_sheet,
    header_fingerprint,
    sheet_items,
)

FP = Fingerprinter.for_node("test-secret-key-for-tests-only-32-bytes", "wf", "node")
BASE = {"credentialId": "c", "gstSpreadsheetId": "S1", "gstSheetName": "Leads"}
BY_ROW = parse_sheets_config(BASE)
BY_EMAIL = parse_sheets_config({**BASE, "gstKeyColumn": "Email"})
HEADER = ["Name", "Email", "Status"]


def _items(values: list[list[str]], config=BY_ROW) -> dict:
    return sheet_items(build_snapshot(values, config.has_header), FP, config)


def _diff(before: list[list[str]], after: list[list[str]], config=BY_ROW) -> list:
    return diff_sheet(_items(before, config), build_snapshot(after, config.has_header), FP, config)


class BuildSnapshotTests(unittest.TestCase):
    def test_skips_header_and_blank_rows_and_keeps_sheet_row_numbers(self) -> None:
        snapshot = build_snapshot([HEADER, ["Ada", "a@x", ""], ["", " "], ["Grace"]], True)
        self.assertEqual(snapshot.header, HEADER)
        self.assertEqual([row.row_index for row in snapshot.rows], [2, 4])
        self.assertEqual(snapshot.rows[0].cells, ["Ada", "a@x"])

    def test_without_a_header_rows_start_at_one(self) -> None:
        snapshot = build_snapshot([["Ada"], ["Grace"]], False)
        self.assertEqual(snapshot.header, [])
        self.assertEqual([row.row_index for row in snapshot.rows], [1, 2])

    def test_too_many_rows_skip_the_poll(self) -> None:
        values = [HEADER] + [[str(index)] for index in range(SHEET_ROW_LIMIT + 1)]
        with self.assertRaises(PollSkippedError):
            build_snapshot(values, True)


class DiffSheetTests(unittest.TestCase):
    def test_new_row_is_created_with_its_live_values(self) -> None:
        [change] = _diff([HEADER, ["Ada", "a@x"]], [HEADER, ["Ada", "a@x"], ["Grace", "g@x"]])
        self.assertEqual(change.event, "created")
        self.assertEqual(
            change.payload["row"], {"Name": "Grace", "Email": "g@x", "Status": "", "rowIndex": 3}
        )
        self.assertEqual(change.payload["changed_columns"], ["Name", "Email"])
        self.assertEqual(change.payload["spreadsheet_id"], "S1")
        self.assertEqual(change.payload["sheet_name"], "Leads")
        self.assertIsNone(change.payload["key"])

    def test_edit_lists_only_the_changed_column(self) -> None:
        [change] = _diff([HEADER, ["Ada", "a@x", "New"]], [HEADER, ["Ada", "a@x", "Paid"]])
        self.assertEqual(change.event, "updated")
        self.assertEqual(change.payload["changed_columns"], ["Status"])
        self.assertEqual(change.payload["row"]["Status"], "Paid")

    def test_clearing_the_last_cell_is_an_update(self) -> None:
        [change] = _diff([HEADER, ["Ada", "a@x", "Paid"]], [HEADER, ["Ada", "a@x"]])
        self.assertEqual(change.event, "updated")
        self.assertEqual(change.payload["changed_columns"], ["Status"])

    def test_deleted_row_reports_only_its_row_number(self) -> None:
        [change] = _diff([HEADER, ["Ada"], ["Grace"]], [HEADER, ["Ada"]])
        self.assertEqual(change.event, "deleted")
        self.assertEqual(change.payload["row"], {"rowIndex": 3})
        self.assertEqual(change.payload["changed_columns"], [])

    def test_row_numbers_shift_when_a_row_is_inserted_above(self) -> None:
        changes = _diff([HEADER, ["Ada"]], [HEADER, ["New"], ["Ada"]])
        self.assertEqual([change.event for change in changes], ["updated", "created"])

    def test_key_column_follows_a_row_that_moved(self) -> None:
        before = [HEADER, ["Ada", "a@x"]]
        after = [HEADER, ["New", "n@x"], ["Ada", "a@x"]]
        changes = _diff(before, after, BY_EMAIL)
        self.assertEqual([change.event for change in changes], ["created", MOVED])
        self.assertEqual(changes[0].payload["key"], "n@x")
        self.assertEqual(changes[1].write.payload["r"], 3)

    def test_rows_without_a_key_are_ignored(self) -> None:
        self.assertEqual(_diff([HEADER], [HEADER, ["Ada", ""]], BY_EMAIL), [])

    def test_duplicate_keys_keep_the_first_row(self) -> None:
        items = _items([HEADER, ["Ada", "a@x"], ["Ada again", "a@x"]], BY_EMAIL)
        self.assertEqual([item["r"] for item in items.values()], [2])

    def test_missing_key_column_skips_the_poll(self) -> None:
        config = parse_sheets_config({**BASE, "gstKeyColumn": "Phone"})
        with self.assertRaises(PollSkippedError):
            _items([HEADER, ["Ada"]], config)

    def test_column_letter_key_without_a_header(self) -> None:
        config = parse_sheets_config({**BASE, "gstHasHeader": False, "gstKeyColumn": "B"})
        [change] = _diff([["Ada", "a@x"]], [["Ada", "a@x"], ["Grace", "g@x"]], config)
        self.assertEqual(change.payload["key"], "g@x")
        self.assertEqual(change.payload["row"], {"A": "Grace", "B": "g@x", "rowIndex": 2})

    def test_stored_items_hold_no_cell_values(self) -> None:
        stored = json.dumps(_items([HEADER, ["Ada Lovelace", "ada@example.com"]], BY_EMAIL))
        self.assertNotIn("Ada", stored)
        self.assertNotIn("ada@example.com", stored)

    def test_header_fingerprint_changes_with_the_header(self) -> None:
        first = header_fingerprint(build_snapshot([HEADER], True), FP)
        second = header_fingerprint(build_snapshot([["Name", "Mail", "Status"]], True), FP)
        self.assertNotEqual(first, second)
        self.assertEqual(header_fingerprint(build_snapshot([["Ada"]], False), FP), "")


if __name__ == "__main__":
    unittest.main()
