from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import get_current_user
from app.db.models import User, Workflow
from app.db.session import get_db
from app.models.schemas import ScheduleEvent, ScheduleListResponse
from app.services.instance_admin import is_instance_admin
from app.services.schedule_events import (
    MAX_RANGE_DAYS,
    cron_occurrences,
    schedule_workflows_clause,
)
from app.services.timezone_utils import get_configured_timezone
from app.services.workflow_access import workflow_access_clause

router = APIRouter()

_MAX_RANGE_DAYS = MAX_RANGE_DAYS


async def _get_schedule_events(
    workflows: list,
    start: datetime,
    end: datetime,
) -> list[ScheduleEvent]:
    """Generate future ScheduleEvent occurrences for all active cron nodes."""
    return [
        ScheduleEvent(**asdict(occurrence))
        for occurrence in cron_occurrences(workflows, start, end, get_configured_timezone())
    ]


def _workflows_where_clause(current_user: User, include_shared: bool) -> ColumnElement[bool]:
    # Instance administrators see every workflow's schedule when shared ones are included.
    if include_shared and is_instance_admin(current_user):
        return workflow_access_clause(current_user.id)
    return schedule_workflows_clause(current_user.id, include_shared)


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
