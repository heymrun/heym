"""HITL/Codex resume must preserve timeline spans for pre-review compute and wait gaps."""

from __future__ import annotations

import time
import unittest
import uuid
from unittest.mock import patch

from app.services.workflow_executor import NodeResult, resume_workflow_execution


class TestHitlTimelineOnResume(unittest.TestCase):
    def _agent_snapshot(
        self,
        *,
        resume_mode: str,
        pending_started_ms: float = 1_000.0,
        pending_ended_ms: float = 2_000.0,
    ) -> dict:
        workflow_id = str(uuid.uuid4())
        return {
            "workflow_id": workflow_id,
            "nodes": [
                {
                    "id": "agent-1",
                    "type": "agent",
                    "data": {"label": "Agent"},
                }
            ],
            "edges": [],
            "workflow_cache": {},
            "initial_inputs": {},
            "node_results": [
                {
                    "node_id": "agent-1",
                    "node_label": "Agent",
                    "node_type": "agent",
                    "status": "pending",
                    "output": {
                        "decision": None,
                        "summary": "Needs review",
                        "draftText": "draft",
                    },
                    "execution_time_ms": pending_ended_ms - pending_started_ms,
                    "error": None,
                    "metadata": {
                        "sequence": 1,
                        "started_at_ms": pending_started_ms,
                        "ended_at_ms": pending_ended_ms,
                        "hitl": {"summary": "Needs review"},
                    },
                }
            ],
            "node_outputs": {},
            "node_execution_contexts": {},
            "label_to_output": {},
            "skipped_nodes": [],
            "inactive_nodes": [],
            "loop_states": {},
            "vars": {},
            "sub_workflow_executions": [],
            "completed_nodes": [],
            "pending_count": {},
            "paused_node_id": "agent-1",
            "paused_node_label": "Agent",
            "hitl_resume_mode": resume_mode,
            "test_mode": True,
        }

    def test_inject_output_preserves_pre_review_and_hitl_wait_spans(self) -> None:
        snapshot = self._agent_snapshot(resume_mode="inject_output")
        resume_started = time.time() * 1000

        result = resume_workflow_execution(
            snapshot=snapshot,
            resolved_output={
                "decision": "accepted",
                "summary": "Needs review",
                "originalDraft": "draft",
                "reviewText": "draft",
                "text": "draft",
                "requestId": str(uuid.uuid4()),
            },
        )

        agent_results = [row for row in result.node_results if row["node_id"] == "agent-1"]
        self.assertGreaterEqual(len(agent_results), 2)

        pre_review = next(
            (
                row
                for row in agent_results
                if (row.get("metadata") or {}).get("hitl_phase") == "pre_review"
            ),
            None,
        )
        wait_row = next(
            (row for row in agent_results if (row.get("metadata") or {}).get("hitl_wait") is True),
            None,
        )
        self.assertIsNotNone(pre_review)
        self.assertIsNotNone(wait_row)
        assert pre_review is not None
        assert wait_row is not None

        self.assertEqual(pre_review["metadata"]["started_at_ms"], 1_000.0)
        self.assertEqual(pre_review["metadata"]["ended_at_ms"], 2_000.0)
        self.assertEqual(wait_row["metadata"]["started_at_ms"], 2_000.0)
        self.assertGreaterEqual(wait_row["metadata"]["ended_at_ms"], resume_started - 50)
        self.assertGreater(wait_row["execution_time_ms"], 0)

    def test_continue_agent_keeps_pre_review_and_wait_before_rerun(self) -> None:
        snapshot = self._agent_snapshot(resume_mode="continue_agent")
        resume_started = time.time() * 1000

        def fake_execute_node_parallel(self, node_id: str, _inputs: dict) -> NodeResult:
            finished = time.time() * 1000
            return self._stamp_node_result(
                NodeResult(
                    node_id=node_id,
                    node_label="Agent",
                    node_type="agent",
                    status="success",
                    output={"text": "continued", "decision": "accepted"},
                    execution_time_ms=250.0,
                    metadata={"started_at_ms": finished - 250.0, "ended_at_ms": finished},
                )
            )

        with patch(
            "app.services.workflow_executor.WorkflowExecutor.execute_node_parallel",
            fake_execute_node_parallel,
        ):
            result = resume_workflow_execution(
                snapshot=snapshot,
                resolved_output={
                    "decision": "accepted",
                    "summary": "Needs review",
                    "originalDraft": "draft",
                    "reviewText": "draft",
                    "text": "draft",
                    "requestId": str(uuid.uuid4()),
                },
            )

        agent_results = [row for row in result.node_results if row["node_id"] == "agent-1"]
        phases = [(row.get("metadata") or {}) for row in agent_results]
        self.assertTrue(any(meta.get("hitl_phase") == "pre_review" for meta in phases))
        self.assertTrue(any(meta.get("hitl_wait") is True for meta in phases))
        self.assertTrue(
            any(
                meta.get("hitl_wait") is not True and meta.get("hitl_phase") != "pre_review"
                for meta in phases
            )
        )
        wait_row = next(
            row for row in agent_results if (row.get("metadata") or {}).get("hitl_wait") is True
        )
        self.assertEqual(wait_row["metadata"]["started_at_ms"], 2_000.0)
        self.assertGreaterEqual(wait_row["metadata"]["ended_at_ms"], resume_started - 50)
