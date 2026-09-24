import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.models.schemas import HighlightPayloadSchema

SharePermission = Literal["read", "write"]


def _clean_dashboard_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Dashboard name cannot be empty")
    return name


DashboardName = Annotated[str, Field(max_length=255), AfterValidator(_clean_dashboard_name)]


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


class DashboardSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    # The caller's access: "owner", "write" or "read".
    permission: str = "owner"
    # Set only on dashboards shared with the caller.
    owner_name: str | None = None
    shared_by: str | None = None
    updated_at: datetime


class DashboardResponse(DashboardSummaryResponse):
    widgets: list[DashboardWidgetResponse]


class DashboardCreateRequest(BaseModel):
    name: DashboardName = "Dashboard"


class DashboardUpdateRequest(BaseModel):
    name: DashboardName


class DashboardShareRequest(BaseModel):
    email: str
    permission: SharePermission = "read"


class DashboardShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str | None = None
    permission: str
    shared_at: datetime


class DashboardTeamShareRequest(BaseModel):
    team_id: uuid.UUID
    permission: SharePermission = "read"


class DashboardTeamShareResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    permission: str
    shared_at: datetime


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
