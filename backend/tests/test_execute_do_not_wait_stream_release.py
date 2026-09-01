"""The streaming endpoint must not stay open for a fire-and-forget sub-workflow.

`executeDoNotWait` dispatches a sub-workflow and the parent's own run ends immediately.
The parent's SSE stream and its active-execution registration have to end with the run,
not with the dispatched work: the API layer still drains that work afterwards so its
history is recorded, and that drain used to hold both open.
"""

import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.execution_cancellation import (
    get_completed_execution_result,
    list_active_executions,
)

TARGET_WF_ID = "22222222-2222-2222-2222-222222222222"

# 1500 ms is long enough that a stream held open by the drain is unmistakable, and short
# enough to keep the test quick.
_TARGET_WORKFLOW = {
    "nodes": [
        {
            "id": "t1",
            "type": "textInput",
            "data": {"label": "input", "inputFields": [{"key": "text"}]},
        },
        {"id": "t2", "type": "wait", "data": {"label": "wait", "duration": 1500}},
        {"id": "t3", "type": "output", "data": {"label": "output"}},
    ],
    "edges": [
        {"id": "te1", "source": "t1", "target": "t2"},
        {"id": "te2", "source": "t2", "target": "t3"},
    ],
    "name": "Target",
}

_PARENT_NODES = [
    {
        "id": "n1",
        "type": "textInput",
        "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
    },
    {
        "id": "n2",
        "type": "execute",
        "data": {
            "label": "callWorkflow",
            "executeWorkflowId": TARGET_WF_ID,
            "executeInput": "$userInput.body.text",
            "executeDoNotWait": True,
        },
    },
]
_PARENT_EDGES = [{"id": "e1", "source": "n1", "target": "n2"}]


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class DoNotWaitStreamReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_ends_before_the_dispatched_sub_workflow_does(self) -> None:
        from app.api.workflows import execute_workflow_stream

        wf_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=wf_id,
            owner_id=uuid.uuid4(),
            name="Parent",
            nodes=_PARENT_NODES,
            edges=_PARENT_EDGES,
            sse_enabled=True,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_node_config={},
            workflow_timeout_seconds=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        request = MagicMock()
        request.method = "POST"
        request.headers = {}
        request.query_params = {}
        request.base_url = "http://localhost/"
        request.is_disconnected = AsyncMock(return_value=False)

        with (
            patch(
                "app.api.workflows.parse_execute_body",
                AsyncMock(return_value=({"text": "hello"}, False, "API", False)),
            ),
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=None)),
            patch("app.api.workflows.enforce_workflow_http_method", MagicMock()),
            patch(
                "app.api.workflows.collect_referenced_workflows",
                AsyncMock(return_value={TARGET_WF_ID: _TARGET_WORKFLOW}),
            ),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.build_public_base_url", return_value="http://localhost"),
            patch(
                "app.api.workflows.persist_stream_execution_result", AsyncMock(return_value=False)
            ),
        ):
            response = await execute_workflow_stream(
                workflow_id=wf_id,
                request=request,
                current_user=None,
                db=db,
            )

            started_at = time.monotonic()
            frames = [chunk async for chunk in response.body_iterator]
            stream_seconds = time.monotonic() - started_at

        payload = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in frames)
        self.assertIn("execution_complete", payload)

        started = next(
            line for line in payload.splitlines() if '"type": "execution_started"' in line
        )
        execution_id = json.loads(started[len("data: ") :])["execution_id"]

        # The parent's own nodes are instant; only the dispatched sub-workflow is slow.
        self.assertLess(
            stream_seconds,
            1.0,
            "the parent's stream was held open by the dispatched sub-workflow",
        )

        parent_still_active = [
            handle for handle in list_active_executions() if handle.workflow_id == wf_id
        ]
        self.assertEqual(
            parent_still_active,
            [],
            "the parent stayed in the active registry while its dispatch ran",
        )

        # The dispatched run is genuinely still going, so the assertions above are not
        # passing merely because everything already finished.
        target_active = [
            handle for handle in list_active_executions() if str(handle.workflow_id) == TARGET_WF_ID
        ]
        self.assertEqual(len(target_active), 1)

        # Releasing the run must hand observers its terminal payload. `execution_complete`
        # is never buffered as a progress event, and the history row is only written once
        # the dispatch is drained, so clearing the handle without this leaves a watcher of
        # the parent with no way at all to learn the run ended.
        completed = get_completed_execution_result(
            uuid.UUID(execution_id),
            workflow_id=wf_id,
        )
        self.assertIsNotNone(
            completed,
            "an observer of the parent has no terminal event while the dispatch runs",
        )
        assert completed is not None
        self.assertEqual(completed["type"], "execution_complete")
        self.assertEqual(completed["status"], "success")
        self.assertEqual(
            [item["node_id"] for item in completed["node_results"]],
            ["n1", "n2"],
            "the terminal payload must carry the run's node results",
        )

        # Let the dispatch finish before the test ends, so it does not run on into the
        # next test (or into interpreter shutdown, where the shared pool is closed).
        deadline = time.time() + 10
        while time.time() < deadline:
            if not [
                handle
                for handle in list_active_executions()
                if str(handle.workflow_id) == TARGET_WF_ID
            ]:
                break
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
