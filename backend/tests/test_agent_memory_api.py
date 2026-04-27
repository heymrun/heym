"""Async unit tests for agent memory REST handlers (mocked DB)."""

import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.agent_memory import add_memory_edge, get_memory_graph, update_memory_node
from app.models.agent_memory_schemas import EdgeCreateRequest, NodeUpdateRequest


class GetMemoryGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_graph(self) -> None:
        wf_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        wf = MagicMock()

        empty_nodes = MagicMock()
        empty_nodes.scalars.return_value.all.return_value = []
        empty_edges = MagicMock()
        empty_edges.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[empty_nodes, empty_edges])

        with patch("app.api.agent_memory.get_workflow_for_user", AsyncMock(return_value=wf)):
            result = await get_memory_graph(wf_id, "canvas-node-1", db, user)

        self.assertEqual(result.nodes, [])
        self.assertEqual(result.edges, [])

    async def test_workflow_not_found_404(self) -> None:
        wf_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()

        with patch("app.api.agent_memory.get_workflow_for_user", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await get_memory_graph(wf_id, "n1", db, user)

        self.assertEqual(ctx.exception.status_code, 404)


class AddMemoryEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_entity_400(self) -> None:
        wf_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        wf = MagicMock()

        src_res = MagicMock()
        src_res.scalars.return_value.first.return_value = None
        tgt_res = MagicMock()
        tgt_row = MagicMock()
        tgt_res.scalars.return_value.first.return_value = tgt_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[src_res, tgt_res])

        body = EdgeCreateRequest(
            source_entity_name="Ghost",
            target_entity_name="Real",
            relationship_type="knows",
        )

        with patch("app.api.agent_memory.get_workflow_for_user", AsyncMock(return_value=wf)):
            with self.assertRaises(HTTPException) as ctx:
                await add_memory_edge(wf_id, "agent-main", body, db, user)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not found", ctx.exception.detail.lower())


class UpdateMemoryNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_row_after_flush_before_response(self) -> None:
        """Expired ORM state after flush must be refreshed for async session (updated_at, etc.)."""
        wf_id = uuid.uuid4()
        memory_node_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        wf = MagicMock()

        now = datetime.now(UTC)
        row = MagicMock()
        row.id = memory_node_id
        row.entity_name = "Entity"
        row.entity_type = "topic"
        row.properties = {}
        row.confidence = 1.0
        row.created_at = now
        row.updated_at = now

        qres = MagicMock()
        qres.scalar_one_or_none.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=qres)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        body = NodeUpdateRequest(properties={"serving_style": "cone"})

        with patch("app.api.agent_memory.get_workflow_for_user", AsyncMock(return_value=wf)):
            await update_memory_node(wf_id, memory_node_id, body, db, user)

        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(row)


if __name__ == "__main__":
    unittest.main()
