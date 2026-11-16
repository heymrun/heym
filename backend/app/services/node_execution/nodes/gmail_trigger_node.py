from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the gmailTrigger node: the email, and its attachments saved to Drive when on."""
    from app.services.gmail_trigger.attachments import download_attachments
    from app.services.imap_attachments import metadata_items

    trigger_inputs = ctx.node_data.get("_initial_inputs") or {}
    email = trigger_inputs.get("email") or {}
    if not isinstance(email, dict):
        email = {}

    if ctx.node_data.get("gmailDownloadAttachments") is True:
        saved = download_attachments(ctx, email)
    else:
        saved = {"attachments": metadata_items(email), "file_ids": []}

    return {
        "email": trigger_inputs.get("email", {}),
        "attachments": saved["attachments"],
        "file_ids": saved["file_ids"],
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
