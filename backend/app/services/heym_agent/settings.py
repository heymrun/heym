"""Where the Heym Agent runs: per-surface switches and the LLM it uses.

A surface is the global MCP server or one named MCP server. Each carries whether the
agent is on, the credential and model it runs with, and whether it is reachable over A2A
as well as through the `heym_chat` MCP tool.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLM_CREDENTIAL_TYPES, Credential, MCPServer, User
from app.services.credential_access import get_accessible_credential
from app.services.heym_agent.errors import AgentError


@dataclass(frozen=True)
class AgentSettings:
    """Resolved Heym Agent configuration for one MCP surface."""

    enabled: bool
    credential_id: uuid.UUID | None
    model: str | None
    a2a_enabled: bool = False

    @property
    def a2a_reachable(self) -> bool:
        """A2A rides on the agent: it answers only while both switches are on."""
        return self.enabled and self.a2a_enabled


@dataclass(frozen=True)
class ResolvedAgentLLM:
    credential: Credential
    model: str


async def load_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Load the persisted user row.

    MCP session-token auth hands handlers a stub `User` carrying only an id, so
    agent settings must always be read back from the database.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_global_agent_settings(db: AsyncSession, user_id: uuid.UUID) -> AgentSettings:
    """The Heym Agent settings of the user's global MCP server."""
    user = await load_user(db, user_id)
    if user is None:
        return AgentSettings(enabled=False, credential_id=None, model=None)
    return AgentSettings(
        enabled=bool(user.mcp_chat_enabled),
        credential_id=user.mcp_chat_credential_id,
        model=user.mcp_chat_model,
        a2a_enabled=bool(user.mcp_a2a_enabled),
    )


async def get_server_agent_settings(
    db: AsyncSession, server_id: uuid.UUID, user_id: uuid.UUID
) -> AgentSettings:
    """The Heym Agent settings of one of the user's named MCP servers."""
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id, MCPServer.user_id == user_id)
    )
    server = result.scalar_one_or_none()
    if server is None:
        return AgentSettings(enabled=False, credential_id=None, model=None)
    return AgentSettings(
        enabled=bool(server.chat_enabled),
        credential_id=server.chat_credential_id,
        model=server.chat_model,
        a2a_enabled=bool(server.a2a_enabled),
    )


async def resolve_agent_llm(
    db: AsyncSession,
    user_id: uuid.UUID,
    settings: AgentSettings,
) -> ResolvedAgentLLM:
    """Pick the credential and model an agent turn runs with.

    The surface's own selection wins. When it is unset, the account-level
    preferred model fills in, matching what the Chat tab offers by default.
    """
    user = await load_user(db, user_id)
    if user is None:
        raise AgentError("User not found.")

    credential_id = settings.credential_id or user.preferred_credential_id
    if credential_id is None:
        raise AgentError(
            "No LLM credential is configured for the Heym Agent. Open the MCP / A2A tab in "
            "Heym and pick a credential and model for the Heym Agent."
        )

    credential = await get_accessible_credential(db, credential_id, user_id)
    if credential is None:
        raise AgentError(
            "The LLM credential configured for the Heym Agent is no longer available. "
            "Pick another one in the MCP / A2A tab in Heym."
        )
    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise AgentError(
            "The credential configured for the Heym Agent is not an LLM credential "
            "(OpenAI, Google, Custom, or Model Router). Pick another one in the MCP / A2A "
            "tab in Heym."
        )

    model = settings.model
    if not model and credential.id == user.preferred_credential_id:
        model = user.preferred_model
    if not model:
        raise AgentError(
            "No model is configured for the Heym Agent. Open the MCP / A2A tab in Heym and "
            "pick a model for the Heym Agent."
        )

    return ResolvedAgentLLM(credential=credential, model=model)
