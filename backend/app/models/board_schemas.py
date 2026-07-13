"""Pydantic schemas for the agentic kanban board API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    updated_at: datetime


class BoardStateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None
    mapper_credential_name: str | None = None
    permission: str = "owner"
    columns: list[BoardColumnResponse]
    cards: list[BoardCardResponse]
    has_active_runs: bool


class BoardCreateRequest(BaseModel):
    name: str = "Board"
    description: str | None = None
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None


class BoardUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    mapper_model: str | None = None
    mapper_credential_id: uuid.UUID | None = None


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


class CardCreateRequest(BaseModel):
    title: str
    content: str = ""
    column_id: uuid.UUID | None = None
    position: int | None = None


class CardUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    card_metadata: dict | None = None
    position: int | None = None


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
