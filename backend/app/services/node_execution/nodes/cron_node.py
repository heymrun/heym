from __future__ import annotations

from datetime import datetime, timezone

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the cron node."""
    node_data = ctx.node_data

    output = {
        "cron": node_data.get("cronExpression", ""),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }
    return output
