"""Tests for the googleDrive node handler."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext


def _ctx(node_data: dict) -> NodeExecutionContext:
    """Build a handler context.

    NodeExecutionContext is a frozen dataclass with nine required fields — all of
    them must be supplied even though the handler only reads four.
    """
    executor = MagicMock()
    executor.trace_user_id = "00000000-0000-0000-0000-000000000001"
    executor.workflow_id = "00000000-0000-0000-0000-0000000000ff"
    executor._base_url = "https://app.test"
    # The handler resolves every field through this. Mirror the real executor: an empty
    # template returns str(inputs), which is "{}" here — the behaviour that leaked "{}"
    # into Drive queries and rename targets.
    executor.evaluate_message_template.side_effect = lambda v, ev_inputs=None, *_a, **_kw: (
        str(v) if v else str(ev_inputs or {})
    )
    executor._get_accessible_credential.return_value = MagicMock(encrypted_config="enc")
    node = {"id": "node-1", "type": "googleDrive", "data": node_data}
    return NodeExecutionContext(
        executor=executor,
        node_id="node-1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node=node,
        node_type="googleDrive",
        node_data=node_data,
        node_label=node_data.get("label", "GoogleDrive"),
    )


class GoogleDriveNodeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MagicMock()
        self.patchers = [
            patch(
                "app.services.google_drive_service.GoogleDriveService",
                return_value=self.service,
            ),
            patch("app.db.session.SessionLocal"),
            patch("app.services.encryption.decrypt_config", return_value={"client_id": "cid"}),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self) -> None:
        for p in self.patchers:
            p.stop()


class TestValidation(GoogleDriveNodeTestBase):
    def test_missing_credential_raises(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(_ctx({"gdOperation": "listFolderFiles"}))
        self.assertIn("credential", str(ctx.exception).lower())

    def test_missing_operation_raises(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(_ctx({"credentialId": "cred-1"}))
        self.assertIn("operation", str(ctx.exception).lower())

    def test_unknown_operation_raises(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(_ctx({"credentialId": "cred-1", "gdOperation": "teleport"}))
        self.assertIn("teleport", str(ctx.exception))


class TestOperationDispatch(GoogleDriveNodeTestBase):
    def test_list_folder_files_passes_parsed_fields(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdFolderId": "folder-1",
                    "gdMaxResults": "25",
                    "gdQuery": "mimeType='application/pdf'",
                    "gdIncludeTrashed": True,
                }
            )
        )

        self.service.list_folder_files.assert_called_once_with(
            "folder-1",
            max_results=25,
            query="mimeType='application/pdf'",
            include_trashed=True,
        )

    def test_max_results_falls_back_on_bad_input(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdMaxResults": "not-a-number",
                }
            )
        )
        self.assertEqual(self.service.list_folder_files.call_args.kwargs["max_results"], 100)

    def test_download_file_requires_file_id(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(
                _ctx({"credentialId": "cred-1", "gdOperation": "downloadFile"})
            )
        self.assertIn("file ID is required", str(ctx.exception))

    def test_download_file_dispatches(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file_base64.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "downloadFile",
                    "gdFileId": "file-1",
                    "gdExportFormat": "pdf",
                }
            )
        )
        self.assertEqual(self.service.download_file_base64.call_args.kwargs["export_format"], "pdf")

    def test_update_file_decodes_data_url(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.update_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "updateFile",
                    "gdFileId": "file-1",
                    # "hello" base64-encoded, wrapped in a data URL
                    "gdBase64Content": "data:text/plain;base64,aGVsbG8=",
                }
            )
        )
        self.assertEqual(self.service.update_file.call_args.kwargs["content"], b"hello")

    def test_update_file_rejects_invalid_base64(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        with self.assertRaises(ValueError) as ctx:
            google_drive_node.execute(
                _ctx(
                    {
                        "credentialId": "cred-1",
                        "gdOperation": "updateFile",
                        "gdFileId": "file-1",
                        "gdBase64Content": "!!!not base64!!!",
                    }
                )
            )
        self.assertIn("invalid base64", str(ctx.exception).lower())

    def test_update_file_passes_none_content_when_blank(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.update_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "updateFile",
                    "gdFileId": "file-1",
                    "gdNewName": "renamed.txt",
                }
            )
        )
        self.assertIsNone(self.service.update_file.call_args.kwargs["content"])
        self.assertEqual(self.service.update_file.call_args.kwargs["new_name"], "renamed.txt")

    def test_remove_file_defaults_to_trash(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.remove_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "removeFile",
                    "gdFileId": "file-1",
                }
            )
        )
        self.assertFalse(self.service.remove_file.call_args.kwargs["permanent"])

    def test_remove_folder_permanent_flag_is_forwarded(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.remove_folder.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "removeFolder",
                    "gdFolderId": "folder-1",
                    "gdPermanentDelete": True,
                }
            )
        )
        self.assertTrue(self.service.remove_folder.call_args.kwargs["permanent"])


class TestBlankOptionalFields(GoogleDriveNodeTestBase):
    """Blank optional fields must stay blank.

    evaluate_message_template returns str(inputs) for an empty template, so routing a
    blank field through it yields the literal "{}" — which leaked into Drive queries,
    export formats, and rename targets.
    """

    def test_blank_query_is_not_sent(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdFolderId": "folder-1",
                    "gdQuery": "",
                }
            )
        )
        self.assertEqual(self.service.list_folder_files.call_args.kwargs["query"], "")

    def test_blank_folder_id_stays_blank_so_root_is_used(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdFolderId": "",
                }
            )
        )
        self.assertEqual(self.service.list_folder_files.call_args.args[0], "")

    def test_blank_export_format_is_not_sent(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file_base64.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "downloadFile",
                    "gdFileId": "file-1",
                    "gdExportFormat": "",
                }
            )
        )
        self.assertEqual(self.service.download_file_base64.call_args.kwargs["export_format"], "")

    def test_blank_update_fields_do_not_become_a_rename(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.update_file.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "updateFile",
                    "gdFileId": "file-1",
                    "gdNewName": "renamed.txt",
                    "gdNewParentId": "",
                    "gdBase64Content": "",
                }
            )
        )
        kwargs = self.service.update_file.call_args.kwargs
        self.assertEqual(kwargs["new_name"], "renamed.txt")
        self.assertEqual(kwargs["new_parent_id"], "")
        self.assertIsNone(kwargs["content"])

    def test_blank_max_results_falls_back_to_default(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        google_drive_node.execute(
            _ctx(
                {
                    "credentialId": "cred-1",
                    "gdOperation": "listFolderFiles",
                    "gdMaxResults": "",
                }
            )
        )
        self.assertEqual(self.service.list_folder_files.call_args.kwargs["max_results"], 100)

    def test_expressions_still_resolve(self) -> None:
        """The blank-field guard must not stop real templates from being evaluated."""
        from app.services.node_execution.nodes import google_drive_node

        self.service.list_folder_files.return_value = {"status": "success"}
        ctx = _ctx(
            {
                "credentialId": "cred-1",
                "gdOperation": "listFolderFiles",
                "gdFolderId": "$input.folder",
            }
        )
        ctx.executor.evaluate_message_template.side_effect = lambda v, *_a, **_kw: (
            "resolved-folder" if v == "$input.folder" else str(v)
        )
        google_drive_node.execute(ctx)
        self.assertEqual(self.service.list_folder_files.call_args.args[0], "resolved-folder")


class TestSyncToHeymDrive(GoogleDriveNodeTestBase):
    def _download_result(self) -> dict:
        return {
            "id": "gfile-1",
            "filename": "Notes.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 5,
            "exported": True,
            "export_format": "pdf",
            "content": b"HELLO",
        }

    def test_requires_owner_context(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        ctx = _ctx(
            {
                "credentialId": "cred-1",
                "gdOperation": "syncToHeymDrive",
                "gdFileId": "gfile-1",
            }
        )
        ctx.executor.trace_user_id = None

        with self.assertRaises(ValueError) as err:
            google_drive_node.execute(ctx)
        self.assertIn("owner context", str(err.exception))

    def test_writes_file_and_returns_download_url(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file.return_value = self._download_result()
        written: dict = {}

        def fake_write(data: bytes) -> None:
            written["bytes"] = data

        abs_path = MagicMock()
        abs_path.write_bytes.side_effect = fake_write

        with patch(
            "app.services.file_storage._normalize_storage_filename", side_effect=lambda n: n
        ):
            with patch("app.services.file_storage._safe_storage_path", return_value=abs_path):
                with patch(
                    "app.services.file_storage.build_download_url",
                    return_value="https://app.test/api/files/dl/tok",
                ):
                    result = google_drive_node.execute(
                        _ctx(
                            {
                                "credentialId": "cred-1",
                                "gdOperation": "syncToHeymDrive",
                                "gdFileId": "gfile-1",
                            }
                        )
                    )

        self.assertEqual(written["bytes"], b"HELLO")
        self.assertEqual(result["operation"], "syncToHeymDrive")
        self.assertEqual(result["google_file_id"], "gfile-1")
        self.assertEqual(result["filename"], "Notes.pdf")
        self.assertEqual(result["download_url"], "https://app.test/api/files/dl/tok")
        # The Heym Drive file gets its own UUID, distinct from the Google file ID.
        self.assertNotEqual(result["id"], "gfile-1")

    def test_filename_override_is_applied(self) -> None:
        from app.services.node_execution.nodes import google_drive_node

        self.service.download_file.return_value = self._download_result()
        abs_path = MagicMock()

        with patch(
            "app.services.file_storage._normalize_storage_filename", side_effect=lambda n: n
        ) as normalize:
            with patch("app.services.file_storage._safe_storage_path", return_value=abs_path):
                with patch(
                    "app.services.file_storage.build_download_url", return_value="https://x/dl"
                ):
                    result = google_drive_node.execute(
                        _ctx(
                            {
                                "credentialId": "cred-1",
                                "gdOperation": "syncToHeymDrive",
                                "gdFileId": "gfile-1",
                                "gdFilename": "custom-name.pdf",
                            }
                        )
                    )

        normalize.assert_called_once_with("custom-name.pdf")
        self.assertEqual(result["filename"], "custom-name.pdf")


if __name__ == "__main__":
    unittest.main()
