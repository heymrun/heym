"""Tests for GoogleDriveService."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.google_drive_service import GoogleDriveService, parse_drive_id


class TestParseDriveId(unittest.TestCase):
    def test_extracts_id_from_file_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://drive.google.com/file/d/1AbC-dEf_2/view?usp=sharing"),
            "1AbC-dEf_2",
        )

    def test_extracts_id_from_folder_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://drive.google.com/drive/folders/1FolderXyz_9"),
            "1FolderXyz_9",
        )

    def test_extracts_id_from_docs_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://docs.google.com/document/d/1DocId_77/edit"),
            "1DocId_77",
        )

    def test_extracts_id_from_open_query_url(self) -> None:
        self.assertEqual(
            parse_drive_id("https://drive.google.com/open?id=1OpenId_5"),
            "1OpenId_5",
        )

    def test_passes_through_bare_id(self) -> None:
        self.assertEqual(parse_drive_id("  1BareId_3  "), "1BareId_3")


def _config(expiry: datetime | None) -> dict:
    return {
        "client_id": "cid",
        "client_secret": "csecret",
        "access_token": "old-token",
        "refresh_token": "rtoken",
        "token_expiry": expiry.isoformat() if expiry else "",
    }


class TestTokenRefresh(unittest.TestCase):
    def test_uses_existing_token_when_not_expired(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        service = GoogleDriveService("cred-1", _config(future), MagicMock())

        with patch("app.services.google_drive_service.httpx.post") as post:
            self.assertEqual(service._get_valid_token(), "old-token")
            post.assert_not_called()

    def test_refreshes_and_persists_when_expired(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        db = MagicMock()
        cred_row = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cred_row
        service = GoogleDriveService("cred-1", _config(past), db)

        response = MagicMock()
        response.json.return_value = {"access_token": "fresh-token", "expires_in": 3600}
        with patch("app.services.google_drive_service.httpx.post", return_value=response):
            self.assertEqual(service._get_valid_token(), "fresh-token")

        # The refreshed token must be written back, or every run re-refreshes.
        self.assertIsNotNone(cred_row.encrypted_config)
        db.commit.assert_called_once()

    def test_refreshes_when_expiry_missing(self) -> None:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        service = GoogleDriveService("cred-1", _config(None), db)

        response = MagicMock()
        response.json.return_value = {"access_token": "fresh-token", "expires_in": 3600}
        with patch("app.services.google_drive_service.httpx.post", return_value=response):
            self.assertEqual(service._get_valid_token(), "fresh-token")


def _valid_service(db=None) -> GoogleDriveService:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    return GoogleDriveService("cred-1", _config(future), db or MagicMock())


def _meta_response(mime: str, name: str = "thing", size: str | None = "100") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    payload = {"id": "file-1", "name": name, "mimeType": mime, "parents": ["parent-1"]}
    if size is not None:
        payload["size"] = size
    resp.json.return_value = payload
    return resp


def _content_response(body: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.content = body
    return resp


class TestAuthHeaders(unittest.TestCase):
    def test_list_sends_bearer_token(self) -> None:
        """Google answers 'unregistered callers' when the token never reaches it."""
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            service.list_folder_files("folder-1", max_results=10)

        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer old-token")

    def test_missing_access_token_raises_a_clear_error(self) -> None:
        config = _config(datetime.now(timezone.utc) + timedelta(hours=1))
        config["access_token"] = ""
        service = GoogleDriveService("cred-1", config, MagicMock())

        with self.assertRaises(ValueError) as ctx:
            service.list_folder_files("folder-1", max_results=10)
        self.assertIn("reconnect", str(ctx.exception).lower())

    def test_blank_query_produces_no_empty_clause(self) -> None:
        """A blank gdQuery must not add 'and ()' to the Drive query."""
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            service.list_folder_files("folder-1", max_results=10, query="   ")

        self.assertEqual(
            get.call_args.kwargs["params"]["q"], "'folder-1' in parents and trashed = false"
        )


class TestListFolderFiles(unittest.TestCase):
    def test_builds_query_and_maps_fields(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "files": [
                {
                    "id": "f1",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                    "size": "2048",
                    "modifiedTime": "2026-07-01T10:00:00.000Z",
                    "webViewLink": "https://drive.google.com/file/d/f1/view",
                },
                {
                    "id": "f2",
                    "name": "Subfolder",
                    "mimeType": "application/vnd.google-apps.folder",
                    "modifiedTime": "2026-07-02T10:00:00.000Z",
                    "webViewLink": "https://drive.google.com/drive/folders/f2",
                },
            ]
        }

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            result = service.list_folder_files("folder-1", max_results=100)
            params = get.call_args.kwargs["params"]

        self.assertIn("'folder-1' in parents", params["q"])
        self.assertIn("trashed = false", params["q"])
        self.assertTrue(params["supportsAllDrives"])
        self.assertTrue(params["includeItemsFromAllDrives"])

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["files"][0]["size_bytes"], 2048)
        self.assertFalse(result["files"][0]["is_folder"])
        # Google-native entries and folders report no size.
        self.assertIsNone(result["files"][1]["size_bytes"])
        self.assertTrue(result["files"][1]["is_folder"])

    def test_defaults_to_root_when_folder_blank(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            result = service.list_folder_files("", max_results=10)
            params = get.call_args.kwargs["params"]

        self.assertIn("'root' in parents", params["q"])
        self.assertEqual(result["folder_id"], "root")

    def test_includes_trashed_when_requested(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            service.list_folder_files("folder-1", max_results=10, include_trashed=True)
            params = get.call_args.kwargs["params"]

        self.assertNotIn("trashed", params["q"])

    def test_appends_user_query(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"files": []}

        with patch("app.services.google_drive_service.httpx.get", return_value=response) as get:
            service.list_folder_files(
                "folder-1", max_results=10, query="mimeType='application/pdf'"
            )
            params = get.call_args.kwargs["params"]

        self.assertIn("mimeType='application/pdf'", params["q"])

    def test_pages_until_max_results_reached(self) -> None:
        service = _valid_service()
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "files": [{"id": f"f{i}", "name": f"n{i}", "mimeType": "text/plain"} for i in range(2)],
            "nextPageToken": "token-2",
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {"files": [{"id": "f9", "name": "n9", "mimeType": "text/plain"}]}

        with patch(
            "app.services.google_drive_service.httpx.get", side_effect=[page1, page2]
        ) as get:
            result = service.list_folder_files("folder-1", max_results=3)

        self.assertEqual(get.call_count, 2)
        self.assertEqual(result["count"], 3)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["pageToken"], "token-2")

    def test_truncates_to_max_results(self) -> None:
        service = _valid_service()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "files": [{"id": f"f{i}", "name": f"n{i}", "mimeType": "text/plain"} for i in range(5)]
        }

        with patch("app.services.google_drive_service.httpx.get", return_value=response):
            result = service.list_folder_files("folder-1", max_results=2)

        self.assertEqual(result["count"], 2)


class TestDownloadFile(unittest.TestCase):
    def test_binary_file_uses_alt_media(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/pdf", "report.pdf"),
            _content_response(b"PDFBYTES"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses) as get:
            result = service.download_file("file-1")

        self.assertEqual(
            get.call_args_list[1].kwargs["params"], {"alt": "media", "supportsAllDrives": True}
        )
        self.assertFalse(result["exported"])
        self.assertIsNone(result["export_format"])
        self.assertEqual(result["content"], b"PDFBYTES")
        self.assertEqual(result["filename"], "report.pdf")
        self.assertEqual(result["size_bytes"], 8)

    def test_google_doc_exports_to_pdf_by_default(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.document", "Notes", size=None),
            _content_response(b"PDF"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses) as get:
            result = service.download_file("file-1")

        # Native docs must go through /export, never alt=media.
        self.assertIn("/export", get.call_args_list[1].args[0])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["mimeType"], "application/pdf")
        self.assertTrue(result["exported"])
        self.assertEqual(result["export_format"], "pdf")
        # The extension is appended so downstream nodes see a usable filename.
        self.assertEqual(result["filename"], "Notes.pdf")

    def test_google_sheet_exports_to_xlsx_by_default(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.spreadsheet", "Budget", size=None),
            _content_response(b"XLSX"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses):
            result = service.download_file("file-1")

        self.assertEqual(result["export_format"], "xlsx")
        self.assertEqual(result["filename"], "Budget.xlsx")

    def test_google_slides_exports_to_pptx_by_default(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.presentation", "Deck", size=None),
            _content_response(b"PPTX"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses):
            result = service.download_file("file-1")

        self.assertEqual(result["export_format"], "pptx")
        self.assertEqual(result["filename"], "Deck.pptx")

    def test_export_format_override_is_honoured(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/vnd.google-apps.document", "Notes", size=None),
            _content_response(b"TXT"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses) as get:
            result = service.download_file("file-1", export_format="txt")

        self.assertEqual(get.call_args_list[1].kwargs["params"]["mimeType"], "text/plain")
        self.assertEqual(result["filename"], "Notes.txt")

    def test_export_format_ignored_for_binary_file(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/pdf", "report.pdf"),
            _content_response(b"PDFBYTES"),
        ]

        with patch("app.services.google_drive_service.httpx.get", side_effect=responses) as get:
            result = service.download_file("file-1", export_format="txt")

        self.assertEqual(get.call_args_list[1].kwargs["params"]["alt"], "media")
        self.assertFalse(result["exported"])

    def test_unknown_export_format_raises(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            side_effect=[
                _meta_response("application/vnd.google-apps.document", "Notes", size=None)
            ],
        ):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("file-1", export_format="rtf")
        self.assertIn("rtf", str(ctx.exception))

    def test_download_of_folder_raises(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            side_effect=[_meta_response("application/vnd.google-apps.folder", "Stuff", size=None)],
        ):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("file-1")
        self.assertIn("folder", str(ctx.exception).lower())

    def test_oversized_download_raises(self) -> None:
        service = _valid_service()
        responses = [
            _meta_response("application/pdf", "big.pdf"),
            _content_response(b"x" * 2048),
        ]
        with patch("app.services.google_drive_service.httpx.get", side_effect=responses):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("file-1", max_bytes=1024)
        self.assertIn("size limit", str(ctx.exception).lower())

    def test_missing_file_gives_actionable_error(self) -> None:
        service = _valid_service()
        missing = MagicMock()
        missing.status_code = 404
        missing.json.return_value = {"error": {"message": "File not found"}}

        with patch("app.services.google_drive_service.httpx.get", return_value=missing):
            with self.assertRaises(ValueError) as ctx:
                service.download_file("nope")
        self.assertIn("not found", str(ctx.exception))


class TestUpdateFile(unittest.TestCase):
    def test_requires_at_least_one_change(self) -> None:
        service = _valid_service()
        with self.assertRaises(ValueError) as ctx:
            service.update_file("file-1")
        self.assertIn("content, a new name, or a new parent", str(ctx.exception))

    def test_renames_via_metadata_patch(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {
            "id": "file-1",
            "name": "renamed.txt",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "old.txt"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.update_file("file-1", new_name="renamed.txt")

        self.assertEqual(do_patch.call_args.kwargs["json"], {"name": "renamed.txt"})
        self.assertEqual(result["updated"], ["name"])
        self.assertEqual(result["name"], "renamed.txt")

    def test_move_sends_add_and_remove_parents(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {
            "id": "file-1",
            "name": "thing",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.update_file("file-1", new_parent_id="parent-2")

        params = do_patch.call_args.kwargs["params"]
        self.assertEqual(params["addParents"], "parent-2")
        # The old parent must be removed or the file ends up in both folders.
        self.assertEqual(params["removeParents"], "parent-1")
        self.assertEqual(result["updated"], ["parent"])

    def test_rename_and_move_share_one_patch(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {
            "id": "file-1",
            "name": "new.txt",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "old.txt"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.update_file("file-1", new_name="new.txt", new_parent_id="parent-2")

        self.assertEqual(do_patch.call_count, 1)
        self.assertEqual(result["updated"], ["name", "parent"])

    def test_content_upload_uses_upload_endpoint(self) -> None:
        service = _valid_service()
        uploaded = MagicMock()
        uploaded.status_code = 200
        uploaded.json.return_value = {
            "id": "file-1",
            "name": "thing",
            "mimeType": "text/plain",
            "modifiedTime": "2026-07-27T10:00:00.000Z",
        }

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=uploaded
            ) as do_patch:
                result = service.update_file("file-1", content=b"hello")

        self.assertIn("/upload/drive/v3/files/file-1", do_patch.call_args.args[0])
        self.assertEqual(do_patch.call_args.kwargs["params"]["uploadType"], "media")
        self.assertEqual(do_patch.call_args.kwargs["content"], b"hello")
        self.assertEqual(result["updated"], ["content"])

    def test_oversized_content_raises(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with self.assertRaises(ValueError) as ctx:
                service.update_file("file-1", content=b"x" * 2048, max_bytes=1024)
        self.assertIn("size limit", str(ctx.exception).lower())


class TestRemove(unittest.TestCase):
    def test_remove_file_trashes_by_default(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {"id": "file-1", "name": "thing"}

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                with patch("app.services.google_drive_service.httpx.delete") as do_delete:
                    result = service.remove_file("file-1")

        self.assertEqual(do_patch.call_args.kwargs["json"], {"trashed": True})
        do_delete.assert_not_called()
        self.assertEqual(result["deleted"], "trashed")

    def test_remove_file_permanent_uses_delete(self) -> None:
        service = _valid_service()
        deleted = MagicMock()
        deleted.status_code = 204

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with patch(
                "app.services.google_drive_service.httpx.delete", return_value=deleted
            ) as do_delete:
                result = service.remove_file("file-1", permanent=True)

        do_delete.assert_called_once()
        self.assertEqual(result["deleted"], "permanent")

    def test_remove_file_rejects_a_folder(self) -> None:
        """A mistyped ID must not delete a folder through the file operation."""
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("application/vnd.google-apps.folder", "Stuff", size=None),
        ):
            with self.assertRaises(ValueError) as ctx:
                service.remove_file("folder-1")
        self.assertIn("is a folder", str(ctx.exception))

    def test_remove_folder_rejects_a_file(self) -> None:
        service = _valid_service()
        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("text/plain", "thing"),
        ):
            with self.assertRaises(ValueError) as ctx:
                service.remove_folder("file-1")
        self.assertIn("is not a folder", str(ctx.exception))

    def test_remove_folder_trashes_by_default(self) -> None:
        service = _valid_service()
        patched = MagicMock()
        patched.status_code = 200
        patched.json.return_value = {"id": "folder-1", "name": "Stuff"}

        with patch(
            "app.services.google_drive_service.httpx.get",
            return_value=_meta_response("application/vnd.google-apps.folder", "Stuff", size=None),
        ):
            with patch(
                "app.services.google_drive_service.httpx.patch", return_value=patched
            ) as do_patch:
                result = service.remove_folder("folder-1")

        self.assertEqual(do_patch.call_args.kwargs["json"], {"trashed": True})
        self.assertEqual(result["operation"], "removeFolder")
        self.assertEqual(result["deleted"], "trashed")


if __name__ == "__main__":
    unittest.main()
