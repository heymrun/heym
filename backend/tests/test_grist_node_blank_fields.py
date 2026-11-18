"""Blank Grist fields stay blank instead of becoming the workflow inputs.

evaluate_message_template renders a blank template as the whole input context, so a blank
document ID, table ID, record ID, or sort expression sent that text in Grist API requests,
leaking workflow inputs into URL paths and query parameters.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_executor import WorkflowExecutor

SECRET = "k_live_grist_secret_9"


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
            "type": "grist",
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
        "body": {"id": "doc123", "blank": "", "tbl": "Table1"},
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


class GristBlankFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict] = []
        config = {
            "api_key": "grist-api-key",
            "server_url": "https://grist.example.com",
        }

        def _make_resp(payload: dict) -> httpx.Response:
            return httpx.Response(
                200, json=payload, request=httpx.Request("GET", "https://grist.example.com")
            )

        self.client = MagicMock()
        self.client.get.side_effect = lambda url, **kwargs: (
            self.sent.append({"method": "GET", "url": url, **kwargs})
            or _make_resp({"records": [], "tables": [], "columns": []})
        )
        self.client.post.side_effect = lambda url, **kwargs: (
            self.sent.append({"method": "POST", "url": url, **kwargs})
            or _make_resp({"records": []})
        )
        self.client.patch.side_effect = lambda url, **kwargs: (
            self.sent.append({"method": "PATCH", "url": url, **kwargs})
            or _make_resp({"records": []})
        )

        for patcher in (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch("app.services.grist_pool.get_grist_client", return_value=self.client),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_blank_doc_id_in_list_tables_raises_and_sends_no_request(self) -> None:
        status, error = _run({"gristOperation": "listTables", "gristDocId": ""})

        self.assertEqual(status, "error")
        self.assertIn("Grist listTables requires a document ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_evaluating_doc_id_in_list_tables_raises_and_sends_no_request(self) -> None:
        status, error = _run({"gristOperation": "listTables", "gristDocId": "$start.body.blank"})

        self.assertEqual(status, "error")
        self.assertIn("Grist listTables requires a document ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_blank_table_id_in_list_columns_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {"gristOperation": "listColumns", "gristDocId": "doc1", "gristTableId": ""}
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist listColumns requires document ID and table ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_evaluating_table_id_in_list_columns_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "listColumns",
                "gristDocId": "doc1",
                "gristTableId": "$start.body.blank",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist listColumns requires document ID and table ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_blank_record_id_in_get_record_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "getRecord",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristRecordId": "",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist getRecord requires a record ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_evaluating_record_id_in_get_record_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "getRecord",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristRecordId": "$start.body.blank",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist getRecord requires a record ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_blank_record_id_in_update_record_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "updateRecord",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristRecordId": "",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist updateRecord requires a record ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_evaluating_record_id_in_update_record_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "updateRecord",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristRecordId": "$start.body.blank",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist updateRecord requires a record ID", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_blank_record_id_in_delete_record_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "deleteRecord",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristRecordId": "",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist deleteRecord requires record ID(s)", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_evaluating_record_id_in_delete_record_raises_and_sends_no_request(self) -> None:
        status, error = _run(
            {
                "gristOperation": "deleteRecord",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristRecordId": "$start.body.blank",
            }
        )

        self.assertEqual(status, "error")
        self.assertIn("Grist deleteRecord requires record ID(s)", error)
        self.assertEqual(self.sent, [])
        self.assertNotIn(SECRET, str(self.sent))

    def test_blank_sort_does_not_append_sort_param(self) -> None:
        status, error = _run(
            {
                "gristOperation": "getRecords",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristSort": "",
            }
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("sort", self.sent[0].get("params", {}))
        self.assertNotIn(SECRET, str(self.sent))

    def test_empty_evaluating_sort_does_not_append_sort_param(self) -> None:
        status, error = _run(
            {
                "gristOperation": "getRecords",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristSort": "$start.body.blank",
            }
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("sort", self.sent[0].get("params", {}))
        self.assertNotIn(SECRET, str(self.sent))

    def test_valid_sort_appends_sort_param(self) -> None:
        status, error = _run(
            {
                "gristOperation": "getRecords",
                "gristDocId": "doc1",
                "gristTableId": "Table1",
                "gristSort": "name",
            }
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].get("params", {}).get("sort"), "name")
        self.assertNotIn(SECRET, str(self.sent))


if __name__ == "__main__":
    unittest.main()
