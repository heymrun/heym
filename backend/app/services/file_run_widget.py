"""The run widget (chart type ``fileRun``): a dashboard widget that runs an ordinary workflow.

Chart widgets render a hidden ``dashboard_widget`` workflow. A run widget has none: it
points at an ordinary workflow and runs it one of three ways, by what the workflow takes.
A workflow with a File Upload trigger takes a dropped file through Heym's file intake
(mint a slot, upload the file to it), like any upload link. Otherwise the widget asks for
the workflow's start fields, or for nothing, and runs it as the dashboard owner. A
dashboard share never grants access to the workflow itself: ``workflow_access_clause`` only
extends dashboard write access to ``dashboard_widget`` workflows.
"""

from typing import Any

from app.services import file_intake_service
from app.services.workflow_inputs import start_input_fields

FILE_RUN_WIDGET_TYPE = "fileRun"


def run_widget_payload(nodes: list[dict] | None, edges: list[dict] | None) -> dict[str, Any]:
    """What the widget shows before a run: the file it takes, its fields, or a Run button."""
    node = file_intake_service.find_file_upload_trigger(nodes or [])
    if node is not None:
        config = file_intake_service.resolve_slot_config(node)
        return {
            "type": FILE_RUN_WIDGET_TYPE,
            "mode": "file",
            "file_label": str((node.get("data") or {}).get("label") or "file"),
            "max_size_mb": config.max_size_bytes // (1024 * 1024),
            "allowed_types": config.allowed_mime or [],
        }
    fields = start_input_fields(nodes, edges)
    return {
        "type": FILE_RUN_WIDGET_TYPE,
        "mode": "form" if fields else "run",
        "input_fields": fields,
    }
