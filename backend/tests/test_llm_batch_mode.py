import queue
import unittest
import uuid
from unittest.mock import patch

from app.services.llm_provider import (
    NON_OPENAI_LLM_BATCH_MESSAGE,
    fetch_custom_models,
    get_default_openai_models,
)
from app.services.workflow_executor import WorkflowExecutor


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    async def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        del headers
        if url.endswith("/models"):
            return _FakeResponse(
                200,
                {
                    "data": [
                        {"id": "provider/gpt-4o-mini"},
                        {"id": "provider/o1-mini"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL requested in test: {url}")


class LlmBatchProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_default_openai_models_are_marked_batch_capable(self) -> None:
        models = get_default_openai_models()

        self.assertTrue(models)
        self.assertTrue(all(model.supports_batch for model in models))
        self.assertTrue(all(model.batch_support_reason for model in models))

    @patch("app.services.llm_provider.httpx.AsyncClient", _FakeAsyncClient)
    async def test_custom_models_mark_batch_unsupported(self) -> None:
        models = await fetch_custom_models("https://example.com", "test-key")

        self.assertEqual(
            [model.id for model in models], ["provider/gpt-4o-mini", "provider/o1-mini"]
        )
        self.assertTrue(all(model.supports_batch is False for model in models))
        self.assertTrue(
            all(model.batch_support_reason == NON_OPENAI_LLM_BATCH_MESSAGE for model in models)
        )


class LlmBatchExecutionTests(unittest.TestCase):
    def test_batch_mode_requires_array_user_message(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        result = executor._execute_llm_node(
            credential_id="credential-id",
            node_id="llm-1",
            model="gpt-4o-mini",
            system_instruction=None,
            user_message="hello",
            temperature=0.7,
            reasoning_effort=None,
            max_tokens=None,
            json_output_enabled=False,
            json_output_schema=None,
            image_input=None,
            batch_mode_enabled=True,
        )

        self.assertIn("resolve to an array", result["error"])

    def test_batch_user_message_dollar_array_uses_preserved_list_type(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        raw = executor.resolve_expression(
            '$array("selamlar", "günaydın", "nasılsınız?")',
            {},
            preserve_type=True,
        )
        self.assertIsInstance(raw, list)
        self.assertEqual(raw, ["selamlar", "günaydın", "nasılsınız?"])

    def test_resolve_expression_serializes_array_without_preserve_type(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        as_default = executor.resolve_expression('$array("a", "b")', {})
        self.assertIsInstance(as_default, str)
        self.assertEqual(as_default, '["a", "b"]')

    def test_batch_mode_rejects_image_input(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        result = executor._execute_llm_node(
            credential_id="credential-id",
            node_id="llm-1",
            model="gpt-4o-mini",
            system_instruction=None,
            user_message=["hello"],
            temperature=0.7,
            reasoning_effort=None,
            max_tokens=None,
            json_output_enabled=False,
            json_output_schema=None,
            image_input="data:image/png;base64,abc",
            batch_mode_enabled=True,
        )

        self.assertIn("does not support image input", result["error"])

    def test_batch_status_branch_runs_connected_nodes_and_emits_progress(self) -> None:
        progress_queue: queue.Queue = queue.Queue()
        nodes = [
            {
                "id": "llm-1",
                "type": "llm",
                "data": {
                    "label": "batchLlm",
                    "batchModeEnabled": True,
                },
            },
            {
                "id": "set-1",
                "type": "set",
                "data": {
                    "label": "captureBatchStatus",
                    "mappings": [
                        {"key": "status", "value": "$input.batchStatus"},
                        {"key": "completed", "value": "$input.completed"},
                    ],
                },
            },
        ]
        edges = [
            {
                "id": "edge-1",
                "source": "llm-1",
                "sourceHandle": "batchStatus",
                "target": "set-1",
            }
        ]
        executor = WorkflowExecutor(
            nodes=nodes,
            edges=edges,
            workflow_id=uuid.uuid4(),
            agent_progress_queue=progress_queue,
        )

        executor._handle_llm_batch_status_update(
            node_id="llm-1",
            node_label="batchLlm",
            payload={
                "batchId": "batch_123",
                "status": "processing",
                "rawStatus": "in_progress",
                "completed": 2,
                "failed": 0,
                "total": 5,
                "requestCounts": {"total": 5, "completed": 2, "failed": 0},
                "provider": "Custom",
                "model": "provider/gpt-4o-mini",
                "timestamp": 123,
            },
        )

        branch_results = [
            result
            for result in executor.notification_branch_node_results
            if result.node_id == "set-1" and result.status == "success"
        ]
        self.assertEqual(len(branch_results), 1)
        self.assertEqual(branch_results[0].output["status"], "processing")
        self.assertEqual(branch_results[0].output["completed"], 2)

        events = []
        while not progress_queue.empty():
            events.append(progress_queue.get_nowait())

        self.assertTrue(any(event.get("type") == "llm_batch_progress" for event in events))
        self.assertTrue(
            any(
                event.get("type") == "node_complete" and event.get("node_id") == "set-1"
                for event in events
            )
        )


if __name__ == "__main__":
    unittest.main()
