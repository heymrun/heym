from __future__ import annotations

import time

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the wait node."""
    self = ctx.executor
    inputs = ctx.inputs
    node_data = ctx.node_data

    duration_ms = node_data.get("duration", 1000)
    # Sleep in small slices so a workflow timeout (or cancel) interrupts
    # a long wait promptly instead of blocking the whole duration.
    remaining = duration_ms / 1000.0
    while remaining > 0:
        self.check_cancelled()
        slice_s = min(0.1, remaining)
        time.sleep(slice_s)
        remaining -= slice_s
    self.check_cancelled()
    first_input = self._first_visible_input(inputs)
    output = first_input if isinstance(first_input, dict) else {"value": first_input}
    return output
