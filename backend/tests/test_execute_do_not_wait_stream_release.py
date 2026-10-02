"""The streaming endpoint must not stay open for a fire-and-forget sub-workflow.

`executeDoNotWait` dispatches a sub-workflow and the parent's own run ends immediately.
The parent's SSE stream and its active-execution registration have to end with the run,
not with the dispatched work: the API layer still drains that work afterwards so its
history is recorded, and that drain used to hold both open.
"""

import asyncio
import json
import threading
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

# The dispatched sub-workflow blocks on a gate the test controls instead of sleeping for a
# fixed time. A wall-clock threshold on the parent's stream is flaky on slow CI runners; a
# gate makes "the stream was held open by the dispatch" fail deterministically, because the
# gate is only released after the stream has been asserted to be over.
_TARGET_WORKFLOW = {
    "nodes": [
        {
            "id": "t1",
            "type": "textInput",
            "data": {"label": "input", "inputFields": [{"key": "text"}]},
        },
        {"id": "t2", "type": "wait", "data": {"label": "wait", "duration": 0}},
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


# Upper bound for waiting on the stream. It is never the pass condition: it only turns a
# stream that is genuinely held open into a failure instead of a hung test run.
_STREAM_DEADLINE_SECONDS = 20.0


class DoNotWaitStreamReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_ends_before_the_dispatched_sub_workflow_does(self) -> None:
        from app.api.workflows import execute_workflow_stream
        from app.services.node_execution import registry

        gate = threading.Event()
        self.addCleanup(gate.set)

        def blocked_wait_handler(ctx: object) -> object:
            """Stand-in for the wait node that only returns once the test opens the gate."""
            gate.wait(timeout=60)
            return {"value": "released"}

        handler_patch = patch.dict(registry._HANDLER_CACHE, {"wait": blocked_wait_handler})
        handler_patch.start()
        self.addCleanup(handler_patch.stop)

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

            async def read_stream() -> list[str | bytes]:
                return [chunk async for chunk in response.body_iterator]

            try:
                frames = await asyncio.wait_for(read_stream(), timeout=_STREAM_DEADLINE_SECONDS)
            except asyncio.TimeoutError:
                self.fail("the parent's stream was held open by the dispatched sub-workflow")

        payload = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in frames)
        self.assertIn("execution_complete", payload)

        started = next(
            line for line in payload.splitlines() if '"type": "execution_started"' in line
        )
        execution_id = json.loads(started[len("data: ") :])["execution_id"]

        # The gate is still closed, so the stream ending proves it did not wait for the
        # dispatched sub-workflow.
        self.assertFalse(gate.is_set())

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
        # next test (or into interpreter shutdown, where the shared pool is closed). Yield to
        # the loop while polling: the drain's bookkeeping is scheduled on it.
        gate.set()
        deadline = time.monotonic() + _STREAM_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            if not [
                handle
                for handle in list_active_executions()
                if str(handle.workflow_id) == TARGET_WF_ID
            ]:
                break
            await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
