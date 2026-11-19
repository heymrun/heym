"""Unit tests for BigQueryService and the BigQuery executor branch."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx


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

    @staticmethod
    def _answer(payload: dict) -> MagicMock:
        response = MagicMock(is_success=True)
        response.json.return_value = payload
        return response

    @staticmethod
    def _page(*ids: int, **extra: object) -> dict:
        return {
            "jobComplete": True,
            "jobReference": {"projectId": "p", "jobId": "job_1", "location": "EU"},
            "schema": {"fields": [{"name": "id", "type": "INTEGER"}]},
            "rows": [{"f": [{"v": str(i)}]} for i in ids],
            "totalRows": "3",
            **extra,
        }

    def test_a_query_still_running_after_the_timeout_is_polled_for_its_rows(self) -> None:
        svc = self._make_service()
        running = {
            "jobComplete": False,
            "jobReference": {"projectId": "p", "jobId": "job_1", "location": "EU"},
        }
        with (
            patch("httpx.post", return_value=self._answer(running)),
            patch(
                "httpx.get",
                side_effect=[self._answer(running), self._answer(self._page(1, 2, 3))],
            ) as get,
        ):
            result = svc.run_query("p", "SELECT id FROM t")
        self.assertEqual([row["id"] for row in result["rows"]], ["1", "2", "3"])
        self.assertEqual(get.call_count, 2)
        self.assertTrue(get.call_args.args[0].endswith("/projects/p/queries/job_1"))
        self.assertEqual(get.call_args.kwargs["params"]["location"], "EU")

    def test_pages_are_followed_up_to_max_results_or_to_the_end(self) -> None:
        svc = self._make_service()
        first = self._page(1, 2, pageToken="next")
        with (
            patch("httpx.post", return_value=self._answer(first)),
            patch("httpx.get", side_effect=[self._answer(self._page(3))]),
        ):
            unlimited = svc.run_query("p", "SELECT id FROM t", max_results=0)
        self.assertEqual([row["id"] for row in unlimited["rows"]], ["1", "2", "3"])

        with (
            patch("httpx.post", return_value=self._answer(first)),
            patch("httpx.get") as get,
        ):
            capped = svc.run_query("p", "SELECT id FROM t", max_results=2)
        self.assertEqual([row["id"] for row in capped["rows"]], ["1", "2"])
        get.assert_not_called()

    def test_query_calls_wait_longer_than_bigquery_holds_them(self) -> None:
        # BigQuery holds jobs.query and getQueryResults open for up to timeoutMs; httpx's
        # 5 s default would raise ReadTimeout first, so both calls need a longer timeout.
        svc = self._make_service()
        running = {"jobComplete": False, "jobReference": {"projectId": "p", "jobId": "job_1"}}
        with (
            patch("httpx.post", return_value=self._answer(running)) as post,
            patch("httpx.get", return_value=self._answer(self._page(1))) as get,
        ):
            svc.run_query("p", "SELECT id FROM t")
        held_seconds = post.call_args.kwargs["json"]["timeoutMs"] / 1000
        self.assertEqual(get.call_args.kwargs["params"]["timeoutMs"] / 1000, held_seconds)
        for call in (post.call_args, get.call_args):
            timeout = call.kwargs.get("timeout")
            self.assertIsInstance(timeout, httpx.Timeout)
            self.assertGreater(timeout.read, held_seconds)

    def test_a_query_that_never_finishes_fails_instead_of_returning_no_rows(self) -> None:
        svc = self._make_service()
        running = {"jobComplete": False, "jobReference": {"projectId": "p", "jobId": "job_1"}}
        with (
            patch("httpx.post", return_value=self._answer(running)),
            patch("httpx.get", return_value=self._answer(running)),
            self.assertRaises(ValueError) as raised,
        ):
            svc.run_query("p", "SELECT id FROM t")
        self.assertIn("did not finish", str(raised.exception))

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

    def test_insert_ids_are_unique_across_calls(self) -> None:
        # BigQuery drops a row whose insertId it saw in about the last minute.
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        ids: list[str] = []
        with patch("httpx.post", return_value=mock_response) as mock_post:
            for rows in ([{"event": "signup"}, {"event": "login"}], [{"event": "logout"}]):
                svc.insert_rows("my-project", "my-dataset", "events", rows)
                ids += [row["insertId"] for row in mock_post.call_args[1]["json"]["rows"]]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)

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
                executor = WorkflowExecutor(
                    nodes=nodes,
                    edges=edges,
                    actor_user_id=_uuid.uuid4(),
                )
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
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
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
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
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
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "my-project", "my-dataset", "users", [{"name": "Alice", "age": "30"}]
        )
        self.assertEqual(result.status, "success")
