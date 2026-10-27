"""Expose the Heym Agent as the single MCP tool heym_chat.

When the chat tool is enabled on the global MCP server or on a named MCP server,
`heym_chat` shows up in `tools/list`. Calling it runs one full turn of the same
agent loop the Chat tab uses, so every capability the Chat tab has today, plus
every one added later, is reachable from an MCP client without registering a
new tool per capability.

Turns are persisted as a normal Chat tab conversation (`source="mcp"`), so the
user can read, continue, and audit everything an MCP client did.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import MCPTool, MCPToolInputProperty, MCPToolInputSchema
from app.services.credential_setup import wait_for_conversation_forms
from app.services.heym_agent.errors import AgentError
from app.services.heym_agent.profile import MCP_TOOL_DESCRIPTION
from app.services.heym_agent.progress import ProgressCallback
from app.services.heym_agent.settings import AgentSettings, resolve_agent_llm
from app.services.heym_agent.turn import (
    AgentOutcome,
    AgentTurnRequest,
    AgentTurnResult,
    run_agent_turn,
)
from app.services.mcp_elicitation import MCPClientChannel

MCP_CHAT_TOOL_NAME = "heym_chat"

MCP_CHAT_TOOL_DESCRIPTION = MCP_TOOL_DESCRIPTION

_MAX_MCP_CHAT_MESSAGE_LENGTH = 20000


def build_chat_mcp_tool() -> MCPTool:
    """The single MCP tool that fronts the whole dashboard chat engine."""
    return MCPTool(
        name=MCP_CHAT_TOOL_NAME,
        description=MCP_CHAT_TOOL_DESCRIPTION,
        inputSchema=MCPToolInputSchema(
            type="object",
            properties={
                "message": MCPToolInputProperty(
                    type="string",
                    description=(
                        "The instruction or question for the Heym assistant, in natural "
                        "language. Include everything it needs in one message."
                    ),
                ),
                "conversation_id": MCPToolInputProperty(
                    type="string",
                    description=(
                        "Optional. The conversation_id from a previous heym_chat result, to "
                        "continue that thread instead of starting a new one."
                    ),
                ),
                "wait_for_credential_form": MCPToolInputProperty(
                    type="boolean",
                    description=(
                        "Optional. Set true, with the same conversation_id, right after you "
                        "showed the user a Heym credential form link. The call waits until "
                        "the user saves or declines the form, then sends `message` and "
                        "returns the reply, so the conversation continues on its own."
                    ),
                ),
            },
            required=["message"],
        ),
    )


def normalize_chat_arguments(arguments: dict) -> tuple[str, uuid.UUID | None]:
    """Validate `heym_chat` arguments coming off the wire."""
    raw_message = arguments.get("message")
    message = str(raw_message).strip() if raw_message is not None else ""
    if not message:
        raise AgentError("`message` is required and cannot be empty.")
    if len(message) > _MAX_MCP_CHAT_MESSAGE_LENGTH:
        raise AgentError(f"`message` is too long (max {_MAX_MCP_CHAT_MESSAGE_LENGTH} characters).")

    raw_conversation_id = arguments.get("conversation_id")
    if raw_conversation_id in (None, ""):
        return message, None
    try:
        return message, uuid.UUID(str(raw_conversation_id))
    except ValueError as exc:
        raise AgentError("`conversation_id` must be a UUID.") from exc


def wants_form_wait(arguments: dict) -> bool:
    """Whether a `heym_chat` call asked to wait for the conversation's credential forms."""
    return arguments.get("wait_for_credential_form") is True


async def run_chat_tool(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    settings: AgentSettings,
    arguments: dict,
    public_base_url: str,
    client: MCPClientChannel | None = None,
    on_progress: ProgressCallback | None = None,
) -> AgentTurnResult:
    """Run one Heym Agent turn on behalf of an MCP client.

    `db` is only used to read configuration. The turn itself runs on its own
    short-lived sessions so it never interleaves with the caller's transaction.
    """
    from app.api.chats import MCP_CONVERSATION_SOURCE

    message, conversation_id = normalize_chat_arguments(arguments)
    if conversation_id is not None and wants_form_wait(arguments):
        # Fail on a broken configuration before waiting minutes for a form.
        await resolve_agent_llm(db, user_id, settings)
        still_open = await wait_for_conversation_forms(
            user_id=user_id, conversation_id=conversation_id, public_base_url=public_base_url
        )
        if still_open:
            return AgentTurnResult(
                conversation_id=conversation_id,
                text="The user has not saved the credential form yet.",
                tool_names=[],
                outcome=AgentOutcome.AUTH_REQUIRED,
                credential_form_urls=tuple(still_open),
            )
    return await run_agent_turn(
        AgentTurnRequest(
            user_id=user_id,
            settings=settings,
            message=message,
            conversation_id=conversation_id,
            public_base_url=public_base_url,
            source=MCP_CONVERSATION_SOURCE,
            client=client,
        ),
        on_progress=on_progress,
        db=db,
    )


def format_chat_tool_text(result: AgentTurnResult) -> str:
    """Render a chat result as the text block an MCP client reads."""
    text = result.text.strip()
    lines = [text or "(The assistant returned no text.)"]
    for url in result.credential_form_urls:
        if url not in text:
            lines.append("")
            lines.append(
                "Open this Heym page in a browser signed in to Heym to enter the credential; "
                f"its values never pass through this client: {url}"
            )
    if result.credential_form_urls:
        lines.append("")
        lines.append(
            "Show the user the link above now. Then call heym_chat again with the same "
            "conversation_id, wait_for_credential_form set to true and the message "
            '"I saved the credential form." That call waits until the user saves the form and '
            "continues the conversation on its own."
        )
    if result.workflow_links:
        lines.append("")
        lines.append("Workflows saved in this call (open in a browser signed in to Heym):")
        for link in result.workflow_links:
            lines.append(f"- {link.name}: {link.url}")
    if result.eval_suite_links:
        lines.append("")
        lines.append("Eval suites saved in this call (open in a browser signed in to Heym):")
        for link in result.eval_suite_links:
            lines.append(f"- {link.name}: {link.url}")
    lines.append("")
    lines.append(f"conversation_id: {result.conversation_id}")
    if result.tool_names:
        lines.append(f"heym actions: {', '.join(result.tool_names)}")
    if result.verified:
        lines.append("Verified: the latest test run of the saved workflow passed.")
    if result.outcome is AgentOutcome.INPUT_REQUIRED:
        lines.append(
            "The assistant is waiting for answers to its clarifying questions. "
            "Reply with the answers using the same conversation_id."
        )
    return "\n".join(lines)
