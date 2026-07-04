import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.schemas import HighlightPayloadSchema


class WidgetLayout(BaseModel):
    x: int = 0
    y: int = 0
    w: int = 4
    h: int = 4


class DashboardWidgetResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    title: str
    description: str | None = None
    chart_type: str
    layout: WidgetLayout
    cache_ttl_seconds: int
    position: int
    updated_at: datetime


class DashboardResponse(BaseModel):
    id: uuid.UUID
    name: str
    widgets: list[DashboardWidgetResponse]


class WidgetCreateRequest(BaseModel):
    title: str = "Untitled"
    description: str | None = None
    chart_type: str = "bar"
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    cache_ttl_seconds: int = 300


class WidgetUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    chart_type: str | None = None
    layout: WidgetLayout | None = None
    cache_ttl_seconds: int | None = None


class MarkdownTaskToggleRequest(BaseModel):
    line_index: int = Field(ge=0)


class MarkdownTaskUpdateRequest(BaseModel):
    line_index: int = Field(ge=0)
    text: str = ""


class WidgetDataResponse(BaseModel):
    widget_id: uuid.UUID
    payload: dict[str, Any] | None
    cached: bool
    computed_at: datetime | None
    error: str | None = None
    highlight: HighlightPayloadSchema | None = None


class AiWidgetRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    credential_id: uuid.UUID
    model: str = Field(min_length=1, max_length=200)


class AiRefineRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    credential_id: uuid.UUID
    model: str = Field(min_length=1, max_length=200)
