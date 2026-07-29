import unittest
import uuid
from unittest.mock import patch

from app.services.workflow_executor import WorkflowExecutor


class WorkflowTraceMetadataTests(unittest.TestCase):
    def test_llm_node_moves_internal_trace_id_to_metadata(self) -> None:
        trace_id = str(uuid.uuid4())
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "llm1",
                    "type": "llm",
                    "data": {
                        "label": "draftReply",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_llm_node",
            return_value={"text": "ok", "model": "gpt-test", "_trace_id": trace_id},
        ):
            result = executor.execute_node_parallel("llm1", {})

        self.assertEqual(result.metadata["trace_id"], trace_id)
        self.assertNotIn("_trace_id", result.output)

    def test_llm_json_output_preserves_trace_metadata(self) -> None:
        trace_id = str(uuid.uuid4())
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "llm1",
                    "type": "llm",
                    "data": {
                        "label": "parseReply",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                        "jsonOutputEnabled": True,
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_llm_node",
            return_value={
                "text": '{"answer":"ok"}',
                "model": "gpt-test",
                "_trace_id": trace_id,
            },
        ):
            result = executor.execute_node_parallel("llm1", {})

        self.assertEqual(result.metadata["trace_id"], trace_id)
        self.assertEqual(result.output["answer"], "ok")
        self.assertNotIn("_trace_id", result.output)

    def test_llm_error_preserves_trace_metadata(self) -> None:
        trace_id = str(uuid.uuid4())
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "llm1",
                    "type": "llm",
                    "data": {
                        "label": "draftReply",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_llm_node",
            return_value={
                "text": "",
                "model": "gpt-test",
                "error": "failed",
                "_trace_id": trace_id,
            },
        ):
            result = executor.execute_node_parallel("llm1", {})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.metadata["trace_id"], trace_id)
        self.assertNotIn("_trace_id", result.output)

    def test_agent_node_moves_internal_trace_id_to_metadata(self) -> None:
        trace_id = str(uuid.uuid4())
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={"text": "ok", "model": "gpt-test", "_trace_id": trace_id},
        ):
            result = executor.execute_node_parallel("agent1", {})

        self.assertEqual(result.metadata["trace_id"], trace_id)
        self.assertNotIn("_trace_id", result.output)

    def test_agent_error_preserves_trace_metadata(self) -> None:
        trace_id = str(uuid.uuid4())
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={
                "text": "",
                "model": "gpt-test",
                "error": "failed",
                "_trace_id": trace_id,
            },
        ):
            result = executor.execute_node_parallel("agent1", {})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.metadata["trace_id"], trace_id)
        self.assertNotIn("_trace_id", result.output)

    def test_delegated_sub_agent_preserves_trace_metadata(self) -> None:
        trace_id = str(uuid.uuid4())
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={
                "text": "ok",
                "model": "gpt-test",
                "timing_breakdown": {"llm_ms": 25, "tools_ms": 0, "mcp_list_ms": 0},
                "_trace_id": trace_id,
            },
        ):
            tool_result = executor._execute_sub_agent_tool(
                {"_sub_agent_labels": ["researchAgent"]},
                "call_sub_agent",
                {"sub_agent_label": "researchAgent", "prompt": "go"},
                30,
            )

        self.assertEqual(tool_result, {"text": "ok"})
        delegated_result = executor.delegated_agent_node_results[0]
        self.assertEqual(delegated_result.metadata["invocation"], "sub_agent_tool")
        self.assertEqual(delegated_result.metadata["trace_id"], trace_id)
        self.assertNotIn("_trace_id", delegated_result.output)

    def test_sub_agent_tool_returns_cancelled_when_cancel_event_set(self) -> None:
        from threading import Event

        from app.services.workflow_executor import WorkflowExecutor

        cancel_event = Event()
        cancel_event.set()
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
            cancel_event=cancel_event,
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={"text": "", "error": "Workflow execution cancelled"},
        ):
            tool_result = executor._execute_sub_agent_tool(
                {"_sub_agent_labels": ["researchAgent"]},
                "call_sub_agent",
                {"sub_agent_label": "researchAgent", "prompt": "go"},
                30,
            )

        self.assertEqual(tool_result["status"], "cancelled")
        self.assertEqual(tool_result["error"], "Workflow execution cancelled")
        # NodeResult stays error for Debug/timeline; lifecycle lives on the tool payload.
        self.assertEqual(executor.delegated_agent_node_results[0].status, "error")

    def test_sub_agent_tool_returns_cancelled_from_nested_tool_metrics(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={
                "text": "",
                "error": "stopped by operator",
                "tool_calls": [{"name": "child", "status": "cancelled"}],
                "tool_metrics": {"cancelled": 1, "error": 0, "timeout": 0},
            },
        ):
            tool_result = executor._execute_sub_agent_tool(
                {"_sub_agent_labels": ["researchAgent"]},
                "call_sub_agent",
                {"sub_agent_label": "researchAgent", "prompt": "go"},
                30,
            )

        self.assertEqual(tool_result["status"], "cancelled")
        self.assertEqual(tool_result["error"], "stopped by operator")
        self.assertEqual(executor.delegated_agent_node_results[0].status, "error")

    def test_sub_agent_tool_returns_timeout_on_workflow_timeout_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor, WorkflowTimeoutError

        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            side_effect=WorkflowTimeoutError("Workflow timed out after 30 seconds"),
        ):
            tool_result = executor._execute_sub_agent_tool(
                {"_sub_agent_labels": ["researchAgent"]},
                "call_sub_agent",
                {"sub_agent_label": "researchAgent", "prompt": "go"},
                30,
            )

        self.assertEqual(tool_result["status"], "timeout")
        self.assertIn("timed out", tool_result["error"])
        self.assertEqual(executor.delegated_agent_node_results[0].status, "error")

    def test_prior_nested_timeout_does_not_reclassify_later_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={
                "text": "",
                "error": "All credential/model attempts failed",
                "tool_calls": [
                    {"name": "slow", "status": "timeout"},
                    {"name": "other", "status": "error", "result": {"error": "boom"}},
                ],
                "tool_metrics": {"timeout": 1, "error": 1, "cancelled": 0},
            },
        ):
            tool_result = executor._execute_sub_agent_tool(
                {"_sub_agent_labels": ["researchAgent"]},
                "call_sub_agent",
                {"sub_agent_label": "researchAgent", "prompt": "go"},
                30,
            )

        self.assertEqual(tool_result["status"], "error")
        self.assertEqual(tool_result["error"], "All credential/model attempts failed")
        self.assertEqual(executor.delegated_agent_node_results[0].status, "error")

    def test_sub_agent_error_text_alone_does_not_become_cancelled(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "agent1",
                    "type": "agent",
                    "data": {
                        "label": "researchAgent",
                        "credentialId": str(uuid.uuid4()),
                        "model": "gpt-test",
                        "userMessage": "hello",
                    },
                }
            ],
            edges=[],
        )

        with patch.object(
            executor,
            "_execute_agent_node",
            return_value={
                "text": "",
                "error": "Variable 'Workflow execution cancelled' not found",
            },
        ):
            tool_result = executor._execute_sub_agent_tool(
                {"_sub_agent_labels": ["researchAgent"]},
                "call_sub_agent",
                {"sub_agent_label": "researchAgent", "prompt": "go"},
                30,
            )

        self.assertEqual(tool_result["status"], "error")
        self.assertEqual(
            tool_result["error"],
            "Variable 'Workflow execution cancelled' not found",
        )


if __name__ == "__main__":
    unittest.main()
