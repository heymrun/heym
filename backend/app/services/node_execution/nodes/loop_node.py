from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the loop node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    allow_branch_skip = ctx.allow_branch_skip
    node_data = ctx.node_data

    is_loop_back = False
    for edge in self.edges:
        if edge.get("target") == node_id and edge.get("targetHandle") == "loop":
            source_id = edge.get("source", "")
            source_label = self.get_node_label(source_id)
            if source_label in inputs and source_id in self.node_outputs:
                is_loop_back = True
                break

    if node_id not in self.loop_states or not is_loop_back:
        array_expression = node_data.get("arrayExpression", "$input")

        if array_expression.startswith("$"):
            array_value = self.resolve_expression(
                array_expression, inputs, node_id, preserve_type=True
            )
        else:
            array_value = self.evaluate_message_template(array_expression, inputs, node_id)

        if not isinstance(array_value, list):
            if array_value is None:
                array_value = []
            else:
                array_value = [array_value]

        self.loop_states[node_id] = {
            "items": array_value,
            "current_index": 0,
            "total": len(array_value),
            "results": [],
        }
    else:
        self.loop_states[node_id]["current_index"] += 1
        loop_back_input = None
        for edge in self.edges:
            if edge.get("target") == node_id and edge.get("targetHandle") == "loop":
                source_label = self.get_node_label(edge.get("source", ""))
                if source_label in inputs:
                    loop_back_input = inputs[source_label]
                    break
        if loop_back_input is not None:
            self.loop_states[node_id]["results"].append(loop_back_input)

    loop_state = self.loop_states[node_id]
    current_index = loop_state["current_index"]
    total = loop_state["total"]
    items = loop_state["items"]

    if current_index < total:
        current_item = items[current_index]
        output = {
            "item": current_item,
            "index": current_index,
            "total": total,
            "isFirst": current_index == 0,
            "isLast": current_index == total - 1,
            "branch": "loop",
        }
    else:
        output = {
            "results": loop_state["results"],
            "total": total,
            "branch": "done",
        }

    if allow_branch_skip:
        if current_index >= total:
            self.skip_branch_targets_preserving_shared_downstream(
                node_id,
                active_targets=self.get_downstream_nodes(node_id, "done"),
                inactive_targets=self.get_downstream_nodes(node_id, "loop"),
                inactive_stop_node_ids={node_id},
            )
        else:
            self.skip_branch_targets_preserving_shared_downstream(
                node_id,
                active_targets=self.get_downstream_nodes(node_id, "loop"),
                inactive_targets=self.get_downstream_nodes(node_id, "done"),
                active_exclude_node_ids={node_id},
                inactive_stop_node_ids={node_id},
            )
    return output
