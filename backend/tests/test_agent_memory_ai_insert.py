"""AI insert and Clear all for the agent memory graph dialog."""

import json
import unittest
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import delete, select, text

from app.api.agent_memory import ai_insert_memory, clear_memory_graph
from app.db.models import AgentMemoryEdge, AgentMemoryNode, CredentialType, User, Workflow
from app.db.session import SessionLocal
from app.models.agent_memory_schemas import MemoryAiInsertRequest
from app.services.agent_memory_service import (
    AI_INSERT_MAX_TEXT_CHARS,
    MEMORY_INSERT_SYSTEM,
    MemoryMergeResult,
    apply_parsed_extraction_sync,
    build_memory_insert_payload,
    insert_only_extraction,
    memory_llm_endpoint,
)

API = "app.api.agent_memory"


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _memory_node(name: str, entity_type: str = "person") -> MagicMock:
    now = datetime.now(UTC)
    row = MagicMock()
    row.id = uuid.uuid4()
    row.entity_name = name
    row.entity_type = entity_type
    row.properties = {}
    row.confidence = 1.0
    row.created_at = now
    row.updated_at = now
    return row


def _rows_result(rows: list[Any]) -> MagicMock:
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    return res


class InsertOnlyExtractionTests(unittest.TestCase):
    def test_drops_revoked_entities(self) -> None:
        out = insert_only_extraction(
            {
                "revoked_entities": ["Old Employer"],
                "entities": [{"name": "Ada", "type": "person"}],
                "relationships": [{"source": "Ada", "target": "Acme", "type": "works for"}],
            }
        )
        self.assertEqual(out["revoked_entities"], [])
        self.assertEqual(out["entities"], [{"name": "Ada", "type": "person"}])
        self.assertEqual(len(out["relationships"]), 1)

    def test_non_list_sections_become_empty(self) -> None:
        out = insert_only_extraction({"entities": "Ada", "relationships": None})
        self.assertEqual(out, {"revoked_entities": [], "entities": [], "relationships": []})

    def test_insert_prompt_never_asks_for_revocations(self) -> None:
        self.assertNotIn("revoked_entities", MEMORY_INSERT_SYSTEM)
        self.assertIn('"entities"', MEMORY_INSERT_SYSTEM)
        self.assertIn('"relationships"', MEMORY_INSERT_SYSTEM)


class BuildMemoryInsertPayloadTests(unittest.TestCase):
    def test_includes_text_and_existing_graph(self) -> None:
        payload = build_memory_insert_payload(
            "  Ada works for Acme.  ",
            [{"name": "Acme", "type": "organization", "properties": {}}],
            [{"source": "Bob", "target": "Acme", "type": "works for"}],
        )
        self.assertIn("Text to add to memory:\nAda works for Acme.\n", payload)
        self.assertIn('"name": "Acme"', payload)
        self.assertIn('"source": "Bob"', payload)

    def test_caps_long_text(self) -> None:
        payload = build_memory_insert_payload("x" * (AI_INSERT_MAX_TEXT_CHARS + 500), [], [])
        self.assertIn("x" * AI_INSERT_MAX_TEXT_CHARS + "\n…", payload)
        self.assertNotIn("x" * (AI_INSERT_MAX_TEXT_CHARS + 1), payload)


class MemoryLlmEndpointTests(unittest.TestCase):
    def test_google_without_base_url_gets_default(self) -> None:
        from app.services.llm_service import GOOGLE_OPENAI_BASE_URL

        self.assertEqual(
            memory_llm_endpoint("google", {"api_key": "k"}), ("k", GOOGLE_OPENAI_BASE_URL)
        )

    def test_custom_base_url_gets_v1_suffix(self) -> None:
        self.assertEqual(
            memory_llm_endpoint("custom", {"api_key": "k", "base_url": "http://llm.local/"}),
            ("k", "http://llm.local/v1"),
        )

    def test_openai_passes_through(self) -> None:
        self.assertEqual(memory_llm_endpoint("openai", {}), ("", None))


class AiInsertMemoryApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workflow_id = uuid.uuid4()
        self.user = MagicMock()
        self.user.id = uuid.uuid4()
        self.credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="OpenAI",
            type=CredentialType.openai,
            encrypted_config="enc",
        )
        self.body = MemoryAiInsertRequest(
            text="Ada works for Acme.",
            credential_id=self.credential.id,
            model="gpt-test",
        )
        self.existing = _memory_node("Acme", "organization")
        self.after = [self.existing, _memory_node("Ada")]

        self.db = AsyncMock()
        self.db.execute = AsyncMock(
            side_effect=[
                _rows_result([self.existing]),
                _rows_result([]),
                _rows_result(self.after),
                _rows_result([]),
            ]
        )
        self.db.run_sync = AsyncMock(side_effect=lambda fn: fn(MagicMock()))
        self.db.flush = AsyncMock()

        self.llm = AsyncMock(
            return_value={
                "text": json.dumps(
                    {
                        "revoked_entities": ["Acme"],
                        "entities": [{"name": "Ada", "type": "person"}],
                        "relationships": [{"source": "Ada", "target": "Acme", "type": "works for"}],
                    }
                )
            }
        )
        self.apply = MagicMock(
            return_value=MemoryMergeResult(entities_applied=1, relationships_applied=1)
        )
        self.write_guard = AsyncMock(return_value=None)
        self.get_credential = AsyncMock(return_value=self.credential)

        patchers = [
            patch(f"{API}.get_workflow_for_user", AsyncMock(return_value=MagicMock())),
            patch(f"{API}.require_workflow_write", self.write_guard),
            patch(f"{API}.get_accessible_credential", self.get_credential),
            patch(f"{API}.decrypt_config", MagicMock(return_value={"api_key": "sk-test"})),
            patch(f"{API}.build_router_for_credential", MagicMock(return_value=None)),
            patch(f"{API}.run_memory_extraction_llm", self.llm),
            patch(f"{API}.apply_parsed_extraction_sync", self.apply),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    async def _insert(self) -> Any:
        return await ai_insert_memory(self.workflow_id, "agent-1", self.body, self.db, self.user)

    async def test_merges_insert_only_extraction_and_returns_fresh_graph(self) -> None:
        result = await self._insert()

        merged_payload = self.apply.call_args.args[3]
        self.assertEqual(merged_payload["revoked_entities"], [])
        self.assertEqual(merged_payload["entities"], [{"name": "Ada", "type": "person"}])
        self.assertEqual(self.apply.call_args.args[1:3], (self.workflow_id, "agent-1"))

        self.assertEqual(result.entities_applied, 1)
        self.assertEqual(result.relationships_applied, 1)
        self.assertEqual(sorted(n.entity_name for n in result.graph.nodes), ["Acme", "Ada"])

        kwargs = self.llm.await_args.kwargs
        self.assertEqual(kwargs["system_instruction"], MEMORY_INSERT_SYSTEM)
        self.assertEqual(kwargs["model"], "gpt-test")
        self.assertEqual(kwargs["api_key"], "sk-test")
        self.assertIn("Ada works for Acme.", kwargs["user_payload"])
        self.assertIn('"name": "Acme"', kwargs["user_payload"])
        self.assertEqual(kwargs["trace_context"].source, "agent_memory")
        self.assertEqual(kwargs["trace_context"].credential_id, self.credential.id)
        self.get_credential.assert_awaited_once_with(self.db, self.credential.id, self.user.id)

    async def test_each_insert_gets_its_own_nonempty_opencode_session(self) -> None:
        await self._insert()
        first = self.llm.await_args.kwargs["trace_context"].session_id
        self.db.execute = AsyncMock(
            side_effect=[_rows_result([]), _rows_result([]), _rows_result([]), _rows_result([])]
        )
        await self._insert()
        second = self.llm.await_args.kwargs["trace_context"].session_id

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertNotEqual(first, second)

    async def test_read_only_collaborator_is_refused_before_the_model_runs(self) -> None:
        self.write_guard.side_effect = HTTPException(status_code=403, detail="read-only")
        with self.assertRaises(HTTPException) as ctx:
            await self._insert()
        self.assertEqual(ctx.exception.status_code, 403)
        self.llm.assert_not_awaited()
        self.apply.assert_not_called()

    async def test_credential_not_shared_with_caller_is_404(self) -> None:
        self.get_credential.return_value = None
        with self.assertRaises(HTTPException) as ctx:
            await self._insert()
        self.assertEqual(ctx.exception.status_code, 404)
        self.llm.assert_not_awaited()

    async def test_non_model_credential_is_400(self) -> None:
        self.credential.type = CredentialType.slack
        with self.assertRaises(HTTPException) as ctx:
            await self._insert()
        self.assertEqual(ctx.exception.status_code, 400)
        self.llm.assert_not_awaited()

    async def test_model_failure_is_502_and_writes_nothing(self) -> None:
        self.llm.side_effect = RuntimeError("upstream down")
        with self.assertRaises(HTTPException) as ctx:
            await self._insert()
        self.assertEqual(ctx.exception.status_code, 502)
        self.apply.assert_not_called()

    async def test_invalid_json_is_502_and_writes_nothing(self) -> None:
        self.llm.return_value = {"text": "Sure! Here are the entities: Ada"}
        with self.assertRaises(HTTPException) as ctx:
            await self._insert()
        self.assertEqual(ctx.exception.status_code, 502)
        self.apply.assert_not_called()

    async def test_workflow_not_found_is_404(self) -> None:
        with patch(f"{API}.get_workflow_for_user", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await self._insert()
        self.assertEqual(ctx.exception.status_code, 404)


class ClearMemoryGraphApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_edges_then_nodes_of_this_agent_only(self) -> None:
        workflow_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        edge_result = MagicMock(rowcount=3)
        node_result = MagicMock(rowcount=2)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[edge_result, node_result])
        db.flush = AsyncMock()

        with (
            patch(f"{API}.get_workflow_for_user", AsyncMock(return_value=MagicMock())),
            patch(f"{API}.require_workflow_write", AsyncMock(return_value=None)),
        ):
            result = await clear_memory_graph(workflow_id, "agent-1", db, user)

        self.assertEqual((result.deleted_nodes, result.deleted_edges), (2, 3))
        edge_stmt, node_stmt = (call.args[0] for call in db.execute.await_args_list)
        self.assertEqual(edge_stmt.table.name, "agent_memory_edges")
        self.assertEqual(node_stmt.table.name, "agent_memory_nodes")
        for stmt in (edge_stmt, node_stmt):
            params = stmt.compile().params
            self.assertIn(workflow_id, params.values())
            self.assertIn("agent-1", params.values())

    async def test_read_only_collaborator_cannot_clear(self) -> None:
        db = AsyncMock()
        with (
            patch(f"{API}.get_workflow_for_user", AsyncMock(return_value=MagicMock())),
            patch(
                f"{API}.require_workflow_write",
                AsyncMock(side_effect=HTTPException(status_code=403, detail="read-only")),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await clear_memory_graph(uuid.uuid4(), "agent-1", db, MagicMock())
        self.assertEqual(ctx.exception.status_code, 403)
        db.execute.assert_not_awaited()


class MergeResultCountsPostgreSqlTests(unittest.TestCase):
    """The counts the AI insert toast reports match what reached the graph."""

    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"ai-insert-{self.user_id}@example.com",
                    hashed_password="hashed_pw",
                    name="AI Insert Tester",
                )
            )
            db.flush()
            db.add(Workflow(id=self.workflow_id, name="AI insert test", owner_id=self.user_id))
            db.commit()

    def tearDown(self) -> None:
        if not _is_db_reachable():
            return
        with SessionLocal() as db:
            db.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def test_counts_created_merged_and_skips_dangling_relationships(self) -> None:
        with SessionLocal() as db:
            db.add(
                AgentMemoryNode(
                    id=uuid.uuid4(),
                    workflow_id=self.workflow_id,
                    canvas_node_id="agent-1",
                    entity_name="Acme",
                    entity_type="organization",
                    properties={"city": "Berlin"},
                    confidence=1.0,
                )
            )
            db.flush()
            merged = apply_parsed_extraction_sync(
                db,
                self.workflow_id,
                "agent-1",
                insert_only_extraction(
                    {
                        "revoked_entities": ["Acme"],
                        "entities": [
                            {"name": "Ada", "type": "person", "properties": {"role": "CTO"}},
                            {"name": "acme", "type": "organization", "properties": {}},
                            {"name": "  ", "type": "person"},
                        ],
                        "relationships": [
                            {"source": "Ada", "target": "Acme", "type": "works for"},
                            {"source": "Ada", "target": "Nobody", "type": "knows"},
                        ],
                    }
                ),
            )
            db.commit()

            names = sorted(
                n.entity_name
                for n in db.execute(
                    select(AgentMemoryNode).where(AgentMemoryNode.workflow_id == self.workflow_id)
                )
                .scalars()
                .all()
            )
            edge_count = len(
                db.execute(
                    select(AgentMemoryEdge).where(AgentMemoryEdge.workflow_id == self.workflow_id)
                )
                .scalars()
                .all()
            )

        self.assertEqual(merged, MemoryMergeResult(entities_applied=2, relationships_applied=1))
        # "acme" merged into the existing Acme row (renamed to the new spelling), Ada is new, and
        # the revoked Acme survived because an insert never revokes.
        self.assertEqual(names, ["Ada", "acme"])
        self.assertEqual(edge_count, 1)


if __name__ == "__main__":
    unittest.main()
