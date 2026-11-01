"""File sandbox workspace: layout, input copies, output collection and its refusals."""

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.services.file_sandbox.manifest import DriveFileRef
from app.services.file_sandbox.workspace import FileWorkspace, WorkspaceQuotaError


def _ref(source: Path, name: str = "report.xlsx", size: int | None = None) -> DriveFileRef:
    return DriveFileRef(
        id=uuid.uuid4(),
        name=name,
        mime="application/octet-stream",
        size=source.stat().st_size if size is None else size,
        created_at=datetime.now(timezone.utc),
        source="manual upload",
        workflow_id=None,
        shared=False,
        storage_path=source,
    )


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = FileWorkspace(self.root / "ws", owner_id=uuid.uuid4())
        self.ws.ensure()
        self.drive_file = self.root / "drive.bin"
        self.drive_file.write_bytes(b"col1,col2\n1,2\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class LayoutTests(WorkspaceTestCase):
    def test_input_and_work_are_siblings(self) -> None:
        self.assertEqual(self.ws.in_dir.parent, self.ws.work_dir.parent)
        self.assertFalse(self.ws.in_dir.is_relative_to(self.ws.work_dir))
        self.assertTrue(self.ws.out_dir.is_dir())

    def test_chat_workspace_is_keyed_by_user_and_conversation(self) -> None:
        conversation = uuid.uuid4()
        with patch("app.services.file_sandbox.workspace.sandbox_root", return_value=self.root):
            alice = FileWorkspace.for_chat(uuid.uuid4(), conversation)
            bob = FileWorkspace.for_chat(uuid.uuid4(), conversation)
        self.assertNotEqual(alice.base, bob.base)
        self.assertIn(conversation.hex, str(alice.base))

    def test_delete_removes_everything(self) -> None:
        self.ws.add_inputs([_ref(self.drive_file)])
        (self.ws.work_dir / "cache.pkl").write_bytes(b"x")
        self.ws.delete()
        self.assertFalse(self.ws.base.exists())


class InputTests(WorkspaceTestCase):
    def test_copies_once_and_indexes_sandbox_paths(self) -> None:
        ref = _ref(self.drive_file)
        first = self.ws.add_inputs([ref])
        second = self.ws.add_inputs([ref])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["path"], f"/input/{ref.id.hex}/report.xlsx")
        self.assertEqual(len(self.ws.inputs()), 1)
        copied = self.ws.in_dir / ref.id.hex / "report.xlsx"
        self.assertEqual(copied.read_bytes(), self.drive_file.read_bytes())

    def test_index_carries_no_storage_path(self) -> None:
        self.ws.add_inputs([_ref(self.drive_file)])
        entry = self.ws.inputs()[0]
        self.assertNotIn("storage_path", entry)
        self.assertNotIn(str(self.drive_file), str(entry))

    def test_unsafe_name_is_replaced(self) -> None:
        ref = _ref(self.drive_file, name="../../etc/passwd")
        entry = self.ws.add_inputs([ref])[0]
        self.assertEqual(entry["path"], f"/input/{ref.id.hex}/file")

    def test_prune_removes_only_files_no_longer_reachable(self) -> None:
        kept = _ref(self.drive_file, name="kept.csv")
        revoked = _ref(self.drive_file, name="revoked.csv")
        self.ws.add_inputs([kept, revoked])
        removed = self.ws.prune({kept.id})
        self.assertEqual(removed, ["revoked.csv"])
        self.assertEqual(self.ws.input_ids(), {kept.id})
        self.assertFalse((self.ws.in_dir / revoked.id.hex).exists())

    def test_quota_refuses_copies_past_the_limit(self) -> None:
        huge = _ref(self.drive_file, size=3 * 1024**3)
        with self.assertRaises(WorkspaceQuotaError):
            self.ws.add_inputs([huge])


class CollectTests(WorkspaceTestCase):
    def test_regular_file_is_collected_and_removed(self) -> None:
        (self.ws.out_dir / "summary.csv").write_bytes(b"a,b\n")
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual([(c.name, c.data) for c in collected], [("summary.csv", b"a,b\n")])
        self.assertEqual(collected[0].mime, "text/csv")
        self.assertEqual(rejected, [])
        self.assertFalse((self.ws.out_dir / "summary.csv").exists())

    def test_symlink_to_a_host_file_is_rejected(self) -> None:
        secret = self.root / "secret.txt"
        secret.write_text("SECRET_KEY=abc")
        os.symlink(secret, self.ws.out_dir / "leak.txt")
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual(collected, [])
        self.assertTrue(any(r.startswith("leak.txt") for r in rejected))

    def test_hardlink_is_rejected(self) -> None:
        secret = self.ws.work_dir / "inner.txt"
        secret.write_text("x")
        os.link(secret, self.ws.out_dir / "linked.txt")
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual(collected, [])
        self.assertIn("linked.txt: hard links are not collected", rejected)

    def test_fifo_and_directories_are_rejected(self) -> None:
        os.mkfifo(self.ws.out_dir / "pipe")
        (self.ws.out_dir / "nested").mkdir()
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual(collected, [])
        self.assertEqual(len(rejected), 2)

    def test_out_replaced_by_a_link_is_not_followed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "host.txt").write_text("host data")
        os.rmdir(self.ws.out_dir)
        os.symlink(outside, self.ws.out_dir)
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual(collected, [])
        self.assertTrue(rejected)
        self.assertTrue((outside / "host.txt").exists())
        self.assertFalse(self.ws.out_dir.is_symlink())

    def test_oversized_file_is_rejected(self) -> None:
        with patch("app.services.file_sandbox.workspace.MAX_OUTPUT_FILE_BYTES", 4):
            (self.ws.out_dir / "big.bin").write_bytes(b"12345")
            collected, rejected = self.ws.collect_outputs()
        self.assertEqual(collected, [])
        self.assertIn("big.bin: larger than 100 MB", rejected)

    def test_file_count_is_capped(self) -> None:
        with patch("app.services.file_sandbox.workspace.MAX_OUTPUT_FILES", 2):
            for index in range(3):
                (self.ws.out_dir / f"f{index}.txt").write_text("x")
            collected, rejected = self.ws.collect_outputs()
        self.assertEqual(len(collected), 2)
        self.assertEqual(len(rejected), 1)


class UsageTests(WorkspaceTestCase):
    def test_link_counts_as_itself_not_its_target(self) -> None:
        big = self.root / "big.bin"
        big.write_bytes(b"x" * 100_000)
        os.symlink(big, self.ws.work_dir / "big-link")
        self.assertLess(self.ws.usage_bytes(), 10_000)

    def test_work_summary_lists_scratch_but_not_out(self) -> None:
        (self.ws.work_dir / "sales.pkl").write_bytes(b"x" * 10)
        summary = self.ws.work_summary()
        self.assertEqual(summary, [{"path": "/work/sales.pkl", "size": 10}])


if __name__ == "__main__":
    unittest.main()
