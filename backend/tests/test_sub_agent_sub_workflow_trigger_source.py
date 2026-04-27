"""Verify trigger_source tagging when a sub-agent (delegated via call_sub_agent)
internally invokes a sub-workflow via call_sub_workflow.

Scenario:
    Orchestrator A -> (call_sub_agent) -> Sub-agent B -> (call_sub_workflow) -> W1

Expected behaviour:
    The SubWorkflowExecution recorded for W1 must carry trigger_source="AI Agents".
"""

from __future__ import annotations

import threading
import unittest
import uuid
from unittest.mock import MagicMock, patch

from app.services.workflow_executor import ExecutionResult, WorkflowExecutor


class SubAgentSubWorkflowTriggerSourceTests(unittest.TestCase):
    """Orchestrator's sub-agent workflow calls must be tagged 'AI Agents'."""

    def _make_fake_result(self, workflow_id: str) -> ExecutionResult:
        return ExecutionResult(
            workflow_id=uuid.UUID(workflow_id),
            status="success",
            outputs={"ok": True},
            execution_time_ms=5.0,
        )

    def test_trigger_source_is_ai_agents_when_tool_called_directly(self) -> None:
        """Baseline: _execute_sub_workflow_tool always tags 'AI Agents'."""
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }
        fake_result = self._make_fake_result(sub_wf_id)

        with (
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
            patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe,
        ):
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            mock_sub.execute.return_value = fake_result
            mock_wfe.return_value = mock_sub

            executor._execute_sub_workflow_tool(
                tool_def={
                    "_sub_workflow_ids": [sub_wf_id],
                    "_sub_workflow_names": {sub_wf_id: "Sub WF"},
                },
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )

        self.assertEqual(len(executor.sub_workflow_executions), 1)
        recorded = executor.sub_workflow_executions[0]
        self.assertEqual(recorded.workflow_id, sub_wf_id)
        self.assertEqual(recorded.trigger_source, "AI Agents")

    def test_trigger_source_is_ai_agents_when_called_by_sub_agent(self) -> None:
        """Full path: orchestrator -> sub-agent -> sub-workflow keeps 'AI Agents'.

        The sub-agent path invokes ``_execute_agent_node`` on the *parent*
        executor, so any ``call_sub_workflow`` tool call inside the sub-agent's
        LLM loop must still route through the same ``_execute_sub_workflow_tool``
        method and tag the record with ``trigger_source='AI Agents'``.
        """
        orchestrator_id = "A"
        sub_agent_id = "B"
        sub_wf_id = str(uuid.uuid4())

        nodes = {
            orchestrator_id: {
                "id": orchestrator_id,
                "type": "agent",
                "data": {
                    "label": "Orchestrator",
                    "isOrchestrator": True,
                    "subAgentLabels": ["SubAgent"],
                },
            },
            sub_agent_id: {
                "id": sub_agent_id,
                "type": "agent",
                "data": {
                    "label": "SubAgent",
                    "subWorkflowIds": [sub_wf_id],
                },
            },
        }

        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.nodes = nodes
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        fake_sub_result = self._make_fake_result(sub_wf_id)

        def fake_execute_agent_node(node_id, inputs, node_data, guardrails_config=None):
            # Simulate the sub-agent's LLM calling `call_sub_workflow` on W1
            # by directly invoking the same private tool routine the custom
            # tool executor would dispatch to.
            self.assertEqual(node_id, sub_agent_id)
            self.assertEqual(node_data["subWorkflowIds"], [sub_wf_id])
            executor._execute_sub_workflow_tool(
                tool_def={
                    "_sub_workflow_ids": [sub_wf_id],
                    "_sub_workflow_names": {sub_wf_id: "Sub WF"},
                },
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )
            return {"text": "done"}

        with (
            patch.object(
                WorkflowExecutor, "_execute_agent_node", side_effect=fake_execute_agent_node
            ),
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
            patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe,
        ):
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            mock_sub.execute.return_value = fake_sub_result
            mock_wfe.return_value = mock_sub

            executor._execute_sub_agent_tool(
                tool_def={"_sub_agent_labels": ["SubAgent"]},
                _name="call_sub_agent",
                args={"sub_agent_label": "SubAgent", "prompt": "go"},
                _timeout_seconds=30.0,
            )

        self.assertEqual(len(executor.sub_workflow_executions), 1)
        recorded = executor.sub_workflow_executions[0]
        self.assertEqual(recorded.workflow_id, sub_wf_id)
        self.assertEqual(
            recorded.trigger_source,
            "AI Agents",
            msg=(
                "Sub-workflows invoked by an orchestrator's sub-agent must still be tagged "
                "'AI Agents' in the run history."
            ),
        )

    def test_sub_executor_for_agent_tool_has_invoked_by_agent_flag(self) -> None:
        """``_execute_sub_workflow_tool`` must spawn a sub-executor whose
        ``_invoked_by_agent`` flag is True so that downstream Execute Workflow
        nodes inside the child workflow inherit the 'AI Agents' tag.
        """
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        captured: dict[str, object] = {}

        real_cls = WorkflowExecutor

        def capture_init(*args: object, **kwargs: object) -> object:
            captured["invoked_by_agent"] = kwargs.get("invoked_by_agent")
            instance = real_cls(*args, **kwargs)  # type: ignore[arg-type]
            return instance

        with (
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
            patch(
                "app.services.workflow_executor.WorkflowExecutor", side_effect=capture_init
            ) as mock_cls,
        ):
            mock_cls.return_value = MagicMock(
                sub_workflow_executions=[],
                execute=MagicMock(return_value=self._make_fake_result(sub_wf_id)),
            )
            executor._execute_sub_workflow_tool(
                tool_def={
                    "_sub_workflow_ids": [sub_wf_id],
                    "_sub_workflow_names": {sub_wf_id: "Sub WF"},
                },
                _name="call_sub_workflow",
                args={"workflow_id": sub_wf_id, "inputs": {}},
                _timeout_seconds=30.0,
            )

        self.assertEqual(captured.get("invoked_by_agent"), True)

    def _run_parent_with_execute_node(self, *, invoked_by_agent: bool) -> WorkflowExecutor:
        """Run a minimal parent workflow that contains one Execute Workflow
        NODE pointing at ``sub_wf``. Returns the parent executor.
        """
        sub_wf_id = str(uuid.uuid4())
        parent_wf_id = uuid.uuid4()
        nodes = [
            {
                "id": "exec_node",
                "type": "execute",
                "data": {
                    "label": "Call Sub",
                    "executeWorkflowId": sub_wf_id,
                    "executeInput": "$userInput.body.text",
                },
            }
        ]
        executor = WorkflowExecutor(
            nodes=nodes,
            edges=[],
            workflow_id=parent_wf_id,
            invoked_by_agent=invoked_by_agent,
        )
        executor.workflow_cache = {
            sub_wf_id: {
                "nodes": [],
                "edges": [],
                "name": "Child WF",
                "input_fields": [{"key": "text"}],
            }
        }

        fake_result = ExecutionResult(
            workflow_id=uuid.UUID(sub_wf_id),
            status="success",
            outputs={"ok": True},
            execution_time_ms=3.0,
        )

        def fake_executor_cls(*_args: object, **_kwargs: object) -> MagicMock:
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            mock_sub.execute.return_value = fake_result
            return mock_sub

        with (
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
            patch(
                "app.services.workflow_executor.WorkflowExecutor",
                side_effect=fake_executor_cls,
            ),
        ):
            executor.execute(
                workflow_id=parent_wf_id,
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
            )

        return executor

    def test_execute_node_tags_ai_agents_when_inside_agent_invoked_workflow(self) -> None:
        """Execute Workflow NODE inside agent-initiated chain must tag
        the sub-workflow with ``trigger_source='AI Agents'``.
        """
        executor = self._run_parent_with_execute_node(invoked_by_agent=True)
        self.assertEqual(len(executor.sub_workflow_executions), 1)
        self.assertEqual(executor.sub_workflow_executions[0].trigger_source, "AI Agents")

    def test_execute_node_keeps_sub_workflow_tag_when_not_agent_invoked(self) -> None:
        """Execute Workflow NODE in a normally-triggered workflow (Canvas,
        webhook, cron, …) must keep the default ``'SUB_WORKFLOW'`` tag.
        """
        executor = self._run_parent_with_execute_node(invoked_by_agent=False)
        self.assertEqual(len(executor.sub_workflow_executions), 1)
        self.assertEqual(executor.sub_workflow_executions[0].trigger_source, "SUB_WORKFLOW")

    def test_custom_tool_executor_routes_call_sub_workflow_with_ai_agents_tag(self) -> None:
        """Realistic routing: the executor returned by ``_build_agent_tool_executor``
        must dispatch ``call_sub_workflow`` to ``_execute_sub_workflow_tool``, which
        tags the SubWorkflowExecution with ``trigger_source='AI Agents'``.
        """
        sub_wf_id = str(uuid.uuid4())
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.workflow_cache = {
            sub_wf_id: {"nodes": [], "edges": [], "name": "Sub WF", "input_fields": []}
        }

        tool_executor = executor._build_agent_tool_executor(
            node_id="sub-agent-node", hitl_fallback_summary=None, hitl_mcp_policy=None
        )

        fake_sub_result = self._make_fake_result(sub_wf_id)

        with (
            patch(
                "app.services.workflow_executor._register_sub_execution",
                return_value=threading.Event(),
            ),
            patch("app.services.workflow_executor._clear_sub_execution"),
            patch("app.services.workflow_executor.WorkflowExecutor") as mock_wfe,
        ):
            mock_sub = MagicMock()
            mock_sub.sub_workflow_executions = []
            mock_sub.execute.return_value = fake_sub_result
            mock_wfe.return_value = mock_sub

            result = tool_executor(
                {
                    "name": "call_sub_workflow",
                    "_source": "sub_workflow",
                    "_sub_workflow_ids": [sub_wf_id],
                    "_sub_workflow_names": {sub_wf_id: "Sub WF"},
                },
                "call_sub_workflow",
                {"workflow_id": sub_wf_id, "inputs": {}},
                30.0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(executor.sub_workflow_executions), 1)
        self.assertEqual(executor.sub_workflow_executions[0].trigger_source, "AI Agents")


if __name__ == "__main__":
    unittest.main()
