"""Unit tests for Drive Node — file id in _generated_files and executor operations."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Task 1 — _persist_skill_files must include 'id' in each file_links entry
# ---------------------------------------------------------------------------


class GeneratedFilesIdTests(unittest.TestCase):
    """_persist_skill_files must include 'id' in each file_links entry."""

    def test_file_links_contain_id(self) -> None:
        """Each entry in _generated_files must have a non-empty 'id' field."""
        file_uuid = uuid.uuid4()
        owner_uuid = uuid.uuid4()
        token_str = "testtoken123"

        generated_files = [
            {"filename": "report.pdf", "file_bytes": b"PDF", "mime_type": "application/pdf"}
        ]

        # Build a fake sync DB session matching the SessionLocal() context-manager pattern
        fake_db = MagicMock()
        fake_db.__enter__ = MagicMock(return_value=fake_db)
        fake_db.__exit__ = MagicMock(return_value=False)
        fake_db.flush = MagicMock()
        fake_db.commit = MagicMock()
        fake_db.rollback = MagicMock()

        # Capture rows added so we can inspect them
        rows_added: list = []
        fake_db.add.side_effect = lambda obj: rows_added.append(obj)

        with (
            patch("app.db.session.SessionLocal", return_value=fake_db),
            patch("uuid.uuid4", return_value=file_uuid),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch(
                "app.services.file_storage.build_download_url",
                return_value="/api/files/dl/testtoken123",
            ),
            patch("secrets.token_urlsafe", return_value=token_str),
        ):
            mock_path = MagicMock()
            mock_path.parent.mkdir = MagicMock()
            mock_path.write_bytes = MagicMock()
            mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

            from app.services.llm_service import _persist_skill_files

            links = _persist_skill_files(
                generated_files,
                owner_id=str(owner_uuid),
                workflow_id=None,
                node_id=None,
                node_label=None,
            )

        self.assertEqual(len(links), 1)
        self.assertIn("id", links[0], "'id' key missing from _generated_files entry")
        self.assertEqual(links[0]["id"], str(file_uuid))
        self.assertIn("filename", links[0])
        self.assertIn("download_url", links[0])

    def test_multiple_files_all_have_id(self) -> None:
        """All entries in _generated_files must have distinct 'id' fields."""
        owner_uuid = uuid.uuid4()
        uuids = [uuid.uuid4(), uuid.uuid4()]
        call_count = 0

        def side_uuid():
            nonlocal call_count
            result = uuids[call_count % len(uuids)]
            call_count += 1
            return result

        generated_files = [
            {"filename": "a.pdf", "file_bytes": b"A", "mime_type": "application/pdf"},
            {"filename": "b.csv", "file_bytes": b"B", "mime_type": "text/csv"},
        ]

        fake_db = MagicMock()
        fake_db.__enter__ = MagicMock(return_value=fake_db)
        fake_db.__exit__ = MagicMock(return_value=False)
        fake_db.flush = MagicMock()
        fake_db.commit = MagicMock()
        fake_db.rollback = MagicMock()
        fake_db.add = MagicMock()

        with (
            patch("app.db.session.SessionLocal", return_value=fake_db),
            patch("uuid.uuid4", side_effect=side_uuid),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch("app.services.file_storage.build_download_url", return_value="/api/files/dl/tok"),
            patch("secrets.token_urlsafe", return_value="tok"),
        ):
            mock_path = MagicMock()
            mock_path.parent.mkdir = MagicMock()
            mock_path.write_bytes = MagicMock()
            mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

            from app.services.llm_service import _persist_skill_files

            links = _persist_skill_files(
                generated_files,
                owner_id=str(owner_uuid),
                workflow_id=None,
                node_id=None,
                node_label=None,
            )

        self.assertEqual(len(links), 2)
        for link in links:
            self.assertIn("id", link)
        ids = [link["id"] for link in links]
        self.assertEqual(len(set(ids)), 2, "File IDs should be distinct")


# ---------------------------------------------------------------------------
# Task 2/3 — Drive Node executor (delete + set* operations via full executor)
# ---------------------------------------------------------------------------


def _make_workflow(drive_data: dict) -> tuple[list, list]:
    """Return (nodes, edges) for a minimal textInput → drive workflow."""
    nodes = [
        {
            "id": "n1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "n2",
            "type": "drive",
            "data": drive_data,
        },
        {"id": "n3", "type": "output", "data": {"label": "output"}},
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ]
    return nodes, edges


def _run_drive_workflow(
    drive_data: dict,
    owner_id: uuid.UUID,
    db_mock: MagicMock,
) -> dict:
    """Execute a textInput → drive workflow and return the drive node output."""
    from app.services.workflow_executor import WorkflowExecutor

    nodes, edges = _make_workflow(drive_data)
    executor = WorkflowExecutor(nodes=nodes, edges=edges)
    executor.trace_user_id = owner_id

    with (
        patch("app.db.session.SessionLocal", return_value=db_mock),
        patch("app.services.file_storage._storage_root") as mock_root,
        patch(
            "app.services.file_storage.build_download_url",
            return_value="/api/files/dl/newtoken",
        ),
    ):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
        )

    drive_nr = next((nr for nr in result.node_results if nr["node_type"] == "drive"), None)
    if drive_nr is None:
        raise AssertionError(
            f"Drive node result not found. Status={result.status}. "
            f"Errors: {[nr for nr in result.node_results if nr.get('status') == 'error']}"
        )
    return drive_nr


def _make_db_mock(
    file_row: object | None,
    default_token: object | None = None,
) -> MagicMock:
    """Build a fake sync SessionLocal context-manager mock."""
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)

    side_effects: list = [file_row, default_token]

    fake_db.query.return_value.filter.return_value.first.side_effect = side_effects
    fake_db.delete = MagicMock()
    fake_db.flush = MagicMock()
    fake_db.commit = MagicMock()
    fake_db.rollback = MagicMock()

    added_objects: list = []
    fake_db.add.side_effect = lambda obj: added_objects.append(obj)
    fake_db._added = added_objects
    deleted_objects: list = []
    fake_db._deleted = deleted_objects
    fake_db.delete.side_effect = lambda obj: deleted_objects.append(obj)
    return fake_db


def _make_get_all_db_mock(file_rows: list[object]) -> MagicMock:
    """Build a fake SessionLocal mock for Drive getAll list queries."""
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)

    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = file_rows
    fake_db.query.return_value = query
    fake_db._query = query
    return fake_db


class DriveNodeDeleteTests(unittest.TestCase):
    """Drive node delete operation."""

    def test_delete_own_file_success(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="report.pdf",
            storage_path=f"{owner_id}/{file_id}/report.pdf",
        )
        db = _make_db_mock(file_row)

        nr = _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "delete",
                "driveFileId": str(file_id),
            },
            owner_id,
            db,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["status"], "success")
        self.assertEqual(nr["output"]["operation"], "delete")
        self.assertEqual(nr["output"]["file_id"], str(file_id))
        self.assertEqual(nr["output"]["filename"], "report.pdf")
        self.assertNotIn("download_url", nr["output"])

    def test_delete_file_not_found_raises(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        db = _make_db_mock(None)  # file not found

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "delete",
                "driveFileId": str(file_id),
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((nr for nr in result.node_results if nr["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")
        self.assertIn("not found", drive_nr["error"].lower())

    def test_delete_invalid_uuid_raises(self) -> None:
        owner_id = uuid.uuid4()
        db = _make_db_mock(None)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "delete",
                "driveFileId": "not-a-uuid",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((nr for nr in result.node_results if nr["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")


class DriveNodeSetPasswordTests(unittest.TestCase):
    """Drive node setPassword operation."""

    def test_set_password_returns_success(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="doc.pdf",
            storage_path=f"{owner_id}/{file_id}/doc.pdf",
        )
        db = _make_db_mock(file_row, default_token=None)

        nr = _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setPassword",
                "driveFileId": str(file_id),
                "drivePassword": "secret123",
            },
            owner_id,
            db,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "setPassword")
        self.assertIn("download_url", nr["output"])

    def test_set_password_new_token_has_basic_auth(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="doc.pdf",
            storage_path=f"{owner_id}/{file_id}/doc.pdf",
        )
        db = _make_db_mock(file_row, default_token=None)

        _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setPassword",
                "driveFileId": str(file_id),
                "drivePassword": "hunter2",
            },
            owner_id,
            db,
        )

        # A FileAccessToken should have been added with basic auth fields
        self.assertEqual(len(db._added), 1)
        new_token = db._added[0]
        self.assertEqual(new_token.basic_auth_username, "file")
        self.assertIsNotNone(new_token.basic_auth_password_hash)

    def test_set_password_replaces_existing_default_token(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="f.pdf",
            storage_path=f"{owner_id}/{file_id}/f.pdf",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(), file_id=file_id, basic_auth_password_hash=None
        )
        db = _make_db_mock(file_row, default_token=default_token)

        _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setPassword",
                "driveFileId": str(file_id),
                "drivePassword": "pw",
            },
            owner_id,
            db,
        )

        self.assertIn(default_token, db._deleted)


class DriveNodeSetTtlTests(unittest.TestCase):
    """Drive node setTtl operation."""

    def test_set_ttl_creates_token_with_expiry(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="data.csv",
            storage_path=f"{owner_id}/{file_id}/data.csv",
        )
        db = _make_db_mock(file_row, default_token=None)

        _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setTtl",
                "driveFileId": str(file_id),
                "driveTtlHours": 48,
            },
            owner_id,
            db,
        )

        self.assertEqual(len(db._added), 1)
        new_token = db._added[0]
        self.assertIsNotNone(new_token.expires_at)
        self.assertIsNone(new_token.basic_auth_password_hash)

    def test_set_ttl_output_contains_download_url(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="img.png",
            storage_path=f"{owner_id}/{file_id}/img.png",
        )
        db = _make_db_mock(file_row, default_token=None)

        nr = _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setTtl",
                "driveFileId": str(file_id),
                "driveTtlHours": 24,
            },
            owner_id,
            db,
        )

        self.assertEqual(nr["output"]["status"], "success")
        self.assertIn("download_url", nr["output"])

    def test_set_ttl_replaces_existing_default_token(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="img.png",
            storage_path=f"{owner_id}/{file_id}/img.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(), file_id=file_id, basic_auth_password_hash=None
        )
        db = _make_db_mock(file_row, default_token=default_token)

        _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setTtl",
                "driveFileId": str(file_id),
                "driveTtlHours": 12,
            },
            owner_id,
            db,
        )

        self.assertIn(default_token, db._deleted)


class DriveNodeSetMaxDownloadsTests(unittest.TestCase):
    """Drive node setMaxDownloads operation."""

    def test_set_max_downloads_creates_limited_token(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="archive.zip",
            storage_path=f"{owner_id}/{file_id}/archive.zip",
        )
        db = _make_db_mock(file_row, default_token=None)

        _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setMaxDownloads",
                "driveFileId": str(file_id),
                "driveMaxDownloads": 5,
            },
            owner_id,
            db,
        )

        self.assertEqual(len(db._added), 1)
        new_token = db._added[0]
        self.assertEqual(new_token.max_downloads, 5)
        self.assertIsNone(new_token.basic_auth_password_hash)
        self.assertIsNone(new_token.expires_at)

    def test_set_max_downloads_output_has_download_url(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="f.txt",
            storage_path=f"{owner_id}/{file_id}/f.txt",
        )
        db = _make_db_mock(file_row, default_token=None)

        nr = _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setMaxDownloads",
                "driveFileId": str(file_id),
                "driveMaxDownloads": 1,
            },
            owner_id,
            db,
        )

        self.assertEqual(nr["output"]["status"], "success")
        self.assertEqual(nr["output"]["operation"], "setMaxDownloads")
        self.assertIn("download_url", nr["output"])

    def test_set_max_downloads_replaces_default_token(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="f.txt",
            storage_path=f"{owner_id}/{file_id}/f.txt",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(), file_id=file_id, basic_auth_password_hash=None
        )
        db = _make_db_mock(file_row, default_token=default_token)

        _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "setMaxDownloads",
                "driveFileId": str(file_id),
                "driveMaxDownloads": 3,
            },
            owner_id,
            db,
        )

        self.assertIn(default_token, db._deleted)


class DriveNodeErrorCaseTests(unittest.TestCase):
    """Drive node error handling."""

    def _run_expect_error(self, drive_data: dict, owner_id: uuid.UUID, db: MagicMock) -> dict:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(drive_data)
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((nr for nr in result.node_results if nr["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        return drive_nr

    def test_missing_operation_results_in_error(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        db = _make_db_mock(None)
        nr = self._run_expect_error(
            {"label": "drive", "driveOperation": "", "driveFileId": str(file_id)},
            owner_id,
            db,
        )
        self.assertEqual(nr["status"], "error")

    def test_invalid_uuid_results_in_error(self) -> None:
        owner_id = uuid.uuid4()
        db = _make_db_mock(None)
        nr = self._run_expect_error(
            {"label": "drive", "driveOperation": "delete", "driveFileId": "not-a-uuid"},
            owner_id,
            db,
        )
        self.assertEqual(nr["status"], "error")

    def test_file_not_found_results_in_error(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        db = _make_db_mock(None)
        nr = self._run_expect_error(
            {"label": "drive", "driveOperation": "delete", "driveFileId": str(file_id)},
            owner_id,
            db,
        )
        self.assertEqual(nr["status"], "error")
        self.assertIn("not found", nr["error"].lower())


class DriveNodeGetTests(unittest.TestCase):
    """Drive node get operation."""

    def test_get_returns_metadata_only(self) -> None:
        """get without driveIncludeBinary returns id/filename/mime_type/size_bytes/download_url, no file_base64."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="photo.png",
            mime_type="image/png",
            size_bytes=12345,
            storage_path=f"{owner_id}/{file_id}/photo.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(),
            file_id=file_id,
            token="tok123",
            basic_auth_password_hash=None,
        )
        db = _make_db_mock(file_row, default_token=default_token)

        nr = _run_drive_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
            },
            owner_id,
            db,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "get")
        self.assertEqual(nr["output"]["id"], str(file_id))
        self.assertEqual(nr["output"]["filename"], "photo.png")
        self.assertEqual(nr["output"]["mime_type"], "image/png")
        self.assertEqual(nr["output"]["size_bytes"], 12345)
        self.assertIn("download_url", nr["output"])
        self.assertNotIn("file_base64", nr["output"])

    def test_get_with_binary_returns_base64(self) -> None:
        """get with driveIncludeBinary=True returns file_base64 as valid base64."""
        import base64

        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_content = b"fake-image-bytes"
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="img.png",
            mime_type="image/png",
            size_bytes=len(file_content),
            storage_path=f"{owner_id}/{file_id}/img.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(),
            file_id=file_id,
            token="tok456",
            basic_auth_password_hash=None,
        )
        db = _make_db_mock(file_row, default_token=default_token)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
                "driveIncludeBinary": True,
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch(
                "app.services.file_storage.build_download_url",
                return_value="/api/files/dl/tok456",
            ),
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_bytes.return_value = file_content
            mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "success")
        self.assertIn("file_base64", nr["output"])
        decoded = base64.b64decode(nr["output"]["file_base64"])
        self.assertEqual(decoded, file_content)

    def test_get_wrong_owner_raises(self) -> None:
        """get for file owned by another user results in error."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        db = _make_db_mock(None)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")
        self.assertIn("not found", drive_nr["error"].lower())

    def test_get_nonexistent_file_raises(self) -> None:
        """get with invalid UUID results in error."""
        owner_id = uuid.uuid4()
        db = _make_db_mock(None)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": "not-a-uuid",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")

    def test_get_binary_missing_file_on_disk_raises(self) -> None:
        """get with binary when file is missing from disk results in error."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="gone.png",
            mime_type="image/png",
            size_bytes=0,
            storage_path=f"{owner_id}/{file_id}/gone.png",
        )
        default_token = SimpleNamespace(
            id=uuid.uuid4(), file_id=file_id, token="tok789", basic_auth_password_hash=None
        )
        db = _make_db_mock(file_row, default_token=default_token)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "drive",
                "driveOperation": "get",
                "driveFileId": str(file_id),
                "driveIncludeBinary": True,
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        drive_nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(drive_nr)
        self.assertEqual(drive_nr["status"], "error")


class DriveNodeGetAllTests(unittest.TestCase):
    """Drive node getAll operation."""

    def test_get_all_returns_file_metadata_list(self) -> None:
        """getAll returns the owner's file metadata without file contents."""
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        first_file_id = uuid.uuid4()
        second_file_id = uuid.uuid4()
        file_rows = [
            SimpleNamespace(
                id=first_file_id,
                owner_id=owner_id,
                filename="report.pdf",
                mime_type="application/pdf",
                size_bytes=45231,
                workflow_id=workflow_id,
                source_node_label="generateReport",
                metadata_json={"page_count": 3},
                created_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
                access_tokens=[
                    SimpleNamespace(token="tok-report", basic_auth_password_hash=None),
                ],
            ),
            SimpleNamespace(
                id=second_file_id,
                owner_id=owner_id,
                filename="image.png",
                mime_type="image/png",
                size_bytes=12345,
                workflow_id=None,
                source_node_label=None,
                metadata_json={},
                created_at=datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc),
                access_tokens=[],
            ),
        ]
        db = _make_get_all_db_mock(file_rows)

        nr = _run_drive_workflow(
            {"label": "drive", "driveOperation": "getAll"},
            owner_id,
            db,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "getAll")
        self.assertEqual(nr["output"]["count"], 2)
        self.assertEqual(len(nr["output"]["files"]), 2)
        self.assertEqual(nr["output"]["files"][0]["id"], str(first_file_id))
        self.assertEqual(nr["output"]["files"][0]["filename"], "report.pdf")
        self.assertEqual(nr["output"]["files"][0]["size_bytes"], 45231)
        self.assertEqual(nr["output"]["files"][0]["workflow_id"], str(workflow_id))
        self.assertEqual(nr["output"]["files"][0]["source_node_label"], "generateReport")
        self.assertEqual(nr["output"]["files"][0]["metadata"], {"page_count": 3})
        self.assertEqual(nr["output"]["files"][0]["download_url"], "/api/files/dl/newtoken")
        self.assertEqual(nr["output"]["files"][1]["download_url"], "")
        self.assertNotIn("file_base64", nr["output"]["files"][0])
        db._query.all.assert_called_once()


class DriveNodeDownloadUrlTests(unittest.TestCase):
    """Drive node downloadUrl operation."""

    def _run_download_workflow(
        self,
        drive_data: dict,
        owner_id: uuid.UUID,
        db_mock: MagicMock,
        http_response: MagicMock,
        storage_path_mock: MagicMock,
    ) -> dict:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(drive_data)
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db_mock),
            patch("app.services.file_storage._safe_storage_path", return_value=storage_path_mock),
            patch(
                "app.services.file_storage.build_download_url",
                return_value="https://heym.run/api/files/dl/dltoken",
            ),
            patch(
                "app.services.workflow_executor.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ),
            patch("httpx.Client") as mock_client_cls,
            patch("secrets.token_urlsafe", return_value="dltoken"),
        ):
            mock_client_cls.return_value.__enter__.return_value.get.return_value = http_response

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        if nr is None:
            raise AssertionError(f"Drive node result not found. Status={result.status}")
        return nr

    def _make_http_response(
        self,
        content: bytes,
        content_type: str = "application/octet-stream",
        content_disposition: str = "",
    ) -> MagicMock:
        resp = MagicMock()
        resp.content = content
        resp.status_code = 200
        resp.headers = {
            "content-type": content_type,
            "content-disposition": content_disposition,
        }
        resp.raise_for_status = MagicMock()
        return resp

    def _make_storage_path(self) -> MagicMock:
        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_path.write_bytes = MagicMock()
        return mock_path

    def test_download_url_stores_file_and_returns_metadata(self) -> None:
        """downloadUrl fetches URL, stores file, returns metadata with download_url."""
        owner_id = uuid.uuid4()
        file_bytes = b"fake-image-content"
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.add = MagicMock()

        http_resp = self._make_http_response(
            file_bytes,
            content_type="image/png",
            content_disposition='attachment; filename="photo.png"',
        )
        storage_path = self._make_storage_path()

        nr = self._run_download_workflow(
            {
                "label": "dl",
                "driveOperation": "downloadUrl",
                "driveSourceUrl": "https://example.com/photo.png",
            },
            owner_id,
            db,
            http_resp,
            storage_path,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "downloadUrl")
        self.assertEqual(nr["output"]["filename"], "photo.png")
        self.assertEqual(nr["output"]["mime_type"], "image/png")
        self.assertEqual(nr["output"]["size_bytes"], len(file_bytes))
        self.assertIn("download_url", nr["output"])
        self.assertIn("id", nr["output"])

    def test_download_url_filename_from_url_path(self) -> None:
        """When Content-Disposition is absent, filename is taken from the URL path."""
        owner_id = uuid.uuid4()
        file_bytes = b"csv-data"
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.add = MagicMock()

        http_resp = self._make_http_response(file_bytes, content_type="text/csv")
        storage_path = self._make_storage_path()

        nr = self._run_download_workflow(
            {
                "label": "dl",
                "driveOperation": "downloadUrl",
                "driveSourceUrl": "https://example.com/exports/data.csv",
            },
            owner_id,
            db,
            http_resp,
            storage_path,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["filename"], "data.csv")

    def test_download_url_rejects_unsafe_content_disposition_filename(self) -> None:
        """Remote filenames cannot escape the generated-file directory."""
        owner_id = uuid.uuid4()
        file_bytes = b"evil"
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.add = MagicMock()

        http_resp = self._make_http_response(
            file_bytes,
            content_type="text/plain",
            content_disposition='attachment; filename="../evil.txt"',
        )
        storage_path = self._make_storage_path()

        nr = self._run_download_workflow(
            {
                "label": "dl",
                "driveOperation": "downloadUrl",
                "driveSourceUrl": "https://example.com/file.txt",
            },
            owner_id,
            db,
            http_resp,
            storage_path,
        )

        self.assertEqual(nr["status"], "error")
        self.assertIn("Filename cannot contain path components", nr["error"])
        storage_path.write_bytes.assert_not_called()

    def test_download_url_rejects_private_ip_before_fetch(self) -> None:
        """Private/internal targets are blocked before httpx connects."""
        from app.services.workflow_executor import WorkflowExecutor

        owner_id = uuid.uuid4()
        nodes, edges = _make_workflow(
            {
                "label": "dl",
                "driveOperation": "downloadUrl",
                "driveSourceUrl": "http://127.0.0.1/metadata",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with patch("httpx.Client") as mock_client_cls:
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("globally routable", nr["error"])
        mock_client_cls.assert_not_called()

    def test_download_url_rejects_non_global_resolved_address_before_fetch(self) -> None:
        """Non-global DNS answers such as carrier-grade NAT are blocked."""
        from app.services.workflow_executor import WorkflowExecutor

        owner_id = uuid.uuid4()
        nodes, edges = _make_workflow(
            {
                "label": "dl",
                "driveOperation": "downloadUrl",
                "driveSourceUrl": "https://example.com/metadata",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch(
                "app.services.workflow_executor.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("100.64.0.1", 0))],
            ),
            patch("httpx.Client") as mock_client_cls,
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("globally routable", nr["error"])
        mock_client_cls.assert_not_called()

    def test_download_url_connects_to_validated_address_with_original_host(self) -> None:
        """The validated address is pinned for the HTTP request."""
        from app.services.workflow_executor import _fetch_drive_download_url

        response = self._make_http_response(b"ok", content_type="text/plain")
        client = MagicMock()
        client.get.return_value = response
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "app.services.workflow_executor.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ) as mock_getaddrinfo,
            patch("httpx.Client", return_value=client),
        ):
            result = _fetch_drive_download_url("https://example.com/downloads/file.txt")

        self.assertIs(result, response)
        mock_getaddrinfo.assert_called_once()
        client.get.assert_called_once_with(
            "https://93.184.216.34/downloads/file.txt",
            headers={"Host": "example.com"},
            extensions={"sni_hostname": "example.com"},
        )

    def test_download_url_rejects_redirect_to_private_ip_before_following(self) -> None:
        """Redirect targets are validated before a follow-up request is made."""
        from app.services.workflow_executor import _fetch_drive_download_url

        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"location": "http://127.0.0.1/metadata"}
        redirect_resp.raise_for_status = MagicMock()

        client = MagicMock()
        client.get.return_value = redirect_resp
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=client):
            with self.assertRaisesRegex(ValueError, "globally routable"):
                _fetch_drive_download_url("http://93.184.216.34/start")

        client.get.assert_called_once_with(
            "http://93.184.216.34/start",
            headers={"Host": "93.184.216.34"},
            extensions=None,
        )

    def test_download_url_missing_url_raises(self) -> None:
        """Empty driveSourceUrl results in an error."""
        owner_id = uuid.uuid4()
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {"label": "dl", "driveOperation": "downloadUrl", "driveSourceUrl": ""}
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("url", nr["error"].lower())

    def test_download_url_http_error_propagated(self) -> None:
        """HTTP error from the remote server results in a descriptive error."""
        import httpx

        owner_id = uuid.uuid4()
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "dl",
                "driveOperation": "downloadUrl",
                "driveSourceUrl": "https://example.com/missing.pdf",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404

        def raise_http_error(*_args, **_kwargs):
            raise httpx.HTTPStatusError("Not Found", request=mock_request, response=mock_response)

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
            patch(
                "app.services.workflow_executor.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = raise_http_error

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("404", nr["error"])


class DriveNodeSaveTests(unittest.TestCase):
    """Drive node save operation."""

    def _run_save_workflow(
        self,
        drive_data: dict,
        owner_id: uuid.UUID,
        db_mock: MagicMock,
        storage_path_mock: MagicMock,
    ) -> dict:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(drive_data)
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db_mock),
            patch("app.services.file_storage._safe_storage_path", return_value=storage_path_mock),
            patch(
                "app.services.file_storage.build_download_url",
                return_value="https://heym.run/api/files/dl/savetoken",
            ),
            patch("secrets.token_urlsafe", return_value="savetoken"),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        if nr is None:
            raise AssertionError(f"Drive node result not found. Status={result.status}")
        return nr

    def _make_storage_path(self) -> MagicMock:
        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_path.write_bytes = MagicMock()
        return mock_path

    def _make_db_mock(self) -> MagicMock:
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.flush = MagicMock()
        db.commit = MagicMock()
        db.add = MagicMock()
        return db

    def test_save_stores_decoded_base64(self) -> None:
        """save decodes base64, stores file, and returns metadata with download_url."""
        import base64

        owner_id = uuid.uuid4()
        file_bytes = b"fake-audio-content"
        b64 = base64.b64encode(file_bytes).decode("ascii")

        nr = self._run_save_workflow(
            {
                "label": "save",
                "driveOperation": "save",
                "driveFilename": "1.mp3",
                "driveBase64Content": b64,
            },
            owner_id,
            self._make_db_mock(),
            self._make_storage_path(),
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "save")
        self.assertEqual(nr["output"]["filename"], "1.mp3")
        self.assertEqual(nr["output"]["mime_type"], "audio/mpeg")
        self.assertEqual(nr["output"]["size_bytes"], len(file_bytes))
        self.assertIn("download_url", nr["output"])
        self.assertIn("id", nr["output"])

    def test_save_accepts_data_url_prefix(self) -> None:
        """save accepts data:...;base64,... payloads."""
        import base64

        owner_id = uuid.uuid4()
        file_bytes = b"audio-bytes"
        b64 = base64.b64encode(file_bytes).decode("ascii")
        data_url = f"data:audio/mpeg;base64,{b64}"

        nr = self._run_save_workflow(
            {
                "label": "save",
                "driveOperation": "save",
                "driveFilename": "track.mp3",
                "driveBase64Content": data_url,
            },
            owner_id,
            self._make_db_mock(),
            self._make_storage_path(),
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["size_bytes"], len(file_bytes))

    def test_save_rejects_invalid_base64(self) -> None:
        """Invalid base64 content results in an error."""
        owner_id = uuid.uuid4()

        nr = self._run_save_workflow(
            {
                "label": "save",
                "driveOperation": "save",
                "driveFilename": "1.mp3",
                "driveBase64Content": "not-valid-base64!!!",
            },
            owner_id,
            self._make_db_mock(),
            self._make_storage_path(),
        )

        self.assertEqual(nr["status"], "error")
        self.assertIn("base64", nr["error"].lower())

    def test_save_requires_filename(self) -> None:
        """Empty driveFilename results in an error."""
        import base64

        owner_id = uuid.uuid4()
        b64 = base64.b64encode(b"data").decode("ascii")

        nr = self._run_save_workflow(
            {
                "label": "save",
                "driveOperation": "save",
                "driveFilename": "",
                "driveBase64Content": b64,
            },
            owner_id,
            self._make_db_mock(),
            self._make_storage_path(),
        )

        self.assertEqual(nr["status"], "error")
        self.assertIn("filename", nr["error"].lower())

    def test_save_rejects_unsafe_filename(self) -> None:
        """Path traversal filenames are rejected."""
        import base64

        owner_id = uuid.uuid4()
        b64 = base64.b64encode(b"evil").decode("ascii")

        nr = self._run_save_workflow(
            {
                "label": "save",
                "driveOperation": "save",
                "driveFilename": "../evil.mp3",
                "driveBase64Content": b64,
            },
            owner_id,
            self._make_db_mock(),
            self._make_storage_path(),
        )

        self.assertEqual(nr["status"], "error")
        self.assertIn("path", nr["error"].lower())

    def test_save_rejects_oversized_file(self) -> None:
        """Files larger than the configured limit are rejected."""
        import base64

        owner_id = uuid.uuid4()
        file_bytes = b"x" * (2 * 1024 * 1024)
        b64 = base64.b64encode(file_bytes).decode("ascii")

        with patch("app.config.settings.file_max_size_mb", 1):
            nr = self._run_save_workflow(
                {
                    "label": "save",
                    "driveOperation": "save",
                    "driveFilename": "big.bin",
                    "driveBase64Content": b64,
                },
                owner_id,
                self._make_db_mock(),
                self._make_storage_path(),
            )

        self.assertEqual(nr["status"], "error")
        self.assertIn("size limit", nr["error"].lower())


# ---------------------------------------------------------------------------
# Task — Drive convertFile helper functions
# ---------------------------------------------------------------------------


class DriveConvertHelpersTests(unittest.TestCase):
    """Unit tests for the three module-level helpers used by convertFile."""

    # --- _detect_pandoc_format ---

    def test_detect_markdown_by_mime(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertEqual(_detect_pandoc_format("text/markdown", "doc.md"), "markdown")

    def test_detect_html_by_mime(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertEqual(_detect_pandoc_format("text/html", "page.html"), "html")

    def test_detect_docx_by_mime(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertEqual(
            _detect_pandoc_format(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "doc.docx",
            ),
            "docx",
        )

    def test_detect_plain_by_mime(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertEqual(_detect_pandoc_format("text/plain", "notes.txt"), "markdown")

    def test_detect_csv_by_mime(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertEqual(_detect_pandoc_format("text/csv", "data.csv"), "csv")

    def test_detect_md_by_extension_fallback(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertEqual(_detect_pandoc_format("application/octet-stream", "readme.md"), "markdown")

    def test_detect_unsupported_returns_none(self) -> None:
        from app.services.workflow_executor import _detect_pandoc_format

        self.assertIsNone(_detect_pandoc_format("application/zip", "archive.zip"))

    # --- _extract_pdf_text ---

    def test_extract_pdf_text_returns_string(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.services.workflow_executor import _extract_pdf_text

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Hello from PDF"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = _extract_pdf_text(b"fake-pdf-bytes")

        self.assertEqual(result, "Hello from PDF")

    def test_extract_pdf_text_joins_pages(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.services.workflow_executor import _extract_pdf_text

        pages = [MagicMock(), MagicMock()]
        pages[0].extract_text.return_value = "Page 1"
        pages[1].extract_text.return_value = "Page 2"
        mock_reader = MagicMock()
        mock_reader.pages = pages

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = _extract_pdf_text(b"fake-pdf-bytes")

        self.assertEqual(result, "Page 1\n\nPage 2")

    # --- _convert_image ---

    def test_convert_image_png_to_jpg(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.services.workflow_executor import _convert_image

        fake_output = b"fake-jpeg-bytes"

        mock_img = MagicMock()
        mock_img.mode = "RGB"

        def fake_save(buf, format):
            buf.write(fake_output)

        mock_img.save.side_effect = fake_save
        mock_img.convert.return_value = mock_img

        with patch("PIL.Image.open", return_value=mock_img):
            out_bytes, out_mime = _convert_image(b"png-bytes", "jpg")

        self.assertEqual(out_bytes, fake_output)
        self.assertEqual(out_mime, "image/jpeg")
        mock_img.save.assert_called_once()
        call_kwargs = mock_img.save.call_args
        self.assertEqual(call_kwargs[1]["format"], "JPEG")

    def test_convert_image_unsupported_format_raises(self) -> None:
        from app.services.workflow_executor import _convert_image

        with self.assertRaises(ValueError) as ctx:
            _convert_image(b"bytes", "docx")
        self.assertIn("unsupported image output format", str(ctx.exception))

    def test_convert_image_rgba_to_jpg_converts_to_rgb(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.services.workflow_executor import _convert_image

        mock_img = MagicMock()
        mock_img.mode = "RGBA"
        rgb_img = MagicMock()
        rgb_img.mode = "RGB"
        mock_img.convert.return_value = rgb_img

        def fake_save(buf, format):
            buf.write(b"data")

        rgb_img.save.side_effect = fake_save

        with patch("PIL.Image.open", return_value=mock_img):
            _convert_image(b"png-rgba-bytes", "jpg")

        mock_img.convert.assert_called_once_with("RGB")
        rgb_img.save.assert_called_once()


# ---------------------------------------------------------------------------
# Task — Drive convertFile operation (executor integration)
# ---------------------------------------------------------------------------


def _make_convert_db_mock(file_row: object) -> MagicMock:
    """DB mock for convertFile: query returns the source file, then two objects are added."""
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_db.query.return_value.filter.return_value.first.return_value = file_row
    fake_db.flush = MagicMock()
    fake_db.commit = MagicMock()
    added: list = []
    fake_db.add.side_effect = lambda obj: added.append(obj)
    fake_db._added = added
    return fake_db


class DriveNodeConvertFileTests(unittest.TestCase):
    """Drive node convertFile operation."""

    def _run_convert_workflow(
        self,
        drive_data: dict,
        owner_id: uuid.UUID,
        db_mock: MagicMock,
        src_bytes: bytes,
        converted_bytes: bytes,
        converted_mime: str,
        is_image: bool = False,
    ) -> dict:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(drive_data)
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db_mock),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch(
                "app.services.file_storage.build_download_url",
                return_value="/api/files/dl/convtoken",
            ),
            patch("secrets.token_urlsafe", return_value="convtoken"),
        ):
            storage_path = MagicMock()
            storage_path.exists.return_value = True
            storage_path.read_bytes.return_value = src_bytes

            mock_root.return_value.__truediv__ = MagicMock(return_value=storage_path)

            if is_image:
                with patch(
                    "app.services.workflow_executor._convert_image",
                    return_value=(converted_bytes, converted_mime),
                ):
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
                    )
            else:
                with (
                    patch(
                        "app.services.workflow_executor._extract_pdf_text",
                        return_value="extracted text",
                    ),
                    patch("pypandoc.convert_file") as mock_pandoc,
                ):

                    def write_output(src, fmt, outputfile, format, extra_args=None):
                        with open(outputfile, "wb") as fh:
                            fh.write(converted_bytes)

                    mock_pandoc.side_effect = write_output
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
                    )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        if nr is None:
            raise AssertionError(
                f"Drive node result not found. Errors: "
                f"{[r for r in result.node_results if r.get('status') == 'error']}"
            )
        return nr

    def test_convert_md_to_html_success(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="readme.md",
            mime_type="text/markdown",
            size_bytes=100,
            storage_path=f"{owner_id}/{file_id}/readme.md",
        )
        db = _make_convert_db_mock(file_row)

        nr = self._run_convert_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": str(file_id),
                "driveConvertTargetFormat": "html",
            },
            owner_id,
            db,
            src_bytes=b"# Hello",
            converted_bytes=b"<h1>Hello</h1>",
            converted_mime="text/html",
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["operation"], "convertFile")
        self.assertEqual(nr["output"]["filename"], "readme.html")
        self.assertEqual(nr["output"]["mime_type"], "text/html")
        self.assertIn("id", nr["output"])
        self.assertIn("download_url", nr["output"])

    def test_convert_pdf_to_txt_success(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=500,
            storage_path=f"{owner_id}/{file_id}/report.pdf",
        )
        db = _make_convert_db_mock(file_row)

        nr = self._run_convert_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": str(file_id),
                "driveConvertTargetFormat": "txt",
            },
            owner_id,
            db,
            src_bytes=b"%PDF-fake",
            converted_bytes=b"extracted text",
            converted_mime="text/plain",
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["filename"], "report.txt")
        self.assertEqual(nr["output"]["mime_type"], "text/plain")

    def test_convert_image_png_to_jpg_success(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="photo.png",
            mime_type="image/png",
            size_bytes=200,
            storage_path=f"{owner_id}/{file_id}/photo.png",
        )
        db = _make_convert_db_mock(file_row)

        nr = self._run_convert_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": str(file_id),
                "driveConvertTargetFormat": "jpg",
            },
            owner_id,
            db,
            src_bytes=b"fake-png",
            converted_bytes=b"fake-jpeg",
            converted_mime="image/jpeg",
            is_image=True,
        )

        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["filename"], "photo.jpg")
        self.assertEqual(nr["output"]["mime_type"], "image/jpeg")

    def test_convert_unsupported_input_format_raises(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="archive.zip",
            mime_type="application/zip",
            size_bytes=1000,
            storage_path=f"{owner_id}/{file_id}/archive.zip",
        )
        db = _make_convert_db_mock(file_row)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": str(file_id),
                "driveConvertTargetFormat": "txt",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        storage_path = MagicMock()
        storage_path.exists.return_value = True
        storage_path.read_bytes.return_value = b"zip-data"

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            mock_root.return_value.__truediv__ = MagicMock(return_value=storage_path)
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("does not support input format", nr["error"])

    def test_convert_image_to_doc_format_raises(self) -> None:
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="photo.png",
            mime_type="image/png",
            size_bytes=200,
            storage_path=f"{owner_id}/{file_id}/photo.png",
        )
        db = _make_convert_db_mock(file_row)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": str(file_id),
                "driveConvertTargetFormat": "docx",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        storage_path = MagicMock()
        storage_path.exists.return_value = True
        storage_path.read_bytes.return_value = b"png-data"

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root") as mock_root,
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            mock_root.return_value.__truediv__ = MagicMock(return_value=storage_path)
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("cannot convert image", nr["error"])

    def test_convert_missing_file_id_raises(self) -> None:
        owner_id = uuid.uuid4()
        db = _make_convert_db_mock(None)

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _make_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": "",
                "driveConvertTargetFormat": "html",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner_id

        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.file_storage._storage_root"),
            patch("app.services.file_storage.build_download_url", return_value=""),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
            )

        nr = next((r for r in result.node_results if r["node_type"] == "drive"), None)
        self.assertIsNotNone(nr)
        self.assertEqual(nr["status"], "error")
        self.assertIn("fileId is required", nr["error"])

    def test_convert_output_is_new_file(self) -> None:
        """Converted file id in output must differ from source file id."""
        owner_id = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner_id,
            filename="doc.md",
            mime_type="text/markdown",
            size_bytes=50,
            storage_path=f"{owner_id}/{file_id}/doc.md",
        )
        db = _make_convert_db_mock(file_row)

        nr = self._run_convert_workflow(
            {
                "label": "convert",
                "driveOperation": "convertFile",
                "driveFileId": str(file_id),
                "driveConvertTargetFormat": "txt",
            },
            owner_id,
            db,
            src_bytes=b"# Hello",
            converted_bytes=b"Hello",
            converted_mime="text/plain",
        )

        self.assertEqual(nr["status"], "success")
        self.assertNotEqual(nr["output"]["id"], str(file_id))
        self.assertEqual(len(db._added), 2)


if __name__ == "__main__":
    unittest.main()
