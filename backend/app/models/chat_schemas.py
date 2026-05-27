from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class ConversationUpdate(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    is_pinned: bool
    is_running: bool
    has_unread: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


class ToolCallRecord(BaseModel):
    id: str
    name: str
    label: str
    args: dict[str, Any] = Field(default_factory=dict)
    response_summary: str | None = None
    elapsed_ms: float | None = None
    status: Literal["running", "success", "error", "compressed"]


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    tool_calls: list[ToolCallRecord] | None = None

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: uuid.UUID
    title: str
    is_pinned: bool
    is_running: bool
    has_unread: bool
    last_credential_id: uuid.UUID | None = None
    last_model: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    model_config = {"from_attributes": True}


class ChatFileAttachment(BaseModel):
    name: str
    kind: Literal["text", "image", "pdf"]
    content: str


class MessageCreate(BaseModel):
    content: str
    credential_id: str
    model: str
    attachment: ChatFileAttachment | None = None


class ConversationTitleGenerate(BaseModel):
    credential_id: str
    model: str


class SendMessageResponse(BaseModel):
    conversation_id: uuid.UUID


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
