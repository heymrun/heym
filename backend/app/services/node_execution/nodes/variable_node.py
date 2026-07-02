from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the variable node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    var_name = node_data.get("variableName", "variable")
    var_value_template = node_data.get("variableValue", "")
    var_type = node_data.get("variableType", "auto")

    vars_value: object = None
    if self._has_arithmetic(var_value_template):
        resolved_value = self.resolve_arithmetic_expression(
            var_value_template, inputs, node_id, preserve_type=True
        )
        vars_value = resolved_value
    elif var_type in ("array", "auto"):
        vars_value = self._try_resolve_variable_self_append(
            var_name,
            var_value_template,
            inputs,
            node_id,
        )
        if vars_value is not None:
            resolved_value = vars_value
    if vars_value is None:
        if self._is_single_dollar_expression(var_value_template):
            # Use raw=True to keep DotList/DotStr in vars, avoiding O(N²)
            # re-wrapping inside _build_context on each subsequent iteration.
            vars_value = self.resolve_expression(
                var_value_template.strip(),
                inputs,
                node_id,
                raw=True,
            )
            resolved_value = self._unwrap_scalar_value(vars_value)
        elif "$" in var_value_template:
            resolved_value = self._resolve_value_with_dollar_refs(
                var_value_template, inputs, node_id
            )
            vars_value = resolved_value
        else:
            resolved_value = var_value_template
            vars_value = var_value_template

    if var_type != "auto":
        if var_type == "string":
            resolved_value = str(resolved_value)
        elif var_type == "number":
            try:
                if isinstance(resolved_value, str):
                    if "." in resolved_value:
                        resolved_value = float(resolved_value)
                    else:
                        resolved_value = int(resolved_value)
                else:
                    resolved_value = float(resolved_value)
            except (ValueError, TypeError):
                pass
        elif var_type == "boolean":
            if isinstance(resolved_value, str):
                resolved_value = resolved_value.lower() in (
                    "true",
                    "1",
                    "yes",
                )
            else:
                resolved_value = bool(resolved_value)
        elif var_type == "array":
            if not isinstance(resolved_value, list):
                resolved_value = [resolved_value]
        elif var_type == "object":
            if not isinstance(resolved_value, dict):
                resolved_value = {"value": resolved_value}

    actual_type = var_type
    if var_type == "auto":
        if isinstance(resolved_value, bool):
            actual_type = "boolean"
        elif isinstance(resolved_value, int):
            actual_type = "number"
        elif isinstance(resolved_value, float):
            actual_type = "number"
        elif isinstance(resolved_value, list):
            actual_type = "array"
        elif isinstance(resolved_value, dict):
            actual_type = "object"
        else:
            actual_type = "string"

    # For array/auto types keep the raw Dot* value (e.g. DotList) so that
    # _build_context and store_node_output cache can skip O(N) re-wrapping.
    # DotList/DotStr are list/str subclasses — JSON-serializable as their base types.
    # For other types the coercion above changed resolved_value, so sync vars_value.
    if var_type not in ("array", "auto"):
        vars_value = resolved_value

    output = {
        "name": var_name,
        "value": vars_value,
        "type": actual_type,
    }
    self.vars[var_name] = vars_value
    self._mark_vars_context_dirty()
    return output
