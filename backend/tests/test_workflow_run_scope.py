import copy
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

from app.api.workflows import execute_workflow_stream
from app.services.workflow_executor import WorkflowExecutor
from app.services.workflow_run_scope import scope_workflow_run


def node(node_id: str, node_type: str = "set", **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": {"label": node_id, **data}}


def edge(source: str, target: str, **handles: str) -> dict[str, str]:
    return {"id": f"{source}-{target}", "source": source, "target": target, **handles}


class WorkflowRunScopeTests(unittest.TestCase):
    def test_runs_ancestors_and_target_without_later_or_unrelated_nodes(self) -> None:
        nodes = [
            node("start", "textInput", inputFields=[{"key": "text"}]),
            node("target", mappings=[{"key": "text", "value": "$start.body.text.toUpperCase()"}]),
            node("later", "throwError", errorMessage="Must not run"),
            node("other", "throwError", errorMessage="Must not run"),
            node("note", "sticky"),
        ]
        edges = [edge("start", "target"), edge("target", "later"), edge("start", "other")]
        original = copy.deepcopy(nodes)
        graph = scope_workflow_run(nodes, edges, "target")
        result = WorkflowExecutor(graph.nodes, graph.edges, test_mode=True).execute(
            uuid.uuid4(), {"body": {"text": "hello"}}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual([row["node_id"] for row in result.node_results], ["start", "target"])
        self.assertEqual(result.node_results[-1]["output"]["text"], "HELLO")
        self.assertEqual(nodes, original)

    def test_retains_both_merge_ancestors(self) -> None:
        graph = scope_workflow_run(
            [node("left"), node("right"), node("merge", "merge"), node("later")],
            [edge("left", "merge"), edge("right", "merge"), edge("merge", "later")],
            "merge",
        )
        self.assertEqual({n["id"] for n in graph.nodes}, {"left", "right", "merge"})

    def test_retains_agent_tools_and_delegated_agents(self) -> None:
        graph = scope_workflow_run(
            [
                node("start"),
                node("agent", "agent", isOrchestrator=True, subAgentLabels=["helper"]),
                node("tool", "http"),
                node("helper", "agent"),
                node("helperTool", "http"),
                node("later"),
            ],
            [
                edge("start", "agent"),
                edge("tool", "agent", targetHandle="tool-input"),
                edge("helperTool", "helper", targetHandle="tool-input"),
                edge("agent", "later"),
            ],
            "agent",
        )
        self.assertEqual(
            {n["id"] for n in graph.nodes}, {"start", "agent", "tool", "helper", "helperTool"}
        )

    def test_selected_tool_can_run_standalone(self) -> None:
        graph = scope_workflow_run(
            [node("tool", mappings=[{"key": "value", "value": "ok"}]), node("agent", "agent")],
            [edge("tool", "agent", targetHandle="tool-input")],
            "tool",
        )
        result = WorkflowExecutor(graph.nodes, graph.edges, test_mode=True).execute(
            uuid.uuid4(), {}
        )
        self.assertEqual([row["node_id"] for row in result.node_results], ["tool"])
        self.assertEqual(result.status, "success")

    def test_loop_body_stops_at_target_but_upstream_loop_keeps_its_body(self) -> None:
        nodes = [node("start"), node("loop", "loop"), node("body"), node("later"), node("done")]
        edges = [
            edge("start", "loop"),
            edge("loop", "body", sourceHandle="loop"),
            edge("body", "later"),
            edge("later", "loop", targetHandle="loop"),
            edge("loop", "done", sourceHandle="done"),
        ]
        for target, expected in [
            ("loop", {"start", "loop"}),
            ("body", {"start", "loop", "body"}),
            ("done", {"start", "loop", "body", "later", "done"}),
        ]:
            with self.subTest(target=target):
                graph = scope_workflow_run(nodes, edges, target)
                self.assertEqual({n["id"] for n in graph.nodes}, expected)

    def test_stops_at_target_in_first_loop_iteration(self) -> None:
        graph = scope_workflow_run(
            [
                node("loop", "loop", arrayExpression="$range(0, 3)"),
                node("target", mappings=[{"key": "value", "value": "$loop.item"}]),
                node("later", "throwError", errorMessage="Must not execute"),
            ],
            [
                edge("loop", "target", sourceHandle="loop"),
                edge("target", "later"),
                edge("later", "loop", targetHandle="loop"),
            ],
            "target",
        )
        result = WorkflowExecutor(graph.nodes, graph.edges, test_mode=True).execute(
            uuid.uuid4(), {}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            [row["output"]["value"] for row in result.node_results if row["node_id"] == "target"],
            [0],
        )
        self.assertFalse(any(row["node_id"] == "later" for row in result.node_results))

    def test_upstream_loop_completes_before_running_target_on_done_branch(self) -> None:
        graph = scope_workflow_run(
            [
                node("loop", "loop", arrayExpression="$range(0, 3)"),
                node("body", mappings=[{"key": "value", "value": "$loop.item"}]),
                node("target", mappings=[{"key": "value", "value": "$loop.total"}]),
            ],
            [
                edge("loop", "body", sourceHandle="loop"),
                edge("body", "loop", targetHandle="loop"),
                edge("loop", "target", sourceHandle="done"),
            ],
            "target",
        )
        result = WorkflowExecutor(graph.nodes, graph.edges, test_mode=True).execute(
            uuid.uuid4(), {}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            [
                row["output"]["value"]
                for row in result.node_results
                if row["node_id"] == "body" and row["status"] == "success"
            ],
            [0, 1, 2],
        )
        self.assertEqual(result.node_results[-1]["node_id"], "target")

    def test_target_inside_loop_excludes_parallel_body_branches(self) -> None:
        graph = scope_workflow_run(
            [node("loop", "loop"), node("target"), node("other")],
            [
                edge("loop", "target", sourceHandle="loop"),
                edge("loop", "other", sourceHandle="loop"),
                edge("target", "loop", targetHandle="loop"),
                edge("other", "loop", targetHandle="loop"),
            ],
            "target",
        )
        self.assertEqual({n["id"] for n in graph.nodes}, {"loop", "target"})

    def test_condition_does_not_force_an_unselected_branch_to_run(self) -> None:
        nodes = [
            node("condition", "condition", condition="false"),
            node("target", mappings=[{"key": "value", "value": "ok"}]),
            node("other"),
        ]
        graph = scope_workflow_run(
            nodes,
            [
                edge("condition", "target", sourceHandle="true"),
                edge("condition", "other", sourceHandle="false"),
            ],
            "target",
        )
        result = WorkflowExecutor(graph.nodes, graph.edges, test_mode=True).execute(
            uuid.uuid4(), {}
        )
        self.assertFalse(
            any(
                row["node_id"] == "target" and row["status"] == "success"
                for row in result.node_results
            )
        )

    def test_rejects_sticky_or_missing_targets(self) -> None:
        for target in ["missing", "note", ""]:
            with self.subTest(target=target), self.assertRaises(HTTPException) as error:
                scope_workflow_run([node("note", "sticky")], [], target)
            self.assertEqual(error.exception.status_code, 400)


class PartialRunAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_run_requires_test_mode_and_workflow_access(self) -> None:
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
        for test_run, user, allowed, expected in [
            (False, SimpleNamespace(id=workflow.owner_id), True, 400),
            (True, None, False, 403),
            (True, SimpleNamespace(id=uuid.uuid4()), False, 403),
        ]:
            with self.subTest(test_run=test_run, user=user, allowed=allowed):
                db = AsyncMock()
                scalar = MagicMock()
                scalar.scalar_one_or_none.return_value = workflow
                db.execute.return_value = scalar

                async def receive() -> dict[str, Any]:
                    return {"type": "http.request", "body": b"", "more_body": False}

                request = Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "headers": [],
                        "query_string": b"test_run=true" if test_run else b"",
                    },
                    receive,
                )
                with patch(
                    "app.api.workflows.user_has_workflow_access", AsyncMock(return_value=allowed)
                ):
                    with self.assertRaises(HTTPException) as error:
                        await execute_workflow_stream(
                            workflow.id,
                            request,
                            current_user=user,
                            db=db,
                            run_until_node_id="target",
                        )
                self.assertEqual(error.exception.status_code, expected)
