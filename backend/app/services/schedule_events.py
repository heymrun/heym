"""Upcoming cron runs for the workflows a user schedules.

The occurrence math takes the timezone as an argument, so the Schedules tab (Heym's
configured timezone) and Heym Work compute the same times without importing settings.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Protocol

from croniter import croniter
from sqlalchemy import ColumnElement, or_, select

from app.db.models import TeamMember, Workflow, WorkflowTeamShare
from app.services.workflow_access import explicit_workflow_share_ids

MAX_RANGE_DAYS = 62


class CronWorkflow(Protocol):
    """What the occurrence math reads from a workflow."""

    id: uuid.UUID
    name: str
    nodes: list[dict[str, Any]]


@dataclass(frozen=True)
class ScheduleOccurrence:
    """One upcoming cron run; field names match ``ScheduleEvent``."""

    workflow_id: uuid.UUID
    workflow_name: str
    description: str | None
    scheduled_at: datetime


def schedule_workflows_clause(user_id: uuid.UUID, include_shared: bool) -> ColumnElement[bool]:
    """Workflows whose schedules the user sees: owned, and shared ones when asked for."""
    if include_shared:
        return or_(
            Workflow.owner_id == user_id,
            Workflow.id.in_(explicit_workflow_share_ids(user_id)),
            Workflow.id.in_(
                select(WorkflowTeamShare.workflow_id).where(
                    WorkflowTeamShare.team_id.in_(
                        select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                    )
                )
            ),
        )
    return Workflow.owner_id == user_id


def cron_occurrences(
    workflows: Iterable[CronWorkflow],
    start: datetime,
    end: datetime,
    tz: tzinfo,
) -> list[ScheduleOccurrence]:
    """Every run of every active cron node in ``[start, end]``, earliest first."""
    start_tz = start.astimezone(tz)
    end_tz = end.astimezone(tz)
    events: list[ScheduleOccurrence] = []

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
                        ScheduleOccurrence(
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
