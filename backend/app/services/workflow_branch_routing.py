"""Branch-routing methods shared by workflow execution scheduling paths."""

from __future__ import annotations

from typing import Any


class WorkflowBranchRoutingMixin:
    def _is_loop_back_edge(self, edge: dict) -> bool:
        """Return whether an edge loops back into a loop node's loop handle."""
        return (
            edge.get("targetHandle") == "loop"
            and self.nodes.get(edge.get("target"), {}).get("type") == "loop"
        )

    @staticmethod
    def _edge_identity(edge: dict) -> str:
        """Return a stable string identity for an edge."""
        edge_id = edge.get("id")
        if edge_id:
            return str(edge_id)
        return (
            f"{edge.get('source')}:{edge.get('sourceHandle')}->"
            f"{edge.get('target')}:{edge.get('targetHandle')}"
        )

    def _edge_matches_skipped_loop_edge(self, edge: dict, skipped_edge_ids: set[str]) -> bool:
        """Return whether an edge is suppressed from loop re-execution."""
        if not skipped_edge_ids:
            return False
        edge_id = edge.get("id")
        if edge_id and str(edge_id) in skipped_edge_ids:
            return True
        return self._edge_identity(edge) in skipped_edge_ids

    def _order_downstream_edges(
        self, edges: list[dict], source_result: Any | None = None
    ) -> list[dict]:
        """Order loop-back edges according to whether the source is branching.

        Branching nodes must evaluate sibling edges first so inactive branches are
        marked skipped before a loop re-execution resets the body. Non-branching
        nodes must advance the loop first so completion state is reset before
        sibling side nodes are scheduled for the next iteration.
        """
        if not edges:
            return edges

        source_node_id = edges[0]["source"]
        source_node = self.nodes.get(source_node_id, {})
        has_skip_metadata = bool(
            source_result is not None
            and (
                source_result.metadata.get("skip_source_handles")
                or source_result.metadata.get("skip_loop_source_handles")
                or source_result.metadata.get("skip_loop_edge_ids")
            )
        )
        is_condition_or_switch = source_node.get("type") in {"condition", "switch"}
        has_error_branch = any(
            edge.get("sourceHandle") == "error"
            for edge in self.get_active_edges()
            if edge.get("source") == source_node_id
        )
        is_branching = has_skip_metadata or is_condition_or_switch or has_error_branch

        if is_branching:
            return sorted(edges, key=lambda edge: 1 if self._is_loop_back_edge(edge) else 0)
        return sorted(edges, key=lambda edge: 0 if self._is_loop_back_edge(edge) else 1)

    def _handle_success_branch_routing(self, node_id: str, result: Any | None = None) -> None:
        """Skip error-handle branches when the source node completed successfully."""
        active_edges = [
            edge for edge in self.get_active_edges() if edge.get("targetHandle") != "tool-input"
        ]
        success_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") != "error"
        ]
        error_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") == "error"
        ]
        if not error_targets:
            return

        if result is not None:
            inactive_loop_edges = [
                edge
                for edge in active_edges
                if edge["source"] == node_id
                and edge.get("sourceHandle") == "error"
                and self._is_loop_back_edge(edge)
            ]
            if inactive_loop_edges:
                skip_edge_ids = set(result.metadata.get("skip_loop_edge_ids") or [])
                for edge in inactive_loop_edges:
                    skip_edge_ids.add(self._edge_identity(edge))
                    if edge.get("id"):
                        skip_edge_ids.add(str(edge["id"]))
                result.metadata["skip_loop_edge_ids"] = list(skip_edge_ids)

        loop_back_targets = {
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and self._is_loop_back_edge(edge)
        }
        # Forward only: following a loop-back edge into the Loop node would reach the
        # whole loop body, error branch included, and nothing would be skipped.
        preserved_node_ids = self.get_reachable_node_ids(
            success_targets, exclude_node_ids=loop_back_targets
        )

        exclusive_targets = [t for t in error_targets if t not in loop_back_targets]
        exclusive_nodes = self.get_exclusive_branch_node_ids(
            root_node_id=node_id,
            start_node_ids=exclusive_targets,
            edges=active_edges,
            preserve_node_ids=preserved_node_ids,
        )
        self.skipped_nodes.update(exclusive_nodes)

    def _handle_error_branch_routing(self, node_id: str, result: Any | None = None) -> None:
        """Skip only non-error downstream nodes that depend exclusively on the failed node."""
        active_edges = [
            edge for edge in self.get_active_edges() if edge.get("targetHandle") != "tool-input"
        ]
        error_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") == "error"
        ]
        inactive_targets = [
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and edge.get("sourceHandle") != "error"
        ]

        if result is not None and error_targets:
            inactive_loop_edges = [
                edge
                for edge in active_edges
                if edge["source"] == node_id
                and edge.get("sourceHandle") != "error"
                and self._is_loop_back_edge(edge)
            ]
            if inactive_loop_edges:
                skip_edge_ids = set(result.metadata.get("skip_loop_edge_ids") or [])
                for edge in inactive_loop_edges:
                    skip_edge_ids.add(self._edge_identity(edge))
                    if edge.get("id"):
                        skip_edge_ids.add(str(edge["id"]))
                result.metadata["skip_loop_edge_ids"] = list(skip_edge_ids)

        loop_back_targets = {
            edge["target"]
            for edge in active_edges
            if edge["source"] == node_id and self._is_loop_back_edge(edge)
        }
        # Forward only, as for the success branch: see _handle_success_branch_routing.
        preserved_node_ids = self.get_reachable_node_ids(
            error_targets, exclude_node_ids=loop_back_targets
        )

        exclusive_targets = [t for t in inactive_targets if t not in loop_back_targets]
        exclusive_nodes = self.get_exclusive_branch_node_ids(
            root_node_id=node_id,
            start_node_ids=exclusive_targets,
            edges=active_edges,
            preserve_node_ids=preserved_node_ids,
        )
        self.skipped_nodes.update(exclusive_nodes)

    def get_exclusive_branch_node_ids(
        self,
        *,
        root_node_id: str,
        start_node_ids: list[str],
        edges: list[dict],
        preserve_node_ids: set[str] | None = None,
    ) -> set[str]:
        """Return downstream nodes whose execution depends only on the branch root.

        Shared downstream nodes, such as a common output reached by another parallel branch, must
        stay active so the other branch can still complete the workflow.
        """
        preserved = preserve_node_ids or set()
        branch_node_ids: set[str] = set()
        for start_node_id in start_node_ids:
            branch_node_ids.update(
                self.get_branch_node_ids(
                    start_node_id,
                    edges,
                    exclude_node_ids=preserved,
                )
            )

        exclusive_node_ids: set[str] = set()
        changed = True
        while changed:
            changed = False
            for candidate in branch_node_ids - exclusive_node_ids - preserved:
                incoming_edges = [
                    edge
                    for edge in edges
                    if edge["target"] == candidate
                    and not (
                        self.nodes.get(candidate, {}).get("type") == "loop"
                        and edge.get("targetHandle") == "loop"
                    )
                ]
                if not incoming_edges:
                    continue

                # An input whose node is already skipped (by a Condition, say) feeds nothing.
                depends_only_on_root_or_exclusive_nodes = all(
                    edge["source"] == root_node_id
                    or edge["source"] in exclusive_node_ids
                    or edge["source"] in self.skipped_nodes
                    for edge in incoming_edges
                )
                if depends_only_on_root_or_exclusive_nodes:
                    exclusive_node_ids.add(candidate)
                    changed = True

        return exclusive_node_ids
