"""Unit tests for ClickHouseService and the clickhouse executor branch."""

import unittest
from unittest.mock import MagicMock, patch


def _make_config() -> dict:
    return {
        "host": "ch.example.com",
        "port": 8443,
        "username": "default",
        "password": "secret",
        "database": "analytics",
        "secure": True,
    }


class TestClickHouseServiceValidation(unittest.TestCase):
    def _make_service(self):
        from app.services.clickhouse_service import ClickHouseService

        return ClickHouseService(_make_config())

    def test_requires_host(self) -> None:
        from app.services.clickhouse_service import ClickHouseService

        with self.assertRaises(ValueError):
            ClickHouseService({"host": "", "database": "db"})

    def test_rejects_bad_table_name(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError):
            svc.find("bad-table; DROP", filters={}, limit=10, sort="")

    def test_rejects_bad_column_in_filter(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError):
            svc.find("events", filters={"bad col": 1}, limit=10, sort="")


class TestClickHouseReads(unittest.TestCase):
    def _svc_with_client(self, mock_client):
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(_make_config())
        svc._client = MagicMock(return_value=mock_client)
        return svc

    def _mock_query_result(self, rows, columns):
        result = MagicMock()
        result.result_rows = rows
        result.column_names = columns
        return result

    def test_query_select_returns_rows(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(1, "a"), (2, "b")], ["id", "name"])
        svc = self._svc_with_client(client)
        out = svc.query("SELECT id, name FROM events")
        self.assertEqual(out["rows"], [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["success"])

    def test_query_non_select_uses_command(self) -> None:
        client = MagicMock()
        client.command.return_value = "OK"
        svc = self._svc_with_client(client)
        out = svc.query("ALTER TABLE events DELETE WHERE id = 1")
        client.command.assert_called_once()
        self.assertEqual(out["result"], "OK")
        self.assertTrue(out["success"])

    def test_query_non_select_returns_json_safe_summary(self) -> None:
        client = MagicMock()
        summary = MagicMock()
        summary.summary = {"written_rows": "1", "written_bytes": "12", "query_id": "q-1"}
        summary.written_rows = 1
        summary.written_bytes.return_value = 12
        summary.query_id.return_value = "q-1"
        client.command.return_value = summary
        svc = self._svc_with_client(client)
        out = svc.query("INSERT INTO events (id) VALUES ('1')")
        self.assertEqual(
            out["result"],
            {
                "summary": {"written_rows": "1", "written_bytes": "12", "query_id": "q-1"},
                "written_rows": 1,
                "written_bytes": 12,
                "query_id": "q-1",
            },
        )
        self.assertTrue(out["success"])

    def test_find_builds_parameterized_where(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(1,)], ["id"])
        svc = self._svc_with_client(client)
        svc.find("events", filters={"status": "active"}, limit=5, sort="created_at DESC")
        sql, kwargs = client.query.call_args[0][0], client.query.call_args[1]
        self.assertIn("status = {", sql)
        self.assertIn("LIMIT 5", sql)
        self.assertIn("ORDER BY", sql)
        self.assertEqual(kwargs["parameters"]["v_status"], "active")

    def test_count_returns_int(self) -> None:
        client = MagicMock()
        result = MagicMock()
        result.result_rows = [(42,)]
        result.column_names = ["count"]
        client.query.return_value = result
        svc = self._svc_with_client(client)
        out = svc.count("events", filters={})
        self.assertEqual(out["count"], 42)
        self.assertTrue(out["success"])

    def test_get_by_id(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(7, "x")], ["id", "name"])
        svc = self._svc_with_client(client)
        out = svc.get_by_id("events", "7")
        self.assertEqual(out["row"], {"id": 7, "name": "x"})

    def test_list_columns(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result(
            [("id", "String", "", ""), ("ts", "DateTime", "", "")],
            ["name", "type", "default_type", "default_expression"],
        )
        svc = self._svc_with_client(client)
        out = svc.list_columns("events")
        self.assertEqual(
            out["columns"],
            [{"name": "id", "type": "String"}, {"name": "ts", "type": "DateTime"}],
        )
        self.assertTrue(out["success"])
        self.assertIn("DESCRIBE TABLE events", client.query.call_args[0][0])

    def test_list_columns_rejects_bad_table(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.list_columns("bad table; DROP")

    def test_find_unlimited_when_limit_zero(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([], [])
        svc = self._svc_with_client(client)
        svc.find("events", filters={}, limit=0, sort="")
        sql = client.query.call_args[0][0]
        self.assertNotIn("LIMIT", sql)

    def test_find_honors_large_limit_without_cap(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([], [])
        svc = self._svc_with_client(client)
        svc.find("events", filters={}, limit=50000, sort="")
        sql = client.query.call_args[0][0]
        self.assertIn("LIMIT 50000", sql)

    def test_get_all_unlimited_when_limit_zero(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([], [])
        svc = self._svc_with_client(client)
        svc.get_all("events", limit=0)
        sql = client.query.call_args[0][0]
        self.assertNotIn("LIMIT", sql)

    def test_rows_coerced_to_json_safe(self) -> None:
        import datetime as dt
        import json
        from decimal import Decimal
        from uuid import UUID

        client = MagicMock()
        client.query.return_value = self._mock_query_result(
            [
                (
                    "evt-1",
                    dt.datetime(2026, 6, 27, 20, 33, 19),
                    dt.date(2026, 6, 27),
                    Decimal("12.50"),
                    UUID("12345678-1234-5678-1234-567812345678"),
                    ["a", "b"],
                )
            ],
            ["id", "ts", "day", "amount", "uid", "tags"],
        )
        svc = self._svc_with_client(client)
        out = svc.find("events", filters={}, limit=0, sort="")
        # The whole payload must be JSON serializable (the reported bug).
        json.dumps(out)
        row = out["rows"][0]
        self.assertEqual(row["ts"], "2026-06-27T20:33:19")
        self.assertEqual(row["day"], "2026-06-27")
        self.assertEqual(row["amount"], 12.5)
        self.assertEqual(row["uid"], "12345678-1234-5678-1234-567812345678")
        self.assertEqual(row["tags"], ["a", "b"])


class TestClickHouseWrites(unittest.TestCase):
    def _svc_with_client(self, mock_client):
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(_make_config())
        svc._client = MagicMock(return_value=mock_client)
        return svc

    def test_insert_aligns_columns(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        out = svc.insert("events", [{"id": 1, "name": "a"}, {"name": "b"}])
        table, data = client.insert.call_args[0][0], client.insert.call_args[0][1]
        column_names = client.insert.call_args[1]["column_names"]
        self.assertEqual(table, "events")
        self.assertEqual(sorted(column_names), ["id", "name"])
        # missing keys become None, aligned to column order
        self.assertEqual(len(data), 2)
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["success"])

    def test_insert_rejects_empty(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.insert("events", [])

    def test_update_builds_alter(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        svc.update("events", data={"name": "z"}, filters={"id": 1})
        sql = client.command.call_args[0][0]
        params = client.command.call_args[1]["parameters"]
        self.assertIn("ALTER TABLE events UPDATE", sql)
        self.assertIn("name = {", sql)
        self.assertIn("WHERE", sql)
        self.assertEqual(params["set_name"], "z")
        self.assertEqual(params["v_id"], 1)

    def test_update_requires_filter(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.update("events", data={"name": "z"}, filters={})

    def test_remove_builds_delete(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        svc.remove("events", filters={"id": 1})
        sql = client.command.call_args[0][0]
        self.assertIn("DELETE FROM events WHERE", sql)

    def test_remove_requires_filter(self) -> None:
        svc = self._svc_with_client(MagicMock())
        with self.assertRaises(ValueError):
            svc.remove("events", filters={})

    def test_upsert_delegates_to_insert(self) -> None:
        client = MagicMock()
        svc = self._svc_with_client(client)
        out = svc.upsert("events", [{"id": 1}])
        client.insert.assert_called_once()
        self.assertTrue(out["success"])


class TestClickHouseDslPrompt(unittest.TestCase):
    def test_prompt_mentions_clickhouse(self) -> None:
        from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT

        self.assertIn('"type": "clickhouse"', WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("clickhouseOperation", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("clickhouseQuery", WORKFLOW_DSL_SYSTEM_PROMPT)


class TestClickHouseExecutorBranch(unittest.TestCase):
    def _executor(self):
        from app.services.workflow_executor import WorkflowExecutor

        return WorkflowExecutor.__new__(WorkflowExecutor)

    def test_find_dispatch(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        node_data = {
            "credentialId": "cred-1",
            "clickhouseOperation": "find",
            "clickhouseTable": "events",
            "clickhouseFilter": '{"status":"active"}',
            "clickhouseLimit": "5",
            "clickhouseSort": "",
        }
        executor = self._executor()
        executor.evaluate_message_template = lambda tpl, inputs, node_id: tpl
        executor.evaluate_nonempty_message_template = lambda tpl, inputs, node_id: tpl
        fake_service = MagicMock()
        fake_service.find.return_value = {"rows": [], "count": 0, "success": True}
        with (
            patch.object(
                WorkflowExecutor,
                "_get_accessible_credential",
                return_value=MagicMock(encrypted_config="x"),
            ),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"host": "h", "database": "d"},
            ),
            patch(
                "app.services.clickhouse_service.ClickHouseService",
                return_value=fake_service,
            ),
        ):
            output = executor._run_clickhouse_node(node_data, {}, "node-1")
        fake_service.find.assert_called_once()
        self.assertTrue(output["success"])

    def test_insert_selective_dispatch(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        node_data = {
            "credentialId": "cred-1",
            "clickhouseOperation": "insert",
            "clickhouseTable": "events",
            "clickhouseInputMode": "selective",
            "clickhouseMappings": [{"key": "name", "value": "Alice"}],
        }
        executor = self._executor()
        executor.evaluate_message_template = lambda tpl, inputs, node_id: tpl
        executor.evaluate_nonempty_message_template = lambda tpl, inputs, node_id: tpl
        fake_service = MagicMock()
        fake_service.insert.return_value = {"count": 1, "success": True}
        with (
            patch.object(
                WorkflowExecutor,
                "_get_accessible_credential",
                return_value=MagicMock(encrypted_config="x"),
            ),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"host": "h", "database": "d"},
            ),
            patch(
                "app.services.clickhouse_service.ClickHouseService",
                return_value=fake_service,
            ),
        ):
            output = executor._run_clickhouse_node(node_data, {}, "node-1")
        fake_service.insert.assert_called_once_with("events", [{"name": "Alice"}])
        self.assertTrue(output["success"])

    def test_unknown_operation_raises(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        node_data = {
            "credentialId": "cred-1",
            "clickhouseOperation": "bogus",
        }
        executor = self._executor()
        executor.evaluate_message_template = lambda tpl, inputs, node_id: tpl
        fake_service = MagicMock()
        with (
            patch.object(
                WorkflowExecutor,
                "_get_accessible_credential",
                return_value=MagicMock(encrypted_config="x"),
            ),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"host": "h", "database": "d"},
            ),
            patch(
                "app.services.clickhouse_service.ClickHouseService",
                return_value=fake_service,
            ),
        ):
            with self.assertRaises(ValueError):
                executor._run_clickhouse_node(node_data, {}, "node-1")


class TestClickHousePool(unittest.TestCase):
    def setUp(self) -> None:
        from app.services import clickhouse_pool

        clickhouse_pool._clients.clear()

    def test_client_is_cached_per_connection(self) -> None:
        from app.services import clickhouse_pool

        created: list = []

        def fake_get_client(**kwargs):
            obj = object()
            created.append(kwargs)
            return obj

        conn = dict(username="u", password="p", database="d", secure=False)
        with patch(
            "app.services.clickhouse_pool.clickhouse_connect.get_client",
            side_effect=fake_get_client,
        ):
            c1 = clickhouse_pool.get_clickhouse_client(host="h", port=8123, **conn)
            c2 = clickhouse_pool.get_clickhouse_client(host="h", port=8123, **conn)
            c3 = clickhouse_pool.get_clickhouse_client(host="h2", port=8123, **conn)

        self.assertIs(c1, c2)  # same connection reused
        self.assertIsNot(c1, c3)  # different host -> new client
        self.assertEqual(len(created), 2)
