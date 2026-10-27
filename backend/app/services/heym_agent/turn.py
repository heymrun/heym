"""One Heym Agent turn, whichever protocol asked for it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker
from app.services.heym_agent.links import WorkflowLink
from app.services.heym_agent.progress import ProgressCallback, TurnProgress
from app.services.heym_agent.settings import AgentSettings, resolve_agent_llm
from app.services.mcp_elicitation import MCPClientChannel


class AgentOutcome(str, Enum):
    """How a turn ended, in the terms both protocols need."""

    COMPLETED = "completed"
    # The agent asked a clarifying question and waits for the answer.
    INPUT_REQUIRED = "input_required"
    # A credential form is open on Heym's own page and waits for the user.
    AUTH_REQUIRED = "auth_required"
    CANCELED = "canceled"


@dataclass(frozen=True)
class AgentTurnResult:
    conversation_id: uuid.UUID
    text: str
    tool_names: list[str]
    outcome: AgentOutcome = AgentOutcome.COMPLETED
    # True when the turn ended with build mode's finish: the latest test run passed.
    verified: bool = False
    # Workflows this turn created or saved that the user can still open.
    workflow_links: tuple[WorkflowLink, ...] = ()
    # Eval suites this turn created or changed that the user still owns.
    eval_suite_links: tuple[WorkflowLink, ...] = ()
    # Credential form links the user still has to open in a browser.
    credential_form_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTurnRequest:
    user_id: uuid.UUID
    settings: AgentSettings
    message: str
    conversation_id: uuid.UUID | None
    public_base_url: str
    # The conversation source for a new conversation: "mcp" or "a2a".
    source: str
    client: MCPClientChannel | None = None
    a2a_task_id: uuid.UUID | None = None


def outcome_of(
    *, cancelled: bool, form_urls: tuple[str, ...], paused_for_clarification: bool
) -> AgentOutcome:
    """A cancel wins, then an open credential form, then a clarifying question."""
    if cancelled:
        return AgentOutcome.CANCELED
    if form_urls:
        return AgentOutcome.AUTH_REQUIRED
    if paused_for_clarification:
        return AgentOutcome.INPUT_REQUIRED
    return AgentOutcome.COMPLETED


async def run_agent_turn(
    request: AgentTurnRequest,
    *,
    on_progress: ProgressCallback | None = None,
    db: AsyncSession | None = None,
) -> AgentTurnResult:
    """Run one turn of the dashboard chat engine for an MCP or A2A client.

    `db` only reads configuration; without one, a short session does, so a long turn never
    holds a pooled connection. The turn itself runs on its own short sessions.
    """
    from app.api.chats import run_agent_chat_turn

    if db is None:
        async with async_session_maker() as config_db:
            resolved = await resolve_agent_llm(config_db, request.user_id, request.settings)
    else:
        resolved = await resolve_agent_llm(db, request.user_id, request.settings)
    progress = TurnProgress(on_progress) if on_progress is not None else None
    return await run_agent_chat_turn(
        user_id=request.user_id,
        message=request.message,
        conversation_id=request.conversation_id,
        credential_id=resolved.credential.id,
        model=resolved.model,
        public_base_url=request.public_base_url,
        client=request.client,
        source=request.source,
        on_event=progress.observe if progress is not None else None,
        a2a_task_id=request.a2a_task_id,
    )
