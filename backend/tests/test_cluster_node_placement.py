"""Placement rules, graph recursion, and full coverage of the node registry."""

import unittest

from app.services.cluster.node_placement import (
    NODE_PLACEMENT,
    Placement,
    node_placement,
    workflow_placement,
)
from app.services.node_execution.registry import handler_module_names


class NodePlacementTests(unittest.TestCase):
    def test_http_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "http", "data": {}}), Placement.ANYWHERE)

    def test_drive_node_is_pinned_to_main(self) -> None:
        self.assertEqual(node_placement({"type": "drive", "data": {}}), Placement.MAIN_ONLY)

    def test_send_email_is_pinned_even_without_attachments(self) -> None:
        self.assertEqual(node_placement({"type": "sendEmail", "data": {}}), Placement.MAIN_ONLY)

    def test_code_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "code", "data": {}}), Placement.ANYWHERE)

    def test_playwright_node_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "playwright", "data": {}}), Placement.ANYWHERE)

    def test_plain_agent_runs_anywhere(self) -> None:
        self.assertEqual(node_placement({"type": "agent", "data": {}}), Placement.ANYWHERE)

    def test_agent_with_a_skill_is_pinned_to_main(self) -> None:
        node = {"type": "agent", "data": {"skills": [{"name": "report"}]}}
        self.assertEqual(node_placement(node), Placement.MAIN_ONLY)

    def test_unknown_node_type_is_pinned_to_main(self) -> None:
        self.assertEqual(node_placement({"type": "acmePlugin", "data": {}}), Placement.MAIN_ONLY)


class WorkflowPlacementTests(unittest.TestCase):
    def test_all_anywhere_nodes_stay_anywhere(self) -> None:
        nodes = [{"type": "http", "data": {}}, {"type": "set", "data": {}}]
        self.assertEqual(
            workflow_placement(nodes, resolve_workflow=lambda _: None), Placement.ANYWHERE
        )

    def test_one_main_only_node_pins_the_whole_graph(self) -> None:
        nodes = [{"type": "http", "data": {}}, {"type": "drive", "data": {}}]
        self.assertEqual(
            workflow_placement(nodes, resolve_workflow=lambda _: None), Placement.MAIN_ONLY
        )

    def test_recursion_finds_a_pinned_node_in_a_sub_workflow(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-2"}}]
        sub = {"wf-2": [{"type": "codex", "data": {}}]}
        placement = workflow_placement(nodes, resolve_workflow=lambda wid: sub.get(wid))
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_recursion_through_an_agent_sub_workflow_tool(self) -> None:
        nodes = [{"type": "agent", "data": {"subWorkflowIds": ["wf-2"]}}]
        sub = {"wf-2": [{"type": "converter", "data": {}}]}
        placement = workflow_placement(nodes, resolve_workflow=lambda wid: sub.get(wid))
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_a_dynamic_sub_workflow_id_pins_the_graph(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "$userInput.body.wf"}}]
        placement = workflow_placement(nodes, resolve_workflow=lambda _: None)
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_an_unresolvable_sub_workflow_pins_the_graph(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-missing"}}]
        placement = workflow_placement(nodes, resolve_workflow=lambda _: None)
        self.assertEqual(placement, Placement.MAIN_ONLY)

    def test_a_cycle_terminates(self) -> None:
        nodes = [{"type": "execute", "data": {"executeWorkflowId": "wf-1"}}]
        sub = {"wf-1": [{"type": "execute", "data": {"executeWorkflowId": "wf-1"}}]}
        placement = workflow_placement(nodes, resolve_workflow=lambda wid: sub.get(wid))
        self.assertEqual(placement, Placement.ANYWHERE)


class RegistryCoverageTests(unittest.TestCase):
    """Every executable node type must declare where it may run.

    There is no default. A new node type without an entry fails the build here,
    the same way TestExpressionOperatorCoverage guards the expression registry.
    """

    def test_every_registered_node_type_has_a_placement(self) -> None:
        missing = sorted(set(handler_module_names()) - set(NODE_PLACEMENT))
        self.assertEqual(
            missing,
            [],
            "Node types with no entry in NODE_PLACEMENT: "
            f"{missing}. Add each one to app/services/cluster/node_placement.py "
            "and read the placement rule in AGENTS.md before choosing.",
        )

    def test_no_placement_entry_is_stale(self) -> None:
        unknown = sorted(set(NODE_PLACEMENT) - set(handler_module_names()))
        self.assertEqual(unknown, [], f"NODE_PLACEMENT names types that no longer exist: {unknown}")
