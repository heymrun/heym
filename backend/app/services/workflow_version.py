from typing import Any

from app.models.schemas import EdgeChange, NodeChange, VersionChange, WorkflowVersionDiffResponse


def calculate_workflow_diff(
    old_nodes: list[dict],
    old_edges: list[dict],
    old_config: dict[str, Any],
    new_nodes: list[dict],
    new_edges: list[dict],
    new_config: dict[str, Any],
    version_id: str,
    version_number: int,
    compared_to_version_id: str | None = None,
    compared_to_version_number: int | None = None,
) -> WorkflowVersionDiffResponse:
    node_changes = _calculate_node_changes(old_nodes, new_nodes)
    edge_changes = _calculate_edge_changes(old_edges, new_edges)
    config_changes = _calculate_config_changes(old_config, new_config)

    return WorkflowVersionDiffResponse(
        version_id=version_id,
        version_number=version_number,
        compared_to_version_id=compared_to_version_id,
        compared_to_version_number=compared_to_version_number,
        node_changes=node_changes,
        edge_changes=edge_changes,
        config_changes=config_changes,
    )


def _calculate_node_changes(old_nodes: list[dict], new_nodes: list[dict]) -> list[NodeChange]:
    changes: list[NodeChange] = []
    old_nodes_map = {node.get("id"): node for node in old_nodes if node.get("id")}
    new_nodes_map = {node.get("id"): node for node in new_nodes if node.get("id")}

    all_node_ids = set(old_nodes_map.keys()) | set(new_nodes_map.keys())

    for node_id in all_node_ids:
        old_node = old_nodes_map.get(node_id)
        new_node = new_nodes_map.get(node_id)

        if old_node is None and new_node is not None:
            changes.append(
                NodeChange(
                    node_id=node_id,
                    change_type="added",
                    new_node=new_node,
                )
            )
        elif old_node is not None and new_node is None:
            changes.append(
                NodeChange(
                    node_id=node_id,
                    change_type="removed",
                    old_node=old_node,
                )
            )
        elif old_node is not None and new_node is not None:
            node_field_changes = _compare_node_fields(old_node, new_node)
            if node_field_changes:
                changes.append(
                    NodeChange(
                        node_id=node_id,
                        change_type="modified",
                        old_node=old_node,
                        new_node=new_node,
                        changes=node_field_changes,
                    )
                )

    return changes


def _compare_node_fields(old_node: dict, new_node: dict) -> list[VersionChange]:
    changes: list[VersionChange] = []
    all_keys = set(old_node.keys()) | set(new_node.keys())

    skip_keys = {"id"}

    for key in all_keys:
        if key in skip_keys:
            continue
        old_value = old_node.get(key)
        new_value = new_node.get(key)

        if old_value != new_value:
            if key == "data" and isinstance(old_value, dict) and isinstance(new_value, dict):
                data_changes = _compare_dict_fields(old_value, new_value, "data")
                changes.extend(data_changes)
            else:
                changes.append(
                    VersionChange(
                        type="node_field",
                        field=key,
                        old_value=old_value,
                        new_value=new_value,
                    )
                )

    return changes


def _compare_dict_fields(old_dict: dict, new_dict: dict, prefix: str = "") -> list[VersionChange]:
    changes: list[VersionChange] = []
    all_keys = set(old_dict.keys()) | set(new_dict.keys())

    for key in all_keys:
        old_value = old_dict.get(key)
        new_value = new_dict.get(key)

        if old_value != new_value:
            field_name = f"{prefix}.{key}" if prefix else key
            changes.append(
                VersionChange(
                    type="field",
                    field=field_name,
                    old_value=old_value,
                    new_value=new_value,
                )
            )

    return changes


def _calculate_edge_changes(old_edges: list[dict], new_edges: list[dict]) -> list[EdgeChange]:
    changes: list[EdgeChange] = []
    old_edges_set = {_edge_key(edge) for edge in old_edges}
    new_edges_set = {_edge_key(edge) for edge in new_edges}

    old_edges_map = {_edge_key(edge): edge for edge in old_edges}
    new_edges_map = {_edge_key(edge): edge for edge in new_edges}

    added_edges = new_edges_set - old_edges_set
    removed_edges = old_edges_set - new_edges_set
    common_edges = old_edges_set & new_edges_set

    for edge_key in added_edges:
        edge = new_edges_map[edge_key]
        changes.append(
            EdgeChange(
                edge_id=edge.get("id"),
                change_type="added",
                new_edge=edge,
            )
        )

    for edge_key in removed_edges:
        edge = old_edges_map[edge_key]
        changes.append(
            EdgeChange(
                edge_id=edge.get("id"),
                change_type="removed",
                old_edge=edge,
            )
        )

    for edge_key in common_edges:
        old_edge = old_edges_map[edge_key]
        new_edge = new_edges_map[edge_key]
        if old_edge != new_edge:
            changes.append(
                EdgeChange(
                    edge_id=new_edge.get("id"),
                    change_type="modified",
                    old_edge=old_edge,
                    new_edge=new_edge,
                )
            )

    return changes


def _edge_key(edge: dict) -> tuple[str, str]:
    source = edge.get("source", "")
    target = edge.get("target", "")
    return (source, target)


def _calculate_config_changes(
    old_config: dict[str, Any], new_config: dict[str, Any]
) -> list[VersionChange]:
    changes: list[VersionChange] = []
    all_keys = set(old_config.keys()) | set(new_config.keys())

    for key in all_keys:
        old_value = old_config.get(key)
        new_value = new_config.get(key)

        if old_value != new_value:
            changes.append(
                VersionChange(
                    type="config",
                    field=key,
                    old_value=old_value,
                    new_value=new_value,
                )
            )

    return changes
