"""Unit tests for Drive Node — file id in _generated_files and executor operations."""

import unittest
import uuid
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
            patch("app.services.file_storage._storage_root") as mock_root,
            patch(
                "app.services.file_storage.build_download_url",
                return_value="https://heym.run/api/files/dl/dltoken",
            ),
            patch("httpx.Client") as mock_client_cls,
            patch("secrets.token_urlsafe", return_value="dltoken"),
        ):
            mock_client_cls.return_value.__enter__.return_value.get.return_value = http_response
            mock_root.return_value.__truediv__ = MagicMock(return_value=storage_path_mock)

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


if __name__ == "__main__":
    unittest.main()
