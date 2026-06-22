from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
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
    """Background coroutine: streams assistant reply, writes to queue, persists to DB."""
    if not await registry.has_task(conv_id):
        return

    # Declared up front so the cancellation handler can persist whatever streamed so far.
    assistant_chunks: list[str] = []
    workflow_context_markers: list[str] = []
    tool_calls_for_message: list[dict] = []

    async with async_session_maker() as db:
        try:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user is None:
                await registry.publish(conv_id, {"type": "error", "text": "User not found"})
                await registry.finish(conv_id)
                return

            credential = await get_accessible_credential(db, credential_id, user_id)
            if credential is None:
                await registry.publish(conv_id, {"type": "error", "text": "Credential not found"})
                await registry.finish(conv_id)
                return

            config = decrypt_config(credential.encrypted_config)
            client, provider = get_openai_client(credential.type, config)

            attachment = (
                FileAttachment(
                    name=attachment_data["name"],
                    kind=attachment_data["kind"],
                    content=attachment_data["content"],
                )
                if attachment_data
                else None
            )

            msg_result = await db.execute(
                select(DashboardMessage)
                .where(DashboardMessage.conversation_id == uuid.UUID(conv_id))
                .order_by(DashboardMessage.created_at)
            )
            all_messages = msg_result.scalars().all()
            history = [{"role": m.role, "content": m.content} for m in all_messages]
            if len(history) > MAX_DASHBOARD_CHAT_HISTORY:
                history = history[-MAX_DASHBOARD_CHAT_HISTORY:]

            messages = list(history)

            trace_context = LLMTraceContext(
                user_id=user_id,
                credential_id=credential.id,
                workflow_id=None,
                node_label="Dashboard Chat",
                source="dashboard_chat",
            )
            parts = await _assemble_system_prompt_parts(
                user, db, include_attachment_instructions=attachment_data is not None
            )
            system_prompt = parts.full_system_prompt

            cancel_event = Event()
            _cancel_events[conv_id] = cancel_event
            workflow_note_ids: set[str] = set()

            async for chunk in stream_dashboard_chat(
                client,
                model,
                system_prompt,
                messages,
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
                await registry.publish(conv_id, chunk)

            assistant_content = "".join(assistant_chunks)
            for marker in workflow_context_markers:
                if marker and marker not in assistant_content:
                    assistant_content += marker
            # A cancelled run can return before a tool's `tool_end` is emitted,
            # leaving its tool_call stuck in "running". Normalize so reloads don't
            # show a perpetual spinner.
            for entry in tool_calls_for_message:
                if entry.get("status") == "running":
                    entry["status"] = "cancelled"
                    if not entry.get("response_summary"):
                        entry["response_summary"] = "Cancelled"
            if assistant_content or tool_calls_for_message:
                db.add(
                    DashboardMessage(
                        conversation_id=uuid.UUID(conv_id),
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls_for_message or None,
                    )
                )

            conv_result = await db.execute(
                select(DashboardConversation).where(DashboardConversation.id == uuid.UUID(conv_id))
            )
            conversation = conv_result.scalar_one_or_none()
            if conversation is not None:
                conversation.is_running = False
                # Subscriber count isn't tracked across workers under the
                # Postgres-backed registry. Mark as unread so the conversation
                # list reflects the new message; the frontend's
                # markConversationRead path clears this immediately when the
                # user is viewing the conversation.
                conversation.has_unread = True
                if should_generate_title and conversation.title == DEFAULT_CONVERSATION_TITLE:
                    conversation.title = _fallback_title_from_content(content)
                    await registry.publish(
                        conv_id,
                        f"data: {json.dumps({'type': 'title', 'title': conversation.title})}\n\n",
                    )
            await db.commit()
            await registry.finish(conv_id)

        except asyncio.CancelledError:
            # The user pressed Stop: an in-flight LLM/tool await was interrupted.
            # Persist whatever streamed so far (with any unfinished tool marked
            # cancelled), clear is_running, and end the stream cleanly. Use a fresh
            # session since the active one may be in a broken state after cancellation.
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
                            conversation_id=uuid.UUID(conv_id),
                            role="assistant",
                            content=assistant_content,
                            tool_calls=tool_calls_for_message or None,
                        )
                    )
                await cancel_db.execute(
                    sa.text("UPDATE dashboard_conversations SET is_running = false WHERE id = :id"),
                    {"id": conv_id},
                )
                await cancel_db.commit()
            await registry.publish(conv_id, f"data: {json.dumps({'type': 'done'})}\n\n")
            await registry.finish(conv_id)
            return

        except Exception:
            logger.exception("Background chat task failed for conv_id=%s", conv_id)
            async with async_session_maker() as err_db:
                await err_db.execute(
                    sa.text("UPDATE dashboard_conversations SET is_running = false WHERE id = :id"),
                    {"id": conv_id},
                )
                await err_db.commit()
            await registry.publish(
                conv_id, f"data: {json.dumps({'type': 'error', 'text': 'Processing failed'})}\n\n"
            )
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
        .options(selectinload(DashboardConversation.messages))
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    sorted_messages = sorted(conversation.messages, key=lambda m: m.created_at)
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
    """Signal the in-progress background chat task to stop at the next tool boundary."""
    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    request_chat_cancel(str(conversation_id))
    if conversation.is_running:
        conversation.is_running = False
        await db.commit()


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
    """Accept a user message, launch background task, return 202."""
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

    db.add(
        DashboardMessage(
            conversation_id=conversation_id,
            role="user",
            content=user_message["content"],
        )
    )
    conversation.is_running = True
    conversation.has_unread = False
    conversation.last_credential_id = credential.id
    conversation.last_model = body.model
    await db.commit()

    should_generate_title = (
        len(existing_messages) == 0 and conversation.title == DEFAULT_CONVERSATION_TITLE
    )
    conv_id_str = str(conversation_id)
    await registry.create_task(conv_id_str)
    public_base_url = build_public_base_url(http_request)

    task = asyncio.create_task(
        _process_chat(
            conv_id=conv_id_str,
            user_id=current_user.id,
            content=body.content,
            credential_id=credential.id,
            model=body.model,
            attachment_data=body.attachment.model_dump() if body.attachment else None,
            public_base_url=public_base_url,
            should_generate_title=should_generate_title,
        )
    )
    _chat_tasks[conv_id_str] = task

    return SendMessageResponse(conversation_id=conversation_id)


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
