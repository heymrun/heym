"""Tests for the per-workflow run history chat tool (`get_workflow_run_history`)."""

import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import ai_assistant
from app.services import mcp_chat_service, workflow_run_history_tool
from app.services.workflow_run_history_tool import get_workflow_run_history

MODULE = "app.services.workflow_run_history_tool"
T0 = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)


def _result(*, all_rows=None, scalars=None, first=None, scalar_one=None, count=0) -> MagicMock:
    result = MagicMock()
    result.all.return_value = all_rows or []
    result.scalars.return_value.all.return_value = scalars or []
    result.first.return_value = first
    result.scalar_one_or_none.return_value = scalar_one
    result.scalar_one.return_value = count
    return result


def _run(status: str = "success", **overrides) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "status": status,
        "started_at": T1,
        "execution_time_ms": 120.0,
        "trigger_source": "cron",
        "recovered": False,
        "inputs": {"q": "hi"},
        "outputs": {"answer": "ok"},
        "node_results": [],
        "encrypted": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _db(*results: MagicMock, encrypted: int = 0) -> AsyncMock:
    """The listing's statements in order, then the count of encrypted runs it leaves out."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[*results, _result(count=encrypted)])
    return db


class TestRunHistoryMetadata(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.workflow = SimpleNamespace(id=self.workflow_id, name="Daily report")

    async def _call(self, db: AsyncMock, **args) -> dict:
        with patch(f"{MODULE}.get_accessible_workflow", AsyncMock(return_value=self.workflow)):
            return await get_workflow_run_history(
                db, self.user_id, {"workflow_id": str(self.workflow_id), **args}
            )

    async def test_returns_counts_status_breakdown_and_times(self) -> None:
        listed = _run("error")
        db = _db(
            _result(all_rows=[("success", 8, T0, T1, 800.0), ("error", 2, T0, T1, 400.0)]),
            _result(scalars=[listed]),
            _result(first=(listed.id, "error", T1, False)),
        )

        out = await self._call(db)

        self.assertEqual(out["workflow_name"], "Daily report")
        self.assertEqual(out["total_runs"], 10)
        self.assertEqual(out["status_counts"], {"success": 8, "error": 2})
        self.assertEqual(out["first_run_at"], T0.isoformat())
        self.assertEqual(out["last_run_at"], T1.isoformat())
        self.assertEqual(out["avg_execution_time_ms"], 120.0)
        self.assertEqual(out["last_run"]["status"], "error")
        self.assertEqual(out["runs"][0]["execution_id"], str(listed.id))
        self.assertNotIn("node_results", out["runs"][0])
        self.assertNotIn("outputs", out["runs"][0])

    async def test_every_query_is_filtered_by_workflow_id_in_sql(self) -> None:
        db = _db(_result(), _result(), _result())

        await self._call(db)

        self.assertEqual(db.execute.await_count, 4)
        for call in db.execute.await_args_list:
            params = call.args[0].compile().params.values()
            self.assertIn(self.workflow_id, params)

    async def test_status_filter_narrows_the_run_list_but_not_the_totals(self) -> None:
        listed = _run("error")
        db = _db(
            _result(all_rows=[("success", 8, T0, T1, 800.0), ("error", 2, T0, T1, 400.0)]),
            _result(scalars=[listed]),
            _result(first=(listed.id, "error", T1, False)),
        )

        out = await self._call(db, status="ERROR", limit=1)

        self.assertEqual(out["total_runs"], 10)
        self.assertEqual(out["matching_runs"], 2)
        self.assertEqual(out["status_filter"], "error")
        self.assertTrue(out["has_more"])
        runs_stmt = db.execute.await_args_list[1].args[0].compile()
        self.assertIn("error", runs_stmt.params.values())

    async def test_encrypted_runs_are_counted_but_left_out_of_the_list(self) -> None:
        db = _db(
            _result(all_rows=[("success", 3, T0, T1, 300.0)]),
            _result(scalars=[]),
            _result(first=(uuid.uuid4(), "success", T1, True)),
            encrypted=3,
        )

        out = await self._call(db)

        self.assertEqual(out["total_runs"], 3)
        self.assertEqual(out["encrypted_runs_skipped"], 3)
        self.assertEqual(out["matching_runs"], 0)
        self.assertTrue(out["last_run"]["encrypted"])
        runs_sql = str(db.execute.await_args_list[1].args[0].compile())
        self.assertIn("execution_history.encrypted IS false", runs_sql)

    async def test_empty_history(self) -> None:
        out = await self._call(_db(_result(), _result(), _result()))

        self.assertEqual(out["total_runs"], 0)
        self.assertEqual(out["runs"], [])
        self.assertIsNone(out["last_run"])
        self.assertIsNone(out["first_run_at"])
        self.assertFalse(out["has_more"])

    async def test_time_range_adds_a_start_bound(self) -> None:
        db = _db(_result(), _result(), _result())

        await self._call(db, time_range="24h")

        stats_sql = str(db.execute.await_args_list[0].args[0].compile())
        self.assertIn("started_at >=", stats_sql)

    async def test_all_time_range_has_no_start_bound(self) -> None:
        db = _db(_result(), _result(), _result())

        await self._call(db)

        stats_sql = str(db.execute.await_args_list[0].args[0].compile())
        self.assertNotIn("started_at >=", stats_sql)

    async def test_unknown_time_range_is_rejected_without_querying(self) -> None:
        db = _db()

        out = await self._call(db, time_range="yesterday")

        self.assertIn("time_range", out["error"])
        db.execute.assert_not_awaited()

    async def test_limit_is_clamped(self) -> None:
        db = _db(_result(), _result(), _result())

        await self._call(db, limit=9999, offset=-5)

        runs_sql = db.execute.await_args_list[1].args[0].compile()
        self.assertIn(workflow_run_history_tool.MAX_RUN_LIMIT, runs_sql.params.values())
        self.assertIn(0, runs_sql.params.values())


class TestRunHistoryDetail(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.workflow = SimpleNamespace(id=self.workflow_id, name="Daily report")

    async def _call(self, db: AsyncMock, **args) -> dict:
        with patch(f"{MODULE}.get_accessible_workflow", AsyncMock(return_value=self.workflow)):
            return await get_workflow_run_history(
                db, self.user_id, {"workflow_id": str(self.workflow_id), **args}
            )

    async def test_execution_id_returns_inputs_outputs_and_node_trace(self) -> None:
        run = _run(
            "error",
            node_results=[
                {
                    "node_id": "n1",
                    "node_label": "Fetch",
                    "node_type": "http",
                    "status": "error",
                    "execution_time_ms": 12.5,
                    "error": "boom",
                    "output": {"body": "x"},
                }
            ],
        )
        db = _db(_result(scalar_one=run))

        out = await self._call(db, execution_id=str(run.id))

        self.assertEqual(out["execution_id"], str(run.id))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["inputs"], {"q": "hi"})
        self.assertEqual(out["outputs"], {"answer": "ok"})
        self.assertEqual(out["nodes"][0]["node_label"], "Fetch")
        self.assertEqual(out["nodes"][0]["error"], "boom")
        self.assertFalse(out["nodes_truncated"])
        params = db.execute.await_args.args[0].compile().params.values()
        self.assertIn(self.workflow_id, params)
        self.assertIn(run.id, params)

    async def test_run_from_another_workflow_is_not_returned(self) -> None:
        db = _db(_result(scalar_one=None))

        out = await self._call(db, execution_id=str(uuid.uuid4()))

        self.assertEqual(out, {"error": "Execution not found for this workflow"})

    async def test_oversized_payloads_are_bounded(self) -> None:
        run = _run(
            outputs={"blob": "x" * 50_000},
            node_results=[
                {"node_id": f"n{i}", "status": "success", "output": {"v": "y" * 5_000}}
                for i in range(100)
            ],
        )
        db = _db(_result(scalar_one=run))

        out = await self._call(db, execution_id=str(run.id))

        self.assertTrue(out["outputs"]["truncated"])
        self.assertEqual(len(out["nodes"]), 40)
        self.assertTrue(out["nodes_truncated"])
        self.assertEqual(out["node_count"], 100)
        self.assertTrue(out["nodes"][0]["output"]["truncated"])
        self.assertLess(len(json.dumps(out, default=str)), 96_000)

    async def test_invalid_execution_id(self) -> None:
        db = _db()

        out = await self._call(db, execution_id="not-a-uuid")

        self.assertEqual(out, {"error": "Invalid execution_id"})
        db.execute.assert_not_awaited()


class TestRunHistoryAccess(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_workflow_id(self) -> None:
        out = await get_workflow_run_history(_db(), uuid.uuid4(), {"workflow_id": "nope"})

        self.assertEqual(out, {"error": "Invalid workflow_id"})

    async def test_missing_workflow_id(self) -> None:
        out = await get_workflow_run_history(_db(), uuid.uuid4(), {})

        self.assertEqual(out, {"error": "Invalid workflow_id"})

    async def test_inaccessible_workflow_returns_no_history(self) -> None:
        db = _db()
        with patch(f"{MODULE}.get_accessible_workflow", AsyncMock(return_value=None)):
            out = await get_workflow_run_history(
                db, uuid.uuid4(), {"workflow_id": str(uuid.uuid4())}
            )

        self.assertEqual(out, {"error": "Workflow not found or no access"})
        db.execute.assert_not_awaited()


class TestRunHistoryToolWiring(unittest.TestCase):
    def test_tool_requires_only_workflow_id(self) -> None:
        tool = next(
            item
            for item in ai_assistant.DASHBOARD_CHAT_TOOLS
            if item["function"]["name"] == "get_workflow_run_history"
        )
        params = tool["function"]["parameters"]
        self.assertEqual(params["required"], ["workflow_id"])
        for name in ("execution_id", "time_range", "status", "limit", "offset"):
            self.assertIn(name, params["properties"])

    def test_prompt_routes_single_workflow_questions_to_the_tool(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("get_workflow_run_history", prompt)
        self.assertIn("execution_id", prompt)

    def test_mcp_chat_tool_advertises_the_capability(self) -> None:
        self.assertIn("run history", mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION)

    def test_summaries(self) -> None:
        summarize = ai_assistant._summarize_tool_result
        self.assertEqual(
            summarize("get_workflow_run_history", json.dumps({"total_runs": 10, "returned": 3})),
            "10 run(s), 3 listed",
        )
        self.assertEqual(
            summarize(
                "get_workflow_run_history",
                json.dumps({"execution_id": "x", "status": "error", "node_count": 4, "nodes": []}),
            ),
            "Run detail: error (4 node(s))",
        )
        self.assertEqual(
            summarize("get_workflow_run_history", json.dumps({"error": "Invalid workflow_id"})),
            "Error: Invalid workflow_id",
        )

    def test_failed_run_detail_is_not_a_failed_tool_call(self) -> None:
        payload = json.dumps({"execution_id": "x", "status": "error", "nodes": []})
        self.assertEqual(
            ai_assistant._chat_tool_lifecycle_status("get_workflow_run_history", payload),
            "success",
        )

    def test_error_payload_marks_tool_call_failed(self) -> None:
        payload = json.dumps({"error": "Workflow not found or no access"})
        self.assertEqual(
            ai_assistant._chat_tool_lifecycle_status("get_workflow_run_history", payload),
            "error",
        )


if __name__ == "__main__":
    unittest.main()
