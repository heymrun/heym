"""Unit tests for optional Drive file access in Python skills."""

import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.skill_python_executor import execute_skill_python


def _skill_file(source: str) -> list[dict[str, str]]:
    """Return a minimal executable skill bundle."""

    return [{"path": "main.py", "content": source}]


class SkillPythonExecutorDriveTests(unittest.TestCase):
    """Verify the generated heym_drive helper for enabled skills."""

    def test_drive_helper_reads_accessible_files_by_id_and_filename(self) -> None:
        new_file_id = str(uuid.uuid4())
        old_file_id = str(uuid.uuid4())
        script = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def execute(params: dict, files: dict) -> dict:
    from heym_drive import (
        get_drive_file,
        get_drive_file_path,
        list_drive_files,
        read_drive_base64,
        read_drive_text,
    )

    newest = get_drive_file(filename="report.txt")
    matches = list_drive_files(filename="report.txt")
    return {
        "newest_id": newest["id"],
        "newest_text": read_drive_text(filename="report.txt"),
        "newest_text_from_file_id_arg": read_drive_text(file_id="report.txt"),
        "old_text": read_drive_text(file_id=params["old_file_id"]),
        "old_base64": read_drive_base64(file_id=params["old_file_id"]),
        "matches": [item["id"] for item in matches],
        "path_exists": Path(get_drive_file_path(filename="report.txt")).exists(),
    }


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    params = json.loads(raw) if raw else {}
    print(json.dumps(execute(params, {}), default=str))
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            new_path = root / "new-report.txt"
            old_path = root / "old-report.txt"
            new_path.write_text("new contents", encoding="utf-8")
            old_path.write_text("old contents", encoding="utf-8")

            result = execute_skill_python(
                _skill_file(script),
                {"old_file_id": old_file_id},
                drive_files=[
                    {
                        "id": old_file_id,
                        "filename": "report.txt",
                        "mime_type": "text/plain",
                        "size_bytes": old_path.stat().st_size,
                        "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                        "source_path": str(old_path),
                    },
                    {
                        "id": new_file_id,
                        "filename": "report.txt",
                        "mime_type": "text/plain",
                        "size_bytes": new_path.stat().st_size,
                        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                        "source_path": str(new_path),
                    },
                ],
            )

        self.assertEqual(result.output["newest_id"], new_file_id)
        self.assertEqual(result.output["newest_text"], "new contents")
        self.assertEqual(result.output["newest_text_from_file_id_arg"], "new contents")
        self.assertEqual(result.output["old_text"], "old contents")
        self.assertEqual(result.output["old_base64"], "b2xkIGNvbnRlbnRz")
        self.assertEqual(result.output["matches"], [new_file_id, old_file_id])
        self.assertTrue(result.output["path_exists"])

    def test_drive_helper_is_unavailable_when_drive_files_are_disabled(self) -> None:
        script = """#!/usr/bin/env python3
import json
import sys


def execute(params: dict, files: dict) -> dict:
    try:
        import heym_drive  # noqa: F401
    except ModuleNotFoundError as exc:
        return {"available": False, "error": str(exc)}
    return {"available": True}


if __name__ == "__main__":
    print(json.dumps(execute({}, {}), default=str))
"""

        result = execute_skill_python(_skill_file(script), {})

        self.assertEqual(result.output["available"], False)
        self.assertIn("heym_drive", result.output["error"])
