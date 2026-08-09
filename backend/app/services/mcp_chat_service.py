"""Expose the dashboard chat engine as a single MCP tool.

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
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialType, MCPServer, User
from app.models.schemas import MCPTool, MCPToolInputProperty, MCPToolInputSchema
from app.services.credential_access import get_accessible_credential

MCP_CHAT_TOOL_NAME = "heym_chat"

MCP_CHAT_TOOL_DESCRIPTION = (
    "Talk to the Heym assistant in natural language and let it act on the user's Heym "
    "account. This is the same engine that powers the Heym Chat tab, so it can do "
    "everything that tab can: list, inspect, create, edit and run workflows with the AI "
    "workflow builder; report analytics, recent executions, and which executions are "
    "running right now (with elapsed time, current node, and a link to each live run); "
    "read and resolve "
    "human-in-the-loop reviews; list and act on agentic kanban boards, cards and "
    "comments; read schedules, teams and global variables; and search the Heym "
    "documentation. New Heym capabilities become available here automatically. "
    "Send one natural-language instruction or question as `message` and read the reply. "
    "Every call is recorded in the user's Chat tab history. To continue an earlier "
    "exchange instead of starting a new thread, pass the `conversation_id` returned by a "
    "previous call."
)

# The credential types the dashboard chat engine accepts, mirroring
# `POST /api/chats/{id}/messages`.
_CHAT_CREDENTIAL_TYPES = (
    CredentialType.openai,
    CredentialType.google,
    CredentialType.custom,
)

_MAX_MCP_CHAT_MESSAGE_LENGTH = 20000


class MCPChatError(Exception):
    """The chat tool cannot run: bad arguments, bad configuration, or a busy thread."""


@dataclass(frozen=True)
class MCPChatSettings:
    """Resolved chat-tool configuration for one MCP surface."""

    enabled: bool
    credential_id: uuid.UUID | None
    model: str | None


@dataclass(frozen=True)
class ResolvedChatLLM:
    credential: Credential
    model: str


@dataclass(frozen=True)
class MCPChatResult:
    conversation_id: uuid.UUID
    text: str
    tool_names: list[str]
    awaiting_clarification: bool


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
            },
            required=["message"],
        ),
    )


async def load_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Load the persisted user row.

    MCP session-token auth hands handlers a stub `User` carrying only an id, so
    chat-tool settings must always be read back from the database.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_global_chat_settings(db: AsyncSession, user_id: uuid.UUID) -> MCPChatSettings:
    user = await load_user(db, user_id)
    if user is None:
        return MCPChatSettings(enabled=False, credential_id=None, model=None)
    return MCPChatSettings(
        enabled=bool(user.mcp_chat_enabled),
        credential_id=user.mcp_chat_credential_id,
        model=user.mcp_chat_model,
    )


async def get_server_chat_settings(
    db: AsyncSession, server_id: uuid.UUID, user_id: uuid.UUID
) -> MCPChatSettings:
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id, MCPServer.user_id == user_id)
    )
    server = result.scalar_one_or_none()
    if server is None:
        return MCPChatSettings(enabled=False, credential_id=None, model=None)
    return MCPChatSettings(
        enabled=bool(server.chat_enabled),
        credential_id=server.chat_credential_id,
        model=server.chat_model,
    )


async def resolve_chat_llm(
    db: AsyncSession,
    user_id: uuid.UUID,
    settings: MCPChatSettings,
) -> ResolvedChatLLM:
    """Pick the credential and model the MCP chat turn runs with.

    The surface's own selection wins. When it is unset, the account-level
    preferred model fills in, matching what the Chat tab offers by default.
    """
    user = await load_user(db, user_id)
    if user is None:
        raise MCPChatError("User not found.")

    credential_id = settings.credential_id or user.preferred_credential_id
    if credential_id is None:
        raise MCPChatError(
            "No LLM credential is configured for the Heym chat tool. Open the MCP tab in "
            "Heym and pick a credential and model for the chat tool."
        )

    credential = await get_accessible_credential(db, credential_id, user_id)
    if credential is None:
        raise MCPChatError(
            "The LLM credential configured for the Heym chat tool is no longer available. "
            "Pick another one in the MCP tab in Heym."
        )
    if credential.type not in _CHAT_CREDENTIAL_TYPES:
        raise MCPChatError(
            "The credential configured for the Heym chat tool is not an LLM credential "
            "(OpenAI, Google, or Custom). Pick another one in the MCP tab in Heym."
        )

    model = settings.model
    if not model and credential.id == user.preferred_credential_id:
        model = user.preferred_model
    if not model:
        raise MCPChatError(
            "No model is configured for the Heym chat tool. Open the MCP tab in Heym and "
            "pick a model for the chat tool."
        )

    return ResolvedChatLLM(credential=credential, model=model)


def normalize_chat_arguments(arguments: dict) -> tuple[str, uuid.UUID | None]:
    """Validate `heym_chat` arguments coming off the wire."""
    raw_message = arguments.get("message")
    message = str(raw_message).strip() if raw_message is not None else ""
    if not message:
        raise MCPChatError("`message` is required and cannot be empty.")
    if len(message) > _MAX_MCP_CHAT_MESSAGE_LENGTH:
        raise MCPChatError(
            f"`message` is too long (max {_MAX_MCP_CHAT_MESSAGE_LENGTH} characters)."
        )

    raw_conversation_id = arguments.get("conversation_id")
    if raw_conversation_id in (None, ""):
        return message, None
    try:
        return message, uuid.UUID(str(raw_conversation_id))
    except ValueError as exc:
        raise MCPChatError("`conversation_id` must be a UUID.") from exc


async def run_chat_tool(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    settings: MCPChatSettings,
    arguments: dict,
    public_base_url: str,
) -> MCPChatResult:
    """Run one dashboard-chat turn on behalf of an MCP client.

    `db` is only used to read configuration. The turn itself runs on its own
    short-lived sessions so it never interleaves with the caller's transaction.
    """
    from app.api.chats import run_mcp_chat_turn

    message, conversation_id = normalize_chat_arguments(arguments)
    resolved = await resolve_chat_llm(db, user_id, settings)
    return await run_mcp_chat_turn(
        user_id=user_id,
        message=message,
        conversation_id=conversation_id,
        credential_id=resolved.credential.id,
        model=resolved.model,
        public_base_url=public_base_url,
    )


def format_chat_tool_text(result: MCPChatResult) -> str:
    """Render a chat result as the text block an MCP client reads."""
    lines = [result.text.strip() or "(The assistant returned no text.)"]
    lines.append("")
    lines.append(f"conversation_id: {result.conversation_id}")
    if result.tool_names:
        lines.append(f"heym actions: {', '.join(result.tool_names)}")
    if result.awaiting_clarification:
        lines.append(
            "The assistant is waiting for answers to its clarifying questions. "
            "Reply with the answers using the same conversation_id."
        )
    return "\n".join(lines)
