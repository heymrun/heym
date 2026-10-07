"""The file-run widget: a dashboard widget that runs a workflow on a dropped file.

Chart widgets render a hidden ``dashboard_widget`` workflow. A file-run widget has
none: it points at an ordinary workflow with a File Upload trigger, and a drop goes
through Heym's file intake (mint a slot, upload the file to it), which runs the
workflow on the main instance as that workflow's owner, like any upload link. A
dashboard share never grants access to the workflow itself: ``workflow_access_clause``
only extends dashboard write access to ``dashboard_widget`` workflows.
"""

from typing import Any

from app.services import file_intake_service

FILE_RUN_WIDGET_TYPE = "fileRun"


def file_run_payload(nodes: list[dict] | None) -> dict[str, Any] | None:
    """What the widget shows before a drop: the file the workflow takes, or None."""
    node = file_intake_service.find_file_upload_trigger(nodes or [])
    if node is None:
        return None
    config = file_intake_service.resolve_slot_config(node)
    return {
        "type": FILE_RUN_WIDGET_TYPE,
        "file_label": str((node.get("data") or {}).get("label") or "file"),
        "max_size_mb": config.max_size_bytes // (1024 * 1024),
        "allowed_types": config.allowed_mime or [],
    }
