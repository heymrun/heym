from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import TeamMember, User, Workflow, WorkflowShare, WorkflowTeamShare
from app.db.session import get_db
from app.models.schemas import ScheduleEvent, ScheduleListResponse
from app.services.timezone_utils import get_configured_timezone

router = APIRouter()

_MAX_RANGE_DAYS = 62


async def _get_schedule_events(
    workflows: list,
    start: datetime,
    end: datetime,
) -> list[ScheduleEvent]:
    """Generate future ScheduleEvent occurrences for all active cron nodes."""
    tz = get_configured_timezone()
    start_tz = start.astimezone(tz)
    end_tz = end.astimezone(tz)
    events: list[ScheduleEvent] = []

    for workflow in workflows:
        for node in workflow.nodes:
            if node.get("type") != "cron":
                continue
            data = node.get("data", {})
            if data.get("active", True) is False:
                continue
            expr = data.get("cronExpression", "")
            if not expr:
                continue
            try:
                cron = croniter(expr, start_tz - timedelta(seconds=1))
                while True:
                    next_dt = cron.get_next(datetime)
                    if next_dt > end_tz:
                        break
                    events.append(
                        ScheduleEvent(
                            workflow_id=workflow.id,
                            workflow_name=workflow.name,
                            description=getattr(workflow, "description", None),
                            scheduled_at=next_dt.astimezone(timezone.utc),
                        )
                    )
            except Exception:
                continue

    events.sort(key=lambda e: e.scheduled_at)
    return events


def _workflows_where_clause(current_user: User, include_shared: bool) -> Any:
    if include_shared:
        return or_(
            Workflow.owner_id == current_user.id,
            Workflow.id.in_(
                select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == current_user.id)
            ),
            Workflow.id.in_(
                select(WorkflowTeamShare.workflow_id).where(
                    WorkflowTeamShare.team_id.in_(
                        select(TeamMember.team_id).where(TeamMember.user_id == current_user.id)
                    )
                )
            ),
        )
    return Workflow.owner_id == current_user.id


async def fetch_schedule_events_for_user(
    db: AsyncSession,
    current_user: User,
    start: datetime,
    end: datetime,
    include_shared: bool,
) -> ScheduleListResponse:
    """Return cron occurrences within [start, end] for owned and optionally shared workflows."""
    if end <= start:
        raise ValueError("end must be after start")
    if (end - start).days > _MAX_RANGE_DAYS:
        raise ValueError(f"Date range must not exceed {_MAX_RANGE_DAYS} days")
    where_clause = _workflows_where_clause(current_user, include_shared)
    result = await db.execute(select(Workflow).where(where_clause))
    workflows = result.scalars().all()
    events = await _get_schedule_events(workflows, start, end)
    return ScheduleListResponse(events=events, total=len(events))


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    include_shared: Annotated[bool, Query()] = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleListResponse:
    """Return future cron occurrences for the current user within [start, end]."""
    try:
        return await fetch_schedule_events_for_user(db, current_user, start, end, include_shared)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
