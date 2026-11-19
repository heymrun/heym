"""Blank ClickHouse and BigQuery fields stay blank instead of becoming the inputs.

evaluate_message_template renders a blank template as the whole input context, so a blank
optional field (a ClickHouse sort, a mapped column value) or a blank required field (a SQL
query, a project id) sent that text to the warehouse.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_executor import WorkflowExecutor

SECRET = "k_live_9"


def _run(node_type: str, data: dict) -> tuple[str, str]:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "id"}]},
        },
        {
            "id": "n",
            "type": node_type,
            "position": {"x": 200, "y": 0},
            "data": {"label": "n", "credentialId": "cred-1", **data},
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "n"}]
    executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
    executor._get_accessible_credential = MagicMock(return_value=MagicMock(encrypted_config="{}"))
    result = executor.execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {"x-api-key": SECRET}, "query": {}, "body": {"id": "7"}},
    )
    row = next(r for r in result.node_results if r["node_label"] == "n")
    return row["status"], str(row.get("error") or "")


def _session() -> MagicMock:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


class ClickHouseBlankFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        client = MagicMock()

        def query(sql: str, parameters: dict | None = None) -> MagicMock:
            self.sent.append((sql, parameters or {}))
            return MagicMock(column_names=["id"], result_rows=[("7",)])

        client.query.side_effect = query
        client.command.side_effect = lambda sql, parameters=None: self.sent.append((sql, {}))
        for patcher in (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value={"host": "ch.test"}),
            patch("app.services.clickhouse_service.guard_http_url"),
            patch("app.services.clickhouse_pool.get_clickhouse_client", return_value=client),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_find_without_a_sort_has_no_order_by(self) -> None:
        status, error = _run(
            "clickhouse", {"clickhouseOperation": "find", "clickhouseTable": "events"}
        )

        self.assertEqual((status, error), ("success", ""))
        self.assertEqual(self.sent[0][0], "SELECT * FROM events LIMIT 100")

    def test_find_with_a_sort_orders_by_it(self) -> None:
        status, _error = _run(
            "clickhouse",
            {"clickhouseOperation": "find", "clickhouseTable": "events", "clickhouseSort": "id"},
        )

        self.assertEqual(status, "success")
        self.assertEqual(self.sent[0][0], "SELECT * FROM events ORDER BY id LIMIT 100")

    def test_a_blank_query_is_not_sent(self) -> None:
        status, error = _run("clickhouse", {"clickhouseOperation": "query"})

        self.assertEqual(status, "error")
        self.assertIn("ClickHouse query is required", error)
        self.assertEqual(self.sent, [])

    def test_a_blank_mapped_value_is_inserted_as_empty_text(self) -> None:
        inserted: list[dict] = []
        with patch(
            "app.services.clickhouse_service.ClickHouseService.insert",
            side_effect=lambda table, rows: inserted.extend(rows) or {"success": True},
        ):
            status, _error = _run(
                "clickhouse",
                {
                    "clickhouseOperation": "insert",
                    "clickhouseTable": "events",
                    "clickhouseInputMode": "selective",
                    "clickhouseMappings": [
                        {"key": "id", "value": "$start.body.id"},
                        {"key": "note", "value": ""},
                    ],
                },
            )

        self.assertEqual(status, "success")
        self.assertEqual(inserted, [{"id": "7", "note": ""}])


class BigQueryBlankFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict] = []

        def post(
            url: str,
            headers: dict,
            json: dict,  # noqa: A002
            timeout: httpx.Timeout | None = None,
        ) -> httpx.Response:
            self.sent.append({"url": url, "json": json})
            request = httpx.Request("POST", url)
            return httpx.Response(200, json={"schema": {"fields": []}, "rows": []}, request=request)

        for patcher in (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value={"access_token": "t"}),
            patch(
                "app.services.bigquery_service.BigQueryService._get_valid_token", return_value="t"
            ),
            patch("app.services.bigquery_service.httpx.post", side_effect=post),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _insert(self, note: str) -> tuple[str, str]:
        return _run(
            "bigquery",
            {
                "bqOperation": "insertRows",
                "bqProjectId": "acme",
                "bqDatasetId": "crm",
                "bqTableId": "leads",
                "bqRowsInputMode": "selective",
                "bqMappings": [
                    {"key": "lead_id", "value": "$start.body.id"},
                    {"key": "note", "value": note},
                ],
            },
        )

    def test_a_blank_mapped_value_is_inserted_as_empty_text(self) -> None:
        status, _error = self._insert("")

        self.assertEqual(status, "success")
        self.assertEqual(self.sent[0]["json"]["rows"][0]["json"], {"lead_id": "7", "note": ""})
        self.assertNotIn(SECRET, str(self.sent))

    def test_a_filled_mapped_value_is_inserted(self) -> None:
        status, _error = self._insert("called back")

        self.assertEqual(status, "success")
        self.assertEqual(
            self.sent[0]["json"]["rows"][0]["json"], {"lead_id": "7", "note": "called back"}
        )

    def test_a_query_reaches_bigquery(self) -> None:
        status, _error = _run(
            "bigquery", {"bqOperation": "query", "bqProjectId": "acme", "bqQuery": "SELECT 1"}
        )

        self.assertEqual(status, "success")
        self.assertEqual(self.sent[0]["json"]["query"], "SELECT 1")
        self.assertIn("/projects/acme/queries", self.sent[0]["url"])


if __name__ == "__main__":
    unittest.main()
