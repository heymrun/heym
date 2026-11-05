"""Pydantic schemas for the agentic kanban board API."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.board_card_fields import normalize_labels

CardPriority = Literal["low", "medium", "high", "urgent"]


class CardFieldsRequest(BaseModel):
    """Typed card fields; a field left out keeps its value, null clears it."""

    assignee_user_id: uuid.UUID | None = None
    priority: CardPriority | None = None
    due_date: date | None = None
    labels: list[str] | None = Field(default=None, max_length=50)

    @field_validator("labels")
    @classmethod
    def _normalize_labels(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_labels(value)


class CardFieldsResponse(BaseModel):
    assignee_user_id: uuid.UUID | None = None
    priority: CardPriority | None = None
    due_date: date | None = None
    labels: list[str] = Field(default_factory=list)


class BoardMemberResponse(BaseModel):
    user_id: uuid.UUID
    name: str | None = None
    email: str
    permission: str


class BoardRevisionResponse(BaseModel):
    revision: str


class BoardColumnWorkflowResponse(BaseModel):
    workflow_id: uuid.UUID
    workflow_name: str
    position: int


class BoardColumnResponse(BaseModel):
    id: uuid.UUID
    board_id: uuid.UUID
    name: str
    position: int
    color: str | None = None
    ai_instructions: str | None = None
    workflows: list[BoardColumnWorkflowResponse] = Field(default_factory=list)


class BoardCardResponse(BaseModel):
    id: uuid.UUID
    board_id: uuid.UUID
    column_id: uuid.UUID
    title: str
    content: str
    position: int
    run_status: str
    card_metadata: dict = Field(default_factory=dict)
    fields: CardFieldsResponse = Field(default_factory=CardFieldsResponse)
    # Fingerprint of title, content and fields; send it back to refuse stale writes.
    edit_version: str = ""
    created_at: datetime
    updated_at: datetime


class BoardSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    column_count: int
    card_count: int
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None
    mapper_credential_name: str | None = None
    # The caller's access: "owner", "write" or "read" (shared boards).
    permission: str = "owner"
    auto_advance: bool = True
    updated_at: datetime


class BoardStateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None
    mapper_credential_name: str | None = None
    permission: str = "owner"
    auto_advance: bool = True
    columns: list[BoardColumnResponse]
    cards: list[BoardCardResponse]
    has_active_runs: bool


class BoardCreateRequest(BaseModel):
    name: str = "Board"
    description: str | None = None
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None
    auto_advance: bool = True


class BoardUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None
    auto_advance: bool | None = None


class ColumnCreateRequest(BaseModel):
    name: str
    position: int | None = None
    color: str | None = None


class ColumnUpdateRequest(BaseModel):
    name: str | None = None
    color: str | None = None
    position: int | None = None
    ai_instructions: str | None = None
    workflow_ids: list[uuid.UUID] | None = None


class CardCreateRequest(CardFieldsRequest):
    title: str
    content: str = ""
    column_id: uuid.UUID | None = None
    position: int | None = None


class CardUpdateRequest(CardFieldsRequest):
    title: str | None = None
    content: str | None = None
    card_metadata: dict | None = None
    position: int | None = None
    # The edit_version the client read; a different current one answers 409.
    expected_edit_version: str | None = None


class CardMoveRequest(BaseModel):
    to_column_id: uuid.UUID
    position: int | None = None


class CommentCreateRequest(BaseModel):
    content: str


class CardActivityResponse(BaseModel):
    id: uuid.UUID
    kind: str
    author_type: str
    author_user_id: uuid.UUID | None = None
    content: str
    data: dict = Field(default_factory=dict)
    run_id: uuid.UUID | None = None
    created_at: datetime


class CardRunResponse(BaseModel):
    id: uuid.UUID
    card_id: uuid.UUID
    column_id: uuid.UUID
    workflow_id: uuid.UUID | None = None
    workflow_name: str
    chain_position: int
    chain_length: int
    status: str
    execution_history_id: uuid.UUID | None = None
    active_execution_id: uuid.UUID | None = None
    output: dict = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class CardDetailResponse(BaseModel):
    card: BoardCardResponse
    activities: list[CardActivityResponse]
    runs: list[CardRunResponse]


class BoardShareRequest(BaseModel):
    email: str
    permission: str = "read"


class BoardShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str | None = None
    permission: str
    shared_at: datetime


class BoardTeamShareRequest(BaseModel):
    team_id: uuid.UUID
    permission: str = "read"


class BoardTeamShareResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    permission: str
    shared_at: datetime


class CardAttachmentResponse(BaseModel):
    file_id: uuid.UUID
    name: str
    url: str
    mime_type: str | None = None
    size: int | None = None
