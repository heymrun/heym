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


if __name__ == "__main__":
    unittest.main()
