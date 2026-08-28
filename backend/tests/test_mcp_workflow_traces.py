import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request

from app.api.mcp import call_mcp_tool
from app.db.models import LLMTrace
from app.services.workflow_executor import ExecutionResult


def make_request(body: dict) -> Request:
    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": json.dumps(body).encode("utf-8"),
            "more_body": False,
        }

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mcp/tools/call",
            "headers": [],
            "query_string": b"",
        },
        receive,
    )


class McpWorkflowTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_tool_workflow_execution_adds_trace(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=user.id,
            name="Daily Report",
            description="Build daily report",
            nodes=[{"id": "input1", "type": "manual", "data": {"label": "Input"}}],
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"result": "ok"},
            execution_time_ms=12.5,
            node_results=[
                {
                    "node_id": "input1",
                    "node_label": "Input",
                    "node_type": "manual",
                    "status": "success",
                    "output": {"result": "ok"},
                    "execution_time_ms": 12.5,
                    "metadata": {},
                }
            ],
            sub_workflow_executions=[],
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.mcp.get_user_mcp_workflows", AsyncMock(return_value=[workflow])),
            patch("app.api.mcp.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.mcp.get_global_variables_context", AsyncMock(return_value={})),
            patch(
                "app.services.cluster.dispatch.execute_workflow", return_value=execution_result
            ) as execute_mock,
            patch("app.api.mcp.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.mcp._persist_global_variables_from_execution", AsyncMock()),
        ):
            response = await call_mcp_tool(
                request=make_request({"name": "daily_report", "arguments": {"date": "2026-05-02"}}),
                mcp_user=user,
                db=db,
            )

        self.assertFalse(response.isError)
        self.assertEqual(execute_mock.call_args.kwargs["trace_user_id"], user.id)
        traces = [
            call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], LLMTrace)
        ]
        self.assertEqual(len(traces), 1)
        trace = traces[0]
        self.assertEqual(trace.user_id, user.id)
        self.assertEqual(trace.workflow_id, workflow.id)
        self.assertEqual(trace.source, "mcp")
        self.assertEqual(trace.request_type, "mcp.workflow.execute")
        self.assertEqual(trace.provider, "Heym MCP")
        self.assertIsNone(trace.credential_id)
        self.assertEqual(trace.request["tool_name"], "daily_report")
        self.assertEqual(trace.request["arguments"], {"date": "2026-05-02"})
        self.assertEqual(trace.response["status"], "success")
        self.assertEqual(trace.response["outputs"], {"result": "ok"})
        self.assertIsNone(trace.error)


if __name__ == "__main__":
    unittest.main()
