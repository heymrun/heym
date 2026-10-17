from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleSheetsTrigger node: hand the detected row change downstream."""
    trigger_inputs = ctx.node_data.get("_initial_inputs") or {}
    change = trigger_inputs.get("change") or {}
    return {
        "event": change.get("event"),
        "row": change.get("row", {}),
        "changed_columns": change.get("changed_columns", []),
        "key": change.get("key"),
        "spreadsheet_id": change.get("spreadsheet_id"),
        "sheet_name": change.get("sheet_name"),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
