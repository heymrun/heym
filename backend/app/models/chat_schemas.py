from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class ConversationUpdate(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None


def _coerce_source(value: object) -> object:
    """Treat a missing/NULL source as a Chat tab conversation."""
    return value or "chat"


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    source: str = "chat"
    is_pinned: bool
    is_running: bool
    has_unread: bool
    created_at: datetime
    updated_at: datetime

    _normalize_source = field_validator("source", mode="before")(_coerce_source)

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


ToolCallStatus = Literal[
    "running", "success", "error", "pending", "timeout", "cancelled", "compressed"
]


class ToolCallRecord(BaseModel):
    id: str
    name: str
    label: str
    args: dict[str, Any] = Field(default_factory=dict)
    response_summary: str | None = None
    elapsed_ms: float | None = None
    status: ToolCallStatus


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    tool_calls: list[ToolCallRecord] | None = None

    model_config = {"from_attributes": True}


class QueuedMessageResponse(BaseModel):
    id: uuid.UUID
    content: str
    credential_id: uuid.UUID
    model: str
    attachment_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: uuid.UUID
    title: str
    source: str = "chat"
    is_pinned: bool
    is_running: bool
    has_unread: bool
    last_credential_id: uuid.UUID | None = None
    last_model: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]
    queued_messages: list[QueuedMessageResponse] = Field(default_factory=list)

    _normalize_source = field_validator("source", mode="before")(_coerce_source)

    model_config = {"from_attributes": True}


class ChatFileAttachment(BaseModel):
    name: str
    kind: Literal["text", "image", "pdf", "zip"]
    content: str


class MessageCreate(BaseModel):
    content: str
    credential_id: str
    model: str
    attachment: ChatFileAttachment | None = None
    allow_build: bool = Field(
        default=False,
        description="Chat build mode: the turn may save, test-run and finish workflows.",
    )
    allow_skill_write: bool = Field(
        default=False,
        description=(
            "The turn may create or update an agent skill. It does not enable the rest of "
            "build mode."
        ),
    )
    target_workflow_id: uuid.UUID | None = Field(
        default=None,
        description="The workflow an AI edit changes. Needs allow_build or allow_skill_write.",
    )


class ConversationTitleGenerate(BaseModel):
    credential_id: str
    model: str


class QueuedMessageUpdate(BaseModel):
    content: str = Field(min_length=1)


class SendMessageResponse(BaseModel):
    conversation_id: uuid.UUID
    status: Literal["started", "queued"]
    user_message: MessageResponse | None = None
    queued_message: QueuedMessageResponse | None = None


class QuickPromptsResponse(BaseModel):
    prompts: list[str]


class QuickPromptsUpdate(BaseModel):
    prompts: list[str]


class ContextBreakdown(BaseModel):
    system: int
    agents_md: int
    workflows: int
    user_rules: int
    history: int
    attachment: int


class ContextSummaryResponse(BaseModel):
    used: int
    limit: int
    breakdown: ContextBreakdown
