"""Unit tests for agent persistent memory helpers."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import AgentMemoryNode
from app.services import agent_memory_service as agent_memory_service_mod
from app.services.agent_memory_service import (
    _is_unsupported_json_object_response_format,
    _trace_context_for_memory_job,
    augment_system_instruction_with_memory,
    entity_name_equals_ci,
    format_conversation_for_memory,
    format_memory_graph_for_prompt,
    memory_extraction_targets_for_agent_node,
    merge_memory_share_targets,
    normalize_relationship_type,
    parse_llm_json_block,
)
from app.services.llm_trace import LLMTraceContext


class UnsupportedJsonObjectResponseFormatTests(unittest.TestCase):
    def test_detects_lm_studio_style_error(self) -> None:
        msg = "Error code: 400 - {'error': \"'response_format.type' must be 'json_schema' or 'text'\"}"
        self.assertTrue(_is_unsupported_json_object_response_format(ValueError(msg)))

    def test_other_errors_false(self) -> None:
        self.assertFalse(_is_unsupported_json_object_response_format(ValueError("rate limit")))


class EntityNameEqualsCiTests(unittest.TestCase):
    def test_sql_lowers_both_column_and_literal(self) -> None:
        """PostgreSQL vs Python lower() must not diverge (e.g. Turkish İ)."""
        wf = uuid.uuid4()
        stmt = select(AgentMemoryNode).where(
            AgentMemoryNode.workflow_id == wf,
            entity_name_equals_ci(AgentMemoryNode.entity_name, "İstanbul"),
        )
        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        self.assertGreaterEqual(sql.count("lower"), 2)


class NormalizeRelationshipTypeTests(unittest.TestCase):
    def test_collapses_whitespace_and_case(self) -> None:
        self.assertEqual(normalize_relationship_type("  Works   FOR "), "works for")

    def test_underscores_to_spaces(self) -> None:
        self.assertEqual(normalize_relationship_type("works_for"), "works for")

    def test_lives_in_normalizes_for_single_slot(self) -> None:
        norm = normalize_relationship_type("lives_in")
        self.assertEqual(norm, "lives in")
        self.assertIn(norm, agent_memory_service_mod._SINGLE_SLOT_OUTGOING_REL_TYPES)


class MemoryExtractionPromptTests(unittest.TestCase):
    def test_system_prompt_documents_revoked_entities(self) -> None:
        self.assertIn("revoked_entities", agent_memory_service_mod._MEMORY_SYSTEM)


class ParseLlmJsonBlockTests(unittest.TestCase):
    def test_plain_object(self) -> None:
        out = parse_llm_json_block('{"entities": [], "relationships": []}')
        self.assertEqual(out["entities"], [])
        self.assertEqual(out["relationships"], [])

    def test_strips_markdown_fence(self) -> None:
        raw = """```json
{"entities": [{"name": "Ada"}], "relationships": []}
```"""
        out = parse_llm_json_block(raw)
        self.assertEqual(len(out["entities"]), 1)
        self.assertEqual(out["entities"][0]["name"], "Ada")


class FormatConversationForMemoryTests(unittest.TestCase):
    def test_includes_final_text_and_tools(self) -> None:
        blob = format_conversation_for_memory(
            "Hello",
            {
                "text": "Done",
                "tool_calls": [
                    {
                        "name": "call_sub_agent",
                        "arguments": {"sub_agent_label": "a", "prompt": "p"},
                        "result": {"text": "sub out"},
                    }
                ],
            },
        )
        self.assertIn("Hello", blob)
        self.assertIn("Done", blob)
        self.assertIn("call_sub_agent", blob)
        self.assertIn("sub out", blob)

    def test_skips_compression_marker(self) -> None:
        blob = format_conversation_for_memory(
            "x",
            {
                "text": "y",
                "tool_calls": [{"name": "_context_compression", "arguments": {}, "result": {}}],
            },
        )
        self.assertNotIn("_context_compression", blob)


class FormatMemoryGraphForPromptTests(unittest.TestCase):
    def test_empty_nodes_returns_none(self) -> None:
        self.assertIsNone(format_memory_graph_for_prompt([], []))

    def test_entities_and_edges(self) -> None:
        aid = uuid.uuid4()
        bid = uuid.uuid4()
        a = SimpleNamespace(
            id=aid,
            entity_name="Acme Corp",
            entity_type="organization",
            properties={},
        )
        b = SimpleNamespace(
            id=bid,
            entity_name="dark roast",
            entity_type="preference",
            properties={"strength": "high"},
        )
        e = SimpleNamespace(
            source_node_id=aid,
            target_node_id=bid,
            relationship_type="prefers",
        )
        text = format_memory_graph_for_prompt([a, b], [e])
        self.assertIsNotNone(text)
        assert text is not None
        self.assertIn("Acme Corp", text)
        self.assertIn("prefers", text)
        self.assertIn("dark roast", text)


class TraceContextForMemoryJobTests(unittest.TestCase):
    def test_sets_source_agent_memory(self) -> None:
        uid = uuid.uuid4()
        cid = uuid.uuid4()
        wf = uuid.uuid4()
        base = LLMTraceContext(
            user_id=uid,
            credential_id=cid,
            workflow_id=wf,
            node_id="n1",
            node_label="Agent",
            source="workflow",
        )
        mem = _trace_context_for_memory_job(base)
        self.assertIsNotNone(mem)
        assert mem is not None
        self.assertEqual(mem.source, "agent_memory")
        self.assertEqual(mem.user_id, uid)
        self.assertEqual(mem.credential_id, cid)
        self.assertEqual(mem.workflow_id, wf)
        self.assertEqual(mem.node_id, "n1")

    def test_none_stays_none(self) -> None:
        self.assertIsNone(_trace_context_for_memory_job(None))


class MergeMemoryShareTargetsTests(unittest.TestCase):
    def test_collects_owner_for_peer(self) -> None:
        wf = str(uuid.uuid4())
        nodes = {
            "owner-a": {
                "type": "agent",
                "data": {
                    "label": "Alpha",
                    "memoryShares": [{"peerCanvasNodeId": "peer-b", "permission": "read"}],
                },
            },
        }
        got = merge_memory_share_targets(nodes, wf, wf, "peer-b")
        self.assertEqual(got, [("owner-a", "Alpha", "read")])

    def test_write_wins_over_read(self) -> None:
        wf = str(uuid.uuid4())
        nodes = {
            "owner-a": {
                "type": "agent",
                "data": {
                    "label": "Alpha",
                    "memoryShares": [
                        {"peerCanvasNodeId": "peer-b", "permission": "read"},
                        {"peerCanvasNodeId": "peer-b", "permission": "write"},
                    ],
                },
            },
        }
        got = merge_memory_share_targets(nodes, wf, wf, "peer-b")
        self.assertEqual(got, [("owner-a", "Alpha", "write")])

    def test_cross_workflow_peer_matches_peer_workflow_id(self) -> None:
        wf_owner = "wf1"
        wf_peer = "wf2"
        nodes = {
            "owner-a": {
                "type": "agent",
                "data": {
                    "label": "Alpha",
                    "memoryShares": [
                        {
                            "peerWorkflowId": wf_peer,
                            "peerCanvasNodeId": "peer-b",
                            "permission": "read",
                        }
                    ],
                },
            },
        }
        got = merge_memory_share_targets(nodes, wf_owner, wf_peer, "peer-b")
        self.assertEqual(got, [("owner-a", "Alpha", "read")])


class MemoryExtractionTargetsTests(unittest.TestCase):
    def test_own_and_write_share(self) -> None:
        wf = uuid.uuid4()
        nodes = {
            "mem-owner": {
                "type": "agent",
                "data": {
                    "memoryShares": [{"peerCanvasNodeId": "runner", "permission": "write"}],
                },
            },
        }
        got = memory_extraction_targets_for_agent_node(nodes, wf, "runner", True, None)
        self.assertEqual(
            {(str(x[0]), x[1]) for x in got}, {(str(wf), "runner"), (str(wf), "mem-owner")}
        )

    def test_read_share_no_extra_target(self) -> None:
        wf = uuid.uuid4()
        nodes = {
            "mem-owner": {
                "type": "agent",
                "data": {
                    "memoryShares": [{"peerCanvasNodeId": "runner", "permission": "read"}],
                },
            },
        }
        got = memory_extraction_targets_for_agent_node(nodes, wf, "runner", False, None)
        self.assertEqual(got, [])


class AugmentSystemInstructionTests(unittest.TestCase):
    def test_disabled_passthrough(self) -> None:
        out = augment_system_instruction_with_memory(
            "base",
            uuid.uuid4(),
            "n1",
            enabled=False,
        )
        self.assertEqual(out, "base")

    def test_missing_workflow_or_node_passthrough(self) -> None:
        self.assertEqual(
            augment_system_instruction_with_memory("base", None, "n1", enabled=True),
            "base",
        )
        self.assertEqual(
            augment_system_instruction_with_memory("base", uuid.uuid4(), None, enabled=True),
            "base",
        )

    def test_appends_block_when_graph_present(self) -> None:
        wf = uuid.uuid4()
        block = "**Entities:**\n- Ada (person)"
        with patch(
            "app.services.agent_memory_service.load_agent_memory_prompt_block_sync",
            return_value=block,
        ):
            out = augment_system_instruction_with_memory(
                "You are helpful.",
                wf,
                "node-a",
                enabled=True,
            )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertIn("You are helpful.", out)
        self.assertIn("Persistent memory", out)
        self.assertIn("Ada", out)

    def test_graph_only_when_no_system_text(self) -> None:
        wf = uuid.uuid4()
        with patch(
            "app.services.agent_memory_service.load_agent_memory_prompt_block_sync",
            return_value="- X (topic)",
        ):
            out = augment_system_instruction_with_memory(None, wf, "n", enabled=True)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertTrue(out.startswith("### Persistent memory"))

    def test_shared_memory_when_own_disabled(self) -> None:
        wf = uuid.uuid4()
        nodes = {
            "owner-a": {
                "type": "agent",
                "data": {
                    "label": "Alpha",
                    "memoryShares": [{"peerCanvasNodeId": "peer-b", "permission": "read"}],
                },
            },
        }

        def fake_load(_wid: uuid.UUID, cid: str) -> str | None:
            if cid == "owner-a":
                return "- Shared (topic)"
            return None

        with patch(
            "app.services.agent_memory_service.load_agent_memory_prompt_block_sync",
            side_effect=fake_load,
        ):
            out = augment_system_instruction_with_memory(
                "base",
                wf,
                "peer-b",
                enabled=False,
                workflow_nodes=nodes,
                trace_user_id=None,
            )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertIn("base", out)
        self.assertIn("Shared agent memory", out)
        self.assertIn("Shared (topic)", out)


if __name__ == "__main__":
    unittest.main()
