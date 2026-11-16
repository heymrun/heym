"""A blank Google Sheets spreadsheet id or sheet name fails with the node's own message.

evaluate_message_template renders a blank template as the whole input context, so a node
whose spreadsheet was not picked, or whose sheet name was cleared, requested a spreadsheet
or a range named after the inputs.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_executor import WorkflowExecutor

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


class GoogleSheetsBlankFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.urls: list[str] = []

        def get(url: str, headers: dict | None = None, **_kw: object) -> httpx.Response:
            self.urls.append(url)
            request = httpx.Request("GET", url)
            body = {"values": [["name"], ["Ann"]], "sheets": [], "properties": {"title": "T"}}
            return httpx.Response(200, json=body, request=request)

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        for patcher in (
            patch("app.db.session.SessionLocal", return_value=db),
            patch("app.services.encryption.decrypt_config", return_value={"access_token": "t"}),
            patch(
                "app.services.google_sheets_service.GoogleSheetsService._get_valid_token",
                return_value="t",
            ),
            patch("app.services.google_sheets_service.httpx.get", side_effect=get),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, data: dict) -> tuple[str, str]:
        nodes = [
            {
                "id": "start",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "start", "inputFields": [{"key": "id"}]},
            },
            {
                "id": "gs",
                "type": "googleSheets",
                "position": {"x": 200, "y": 0},
                "data": {"label": "gs", "credentialId": "cred-1", **data},
            },
        ]
        edges = [{"id": "e1", "source": "start", "target": "gs"}]
        executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
        executor._get_accessible_credential = MagicMock(
            return_value=MagicMock(encrypted_config="{}")
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {"x-api-key": "k"}, "query": {}, "body": {"id": "7"}},
        )
        row = next(r for r in result.node_results if r["node_label"] == "gs")
        return row["status"], str(row.get("error") or "")

    def test_no_spreadsheet_fails_without_a_request(self) -> None:
        status, error = self._run({"gsOperation": "readRange", "gsSheetName": "Sheet1"})

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets node requires a spreadsheet ID", error)
        self.assertEqual(self.urls, [])

    def test_a_cleared_sheet_name_fails_without_a_request(self) -> None:
        status, error = self._run(
            {"gsOperation": "readRange", "gsSpreadsheetId": SHEET_ID, "gsSheetName": ""}
        )

        self.assertEqual(status, "error")
        self.assertIn("Google Sheets readRange requires a sheet name", error)
        self.assertEqual(self.urls, [])

    def test_sheet_info_needs_no_sheet_name(self) -> None:
        status, error = self._run(
            {"gsOperation": "getSheetInfo", "gsSpreadsheetId": SHEET_ID, "gsSheetName": ""}
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertIn(SHEET_ID, self.urls[0])

    def test_a_filled_node_reads_its_range(self) -> None:
        status, error = self._run(
            {"gsOperation": "readRange", "gsSpreadsheetId": SHEET_ID, "gsSheetName": "Sheet1"}
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertIn(f"/spreadsheets/{SHEET_ID}/values/", self.urls[0])
        self.assertNotIn("x-api-key", self.urls[0])


if __name__ == "__main__":
    unittest.main()
