"""Editors set the limit through PUT; 0 clears it and negatives are rejected."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.schemas import WorkflowUpdate


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="wf",
        nodes=[],
        edges=[],
        http_method="POST",
        sse_node_config=None,
        updated_at=None,
        auth_type=None,
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode=None,
        description=None,
        folder_id=None,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        auto_recover_runs=True,
        error_workflow_id=None,
        minutes_saved_per_run=None,
        workflow_timeout_seconds=None,
        concurrency_limit=None,
        concurrency_max_queue=None,
        concurrency_max_wait_seconds=None,
        kind="workflow",
        portal_enabled=False,
        portal_slug=None,
        mcp_enabled=False,
    )


class ConcurrencySettingsUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def _update(
        self, workflow: SimpleNamespace, data: WorkflowUpdate, *, writable: bool = True
    ) -> AsyncMock:
        from app.api.workflows import update_workflow

        promote = AsyncMock(return_value=0)
        write_check = AsyncMock()
        if not writable:
            write_check.side_effect = HTTPException(status_code=403, detail="read-only")
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows.require_workflow_write", write_check),
            patch("app.api.workflows.publish_event", AsyncMock()),
            patch("app.api.workflows._build_workflow_response", lambda wf, uid: wf),
            patch("app.api.workflows.workflow_concurrency.promote", promote),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=data,
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        return promote

    async def test_positive_values_are_stored(self) -> None:
        workflow = _workflow()
        await self._update(
            workflow,
            WorkflowUpdate(
                concurrency_limit=2, concurrency_max_queue=50, concurrency_max_wait_seconds=300
            ),
        )
        self.assertEqual(workflow.concurrency_limit, 2)
        self.assertEqual(workflow.concurrency_max_queue, 50)
        self.assertEqual(workflow.concurrency_max_wait_seconds, 300)

    async def test_zero_clears_each_field(self) -> None:
        workflow = _workflow()
        workflow.concurrency_limit = 3
        workflow.concurrency_max_queue = 10
        workflow.concurrency_max_wait_seconds = 60
        await self._update(
            workflow,
            WorkflowUpdate(
                concurrency_limit=0, concurrency_max_queue=0, concurrency_max_wait_seconds=0
            ),
        )
        self.assertIsNone(workflow.concurrency_limit)
        self.assertIsNone(workflow.concurrency_max_queue)
        self.assertIsNone(workflow.concurrency_max_wait_seconds)

    async def test_a_change_promotes_waiting_runs_right_away(self) -> None:
        workflow = _workflow()
        promote = await self._update(workflow, WorkflowUpdate(concurrency_limit=4))
        promote.assert_awaited_once_with(workflow.id)

    async def test_an_unrelated_save_does_not_promote(self) -> None:
        promote = await self._update(_workflow(), WorkflowUpdate(name="renamed"))
        promote.assert_not_awaited()

    async def test_a_read_only_collaborator_is_rejected(self) -> None:
        workflow = _workflow()
        with self.assertRaises(HTTPException) as ctx:
            await self._update(workflow, WorkflowUpdate(concurrency_limit=1), writable=False)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsNone(workflow.concurrency_limit)

    def test_negative_values_fail_validation(self) -> None:
        for field in ("concurrency_limit", "concurrency_max_queue", "concurrency_max_wait_seconds"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                WorkflowUpdate(**{field: -1})
