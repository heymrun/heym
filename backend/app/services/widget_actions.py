"""Select the render graph or one HTML widget's Action branch for a run."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

ACTION_HANDLE = "action"
ACTION_INPUT_KEY = "__heym_widget_action"


@dataclass(frozen=True)
class WidgetAction:
    node_id: str
    message: str | None
    data: Any

    def output(self) -> dict[str, Any]:
        """The event output exposed under the source node's label."""
        return {"message": self.message, "data": self.data}

    def inputs(self) -> dict[str, Any]:
        """The Action event and source that travel with the run on the cluster queue."""
        return {ACTION_INPUT_KEY: {"node_id": self.node_id, **self.output()}}

    @classmethod
    def from_inputs(cls, inputs: dict) -> "WidgetAction | None":
        """Read the internal run input set by the dashboard action endpoint."""
        value = inputs.get(ACTION_INPUT_KEY)
        if isinstance(value, dict) and isinstance(value.get("node_id"), str):
            return cls(value["node_id"], value.get("message"), value.get("data"))
        return None


def _html_chart(node: dict) -> bool:
    return node.get("type") == "chartOutput" and (node.get("data") or {}).get("chartType") == "html"


def _endpoints(edge: dict) -> tuple[str, str]:
    # During graph selection, the agent owns its attached tools.
    if edge.get("targetHandle") == "tool-input":
        return edge["target"], edge["source"]
    return edge["source"], edge["target"]


def _reachable(edges: list[dict], starts: set[str]) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source, target = _endpoints(edge)
        children[source].append(target)
    seen = set(starts)
    pending = list(starts)
    while pending:
        for child in children[pending.pop()]:
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return seen


@dataclass
class WidgetActionGraph:
    nodes: list[dict]
    edges: list[dict]

    def _regular_edges(self) -> list[dict]:
        return [edge for edge in self.edges if edge.get("sourceHandle") != ACTION_HANDLE]

    def _branch_edges(self, charts: set[str]) -> list[dict]:
        return [edge for edge in self._regular_edges() if _endpoints(edge)[0] not in charts]

    def _select(self, ids: set[str], edges: list[dict]) -> tuple[list[dict], list[dict]]:
        return (
            [node for node in self.nodes if node["id"] in ids],
            [edge for edge in edges if edge["source"] in ids and edge["target"] in ids],
        )

    def render(self) -> tuple[list[dict], list[dict]]:
        """Leave Action-only nodes dormant during a regular run."""
        action_edges = [e for e in self.edges if e.get("sourceHandle") == ACTION_HANDLE]
        if not action_edges:
            return self.nodes, self.edges
        regular = self._regular_edges()
        action_only = _reachable(regular, {e["target"] for e in action_edges})
        shared = {
            target
            for source, target in map(_endpoints, regular)
            if source not in action_only and target in action_only
        }
        action_only -= _reachable(regular, shared)
        return self._select({node["id"] for node in self.nodes} - action_only, regular)

    def sources(self) -> set[str]:
        """Active HTML charts in the render graph with one valid Action connection."""
        render_nodes, _ = self.render()
        node_ids = {node["id"] for node in self.nodes}
        targets: dict[str, list[dict]] = defaultdict(list)
        for edge in self.edges:
            if edge.get("sourceHandle") == ACTION_HANDLE:
                targets[edge["source"]].append(edge)
        if not targets:
            return set()
        charts = {node["id"] for node in self.nodes if node.get("type") == "chartOutput"}
        action_results = (
            _reachable(
                self._branch_edges(charts),
                {edge["target"] for source in charts for edge in targets.get(source, [])},
            )
            & charts
        )
        sources = set()
        for node in render_nodes:
            if not _html_chart(node) or (node.get("data") or {}).get("active") is False:
                continue
            node_id = node["id"]
            connections = targets[node_id]
            if node_id in action_results or len(connections) != 1:
                continue
            edge = connections[0]
            if (
                edge["target"] in node_ids
                and edge["target"] != node_id
                and edge.get("targetHandle") != "tool-input"
            ):
                sources.add(node_id)
        return sources

    def render_chart(self) -> dict | None:
        """The chart on the render side of the graph, for the widget's saved settings."""
        nodes, _ = self.render()
        return next(
            (
                node
                for node in reversed(nodes)
                if isinstance(node, dict) and node.get("type") == "chartOutput"
            ),
            None,
        )

    def branch(self, source: str) -> tuple[list[dict], list[dict]]:
        """Start at the Action source and stop at chart outputs on its branch."""
        if source not in self.sources():
            return [], []
        charts = {node["id"] for node in self.nodes if node.get("type") == "chartOutput"}
        regular = [edge for edge in self._branch_edges(charts) if edge["target"] != source]
        action_edge = next(
            edge
            for edge in self.edges
            if edge["source"] == source and edge.get("sourceHandle") == ACTION_HANDLE
        )
        edges = [*regular, action_edge]
        # This connection is now an ordinary dependency in the action execution graph.
        return self._select(
            _reachable(edges, {source}), [*regular, {**action_edge, "sourceHandle": "output"}]
        )
