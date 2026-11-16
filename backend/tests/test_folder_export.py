import io
import json
import unittest
import zipfile

from app.api.folders import _build_zip_bytes


class BuildZipBytesTests(unittest.TestCase):
    def _load_zip(self, data: bytes) -> dict[str, bytes]:
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf) as zf:
            return {name: zf.read(name) for name in zf.namelist()}

    def test_single_folder_single_workflow(self) -> None:
        data = _build_zip_bytes(
            folder_name="MyFolder",
            workflows=[{"name": "WF1", "nodes": [{"id": "n1"}], "edges": []}],
            children=[],
        )
        files = self._load_zip(data)
        self.assertIn("MyFolder/WF1.json", files)
        payload = json.loads(files["MyFolder/WF1.json"])
        self.assertEqual(payload["name"], "WF1")
        self.assertEqual(payload["nodes"], [{"id": "n1"}])
        self.assertEqual(payload["edges"], [])

    def test_nested_subfolder(self) -> None:
        data = _build_zip_bytes(
            folder_name="Root",
            workflows=[],
            children=[
                {
                    "name": "Child",
                    "workflows": [{"name": "WF2", "nodes": [], "edges": []}],
                    "children": [],
                }
            ],
        )
        files = self._load_zip(data)
        self.assertIn("Root/Child/WF2.json", files)

    def test_slash_in_name_is_sanitized(self) -> None:
        data = _build_zip_bytes(
            folder_name="My/Folder",
            workflows=[{"name": "A/B", "nodes": [], "edges": []}],
            children=[],
        )
        files = self._load_zip(data)
        self.assertIn("My_Folder/A_B.json", files)

    def test_empty_folder_produces_valid_zip(self) -> None:
        data = _build_zip_bytes(
            folder_name="Empty",
            workflows=[],
            children=[],
        )
        files = self._load_zip(data)
        self.assertEqual(files, {})

    def test_multiple_workflows_in_folder(self) -> None:
        data = _build_zip_bytes(
            folder_name="Multi",
            workflows=[
                {"name": "Alpha", "nodes": [], "edges": []},
                {"name": "Beta", "nodes": [], "edges": []},
            ],
            children=[],
        )
        files = self._load_zip(data)
        self.assertIn("Multi/Alpha.json", files)
        self.assertIn("Multi/Beta.json", files)

    def test_workflows_with_the_same_name_each_get_a_file(self) -> None:
        data = _build_zip_bytes(
            folder_name="Support",
            workflows=[
                {"name": "New Workflow", "nodes": [{"id": "first"}], "edges": []},
                {"name": "New Workflow", "nodes": [{"id": "second"}], "edges": []},
                {"name": "new workflow", "nodes": [{"id": "third"}], "edges": []},
            ],
            children=[],
        )
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        files = self._load_zip(data)

        self.assertEqual(
            names,
            [
                "Support/New Workflow.json",
                "Support/New Workflow (2).json",
                "Support/new workflow (3).json",
            ],
        )
        # The name inside the file is unchanged, so an import restores the original name.
        self.assertEqual(
            [json.loads(files[name])["name"] for name in names],
            ["New Workflow", "New Workflow", "new workflow"],
        )
        self.assertEqual(
            [json.loads(files[name])["nodes"][0]["id"] for name in names],
            ["first", "second", "third"],
        )

    def test_sibling_folders_with_the_same_name_stay_apart(self) -> None:
        data = _build_zip_bytes(
            folder_name="Root",
            workflows=[],
            children=[
                {
                    "name": "Archive",
                    "workflows": [{"name": "Daily", "nodes": [{"id": "a"}], "edges": []}],
                    "children": [],
                },
                {
                    "name": "Archive",
                    "workflows": [{"name": "Daily", "nodes": [{"id": "b"}], "edges": []}],
                    "children": [],
                },
            ],
        )
        files = self._load_zip(data)

        self.assertEqual(sorted(files), ["Root/Archive (2)/Daily.json", "Root/Archive/Daily.json"])
        self.assertEqual(json.loads(files["Root/Archive/Daily.json"])["nodes"], [{"id": "a"}])
        self.assertEqual(json.loads(files["Root/Archive (2)/Daily.json"])["nodes"], [{"id": "b"}])

    def test_a_workflow_and_a_folder_may_share_a_name(self) -> None:
        data = _build_zip_bytes(
            folder_name="Root",
            workflows=[{"name": "Reports", "nodes": [], "edges": []}],
            children=[
                {
                    "name": "Reports",
                    "workflows": [{"name": "Weekly", "nodes": [], "edges": []}],
                    "children": [],
                }
            ],
        )

        self.assertEqual(
            sorted(self._load_zip(data)), ["Root/Reports.json", "Root/Reports/Weekly.json"]
        )
