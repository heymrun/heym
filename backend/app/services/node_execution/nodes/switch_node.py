from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the switch node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    allow_branch_skip = ctx.allow_branch_skip
    node_data = ctx.node_data

    expression = node_data.get("expression", "$input.text")
    value = self.resolve_expression(expression, inputs, node_id)
    cases_raw = node_data.get("cases", [])
    if isinstance(cases_raw, list):
        cases = cases_raw
    elif isinstance(cases_raw, str):
        cases = [case.strip() for case in cases_raw.split(",") if case.strip()]
    else:
        cases = []
    selected_handle = "default"

    for index, case_value in enumerate(cases):
        if str(value) == str(case_value):
            selected_handle = f"case-{index}"
            break

    handle_ids = [f"case-{index}" for index in range(len(cases))] + ["default"]
    output = {
        "branch": selected_handle,
        "value": value,
        "_skip_loop_source_handles": [
            handle_id for handle_id in handle_ids if handle_id != selected_handle
        ],
    }

    if allow_branch_skip:
        active_targets = self.get_downstream_nodes(node_id, selected_handle)
        inactive_targets: list[str] = []
        for handle_id in handle_ids:
            if handle_id != selected_handle:
                inactive_targets.extend(self.get_downstream_nodes(node_id, handle_id))
        loop_back_targets = self._loop_back_targets_for_source_handle(node_id, selected_handle)
        self.skip_branch_targets_preserving_shared_downstream(
            node_id,
            active_targets=active_targets,
            inactive_targets=inactive_targets,
            active_exclude_node_ids=loop_back_targets,
            inactive_stop_node_ids=loop_back_targets,
        )
    return output
