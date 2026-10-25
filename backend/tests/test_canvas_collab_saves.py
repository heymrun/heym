"""Saves tell the workflow's canvas room, inside the saving transaction."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from app.api.workflows import update_workflow
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate
from app.services.collab.saves import queue_collab_saved
from app.services.collab.wire import CHANNEL


def _workflow(owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Collab workflow",
        description=None,
        nodes=[],
        edges=[],
        auth_type=WorkflowAuthType.anonymous,
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode=WebhookBodyMode.generic,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
        allow_anonymous=True,
        owner_id=owner_id,
        folder_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class QueueCollabSavedTests(unittest.IsolatedAsyncioTestCase):
    async def test_queues_one_notify_on_the_saving_session(self) -> None:
        db = AsyncMock()
        workflow_id, actor_id, sid = uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())

        await queue_collab_saved(db, workflow_id, actor_id, session=sid, state_hash="abc123")

        db.execute.assert_awaited_once()
        statement, params = db.execute.await_args.args
        self.assertIn("pg_notify", str(statement))
        self.assertEqual(CHANNEL, params["channel"])
        self.assertTrue(params["prefix"].startswith(f"{workflow_id}|"))
        self.assertTrue(params["prefix"].endswith("|0/1|"))
        self.assertEqual(
            (sid, "abc123", str(actor_id)), (params["sid"], params["hash"], params["by"])
        )


class UpdateWorkflowAnnouncesTests(unittest.IsolatedAsyncioTestCase):
    async def _save(self, **headers: Any) -> tuple[AsyncMock, list[str]]:
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id)
        order: list[str] = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        db.add = lambda _row: None
        db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
        queue = AsyncMock(side_effect=lambda *_a, **_k: order.append("queue"))
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows._build_workflow_response", return_value={}),
            patch("app.api.workflows.announce_workflow_saved", AsyncMock()),
            patch("app.api.workflows.queue_collab_saved", queue),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=WorkflowUpdate(nodes=[], edges=[]),
                current_user=SimpleNamespace(id=owner_id),
                db=db,
                **headers,
            )
        return queue, order

    async def test_an_editor_save_names_its_session_before_commit(self) -> None:
        sid = str(uuid.uuid4())

        queue, order = await self._save(collab_session=sid, collab_hash="k3x9")

        self.assertEqual(sid, queue.await_args.kwargs["session"])
        self.assertEqual("k3x9", queue.await_args.kwargs["state_hash"])
        self.assertEqual(["queue", "commit"], order)

    async def test_invalid_headers_count_as_an_external_save(self) -> None:
        queue, _order = await self._save(collab_session="nope", collab_hash="BAD!")

        self.assertIsNone(queue.await_args.kwargs["session"])
        self.assertIsNone(queue.await_args.kwargs["state_hash"])

    async def test_a_save_without_headers_is_external(self) -> None:
        queue, _order = await self._save()

        self.assertIsNone(queue.await_args.kwargs["session"])
