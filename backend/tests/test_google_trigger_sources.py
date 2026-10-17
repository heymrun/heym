"""Poller adapters wrap config, Google reads, and diffs for one node."""

import unittest
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.google_triggers.fingerprint import Fingerprinter
from app.services.google_triggers.sources import DriveSource, SheetsSource, build_source

FP = Fingerprinter.for_node("test-secret-key-for-tests-only-32-bytes", "wf", "node")


class BuildSourceTests(unittest.TestCase):
    def test_builds_a_drive_source(self) -> None:
        source = build_source(
            {"type": "googleDriveTrigger", "data": {"credentialId": "c", "gdtFolderId": "F1"}}, FP
        )
        self.assertIsInstance(source, DriveSource)
        self.assertEqual(source.trigger_source, "google_drive")
        self.assertEqual(source.credential_type, CredentialType.google_drive)
        self.assertEqual(source.credential_id, "c")

    def test_builds_a_sheets_source(self) -> None:
        source = build_source(
            {"type": "googleSheetsTrigger", "data": {"credentialId": "c", "gstSpreadsheetId": "S"}},
            FP,
        )
        self.assertIsInstance(source, SheetsSource)
        self.assertEqual(source.trigger_source, "google_sheets")

    def test_rejects_other_nodes(self) -> None:
        with self.assertRaises(ValueError):
            build_source({"type": "imapTrigger", "data": {}}, FP)


class DriveSourceTests(unittest.TestCase):
    def test_fetch_lists_the_folder_with_the_credential(self) -> None:
        source = build_source(
            {"type": "googleDriveTrigger", "data": {"credentialId": "c", "gdtFolderId": "F1"}}, FP
        )
        service = MagicMock()
        service.list_folder_entries.return_value = [{"id": "a", "name": "a.pdf"}]
        with (
            patch("app.services.google_triggers.sources.SessionLocal"),
            patch(
                "app.services.google_triggers.sources.GoogleDriveService", return_value=service
            ) as service_class,
        ):
            live = source.fetch({"access_token": "t"})
        self.assertEqual(service_class.call_args.args[0], "c")
        self.assertEqual(live[0]["name"], "a.pdf")
        self.assertEqual(set(source.items(live)), {"a"})


class SheetsSourceTests(unittest.TestCase):
    def _source(self) -> SheetsSource:
        return build_source(
            {"type": "googleSheetsTrigger", "data": {"credentialId": "c", "gstSpreadsheetId": "S"}},
            FP,
        )

    def _fetch(self, source: SheetsSource, values: list) -> object:
        service = MagicMock()
        service.read_sheet_values.return_value = values
        with (
            patch("app.services.google_triggers.sources.SessionLocal"),
            patch("app.services.google_triggers.sources.GoogleSheetsService", return_value=service),
        ):
            return source.fetch({"access_token": "t"})

    def test_scope_follows_the_header_row(self) -> None:
        source = self._source()
        first = source.scope_fingerprint(self._fetch(source, [["Name"], ["Ada"]]))
        renamed = source.scope_fingerprint(self._fetch(source, [["Full name"], ["Ada"]]))
        self.assertNotEqual(first, renamed)

    def test_diff_finds_a_new_row(self) -> None:
        source = self._source()
        stored = source.items(self._fetch(source, [["Name"], ["Ada"]]))
        changes = source.diff(stored, self._fetch(source, [["Name"], ["Ada"], ["Grace"]]))
        self.assertEqual([change.event for change in changes], ["created"])


if __name__ == "__main__":
    unittest.main()
