"""Blank Google Sheets fields stay blank instead of becoming the workflow inputs.

evaluate_message_template renders a blank template as the whole input context, so a blank
Spreadsheet ID or Sheet Name sent that text in Google Sheets API requests, leaking workflow
inputs into URLs.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_executor import WorkflowExecutor

SECRET = "k_live_sheets_secret_9"


def _run(data: dict, inputs: dict | None = None) -> tuple[str, str]:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "id"}]},
        },
        {
            "id": "n",
            "type": "googleSheets",
            "position": {"x": 200, "y": 0},
            "data": {"label": "n", "credentialId": "cred-1", **data},
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "n"}]
    executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
    executor._get_accessible_credential = MagicMock(return_value=MagicMock(encrypted_config="{}"))
    initial_inputs = inputs or {
        "headers": {"x-api-key": SECRET},
        "query": {},
        "body": {"id": "sheet_123", "blank": "", "sheet_name": "MyCustomSheet"},
    }
    result = executor.execute(
        workflow_id=uuid.uuid4(),
        initial_inputs=initial_inputs,
    )
    row = next(r for r in result.node_results if r["node_label"] == "n")
    return row["status"], str(row.get("error") or "")


def _session() -> MagicMock:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


class GoogleSheetsBlankFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict] = []
        future_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        config = {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "access_token": "ya29.test-token",
            "refresh_token": "1//test-refresh",
            "token_expiry": future_expiry,
        }

        def mock_get(url: str, **kwargs) -> httpx.Response:
            self.sent.append({"method": "GET", "url": url, **kwargs})
            request = httpx.Request("GET", url)
            if "sheets.properties" in str(kwargs.get("params", {})):
                return httpx.Response(
                    200,
                    json={
                        "sheets": [{"properties": {"title": "Sheet1", "sheetId": 0, "index": 0}}]
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={"values": [["Col1", "Col2"], ["val1", "val2"]]},
                request=request,
            )

        def mock_post(url: str, **kwargs) -> httpx.Response:
            self.sent.append({"method": "POST", "url": url, **kwargs})
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={"updatedRange": "Sheet1!A1", "clearedRange": "Sheet1!A:Z"},
                request=request,
            )

        for patcher in (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch("app.services.google_sheets_service.httpx.get", side_effect=mock_get),
            patch("app.services.google_sheets_service.httpx.post", side_effect=mock_post),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_blank_spreadsheet_id_raises_and_sends_no_request(self) -> None:
        status, error = _run({"gsOperation": "readRange", "gsSpreadsheetId": ""})

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a spreadsheet ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_expression_resolving_to_empty_spreadsheet_id_raises_and_sends_no_request(self) -> None:
        status, error = _run({"gsOperation": "readRange", "gsSpreadsheetId": "$start.body.blank"})

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a spreadsheet ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_omitted_sheet_name_defaults_to_sheet1(self) -> None:
        status, error = _run({"gsOperation": "readRange", "gsSpreadsheetId": "sheet_123"})

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("/sheet_123/values/Sheet1!A1:Z", self.sent[0]["url"])
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_string_sheet_name_defaults_to_sheet1(self) -> None:
        status, error = _run(
            {"gsOperation": "readRange", "gsSpreadsheetId": "sheet_123", "gsSheetName": ""}
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("/sheet_123/values/Sheet1!A1:Z", self.sent[0]["url"])
        self.assertNotIn(SECRET, str(self.sent))

    def test_expression_resolving_to_empty_sheet_name_raises_for_read_range(self) -> None:
        status, error = _run(
            {
                "gsOperation": "readRange",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "$start.body.blank",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a sheet name", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_expression_resolving_to_empty_sheet_name_raises_for_clear_range(self) -> None:
        status, error = _run(
            {
                "gsOperation": "clearRange",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "$start.body.blank",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a sheet name", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_expression_resolving_to_empty_sheet_name_raises_for_append_rows(self) -> None:
        status, error = _run(
            {
                "gsOperation": "appendRows",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "$start.body.blank",
                "gsValues": '[["a", "b"]]',
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a sheet name", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_expression_resolving_to_empty_sheet_name_raises_for_update_range(self) -> None:
        status, error = _run(
            {
                "gsOperation": "updateRange",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "$start.body.blank",
                "gsValues": '[["a", "b"]]',
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a sheet name", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_expression_resolving_to_empty_sheet_name_allowed_for_get_sheet_info(self) -> None:
        status, error = _run(
            {
                "gsOperation": "getSheetInfo",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "$start.body.blank",
            }
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(
            self.sent[0]["url"],
            "https://sheets.googleapis.com/v4/spreadsheets/sheet_123",
        )
        self.assertNotIn(SECRET, str(self.sent))

    def test_row_number_expressions_evaluated_with_nonempty_template(self) -> None:
        status, error = _run(
            {
                "gsOperation": "readRange",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "Sheet1",
                "gsStartRow": "$start.body.blank",
                "gsMaxRows": "$start.body.blank",
            }
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        # start_row defaults to 1, max_rows defaults to 0 -> range is A1:Z
        self.assertIn("/sheet_123/values/Sheet1!A1:Z", self.sent[0]["url"])
        self.assertNotIn(SECRET, str(self.sent))

    def test_zero_blank_or_unset_max_rows_reads_every_row(self) -> None:
        # "Max rows (0 = all)": a number 0, a cleared field or no field read 100 rows.
        base = {"gsOperation": "readRange", "gsSpreadsheetId": "sheet_123", "gsSheetName": "Sheet1"}
        for extra in ({"gsMaxRows": 0}, {"gsMaxRows": ""}, {}, {"gsMaxRows": "0"}):
            with self.subTest(extra=extra):
                self.sent.clear()
                status, error = _run({**base, **extra})

                self.assertEqual((status, error), ("success", ""))
                self.assertTrue(self.sent[0]["url"].endswith("/sheet_123/values/Sheet1!A1:Z"))

    def test_a_max_rows_number_still_caps_the_range(self) -> None:
        status, _ = _run(
            {
                "gsOperation": "readRange",
                "gsSpreadsheetId": "sheet_123",
                "gsSheetName": "Sheet1",
                "gsMaxRows": 25,
            }
        )

        self.assertEqual(status, "success")
        self.assertTrue(self.sent[0]["url"].endswith("/sheet_123/values/Sheet1!A1:Z26"))


if __name__ == "__main__":
    unittest.main()
