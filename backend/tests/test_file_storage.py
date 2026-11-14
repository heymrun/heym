"""Tests for generated file storage path safety."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENCRYPTION_KEY", "0" * 64)

from app.services.file_storage import get_file_path, store_file, store_file_sync


class FileStoragePathSafetyTests(unittest.IsolatedAsyncioTestCase):
    """File storage must keep attacker-controlled names inside the storage root."""

    async def test_store_file_rejects_posix_traversal_filename(self) -> None:
        """A multipart filename with ../ segments must not escape the storage root."""
        owner_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()

        with tempfile.TemporaryDirectory() as storage_dir:
            outside_file = Path(storage_dir).parent / "poc-owned-by-attacker.txt"
            if outside_file.exists():
                outside_file.unlink()

            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaisesRegex(ValueError, "path components"):
                    await store_file(
                        db,
                        owner_id=owner_id,
                        file_bytes=b"PWNED",
                        filename="../../../poc-owned-by-attacker.txt",
                    )

            self.assertFalse(outside_file.exists())
            db.add.assert_not_called()
            db.flush.assert_not_awaited()

    async def test_store_file_rejects_windows_path_filename(self) -> None:
        """Backslash-separated path components must be rejected on Unix too."""
        db = AsyncMock()
        db.add = MagicMock()

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaisesRegex(ValueError, "path components"):
                    await store_file(
                        db,
                        owner_id=uuid.uuid4(),
                        file_bytes=b"PWNED",
                        filename=r"..\\..\\poc-owned-by-attacker.txt",
                    )

            db.add.assert_not_called()
            db.flush.assert_not_awaited()

    async def test_store_file_writes_valid_filename_under_storage_root(self) -> None:
        """Safe filenames are still persisted below owner/file UUID directories."""
        db = AsyncMock()
        db.add = MagicMock()
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()

        with tempfile.TemporaryDirectory() as storage_dir:
            with (
                patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)),
                patch("app.services.file_storage.uuid.uuid4", return_value=file_id),
            ):
                row = await store_file(
                    db,
                    owner_id=owner_id,
                    file_bytes=b"safe content",
                    filename="report.txt",
                )

            stored_path = Path(storage_dir) / str(owner_id) / str(file_id) / "report.txt"
            self.assertEqual(stored_path.read_bytes(), b"safe content")
            self.assertEqual(row.storage_path, f"{owner_id}/{file_id}/report.txt")
            db.add.assert_called_once_with(row)
            db.flush.assert_awaited_once()

    def test_get_file_path_rejects_escaped_legacy_storage_path(self) -> None:
        """Legacy DB paths containing traversal are not resolved outside storage root."""
        escaped = SimpleNamespace(storage_path="owner/file/../../../escaped.txt")

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaisesRegex(ValueError, "escapes storage root"):
                    get_file_path(escaped)


class FileStorageFlushFailureTests(unittest.IsolatedAsyncioTestCase):
    """A file whose row never reached the database must not stay on disk."""

    @staticmethod
    def _files(root: str) -> list[Path]:
        return [p for p in Path(root).rglob("*") if p.is_file()]

    @staticmethod
    def _file_dirs(root: str) -> list[Path]:
        return [
            p for p in Path(root).rglob("*") if p.is_dir() and len(p.relative_to(root).parts) == 2
        ]

    async def test_store_file_removes_the_file_when_flush_fails(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush.side_effect = RuntimeError("flush failed")

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaisesRegex(RuntimeError, "flush failed"):
                    await store_file(db, owner_id=uuid.uuid4(), file_bytes=b"x", filename="a.txt")

            self.assertEqual(self._files(storage_dir), [])
            self.assertEqual(self._file_dirs(storage_dir), [])

    def test_store_file_sync_removes_the_file_when_flush_fails(self) -> None:
        db = MagicMock()
        db.flush.side_effect = RuntimeError("flush failed")

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaisesRegex(RuntimeError, "flush failed"):
                    store_file_sync(
                        db,
                        owner_id=uuid.uuid4(),
                        file_bytes=b"x",
                        filename="a.txt",
                        mime_type="text/plain",
                    )

            self.assertEqual(self._files(storage_dir), [])
            self.assertEqual(self._file_dirs(storage_dir), [])

    async def test_store_file_removes_the_directory_when_the_write_fails(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        long_name = "a" * 300 + ".txt"  # over NAME_MAX: the write raises ENAMETOOLONG

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaises(OSError):
                    await store_file(db, owner_id=uuid.uuid4(), file_bytes=b"x", filename=long_name)

            self.assertEqual(self._files(storage_dir), [])
            self.assertEqual(self._file_dirs(storage_dir), [])
            db.add.assert_not_called()

    def test_store_file_sync_removes_the_directory_when_the_write_fails(self) -> None:
        db = MagicMock()
        long_name = "a" * 300 + ".txt"

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                with self.assertRaises(OSError):
                    store_file_sync(
                        db,
                        owner_id=uuid.uuid4(),
                        file_bytes=b"x",
                        filename=long_name,
                        mime_type="text/plain",
                    )

            self.assertEqual(self._file_dirs(storage_dir), [])
            db.add.assert_not_called()

    def test_store_file_sync_keeps_the_file_when_the_row_is_flushed(self) -> None:
        db = MagicMock()

        with tempfile.TemporaryDirectory() as storage_dir:
            with patch("app.services.file_storage._storage_root", return_value=Path(storage_dir)):
                row, token = store_file_sync(
                    db,
                    owner_id=uuid.uuid4(),
                    file_bytes=b"x",
                    filename="a.txt",
                    mime_type="text/plain",
                )

            self.assertEqual(len(self._files(storage_dir)), 1)
            self.assertEqual(row.filename, "a.txt")
            self.assertTrue(token)


if __name__ == "__main__":
    unittest.main()
