import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.models.schemas import HighlightPayloadSchema
from app.services.page_params import RecordFormat

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
    # Row link (table widgets): rows open link_dashboard_id with ?record=<link_record_field>.
    link_dashboard_id: uuid.UUID | None = None
    link_record_field: str | None = None
    link_label_field: str | None = None
    # Whether the caller can open the linked dashboard; rows are clickable only then.
    link_accessible: bool = False
    updated_at: datetime


class DashboardSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    # The caller's access: "owner", "write" or "read".
    permission: str = "owner"
    # Set only on dashboards shared with the caller.
    owner_name: str | None = None
    shared_by: str | None = None
    # Which `?record=` values the dashboard accepts as a detail page.
    record_format: RecordFormat = "id"
    updated_at: datetime


class DashboardResponse(DashboardSummaryResponse):
    widgets: list[DashboardWidgetResponse]


class DashboardCreateRequest(BaseModel):
    name: DashboardName = "Dashboard"


class DashboardUpdateRequest(BaseModel):
    name: DashboardName | None = None
    record_format: RecordFormat | None = None


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
    workflow_id: uuid.UUID | None = Field(
        default=None,
        description="For a fileRun widget: the workflow with a File Upload trigger it runs.",
    )


class WidgetUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    chart_type: str | None = None
    layout: WidgetLayout | None = None
    cache_ttl_seconds: int | None = None
    link_dashboard_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Row link target. Send it with link_record_field (and optionally link_label_field) "
            "to set the link, or as null to remove it; leave it out to keep the link as it is."
        ),
    )
    link_record_field: str | None = Field(default=None, max_length=255)
    link_label_field: str | None = Field(default=None, max_length=255)


class FileRunSlotResponse(BaseModel):
    """A single-use upload link for one drop on a file-run widget."""

    upload_url: str
    expires_at: str
    max_size_mb: int
    allowed_types: list[str] = []
    slot_id: str


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
