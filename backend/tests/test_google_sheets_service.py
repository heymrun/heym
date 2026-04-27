"""Unit tests for GoogleSheetsService."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_config(expired: bool = False) -> dict:
    """Return a minimal encrypted_config dict."""
    if expired:
        expiry = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    else:
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "access_token": "ya29.valid-token",
        "refresh_token": "1//refresh-token",
        "token_expiry": expiry,
        "scope": "https://www.googleapis.com/auth/spreadsheets",
    }


class TestParseSpreadsheetId(unittest.TestCase):
    def setUp(self) -> None:
        from app.services.google_sheets_service import GoogleSheetsService

        self.svc_cls = GoogleSheetsService

    def test_bare_id_returned_as_is(self) -> None:
        result = self.svc_cls.parse_spreadsheet_id("1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")
        self.assertEqual(result, "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")

    def test_full_url_parsed_to_id(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit#gid=0"
        result = self.svc_cls.parse_spreadsheet_id(url)
        self.assertEqual(result, "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms")

    def test_url_without_trailing_path_parsed(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/abc123DEF_-456/edit"
        result = self.svc_cls.parse_spreadsheet_id(url)
        self.assertEqual(result, "abc123DEF_-456")


class TestTokenRefresh(unittest.TestCase):
    def _make_service(self, expired: bool = False):
        from app.services.google_sheets_service import GoogleSheetsService

        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        return GoogleSheetsService("cred-id-1", _make_config(expired=expired), fake_db)

    def test_valid_token_no_refresh_called(self) -> None:
        svc = self._make_service(expired=False)
        with patch("httpx.post") as mock_post:
            token = svc._get_valid_token()
        mock_post.assert_not_called()
        self.assertEqual(token, "ya29.valid-token")

    def test_expired_token_triggers_refresh(self) -> None:
        svc = self._make_service(expired=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "ya29.new-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            token = svc._get_valid_token()
        mock_post.assert_called_once()
        call_data = mock_post.call_args[1]["data"]
        self.assertEqual(call_data["grant_type"], "refresh_token")
        self.assertEqual(call_data["refresh_token"], "1//refresh-token")
        self.assertEqual(token, "ya29.new-token")


class TestReadRange(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService

        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_read_range_with_header_returns_objects(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "values": [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]],
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response):
            result = svc.read_range(
                "spreadsheet-id", "Sheet1", start_row=1, max_rows=100, has_header=True
            )
        self.assertEqual(
            result["rows"],
            [
                {"Name": "Alice", "Age": "30", "rowIndex": 2},
                {"Name": "Bob", "Age": "25", "rowIndex": 3},
            ],
        )
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["success"])

    def test_read_range_header_respects_start_row(self) -> None:
        """When has_header=True, row 1 is the header; start_row sets where DATA begins.

        Sheet layout (start_row=2):
          row 1: Date, Notes   <- header
          row 2: 16 April, OK  <- first data row
          row 3: 14 March, NO  <- second data row

        Expected: URL starts at A1, header=["Date","Notes"], rows=[{Date:16 April, Notes:OK}, ...]
        """
        svc = self._make_service()
        mock_response = MagicMock()
        # raw[0] = header row, raw[1] = first data row (row 2), raw[2] = row 3
        mock_response.json.return_value = {
            "values": [["Date", "Notes"], ["16 April", "OK"], ["14 March", "NO"]],
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = svc.read_range(
                "spreadsheet-id", "Sheet1", start_row=2, max_rows=0, has_header=True
            )
        called_url = mock_get.call_args[0][0]
        # Header is always at row 1 — URL must start from A1
        self.assertIn("A1:", called_url)
        self.assertEqual(
            result["rows"],
            [
                {"Date": "16 April", "Notes": "OK", "rowIndex": 2},
                {"Date": "14 March", "Notes": "NO", "rowIndex": 3},
            ],
        )
        self.assertEqual(result["total"], 2)

    def test_read_range_max_rows_zero_fetches_all(self) -> None:
        """max_rows=0 means fetch all rows — no end row in A1 notation."""
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"values": [["A", "B"], ["1", "2"], ["3", "4"]]}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = svc.read_range(
                "spreadsheet-id", "Sheet1", start_row=1, max_rows=0, has_header=True
            )
        called_url = mock_get.call_args[0][0]
        # No digit after the last colon — open-ended range
        self.assertIn("A1:Z", called_url)
        self.assertFalse(called_url.rstrip("/").split("!")[-1].split("Z")[-1].isdigit())
        self.assertEqual(result["total"], 2)

    def test_read_range_without_header_returns_indexed_objects(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "values": [["Alice", "30"], ["Bob", "25"]],
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = svc.read_range(
                "spreadsheet-id", "Sheet1", start_row=2, max_rows=100, has_header=False
            )
        called_url = mock_get.call_args[0][0]
        self.assertIn("A2:Z101", called_url)
        self.assertEqual(
            result["rows"],
            [
                {"A": "Alice", "B": "30", "rowIndex": 2},
                {"A": "Bob", "B": "25", "rowIndex": 3},
            ],
        )
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["success"])

    def test_read_range_without_header_open_range_from_start_row(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"values": [["x"]]}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = svc.read_range(
                "spreadsheet-id", "Sheet1", start_row=5, max_rows=0, has_header=False
            )
        called_url = mock_get.call_args[0][0]
        self.assertIn("A5:Z", called_url)
        self.assertEqual(result["rows"], [{"A": "x", "rowIndex": 5}])
        self.assertTrue(result["success"])

    def test_read_range_empty_returns_empty(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"values": []}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response):
            result = svc.read_range("spreadsheet-id", "Sheet1")
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total"], 0)
        self.assertTrue(result["success"])

    def test_read_range_header_only_no_data_rows(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"values": [["Name", "Age"]]}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response):
            result = svc.read_range("spreadsheet-id", "Sheet1", has_header=True)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total"], 0)


class TestAppendRows(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService

        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_append_rows_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "updates": {"updatedRange": "Sheet1!A3:B3", "updatedRows": 1}
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.append_rows("spreadsheet-id", "Sheet1", [["Bob", "25"]])
        self.assertEqual(result["updatedRows"], 1)
        self.assertEqual(result["updatedRange"], "Sheet1!A3:B3")
        self.assertTrue(result["success"])


class TestPrependRows(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService

        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_prepend_rows_batch_then_put(self) -> None:
        svc = self._make_service()
        get_resp = MagicMock()
        get_resp.json.return_value = {
            "sheets": [{"properties": {"title": "Sheet1", "sheetId": 7, "index": 0}}]
        }
        get_resp.raise_for_status = MagicMock()
        batch_resp = MagicMock()
        batch_resp.raise_for_status = MagicMock()
        put_resp = MagicMock()
        put_resp.json.return_value = {
            "updatedRange": "Sheet1!A2:B2",
            "updatedCells": 2,
        }
        put_resp.raise_for_status = MagicMock()
        with (
            patch("httpx.get", return_value=get_resp),
            patch("httpx.post", return_value=batch_resp),
            patch("httpx.put", return_value=put_resp),
        ):
            result = svc.prepend_rows("spreadsheet-id", "Sheet1", [["a", "b"]])
        self.assertEqual(result["updatedRows"], 1)
        self.assertEqual(result["updatedCells"], 2)
        self.assertTrue(result["success"])


class TestUpdateRange(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService

        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_update_range_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "updatedRange": "Sheet1!A2:B2",
            "updatedCells": 2,
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.put", return_value=mock_response):
            result = svc.update_range("spreadsheet-id", "Sheet1", 2, [["X", "Y"]])
        self.assertEqual(result["updatedCells"], 2)
        self.assertTrue(result["success"])


class TestClearRange(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService

        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_clear_range_clears_full_columns(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"clearedRange": "Sheet1!A:Z"}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = svc.clear_range("spreadsheet-id", "Sheet1")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        self.assertIn("Sheet1!A:Z:clear", call_url)
        self.assertEqual(result["clearedRange"], "Sheet1!A:Z")
        self.assertTrue(result["success"])

    def test_clear_range_keep_header_starts_at_row_two(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {"clearedRange": "Sheet1!A2:Z1048576"}
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = svc.clear_range("spreadsheet-id", "Sheet1", keep_header=True)
        call_url = mock_post.call_args[0][0]
        self.assertIn("Sheet1!A2:Z1048576:clear", call_url)
        self.assertTrue(result["success"])


class TestGetSheetInfo(unittest.TestCase):
    def _make_service(self):
        from app.services.google_sheets_service import GoogleSheetsService

        return GoogleSheetsService("cred-id-1", _make_config(), MagicMock())

    def test_get_sheet_info_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sheets": [
                {"properties": {"title": "Sheet1", "sheetId": 0, "index": 0}},
                {"properties": {"title": "Data", "sheetId": 1, "index": 1}},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_response):
            result = svc.get_sheet_info("spreadsheet-id")
        self.assertEqual(len(result["sheets"]), 2)
        self.assertEqual(result["sheets"][0]["title"], "Sheet1")
        self.assertTrue(result["success"])
