from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the imapTrigger node: the email, and its attachments saved to Drive when on."""
    from app.services.imap_attachments import download_attachments, metadata_items

    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs") or {}
    email = trigger_inputs.get("email") or {}
    if not isinstance(email, dict):
        email = {}

    if node_data.get("imapDownloadAttachments") is True:
        saved = download_attachments(ctx, email)
    else:
        saved = {"attachments": metadata_items(email), "file_ids": []}

    output = {
        "email": trigger_inputs.get("email", {}),
        "attachments": saved["attachments"],
        "file_ids": saved["file_ids"],
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
    return output
