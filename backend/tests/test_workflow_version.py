"""Unit tests for workflow diff calculation in app.services.workflow_version."""

import unittest

from app.services.workflow_version import (
    _calculate_config_changes,
    _calculate_edge_changes,
    _calculate_node_changes,
    _edge_key,
    calculate_workflow_diff,
)


class EdgeKeyTests(unittest.TestCase):
    def test_returns_source_target_tuple(self) -> None:
        self.assertEqual(_edge_key({"source": "a", "target": "b"}), ("a", "b"))

    def test_missing_keys_default_to_empty_string(self) -> None:
        self.assertEqual(_edge_key({}), ("", ""))


class CalculateNodeChangesTests(unittest.TestCase):
    def _node(self, node_id: str, label: str = "N") -> dict:
        return {"id": node_id, "type": "llm", "data": {"label": label}}

    def test_added_node_detected(self) -> None:
        changes = _calculate_node_changes([], [self._node("n1")])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "added")
        self.assertEqual(changes[0].node_id, "n1")

    def test_removed_node_detected(self) -> None:
        changes = _calculate_node_changes([self._node("n1")], [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "removed")

    def test_unchanged_node_produces_no_change(self) -> None:
        node = self._node("n1")
        changes = _calculate_node_changes([node], [node])
        self.assertEqual(changes, [])

    def test_modified_node_detected(self) -> None:
        old = self._node("n1", label="Old")
        new = self._node("n1", label="New")
        changes = _calculate_node_changes([old], [new])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "modified")

    def test_multiple_changes_at_once(self) -> None:
        old_nodes = [self._node("n1"), self._node("n2")]
        new_nodes = [self._node("n1"), self._node("n3")]
        changes = _calculate_node_changes(old_nodes, new_nodes)
        change_types = {c.change_type for c in changes}
        self.assertIn("added", change_types)
        self.assertIn("removed", change_types)


class CalculateEdgeChangesTests(unittest.TestCase):
    def _edge(self, eid: str, source: str, target: str) -> dict:
        return {"id": eid, "source": source, "target": target}

    def test_added_edge_detected(self) -> None:
        e = self._edge("e1", "n1", "n2")
        changes = _calculate_edge_changes([], [e])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "added")

    def test_removed_edge_detected(self) -> None:
        e = self._edge("e1", "n1", "n2")
        changes = _calculate_edge_changes([e], [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "removed")

    def test_unchanged_edge_no_change(self) -> None:
        e = self._edge("e1", "n1", "n2")
        changes = _calculate_edge_changes([e], [e])
        self.assertEqual(changes, [])

    def test_modified_edge_detected(self) -> None:
        old = {"id": "e1", "source": "n1", "target": "n2", "label": "old"}
        new = {"id": "e1", "source": "n1", "target": "n2", "label": "new"}
        changes = _calculate_edge_changes([old], [new])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "modified")


class CalculateConfigChangesTests(unittest.TestCase):
    def test_no_changes(self) -> None:
        cfg = {"timeout": 30, "retries": 3}
        self.assertEqual(_calculate_config_changes(cfg, cfg), [])

    def test_added_key(self) -> None:
        changes = _calculate_config_changes({}, {"newKey": "value"})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].field, "newKey")
        self.assertIsNone(changes[0].old_value)
        self.assertEqual(changes[0].new_value, "value")

    def test_removed_key(self) -> None:
        changes = _calculate_config_changes({"oldKey": "x"}, {})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].old_value, "x")
        self.assertIsNone(changes[0].new_value)

    def test_changed_value(self) -> None:
        changes = _calculate_config_changes({"timeout": 10}, {"timeout": 30})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].old_value, 10)
        self.assertEqual(changes[0].new_value, 30)


_V1 = "00000000-0000-0000-0000-000000000001"
_V2 = "00000000-0000-0000-0000-000000000002"


class CalculateWorkflowDiffTests(unittest.TestCase):
    def test_empty_workflows_produce_no_changes(self) -> None:
        result = calculate_workflow_diff(
            old_nodes=[],
            old_edges=[],
            old_config={},
            new_nodes=[],
            new_edges=[],
            new_config={},
            version_id=_V2,
            version_number=2,
            compared_to_version_id=_V1,
            compared_to_version_number=1,
        )
        self.assertEqual(result.node_changes, [])
        self.assertEqual(result.edge_changes, [])
        self.assertEqual(result.config_changes, [])

    def test_result_carries_version_metadata(self) -> None:
        import uuid

        result = calculate_workflow_diff(
            old_nodes=[],
            old_edges=[],
            old_config={},
            new_nodes=[],
            new_edges=[],
            new_config={},
            version_id=_V2,
            version_number=5,
            compared_to_version_id=_V1,
            compared_to_version_number=4,
        )
        self.assertEqual(result.version_id, uuid.UUID(_V2))
        self.assertEqual(result.version_number, 5)
        self.assertEqual(result.compared_to_version_id, uuid.UUID(_V1))

    def test_full_diff_aggregates_all_change_types(self) -> None:
        old_node = {"id": "n1", "type": "llm", "data": {"label": "Old"}}
        new_node = {"id": "n1", "type": "llm", "data": {"label": "New"}}
        old_edge = {"id": "e1", "source": "n1", "target": "n2"}
        new_edge = {"id": "e2", "source": "n1", "target": "n3"}

        result = calculate_workflow_diff(
            old_nodes=[old_node],
            old_edges=[old_edge],
            old_config={"timeout": 10},
            new_nodes=[new_node],
            new_edges=[new_edge],
            new_config={"timeout": 20},
            version_id=_V2,
            version_number=2,
        )
        self.assertEqual(len(result.node_changes), 1)
        self.assertGreater(len(result.edge_changes), 0)
        self.assertEqual(len(result.config_changes), 1)

    def test_nodes_only_no_edges(self) -> None:
        """Version with nodes but empty edges produces only node changes."""
        old_node = {"id": "n1", "type": "llm", "data": {"label": "A"}}
        new_node = {"id": "n1", "type": "llm", "data": {"label": "B"}}
        result = calculate_workflow_diff(
            old_nodes=[old_node],
            old_edges=[],
            old_config={},
            new_nodes=[new_node],
            new_edges=[],
            new_config={},
            version_id=_V2,
            version_number=2,
            compared_to_version_id=_V1,
            compared_to_version_number=1,
        )
        self.assertEqual(len(result.node_changes), 1)
        self.assertEqual(result.edge_changes, [])
        self.assertEqual(result.config_changes, [])

    def test_edges_only_no_nodes(self) -> None:
        """Version with edges but empty nodes produces only edge changes."""
        old_edge = {"id": "e1", "source": "a", "target": "b"}
        new_edge = {"id": "e1", "source": "a", "target": "c"}
        result = calculate_workflow_diff(
            old_nodes=[],
            old_edges=[old_edge],
            old_config={},
            new_nodes=[],
            new_edges=[new_edge],
            new_config={},
            version_id=_V2,
            version_number=2,
            compared_to_version_id=_V1,
            compared_to_version_number=1,
        )
        self.assertEqual(result.node_changes, [])
        self.assertGreater(len(result.edge_changes), 0)
        self.assertEqual(result.config_changes, [])
