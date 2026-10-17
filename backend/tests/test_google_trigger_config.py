"""Google trigger node data parsed into configs."""

import unittest

from app.services.google_triggers.config import (
    TRIGGER_EVENTS,
    parse_drive_config,
    parse_poll_minutes,
    parse_sheets_config,
)


class DriveConfigTests(unittest.TestCase):
    def test_defaults_watch_my_drive_root_for_every_event(self) -> None:
        config = parse_drive_config({"credentialId": "cred"})
        self.assertEqual(config.scope, "folder")
        self.assertEqual(config.folder_id, "")
        self.assertEqual(config.events, frozenset(TRIGGER_EVENTS))
        self.assertFalse(config.include_folders)
        self.assertEqual(config.poll_minutes, 1)
        self.assertIsNone(config.problem())

    def test_folder_url_is_parsed_to_an_id(self) -> None:
        config = parse_drive_config(
            {
                "credentialId": "cred",
                "gdtFolderId": "https://drive.google.com/drive/folders/1FolderXyz_9",
            }
        )
        self.assertEqual(config.folder_id, "1FolderXyz_9")

    def test_file_scope_never_fires_created(self) -> None:
        config = parse_drive_config(
            {
                "credentialId": "cred",
                "gdtScope": "file",
                "gdtFileId": "https://drive.google.com/file/d/1AbC/view",
                "gdtEvents": ["created", "updated"],
            }
        )
        self.assertEqual(config.file_id, "1AbC")
        self.assertEqual(config.events, frozenset({"updated"}))

    def test_file_scope_without_a_file_is_a_problem(self) -> None:
        config = parse_drive_config({"credentialId": "cred", "gdtScope": "file"})
        self.assertEqual(config.problem(), "no file selected")

    def test_missing_credential_is_a_problem(self) -> None:
        self.assertEqual(parse_drive_config({}).problem(), "no credential selected")

    def test_unknown_events_are_dropped(self) -> None:
        config = parse_drive_config({"credentialId": "c", "gdtEvents": ["created", "renamed"]})
        self.assertEqual(config.events, frozenset({"created"}))

    def test_scope_fingerprint_ignores_events_and_interval(self) -> None:
        base = {"credentialId": "c", "gdtFolderId": "F1"}
        first = parse_drive_config({**base, "gdtEvents": ["created"], "pollIntervalMinutes": 1})
        second = parse_drive_config({**base, "gdtEvents": ["deleted"], "pollIntervalMinutes": 9})
        other_folder = parse_drive_config({**base, "gdtFolderId": "F2"})
        self.assertEqual(first.scope_fingerprint(), second.scope_fingerprint())
        self.assertNotEqual(first.scope_fingerprint(), other_folder.scope_fingerprint())


class SheetsConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = parse_sheets_config({"credentialId": "c", "gstSpreadsheetId": "S1"})
        self.assertEqual(config.sheet_name, "Sheet1")
        self.assertTrue(config.has_header)
        self.assertEqual(config.key_column, "")
        self.assertEqual(config.events, frozenset(TRIGGER_EVENTS))
        self.assertIsNone(config.problem())

    def test_spreadsheet_url_is_parsed_to_an_id(self) -> None:
        config = parse_sheets_config(
            {
                "credentialId": "c",
                "gstSpreadsheetId": "https://docs.google.com/spreadsheets/d/1SheetId_7/edit#gid=0",
            }
        )
        self.assertEqual(config.spreadsheet_id, "1SheetId_7")

    def test_missing_spreadsheet_is_a_problem(self) -> None:
        config = parse_sheets_config({"credentialId": "c"})
        self.assertEqual(config.problem(), "no spreadsheet selected")

    def test_header_is_off_only_when_set_false(self) -> None:
        base = {"credentialId": "c", "gstSpreadsheetId": "S1"}
        self.assertTrue(parse_sheets_config({**base, "gstHasHeader": None}).has_header)
        self.assertFalse(parse_sheets_config({**base, "gstHasHeader": False}).has_header)

    def test_scope_fingerprint_tracks_header_and_key_column(self) -> None:
        base = {"credentialId": "c", "gstSpreadsheetId": "S1"}
        plain = parse_sheets_config(base)
        keyed = parse_sheets_config({**base, "gstKeyColumn": "Email"})
        self.assertNotEqual(plain.scope_fingerprint("h1"), plain.scope_fingerprint("h2"))
        self.assertNotEqual(plain.scope_fingerprint("h1"), keyed.scope_fingerprint("h1"))


class PollMinutesTests(unittest.TestCase):
    def test_interval_is_at_least_one_minute(self) -> None:
        self.assertEqual(parse_poll_minutes("0"), 1)
        self.assertEqual(parse_poll_minutes("abc"), 1)
        self.assertEqual(parse_poll_minutes(None), 1)
        self.assertEqual(parse_poll_minutes(15), 15)


if __name__ == "__main__":
    unittest.main()
