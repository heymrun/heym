"""Google Drive Trigger diff: created, updated, deleted from stored metadata."""

import unittest
from unittest.mock import MagicMock

from app.services.google_drive_service import FOLDER_MIME
from app.services.google_triggers.config import parse_drive_config
from app.services.google_triggers.drive_source import (
    DRIVE_ENTRY_LIMIT,
    diff_drive,
    entry_metadata,
    fetch_drive_entries,
)
from app.services.google_triggers.events import ItemWrite, PollSkippedError

FOLDER = parse_drive_config({"credentialId": "c", "gdtFolderId": "F1"})


def _raw(file_id: str, name: str = "a.pdf", modified: str = "2026-10-17T10:00:00Z") -> dict:
    return {
        "id": file_id,
        "name": name,
        "mimeType": "application/pdf",
        "size": "10",
        "createdTime": "2026-10-17T09:00:00Z",
        "modifiedTime": modified,
        "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
    }


class EntryMetadataTests(unittest.TestCase):
    def test_maps_drive_fields(self) -> None:
        meta = entry_metadata(_raw("a"))
        self.assertEqual(meta["size_bytes"], 10)
        self.assertEqual(meta["mime_type"], "application/pdf")
        self.assertFalse(meta["is_folder"])

    def test_folders_have_no_size(self) -> None:
        meta = entry_metadata({"id": "f", "name": "Q4", "mimeType": FOLDER_MIME})
        self.assertTrue(meta["is_folder"])
        self.assertIsNone(meta["size_bytes"])


class DiffDriveTests(unittest.TestCase):
    def test_new_file_is_created(self) -> None:
        live = [entry_metadata(_raw("a"))]
        [change] = diff_drive({}, live, FOLDER)
        self.assertEqual(change.event, "created")
        self.assertEqual(change.payload["file"]["id"], "a")
        self.assertEqual(change.payload["changed_fields"], [])
        self.assertEqual(change.payload["folder_id"], "F1")
        self.assertEqual(change.write, ItemWrite("a", live[0]))
        self.assertEqual(change.revert, ItemWrite("a", None))

    def test_rename_is_updated_with_changed_fields(self) -> None:
        before = entry_metadata(_raw("a"))
        after = entry_metadata(_raw("a", name="b.pdf"))
        [change] = diff_drive({"a": before}, [after], FOLDER)
        self.assertEqual(change.event, "updated")
        self.assertEqual(change.payload["changed_fields"], ["name"])
        self.assertEqual(change.revert, ItemWrite("a", before))

    def test_unchanged_file_is_quiet(self) -> None:
        meta = entry_metadata(_raw("a"))
        self.assertEqual(diff_drive({"a": meta}, [meta], FOLDER), [])

    def test_missing_file_is_deleted_with_its_last_known_metadata(self) -> None:
        before = entry_metadata(_raw("a", name="contract.pdf"))
        [change] = diff_drive({"a": before}, [], FOLDER)
        self.assertEqual(change.event, "deleted")
        self.assertEqual(change.payload["file"]["name"], "contract.pdf")
        self.assertEqual(change.write, ItemWrite("a", None))
        self.assertEqual(change.revert, ItemWrite("a", before))

    def test_root_folder_reports_root(self) -> None:
        root = parse_drive_config({"credentialId": "c"})
        [change] = diff_drive({}, [entry_metadata(_raw("a"))], root)
        self.assertEqual(change.payload["folder_id"], "root")

    def test_file_scope_reports_no_folder(self) -> None:
        one_file = parse_drive_config({"credentialId": "c", "gdtScope": "file", "gdtFileId": "a"})
        before = entry_metadata(_raw("a"))
        [change] = diff_drive({"a": before}, [entry_metadata(_raw("a", name="b"))], one_file)
        self.assertIsNone(change.payload["folder_id"])


class FetchDriveEntriesTests(unittest.TestCase):
    def test_file_scope_returns_nothing_for_a_missing_file(self) -> None:
        one_file = parse_drive_config({"credentialId": "c", "gdtScope": "file", "gdtFileId": "a"})
        service = MagicMock()
        service.get_file_entry.return_value = None
        self.assertEqual(fetch_drive_entries(service, one_file), [])

    def test_folder_over_the_limit_is_skipped(self) -> None:
        service = MagicMock()
        service.list_folder_entries.return_value = [
            _raw(str(index)) for index in range(DRIVE_ENTRY_LIMIT + 1)
        ]
        with self.assertRaises(PollSkippedError):
            fetch_drive_entries(service, FOLDER)
        service.list_folder_entries.assert_called_once_with(
            "F1", include_folders=False, max_entries=DRIVE_ENTRY_LIMIT + 1
        )


if __name__ == "__main__":
    unittest.main()
