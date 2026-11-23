"""Send a Heym Chat message from a workflow: the async side of the Heym node's chat operation.

The Heym node's `sendChatMessage` operation runs one turn of the same agent the Chat tab,
MCP `heym_chat` and A2A use (`run_agent_chat_turn`). The node handler is synchronous and
runs in an executor thread; it submits one of the coroutines below to the application loop
(`app_loop.submit`), where the async engine, the chat task map and the chat stream bus live.

The turn runs as the run's user with that user's Chat default model. Conversations the
node starts carry `source="workflow"`. With chat history off, the turn runs in a
`workflow_temp` conversation, which the Chat list never shows and which is deleted as soon
as the turn ends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.db.models import LLM_CREDENTIAL_TYPES, DashboardConversation
from app.db.session import async_session_maker
from app.services.app_loop import chat_turn_depth_scope
from app.services.credential_access import get_accessible_credential
from app.services.heym_agent.errors import AgentError
from app.services.heym_agent.settings import ResolvedAgentLLM, load_user
from app.services.heym_agent.turn import AgentOutcome, AgentTurnResult

logger = logging.getLogger(__name__)

WORKFLOW_CONVERSATION_SOURCE = "workflow"
TEMPORARY_CONVERSATION_SOURCE = "workflow_temp"
TEMPORARY_CONVERSATION_TITLE = "Workflow message"

# Same cap as MCP `heym_chat`.
MAX_CHAT_MESSAGE_LENGTH = 20000

# Outcomes that wait on a person: they leave through the node's `question` handle.
QUESTION_OUTCOMES = frozenset({AgentOutcome.INPUT_REQUIRED, AgentOutcome.AUTH_REQUIRED})

# A clarifying question arrives as a fenced JSON block in the reply (see the Chat prompt).
_CLARIFY_BLOCK = re.compile(r"```heym-clarify[^\S\n]*\n(?P<body>.*?)\n?```", re.DOTALL)

# Fire-and-forget turns outlive the call that started them; keep a reference so the
# event loop does not garbage-collect a running task.
_background_turns: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class ChatNodeRequest:
    """One chat message a Heym node sends."""

    user_id: uuid.UUID
    message: str
    # Set to continue that conversation; None starts a new one.
    conversation_id: uuid.UUID | None
    # Chat history off: run in a temporary conversation and delete it afterwards.
    temporary: bool
    # The chat hop depth the turn runs at, so workflows it starts can stop a loop.
    depth: int
    public_base_url: str


@dataclass(frozen=True)
class _PreparedTurn:
    conversation_id: uuid.UUID
    llm: ResolvedAgentLLM


def conversation_not_found(raw_id: str) -> ValueError:
    """One message for a missing, deleted, malformed or someone else's conversation."""
    return ValueError(f"Conversation not found or not accessible: {raw_id}")


async def resolve_chat_default_llm(db: Any, user_id: uuid.UUID) -> ResolvedAgentLLM:
    """The credential and model the user's Chat tab uses by default."""
    user = await load_user(db, user_id)
    if user is None:
        raise ValueError("Heym Chat cannot find the user this run belongs to.")
    if user.preferred_credential_id is None or not user.preferred_model:
        raise ValueError(
            "Heym Chat has no default model for this user. Pick a model in the Chat tab, "
            "then run the workflow again."
        )
    credential = await get_accessible_credential(db, user.preferred_credential_id, user_id)
    if credential is None or credential.type not in LLM_CREDENTIAL_TYPES:
        raise ValueError(
            "The credential of the default Chat model is no longer available. Pick another "
            "model in the Chat tab, then run the workflow again."
        )
    return ResolvedAgentLLM(credential=credential, model=user.preferred_model)


async def _prepare(request: ChatNodeRequest) -> _PreparedTurn:
    """Resolve the model and the conversation before anything runs.

    Fire and forget returns right after this, so every refusal the node can report (no
    model, missing conversation, a conversation that is already running) happens here.
    """
    async with async_session_maker() as db:
        llm = await resolve_chat_default_llm(db, request.user_id)
        if request.conversation_id is not None:
            result = await db.execute(
                select(DashboardConversation).where(
                    DashboardConversation.id == request.conversation_id,
                    DashboardConversation.user_id == request.user_id,
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation is None:
                raise conversation_not_found(str(request.conversation_id))
            if conversation.is_running:
                raise ValueError(
                    "This conversation is already running. Wait for it to finish, or start "
                    "a new conversation."
                )
            return _PreparedTurn(conversation_id=conversation.id, llm=llm)

        from app.api.chats import DEFAULT_CONVERSATION_TITLE

        conversation = DashboardConversation(
            id=uuid.uuid4(),
            user_id=request.user_id,
            # A turn generates a title only for the default one; a temporary conversation
            # is deleted right after, so it skips that model call.
            title=TEMPORARY_CONVERSATION_TITLE if request.temporary else DEFAULT_CONVERSATION_TITLE,
            source=(
                TEMPORARY_CONVERSATION_SOURCE if request.temporary else WORKFLOW_CONVERSATION_SOURCE
            ),
        )
        db.add(conversation)
        await db.commit()
        return _PreparedTurn(conversation_id=conversation.id, llm=llm)


async def _delete_temporary_conversation(user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    """Remove a temporary conversation the way the Chat tab's delete does."""
    from app.services.file_sandbox.chat_workspaces import delete_chat_workspace

    async with async_session_maker() as db:
        result = await db.execute(
            select(DashboardConversation).where(
                DashboardConversation.id == conversation_id,
                DashboardConversation.user_id == user_id,
                DashboardConversation.source == TEMPORARY_CONVERSATION_SOURCE,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is not None:
            await db.delete(conversation)
            await db.commit()
    await asyncio.to_thread(delete_chat_workspace, user_id, conversation_id)


async def _run_turn(request: ChatNodeRequest, prepared: _PreparedTurn) -> AgentTurnResult:
    """Run the turn, then delete a temporary conversation however the turn ended."""
    from app.api.chats import run_agent_chat_turn

    try:
        # The turn task is created inside this scope and copies the context, so every
        # workflow the turn runs is built at this depth.
        with chat_turn_depth_scope(request.depth):
            return await run_agent_chat_turn(
                user_id=request.user_id,
                message=request.message,
                conversation_id=prepared.conversation_id,
                credential_id=prepared.llm.credential.id,
                model=prepared.llm.model,
                public_base_url=request.public_base_url,
                source=(
                    TEMPORARY_CONVERSATION_SOURCE
                    if request.temporary
                    else WORKFLOW_CONVERSATION_SOURCE
                ),
            )
    except AgentError as exc:
        raise ValueError(str(exc)) from exc
    finally:
        if request.temporary:
            await asyncio.shield(
                _delete_temporary_conversation(request.user_id, prepared.conversation_id)
            )


def split_clarify_questions(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Separate a reply's clarifying questions from its prose.

    The Chat tab renders the `heym-clarify` block as a form; a workflow gets the questions
    as data instead, so the next node can ask a person without parsing JSON out of text.
    A block that does not parse stays in the text untouched.
    """
    questions: list[dict[str, Any]] = []

    def take(match: re.Match[str]) -> str:
        try:
            parsed = json.loads(match.group("body"))
        except json.JSONDecodeError:
            return match.group(0)
        found = parsed.get("questions") if isinstance(parsed, dict) else None
        if not isinstance(found, list):
            return match.group(0)
        questions.extend(item for item in found if isinstance(item, dict))
        return ""

    remaining = _CLARIFY_BLOCK.sub(take, text)
    return (remaining.strip() if questions else text), questions


def build_chat_output(result: AgentTurnResult, *, temporary: bool) -> dict[str, Any]:
    """The node output for a turn the node waited for."""
    reply, questions = split_clarify_questions(result.text)
    return {
        "conversation_id": None if temporary else str(result.conversation_id),
        "status": result.outcome.value,
        "reply": reply,
        "questions": questions,
        "tool_names": list(result.tool_names),
        "verified": result.verified,
        "workflow_links": [{"name": link.name, "url": link.url} for link in result.workflow_links],
        "eval_suite_links": [
            {"name": link.name, "url": link.url} for link in result.eval_suite_links
        ],
        "credential_form_urls": list(result.credential_form_urls),
    }


async def send_and_wait(request: ChatNodeRequest) -> dict[str, Any]:
    """Send the message and return the reply once the turn ends."""
    prepared = await _prepare(request)
    result = await _run_turn(request, prepared)
    return build_chat_output(result, temporary=request.temporary)


async def _run_in_background(request: ChatNodeRequest, prepared: _PreparedTurn) -> None:
    try:
        await _run_turn(request, prepared)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Heym node chat turn failed in the background (conversation %s)",
            prepared.conversation_id,
        )


async def send_in_background(request: ChatNodeRequest) -> dict[str, Any]:
    """Start the turn and return as soon as the conversation has accepted it."""
    prepared = await _prepare(request)
    with chat_turn_depth_scope(request.depth):
        task = asyncio.create_task(_run_in_background(request, prepared))
    _background_turns.add(task)
    task.add_done_callback(_background_turns.discard)
    return {
        "conversation_id": None if request.temporary else str(prepared.conversation_id),
        "status": "started",
    }
