"""Unit tests for BigQueryService and the BigQuery executor branch."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_config(expired: bool = False) -> dict:
    """Return a minimal BigQuery OAuth2 config dict."""
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
        "scope": "https://www.googleapis.com/auth/bigquery",
    }


class TestTokenRefresh(unittest.TestCase):
    def _make_service(self, expired: bool = False):
        from app.services.bigquery_service import BigQueryService

        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        return BigQueryService("cred-id-1", _make_config(expired=expired), fake_db)

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


class TestRunQuery(unittest.TestCase):
    def _make_service(self):
        from app.services.bigquery_service import BigQueryService

        fake_db = MagicMock()
        return BigQueryService("cred-id-1", _make_config(), fake_db)

    def test_run_query_returns_rows(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "schema": {
                "fields": [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "STRING"}]
            },
            "rows": [{"f": [{"v": "1"}, {"v": "Alice"}]}, {"f": [{"v": "2"}, {"v": "Bob"}]}],
            "totalRows": "2",
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.run_query("my-project", "SELECT id, name FROM dataset.users LIMIT 2")
        self.assertTrue(result["success"])
        self.assertEqual(result["totalRows"], 2)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0], {"id": "1", "name": "Alice"})
        self.assertEqual(
            result["schema"],
            [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "STRING"}],
        )

    def test_run_query_empty_result(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "schema": {"fields": [{"name": "id", "type": "INTEGER"}]},
            "rows": [],
            "totalRows": "0",
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            result = svc.run_query("my-project", "SELECT id FROM dataset.empty_table")
        self.assertTrue(result["success"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["totalRows"], 0)


class TestInsertRows(unittest.TestCase):
    def _make_service(self):
        from app.services.bigquery_service import BigQueryService

        fake_db = MagicMock()
        return BigQueryService("cred-id-1", _make_config(), fake_db)

    def test_insert_rows_success(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # no insertErrors key = success
        mock_response.raise_for_status = MagicMock()
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = svc.insert_rows("my-project", "my-dataset", "users", rows)
        self.assertTrue(result["success"])
        self.assertEqual(result["insertedCount"], 2)
        call_body = mock_post.call_args[1]["json"]
        self.assertEqual(len(call_body["rows"]), 2)
        self.assertEqual(call_body["rows"][0]["json"], {"id": 1, "name": "Alice"})

    def test_insert_rows_api_error_raises(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "insertErrors": [
                {"index": 0, "errors": [{"reason": "invalid", "message": "bad value"}]}
            ]
        }
        mock_response.raise_for_status = MagicMock()
        with patch("httpx.post", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.insert_rows("my-project", "my-dataset", "users", [{"id": "bad"}])
        self.assertIn("insertAll errors", str(ctx.exception))


def _make_bq_workflow(bq_data: dict) -> tuple:
    """Build a minimal workflow: textInput → bigquery → output."""
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "bq",
            "type": "bigquery",
            "position": {"x": 200, "y": 0},
            "data": {"label": "bqNode", **bq_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$bqNode", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "bq"},
        {"id": "e2", "source": "bq", "target": "out"},
    ]
    return nodes, edges, {"text": "hello"}


class TestBigQueryExecutorBranch(unittest.TestCase):
    """Test the workflow executor BigQuery branch via full WorkflowExecutor.execute()."""

    def test_missing_credential_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow({"credentialId": "", "bqOperation": "query"})
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        bq_result = next((r for r in result.node_results if r["node_label"] == "bqNode"), None)
        self.assertIsNotNone(bq_result)
        self.assertEqual(bq_result["status"], "error")
        self.assertIn("credential", bq_result.get("error", "").lower())

    def test_missing_operation_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow({"credentialId": "some-id", "bqOperation": ""})
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch(
                "app.services.encryption.decrypt_config",
                return_value={"client_id": "x", "client_secret": "y"},
            ):
                executor = WorkflowExecutor(nodes=nodes, edges=edges)
                result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        bq_result = next((r for r in result.node_results if r["node_label"] == "bqNode"), None)
        self.assertIsNotNone(bq_result)
        self.assertEqual(bq_result["status"], "error")
        self.assertIn("operation", bq_result.get("error", "").lower())

    def test_query_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow(
            {
                "credentialId": "cred-1",
                "bqOperation": "query",
                "bqProjectId": "my-project",
                "bqQuery": "SELECT 1",
                "bqMaxResults": "100",
            }
        )
        expected_output = {"rows": [{"val": "1"}], "totalRows": 1, "schema": [], "success": True}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.bigquery_service.BigQueryService.run_query",
                    return_value=expected_output,
                ) as mock_query:
                    executor = WorkflowExecutor(nodes=nodes, edges=edges)
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_query.assert_called_once_with("my-project", "SELECT 1", 100)
        self.assertEqual(result.status, "success")

    def test_insert_rows_raw_mode(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow(
            {
                "credentialId": "cred-1",
                "bqOperation": "insertRows",
                "bqProjectId": "my-project",
                "bqDatasetId": "my-dataset",
                "bqTableId": "users",
                "bqRowsInputMode": "raw",
                "bqRows": '[{"id": 1, "name": "Alice"}]',
            }
        )
        expected_output = {"insertedCount": 1, "success": True}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.bigquery_service.BigQueryService.insert_rows",
                    return_value=expected_output,
                ) as mock_insert:
                    executor = WorkflowExecutor(nodes=nodes, edges=edges)
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "my-project", "my-dataset", "users", [{"id": 1, "name": "Alice"}]
        )
        self.assertEqual(result.status, "success")

    def test_insert_rows_selective_mode(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_bq_workflow(
            {
                "credentialId": "cred-1",
                "bqOperation": "insertRows",
                "bqProjectId": "my-project",
                "bqDatasetId": "my-dataset",
                "bqTableId": "users",
                "bqRowsInputMode": "selective",
                "bqMappings": [{"key": "name", "value": "Alice"}, {"key": "age", "value": "30"}],
            }
        )
        expected_output = {"insertedCount": 1, "success": True}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.bigquery_service.BigQueryService.insert_rows",
                    return_value=expected_output,
                ) as mock_insert:
                    executor = WorkflowExecutor(nodes=nodes, edges=edges)
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "my-project", "my-dataset", "users", [{"name": "Alice", "age": "30"}]
        )
        self.assertEqual(result.status, "success")
