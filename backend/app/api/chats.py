from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.ai_assistant import (
    _ATTACHMENT_ROUTING_INSTRUCTIONS,
    DASHBOARD_CHAT_SYSTEM_PROMPT,
    MAX_DASHBOARD_CHAT_HISTORY,
    FileAttachment,
    _build_user_message,
    _format_workflows_for_prompt,
    _load_agents_md_content,
    get_openai_client,
    get_workflows_for_user_with_inputs,
    stream_dashboard_chat,
)
from app.api.deps import get_current_user, get_current_user_id, get_db
from app.db.models import (
    CredentialType,
    DashboardChatQueueItem,
    DashboardChatQuickPrompts,
    DashboardConversation,
    DashboardMessage,
    User,
)
from app.db.session import async_session_maker
from app.models.chat_schemas import (
    ContextSummaryResponse,
    ConversationCreate,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationTitleGenerate,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
    QueuedMessageResponse,
    QueuedMessageUpdate,
    QuickPromptsResponse,
    QuickPromptsUpdate,
    SendMessageResponse,
)
from app.services import chat_task_registry as registry
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.hitl_service import build_public_base_url
from app.services.llm_trace import LLMTraceContext

router = APIRouter()
logger = logging.getLogger(__name__)

DEFAULT_CONVERSATION_TITLE = "New Chat"
DEFAULT_QUICK_PROMPTS: list[str] = [
    "List my workflows",
    "Show recent runs",
    "Show analytics today",
    "What's on my schedule?",
    "Run a workflow",
    "Show my teams",
    "Create a workflow",
]
MAX_QUICK_PROMPTS = 7
MAX_PROMPT_LENGTH = 200
CHAT_STREAM_HEARTBEAT_SECONDS = 10.0
CLARIFY_FENCE = "```heym-clarify"


@dataclass(frozen=True)
class ChatTurn:
    content: str
    credential_id: uuid.UUID
    model: str
    attachment_data: dict | None
    should_generate_title: bool


@dataclass(frozen=True)
class ChatTurnResult:
    paused_for_clarification: bool
    assistant_message_id: uuid.UUID
    stop_worker: bool = False


def _build_hidden_workflow_context_marker(workflow_id: str, workflow_name: str) -> str:
    safe_name = workflow_name.replace("--", "").strip()
    return f"\n<!-- heym-workflow-id:{workflow_id} heym-workflow-name:{safe_name} -->"


def _ingest_tool_event(tool_calls_for_message: list[dict], payload: dict) -> None:
    """Update tool_calls_for_message in place from a parsed SSE payload."""
    ptype = payload.get("type")
    if ptype == "tool_start":
        tool_calls_for_message.append(
            {
                "id": str(payload.get("id") or ""),
                "name": str(payload.get("name") or ""),
                "label": str(payload.get("label") or ""),
                "args": payload.get("args") or {},
                "status": "running",
            }
        )
    elif ptype == "tool_end":
        tc_id = str(payload.get("id") or "")
        for entry in tool_calls_for_message:
            if entry.get("id") == tc_id:
                entry["response_summary"] = str(payload.get("response_summary") or "")
                entry["elapsed_ms"] = payload.get("elapsed_ms")
                entry["status"] = str(payload.get("status") or "success")
                break
    elif ptype == "compressed":
        tokens_before = int(payload.get("tokens_before") or 0)
        tokens_after = int(payload.get("tokens_after") or 0)
        tool_calls_for_message.append(
            {
                "id": f"cmp_{len(tool_calls_for_message)}",
                "name": "_context_compression",
                "label": "Context compressed",
                "args": {"messages_compressed": int(payload.get("messages_compressed") or 0)},
                "response_summary": (
                    f"~{tokens_before // 1000}k → ~{tokens_after // 1000}k tokens"
                ),
                "elapsed_ms": payload.get("elapsed_ms"),
                "status": "compressed",
            }
        )


def _queued_message_response(item: DashboardChatQueueItem) -> QueuedMessageResponse:
    attachment = item.attachment if isinstance(item.attachment, dict) else None
    attachment_name = attachment.get("name") if attachment else None
    return QueuedMessageResponse(
        id=item.id,
        content=item.content,
        credential_id=item.credential_id,
        model=item.model,
        attachment_name=str(attachment_name) if attachment_name else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _message_response(message: DashboardMessage) -> MessageResponse:
    return MessageResponse.model_validate(message)


def _has_clarify_block(content: str) -> bool:
    return CLARIFY_FENCE in content


async def _publish_payload_with_message_id(
    conv_id: str,
    chunk: str,
    assistant_message_id: uuid.UUID,
) -> None:
    if not chunk.startswith("data: "):
        await registry.publish(conv_id, chunk)
        return
    try:
        payload = json.loads(chunk[6:].strip())
    except json.JSONDecodeError:
        await registry.publish(conv_id, chunk)
        return
    if payload.get("type") == "done":
        return
    payload["message_id"] = str(assistant_message_id)
    await registry.publish(conv_id, payload)


async def _clear_queue_items(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> None:
    await db.execute(
        delete(DashboardChatQueueItem).where(
            DashboardChatQueueItem.conversation_id == conversation_id
        )
    )


@dataclass(frozen=True)
class SystemPromptParts:
    full_system_prompt: str
    base_system_prompt: str
    agents_md: str
    workflows_block: str
    user_rules: str


async def _assemble_system_prompt_parts(
    user: User,
    db: AsyncSession,
    *,
    include_attachment_instructions: bool,
) -> SystemPromptParts:
    workflows = await get_workflows_for_user_with_inputs(db, user.id)
    workflows_block = _format_workflows_for_prompt(workflows)
    agents_md = _load_agents_md_content() or ""
    user_rules = (user.user_rules or "").strip()

    system_prompt = DASHBOARD_CHAT_SYSTEM_PROMPT
    if agents_md:
        system_prompt = (
            "## Heym Platform Context\n\n"
            "Use the following Heym platform documentation to answer questions about the platform, structure, commands, code style, and conventions:\n\n"
            + agents_md
            + "\n\n---\n\n"
            + system_prompt
        )
    if workflows_block:
        system_prompt = (
            system_prompt
            + "\n\nAvailable workflows (always check these first when user asks for information):\n"
            + workflows_block
        )
    if user_rules:
        system_prompt = (
            system_prompt
            + "\n\nUser preferences / custom instructions (follow these when relevant):\n"
            + user_rules
        )
    if include_attachment_instructions:
        system_prompt = system_prompt + "\n\n" + _ATTACHMENT_ROUTING_INSTRUCTIONS

    return SystemPromptParts(
        full_system_prompt=system_prompt,
        base_system_prompt=DASHBOARD_CHAT_SYSTEM_PROMPT,
        agents_md=agents_md,
        workflows_block=workflows_block,
        user_rules=user_rules,
    )


async def _get_conversation_or_404(
    conversation_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> DashboardConversation:
    result = await db.execute(
        select(DashboardConversation).where(
            DashboardConversation.id == conversation_id,
            DashboardConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


# Maps an in-progress conversation id to the cancel Event and asyncio task of its
# background chat coroutine. In-process only: works for the single-worker dev/self-host
# setup. A multi-worker deployment would need to broadcast the cancel via the
# Postgres-backed registry.
_cancel_events: dict[str, Event] = {}
_chat_tasks: dict[str, "asyncio.Task[None]"] = {}


def request_chat_cancel(conv_id: str) -> bool:
    """Stop a running background chat task immediately. Returns True if one was found.

    Sets the cooperative cancel Event (checked at tool boundaries) AND cancels the
    asyncio task so an in-flight LLM/tool `await` is interrupted right away instead of
    finishing the current request first.
    """
    found = False
    event = _cancel_events.get(conv_id)
    if event is not None:
        event.set()
        found = True
    task = _chat_tasks.get(conv_id)
    if task is not None and not task.done():
        task.cancel()
        found = True
    return found


async def _run_chat_turn(
    conv_id: str,
    user_id: uuid.UUID,
    turn: ChatTurn,
    public_base_url: str,
) -> ChatTurnResult:
    """Stream and persist one assistant turn for a conversation worker."""
    conv_uuid = uuid.UUID(conv_id)
    assistant_message_id = uuid.uuid4()
    assistant_chunks: list[str] = []
    workflow_context_markers: list[str] = []
    tool_calls_for_message: list[dict] = []

    try:
        async with async_session_maker() as db:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user is None:
                await registry.publish(conv_id, {"type": "error", "text": "User not found"})
                return ChatTurnResult(False, assistant_message_id, stop_worker=True)

            credential = await get_accessible_credential(db, turn.credential_id, user_id)
            if credential is None:
                await registry.publish(conv_id, {"type": "error", "text": "Credential not found"})
                return ChatTurnResult(False, assistant_message_id, stop_worker=True)

            config = decrypt_config(credential.encrypted_config)
            client, provider = get_openai_client(credential.type, config)

            attachment = (
                FileAttachment(
                    name=turn.attachment_data["name"],
                    kind=turn.attachment_data["kind"],
                    content=turn.attachment_data["content"],
                )
                if turn.attachment_data
                else None
            )

            msg_result = await db.execute(
                select(DashboardMessage)
                .where(DashboardMessage.conversation_id == conv_uuid)
                .order_by(DashboardMessage.created_at)
            )
            all_messages = msg_result.scalars().all()
            history = [{"role": m.role, "content": m.content} for m in all_messages]
            if len(history) > MAX_DASHBOARD_CHAT_HISTORY:
                history = history[-MAX_DASHBOARD_CHAT_HISTORY:]

            trace_context = LLMTraceContext(
                user_id=user_id,
                credential_id=credential.id,
                workflow_id=None,
                node_label="Dashboard Chat",
                source="dashboard_chat",
            )
            parts = await _assemble_system_prompt_parts(
                user, db, include_attachment_instructions=turn.attachment_data is not None
            )

            cancel_event = _cancel_events.get(conv_id)
            if cancel_event is None:
                cancel_event = Event()
                _cancel_events[conv_id] = cancel_event
            workflow_note_ids: set[str] = set()

            async for chunk in stream_dashboard_chat(
                client,
                turn.model,
                parts.full_system_prompt,
                list(history),
                db,
                user,
                provider,
                public_base_url,
                trace_context,
                cancel_event,
                attachment,
                credential,
                system_prompt_parts=parts,
            ):
                if chunk.startswith("data: "):
                    try:
                        payload = json.loads(chunk[6:].strip())
                    except json.JSONDecodeError:
                        payload = {}
                    ptype = payload.get("type")
                    if ptype == "content":
                        assistant_chunks.append(str(payload.get("text") or ""))
                    elif ptype == "workflow_created":
                        w_id = str(payload.get("workflow_id") or "").strip()
                        w_name = str(payload.get("workflow_name") or "").strip()
                        if w_id and w_id not in workflow_note_ids:
                            workflow_note_ids.add(w_id)
                            workflow_context_markers.append(
                                _build_hidden_workflow_context_marker(w_id, w_name or "Workflow")
                            )
                    elif ptype in ("tool_start", "tool_end", "compressed"):
                        _ingest_tool_event(tool_calls_for_message, payload)
                await _publish_payload_with_message_id(conv_id, chunk, assistant_message_id)

            assistant_content = "".join(assistant_chunks)
            for marker in workflow_context_markers:
                if marker and marker not in assistant_content:
                    assistant_content += marker

            paused_for_clarification = _has_clarify_block(assistant_content)
            if assistant_content or tool_calls_for_message:
                db.add(
                    DashboardMessage(
                        id=assistant_message_id,
                        conversation_id=conv_uuid,
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls_for_message or None,
                    )
                )

            conv_result = await db.execute(
                select(DashboardConversation).where(DashboardConversation.id == conv_uuid)
            )
            conversation = conv_result.scalar_one_or_none()
            if conversation is not None:
                conversation.has_unread = True
                if paused_for_clarification:
                    conversation.is_running = False
                    conversation.queue_paused_by_message_id = assistant_message_id
                if turn.should_generate_title and conversation.title == DEFAULT_CONVERSATION_TITLE:
                    conversation.title = _fallback_title_from_content(turn.content)
                    await registry.publish(
                        conv_id,
                        {"type": "title", "title": conversation.title},
                    )
            await db.commit()
            await registry.publish(
                conv_id,
                {
                    "type": "assistant_done",
                    "message_id": str(assistant_message_id),
                    "paused_for_clarification": paused_for_clarification,
                },
            )
            return ChatTurnResult(paused_for_clarification, assistant_message_id)

    except asyncio.CancelledError:
        assistant_content = "".join(assistant_chunks)
        for marker in workflow_context_markers:
            if marker and marker not in assistant_content:
                assistant_content += marker
        for entry in tool_calls_for_message:
            if entry.get("status") == "running":
                entry["status"] = "cancelled"
                if not entry.get("response_summary"):
                    entry["response_summary"] = "Cancelled"
        async with async_session_maker() as cancel_db:
            if assistant_content or tool_calls_for_message:
                cancel_db.add(
                    DashboardMessage(
                        id=assistant_message_id,
                        conversation_id=conv_uuid,
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls_for_message or None,
                    )
                )
            conv_result = await cancel_db.execute(
                select(DashboardConversation).where(DashboardConversation.id == conv_uuid)
            )
            conversation = conv_result.scalar_one_or_none()
            if conversation is not None:
                conversation.is_running = False
                conversation.queue_paused_by_message_id = None
            await _clear_queue_items(cancel_db, conv_uuid)
            await cancel_db.commit()
        await registry.publish(conv_id, {"type": "queue_cleared"})
        await registry.publish(
            conv_id,
            {
                "type": "assistant_done",
                "message_id": str(assistant_message_id),
                "cancelled": True,
            },
        )
        raise


async def _dequeue_next_turn(conv_id: str) -> ChatTurn | None:
    conv_uuid = uuid.UUID(conv_id)
    async with async_session_maker() as db:
        conv_result = await db.execute(
            select(DashboardConversation).where(DashboardConversation.id == conv_uuid)
        )
        conversation = conv_result.scalar_one_or_none()
        if conversation is None:
            return None
        if conversation.queue_paused_by_message_id is not None:
            conversation.is_running = False
            await db.commit()
            return None

        item_result = await db.execute(
            select(DashboardChatQueueItem)
            .where(DashboardChatQueueItem.conversation_id == conv_uuid)
            .order_by(DashboardChatQueueItem.created_at, DashboardChatQueueItem.id)
            .limit(1)
        )
        item = item_result.scalar_one_or_none()
        if item is None:
            conversation.is_running = False
            await db.commit()
            return None

        attachment = (
            FileAttachment(
                name=item.attachment["name"],
                kind=item.attachment["kind"],
                content=item.attachment["content"],
            )
            if isinstance(item.attachment, dict)
            else None
        )
        user_message_data = _build_user_message(item.content, attachment)
        message_created_at = datetime.now(timezone.utc)
        user_message = DashboardMessage(
            id=uuid.uuid4(),
            conversation_id=conv_uuid,
            role="user",
            content=user_message_data["content"],
            created_at=message_created_at,
        )
        db.add(user_message)
        await db.flush()
        turn = ChatTurn(
            content=item.content,
            credential_id=item.credential_id,
            model=item.model,
            attachment_data=dict(item.attachment) if isinstance(item.attachment, dict) else None,
            should_generate_title=False,
        )
        queued_item_id = item.id
        await db.delete(item)
        conversation.has_unread = False
        conversation.last_credential_id = turn.credential_id
        conversation.last_model = turn.model
        await db.commit()
        await db.refresh(user_message)

    await registry.publish(
        conv_id,
        {
            "type": "queued_message_started",
            "queued_message_id": str(queued_item_id),
            "user_message": _message_response(user_message).model_dump(mode="json"),
        },
    )
    return turn


async def _finish_worker_state(conv_id: str) -> None:
    async with async_session_maker() as db:
        conv_uuid = uuid.UUID(conv_id)
        result = await db.execute(
            select(DashboardConversation).where(DashboardConversation.id == conv_uuid)
        )
        conversation = result.scalar_one_or_none()
        if conversation is not None and conversation.queue_paused_by_message_id is None:
            conversation.is_running = False
        await db.commit()


async def _process_chat(
    conv_id: str,
    user_id: uuid.UUID,
    content: str,
    credential_id: uuid.UUID,
    model: str,
    attachment_data: dict | None,
    public_base_url: str,
    should_generate_title: bool,
) -> None:
    """Background coroutine: streams assistant replies and drains queued messages."""
    if not await registry.has_task(conv_id):
        return

    _cancel_events[conv_id] = Event()
    turn: ChatTurn | None = ChatTurn(
        content=content,
        credential_id=credential_id,
        model=model,
        attachment_data=attachment_data,
        should_generate_title=should_generate_title,
    )

    try:
        while turn is not None:
            result = await _run_chat_turn(conv_id, user_id, turn, public_base_url)
            if result.stop_worker or result.paused_for_clarification:
                break
            turn = await _dequeue_next_turn(conv_id)
        await _finish_worker_state(conv_id)
        await registry.finish(conv_id)
    except asyncio.CancelledError:
        await registry.finish(conv_id)
        return
    except Exception:
        logger.exception("Background chat task failed for conv_id=%s", conv_id)
        async with async_session_maker() as err_db:
            conv_uuid = uuid.UUID(conv_id)
            await err_db.execute(
                sa.text(
                    "UPDATE dashboard_conversations "
                    "SET is_running = false WHERE id = CAST(:id AS uuid)"
                ),
                {"id": conv_id},
            )
            await _clear_queue_items(err_db, conv_uuid)
            await err_db.commit()
        await registry.publish(
            conv_id, f"data: {json.dumps({'type': 'error', 'text': 'Processing failed'})}\n\n"
        )
        await registry.publish(conv_id, {"type": "queue_cleared"})
        await registry.finish(conv_id)
    finally:
        _cancel_events.pop(conv_id, None)
        _chat_tasks.pop(conv_id, None)


async def _process_chat_queue(
    conv_id: str,
    user_id: uuid.UUID,
    public_base_url: str,
) -> None:
    """Background coroutine: starts from the persisted queue and drains it."""
    if not await registry.has_task(conv_id):
        return

    _cancel_events[conv_id] = Event()
    try:
        turn = await _dequeue_next_turn(conv_id)
        while turn is not None:
            result = await _run_chat_turn(conv_id, user_id, turn, public_base_url)
            if result.stop_worker or result.paused_for_clarification:
                break
            turn = await _dequeue_next_turn(conv_id)
        await _finish_worker_state(conv_id)
        await registry.finish(conv_id)
    except asyncio.CancelledError:
        await registry.finish(conv_id)
        return
    except Exception:
        logger.exception("Background queued chat task failed for conv_id=%s", conv_id)
        async with async_session_maker() as err_db:
            conv_uuid = uuid.UUID(conv_id)
            await err_db.execute(
                sa.text(
                    "UPDATE dashboard_conversations "
                    "SET is_running = false WHERE id = CAST(:id AS uuid)"
                ),
                {"id": conv_id},
            )
            await _clear_queue_items(err_db, conv_uuid)
            await err_db.commit()
        await registry.publish(
            conv_id, f"data: {json.dumps({'type': 'error', 'text': 'Processing failed'})}\n\n"
        )
        await registry.publish(conv_id, {"type": "queue_cleared"})
        await registry.finish(conv_id)
    finally:
        _cancel_events.pop(conv_id, None)
        _chat_tasks.pop(conv_id, None)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    """List all conversations for the current user, pinned first then newest."""
    result = await db.execute(
        select(DashboardConversation)
        .where(DashboardConversation.user_id == current_user.id)
        .order_by(
            DashboardConversation.is_pinned.desc(),
            DashboardConversation.updated_at.desc(),
        )
    )
    conversations = result.scalars().all()
    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(c) for c in conversations]
    )


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Create a new conversation."""
    conversation = DashboardConversation(
        user_id=current_user.id,
        title=body.title or DEFAULT_CONVERSATION_TITLE,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all conversations for the current user."""
    await db.execute(
        delete(DashboardConversation).where(DashboardConversation.user_id == current_user.id)
    )
    await db.commit()


@router.get("/quick-prompts", response_model=QuickPromptsResponse)
async def get_quick_prompts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickPromptsResponse:
    """Return the current user's quick prompts, or defaults if none saved."""
    result = await db.execute(
        select(DashboardChatQuickPrompts).where(
            DashboardChatQuickPrompts.user_id == current_user.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return QuickPromptsResponse(prompts=DEFAULT_QUICK_PROMPTS)
    return QuickPromptsResponse(prompts=list(row.prompts))


@router.put("/quick-prompts", response_model=QuickPromptsResponse)
async def save_quick_prompts(
    body: QuickPromptsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickPromptsResponse:
    """Replace the current user's quick prompts list (max 7 items)."""
    cleaned = [p.strip() for p in body.prompts if p.strip()]
    if len(cleaned) > MAX_QUICK_PROMPTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Maximum {MAX_QUICK_PROMPTS} prompts allowed",
        )
    for p in cleaned:
        if len(p) > MAX_PROMPT_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Each prompt must be at most {MAX_PROMPT_LENGTH} characters",
            )

    result = await db.execute(
        select(DashboardChatQuickPrompts).where(
            DashboardChatQuickPrompts.user_id == current_user.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        db.add(DashboardChatQuickPrompts(user_id=current_user.id, prompts=cleaned))
    else:
        row.prompts = cleaned
    await db.commit()
    return QuickPromptsResponse(prompts=cleaned)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    """Get a conversation with all its messages."""
    result = await db.execute(
        select(DashboardConversation)
        .where(
            DashboardConversation.id == conversation_id,
            DashboardConversation.user_id == current_user.id,
        )
        .options(
            selectinload(DashboardConversation.messages),
            selectinload(DashboardConversation.queue_items),
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    sorted_messages = sorted(conversation.messages, key=lambda m: m.created_at)
    sorted_queue = sorted(conversation.queue_items, key=lambda item: (item.created_at, item.id))
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        is_pinned=conversation.is_pinned,
        is_running=conversation.is_running,
        has_unread=conversation.has_unread,
        last_credential_id=conversation.last_credential_id,
        last_model=conversation.last_model,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(m) for m in sorted_messages],
        queued_messages=[_queued_message_response(item) for item in sorted_queue],
    )


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Rename a conversation and/or toggle its pin state."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    if body.title is not None:
        conversation.title = body.title
    if body.is_pinned is not None:
        conversation.is_pinned = body.is_pinned
    await db.commit()
    await db.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    await db.delete(conversation)
    await db.commit()


def _fallback_title_from_content(content: str) -> str:
    cleaned = " ".join(content.replace("\n", " ").split())
    cleaned = cleaned.split("[ATTACHED", maxsplit=1)[0].strip()
    if not cleaned:
        return DEFAULT_CONVERSATION_TITLE
    title_source = cleaned.strip("\"'`“”‘’")
    if len(title_source) > 50:
        word_boundary = title_source.find(" ", 50)
        title_source = title_source[: word_boundary if word_boundary != -1 else 50]
    title = title_source.rstrip(".,:;!?")
    return f"{title}..." if title else DEFAULT_CONVERSATION_TITLE


@router.post("/{conversation_id}/title", response_model=ConversationResponse)
async def generate_conversation_title(
    conversation_id: uuid.UUID,
    body: ConversationTitleGenerate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Generate a deterministic title for a new conversation."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    if conversation.title != DEFAULT_CONVERSATION_TITLE:
        return ConversationResponse.model_validate(conversation)

    msg_result = await db.execute(
        select(DashboardMessage)
        .where(DashboardMessage.conversation_id == conversation_id)
        .order_by(DashboardMessage.created_at)
    )
    messages = msg_result.scalars().all()
    user_message = next((m for m in messages if m.role == "user" and m.content.strip()), None)
    if user_message is None:
        return ConversationResponse.model_validate(conversation)
    title = _fallback_title_from_content(user_message.content)
    if title is not None and conversation.title == DEFAULT_CONVERSATION_TITLE:
        conversation.title = title
        await db.commit()
        await db.refresh(conversation)

    return ConversationResponse.model_validate(conversation)


@router.post("/{conversation_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_conversation_stream(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Signal the in-progress background chat task to stop and clear queued messages."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    request_chat_cancel(str(conversation_id))
    await _clear_queue_items(db, conversation_id)
    if conversation.is_running:
        conversation.is_running = False
    await db.commit()
    await registry.publish(str(conversation_id), {"type": "queue_cleared"})


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    http_request: Request,
    conversation_id: uuid.UUID,
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SendMessageResponse:
    """Accept a user message, launch a worker or persist it in the queue."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)

    msg_result = await db.execute(
        select(DashboardMessage)
        .where(DashboardMessage.conversation_id == conversation_id)
        .order_by(DashboardMessage.created_at)
    )
    existing_messages = msg_result.scalars().all()

    credential = await get_accessible_credential(db, uuid.UUID(body.credential_id), current_user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    attachment_data = body.attachment.model_dump() if body.attachment else None
    conv_id_str = str(conversation_id)
    if conversation.is_running:
        queued_at = datetime.now(timezone.utc)
        queue_item = DashboardChatQueueItem(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            content=body.content,
            credential_id=credential.id,
            model=body.model,
            attachment=attachment_data,
            created_at=queued_at,
            updated_at=queued_at,
        )
        db.add(queue_item)
        conversation.has_unread = False
        conversation.last_credential_id = credential.id
        conversation.last_model = body.model
        await db.commit()
        await db.refresh(queue_item)
        await db.refresh(conversation)
        queued_response = _queued_message_response(queue_item)
        if conversation.is_running:
            await registry.publish(
                conv_id_str,
                {
                    "type": "queued_message_created",
                    "queued_message": queued_response.model_dump(mode="json"),
                },
            )
        else:
            conversation.is_running = True
            await db.commit()
            await registry.create_task(conv_id_str)
            task = asyncio.create_task(
                _process_chat_queue(
                    conv_id=conv_id_str,
                    user_id=current_user.id,
                    public_base_url=build_public_base_url(http_request),
                )
            )
            _chat_tasks[conv_id_str] = task
        return SendMessageResponse(
            conversation_id=conversation_id,
            status="queued",
            queued_message=queued_response,
        )

    attachment = (
        FileAttachment(
            name=body.attachment.name,
            kind=body.attachment.kind,
            content=body.attachment.content,
        )
        if body.attachment
        else None
    )
    user_message = _build_user_message(body.content, attachment)
    message_created_at = datetime.now(timezone.utc)
    message = DashboardMessage(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role="user",
        content=user_message["content"],
        created_at=message_created_at,
    )
    db.add(message)
    conversation.is_running = True
    conversation.has_unread = False
    conversation.queue_paused_by_message_id = None
    conversation.last_credential_id = credential.id
    conversation.last_model = body.model
    await db.commit()
    await db.refresh(message)

    should_generate_title = (
        len(existing_messages) == 0 and conversation.title == DEFAULT_CONVERSATION_TITLE
    )
    await registry.create_task(conv_id_str)
    public_base_url = build_public_base_url(http_request)

    task = asyncio.create_task(
        _process_chat(
            conv_id=conv_id_str,
            user_id=current_user.id,
            content=body.content,
            credential_id=credential.id,
            model=body.model,
            attachment_data=attachment_data,
            public_base_url=public_base_url,
            should_generate_title=should_generate_title,
        )
    )
    _chat_tasks[conv_id_str] = task

    return SendMessageResponse(
        conversation_id=conversation_id,
        status="started",
        user_message=_message_response(message),
    )


async def _get_queue_item_or_404(
    conversation_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> DashboardChatQueueItem:
    result = await db.execute(
        select(DashboardChatQueueItem)
        .join(
            DashboardConversation,
            DashboardChatQueueItem.conversation_id == DashboardConversation.id,
        )
        .where(
            DashboardChatQueueItem.id == item_id,
            DashboardChatQueueItem.conversation_id == conversation_id,
            DashboardConversation.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Queued message not found"
        )
    return item


@router.patch(
    "/{conversation_id}/queue/{item_id}",
    response_model=QueuedMessageResponse,
)
async def update_queued_message(
    conversation_id: uuid.UUID,
    item_id: uuid.UUID,
    body: QueuedMessageUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QueuedMessageResponse:
    """Update a queued message before it starts running."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    item = await _get_queue_item_or_404(conversation_id, item_id, current_user.id, db)
    cleaned = body.content.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Queued message content cannot be empty",
        )
    item.content = cleaned
    await db.commit()
    await db.refresh(item)
    response = _queued_message_response(item)
    if conversation.is_running:
        await registry.publish(
            str(conversation_id),
            {
                "type": "queued_message_updated",
                "queued_message": response.model_dump(mode="json"),
            },
        )
    return response


@router.delete("/{conversation_id}/queue/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queued_message(
    conversation_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a queued message before it starts running."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    item = await _get_queue_item_or_404(conversation_id, item_id, current_user.id, db)
    await db.delete(item)
    await db.commit()
    if conversation.is_running:
        await registry.publish(
            str(conversation_id),
            {"type": "queued_message_deleted", "queued_message_id": str(item_id)},
        )


@router.get("/{conversation_id}/stream")
async def stream_conversation(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> StreamingResponse:
    """SSE endpoint: subscribe to in-progress or already-finished background task.

    Auth and the pre-stream check run in a short-lived session that is released before
    streaming starts, so a long-lived SSE response never pins a DB connection.
    """
    conv_id_str = str(conversation_id)
    async with async_session_maker() as db:
        conversation = await _get_conversation_or_404(conversation_id, user_id, db)
        if conversation.is_running and not await registry.has_task(conv_id_str):
            conversation.is_running = False
            await db.commit()

    async def event_generator() -> AsyncGenerator[str, None]:
        async with registry.subscribe(conv_id_str) as queue:
            if queue is None:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=CHAT_STREAM_HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                if isinstance(item, str):
                    yield item
                else:
                    yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_conversation_read(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the has_unread flag for a conversation."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    conversation.has_unread = False
    await db.commit()


@router.get("/{conversation_id}/context-summary", response_model=ContextSummaryResponse)
async def get_context_summary(
    conversation_id: uuid.UUID,
    credential_id: uuid.UUID,
    model: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextSummaryResponse:
    """Compute the static (idle-state) context usage for a conversation."""
    from app.api.ai_assistant import _context_breakdown
    from app.services.context_compressor import get_context_limit

    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    msg_result = await db.execute(
        select(DashboardMessage)
        .where(DashboardMessage.conversation_id == conversation.id)
        .order_by(DashboardMessage.created_at)
    )
    all_messages = msg_result.scalars().all()
    history = [{"role": m.role, "content": m.content} for m in all_messages]
    if len(history) > MAX_DASHBOARD_CHAT_HISTORY:
        history = history[-MAX_DASHBOARD_CHAT_HISTORY:]

    credential = await get_accessible_credential(db, credential_id, current_user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    config = decrypt_config(credential.encrypted_config)
    client, _provider = get_openai_client(credential.type, config)

    parts = await _assemble_system_prompt_parts(
        current_user, db, include_attachment_instructions=False
    )
    breakdown = _context_breakdown(
        base_system_prompt=parts.base_system_prompt,
        agents_md=parts.agents_md,
        workflows_block=parts.workflows_block,
        user_rules=parts.user_rules,
        history=history,
        attachment_content=None,
    )
    used = sum(breakdown.values())
    limit = get_context_limit(model, client)
    return ContextSummaryResponse(used=used, limit=limit, breakdown=breakdown)
