from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import cast

from app.services.node_execution.base import NodeExecutionContext

NodeHandler = Callable[[NodeExecutionContext], object]

_HANDLER_MODULES: dict[str, str] = {
    "agent": "agent_node",
    "bigquery": "bigquery_node",
    "chartOutput": "chart_output_node",
    "clickhouse": "clickhouse_node",
    "condition": "condition_node",
    "consoleLog": "console_log_node",
    "crawler": "crawler_node",
    "cron": "cron_node",
    "dataTable": "data_table_node",
    "disableNode": "disable_node_node",
    "discord": "discord_node",
    "discordTrigger": "discord_trigger_node",
    "drive": "drive_node",
    "errorHandler": "error_handler_node",
    "execute": "execute_node",
    "fileUploadTrigger": "file_upload_trigger_node",
    "github": "github_node",
    "googleSheets": "google_sheets_node",
    "grist": "grist_node",
    "http": "http_node",
    "imapTrigger": "imap_trigger_node",
    "jsonOutputMapper": "json_output_mapper_node",
    "linear": "linear_node",
    "llm": "llm_node",
    "loop": "loop_node",
    "mcpCall": "mcp_call_node",
    "merge": "merge_node",
    "notion": "notion_node",
    "output": "output_node",
    "playwright": "playwright_node",
    "rabbitmq": "rabbitmq_node",
    "rag": "rag_node",
    "redis": "redis_node",
    "s3": "s3_node",
    "sendEmail": "send_email_node",
    "set": "set_node",
    "slack": "slack_node",
    "slackTrigger": "slack_trigger_node",
    "sticky": "sticky_node",
    "supabase": "supabase_node",
    "switch": "switch_node",
    "telegram": "telegram_node",
    "telegramTrigger": "telegram_trigger_node",
    "textInput": "text_input_node",
    "throwError": "throw_error_node",
    "variable": "variable_node",
    "wait": "wait_node",
    "websocketSend": "websocket_send_node",
    "websocketTrigger": "websocket_trigger_node",
}
_HANDLER_CACHE: dict[str, NodeHandler] = {}


def get_node_handler(node_type: str) -> NodeHandler | None:
    """Return the registered handler for a workflow node type."""
    module_name = _HANDLER_MODULES.get(node_type)
    if module_name is None:
        return None
    cached = _HANDLER_CACHE.get(node_type)
    if cached is not None:
        return cached
    module = import_module(f"app.services.node_execution.nodes.{module_name}")
    handler = cast(NodeHandler, getattr(module, "execute"))
    _HANDLER_CACHE[node_type] = handler
    return handler


def execute_node_handler(ctx: NodeExecutionContext) -> object:
    """Execute a workflow node via its modular handler."""
    handler = get_node_handler(ctx.node_type)
    if handler is None:
        return {"passthrough": ctx.inputs}
    return handler(ctx)
