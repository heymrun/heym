from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the condition node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    allow_branch_skip = ctx.allow_branch_skip
    node_data = ctx.node_data

    condition = node_data.get("condition", "true")
    result = self.evaluate_condition(condition, inputs, node_id)
    selected_handle = "true" if result else "false"
    output = {
        "branch": selected_handle,
        "_skip_loop_source_handles": ["false" if result else "true"],
    }

    if allow_branch_skip:
        true_targets = self.get_downstream_nodes(node_id, "true")
        false_targets = self.get_downstream_nodes(node_id, "false")

        if result:
            loop_back_targets = self._loop_back_targets_for_source_handle(node_id, "true")
            self.skip_branch_targets_preserving_shared_downstream(
                node_id,
                active_targets=true_targets,
                inactive_targets=false_targets,
                active_exclude_node_ids=loop_back_targets,
                inactive_stop_node_ids=loop_back_targets,
            )
        else:
            loop_back_targets = self._loop_back_targets_for_source_handle(node_id, "false")
            self.skip_branch_targets_preserving_shared_downstream(
                node_id,
                active_targets=false_targets,
                inactive_targets=true_targets,
                active_exclude_node_ids=loop_back_targets,
                inactive_stop_node_ids=loop_back_targets,
            )
    return output
