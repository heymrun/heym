"""The single definition of which workflows a user can reach.

Both the async API layer and the synchronous node handlers need this answer, so
it is expressed as a SQLAlchemy clause rather than an executed query - the caller
supplies the session and the engine.
"""

from uuid import UUID

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import (
    Alert,
    TeamMember,
    Workflow,
    WorkflowExecutionToken,
    WorkflowShare,
    WorkflowTeamShare,
)
from app.services.dashboard_access import writable_shared_widget_workflow_ids


def explicit_workflow_share_ids(user_id: UUID):
    """Workflow ids ``user_id`` reaches through a real, owner-granted direct share.

    Excludes a ``WorkflowShare`` row with ``is_explicit_share`` false: that row only
    remembers which folder the user filed a team-shared workflow into and must never
    substitute for the team share that actually gave them access. Every query that
    means "workflows this user holds a direct share on" - access checks, MCP
    exposure, chat/analytics/schedule scoping, active-execution visibility - must
    use this instead of querying ``WorkflowShare`` directly, so a revoked team
    member's leftover row cannot stand in for the removed grant anywhere.
    """
    return select(WorkflowShare.workflow_id).where(
        WorkflowShare.user_id == user_id,
        WorkflowShare.is_explicit_share.is_(True),
    )


def _instance_admin_clause(user_id: UUID, is_admin: bool | None) -> ColumnElement[bool]:
    if is_admin is not None:
        return true() if is_admin else false()
    # Unset means Heym's own HEYM_ADMIN_EMAILS, which needs Heym's settings.
    from app.services.instance_admin import instance_admin_clause

    return instance_admin_clause(user_id)


def workflow_access_clause(user_id: UUID, *, is_admin: bool | None = None) -> ColumnElement[bool]:
    """Return the WHERE clause matching every workflow ``user_id`` can reach.

    Instance administrators reach every workflow. Other users reach a workflow by
    owning it, holding a direct share, or belonging to a team it is shared with.
    A dashboard widget's hidden
    workflow is also reachable with write access to its dashboard; read access
    to a dashboard never reaches a workflow.

    ``is_admin`` says whether ``user_id`` administers the instance. Heym leaves it
    unset and reads ``HEYM_ADMIN_EMAILS``; Heym Work imports this module without
    Heym's settings and passes its own answer.
    """
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
        and_(
            Workflow.kind == "dashboard_widget",
            Workflow.id.in_(writable_shared_widget_workflow_ids(user_id)),
        ),
        _instance_admin_clause(user_id, is_admin),
    )


async def get_accessible_workflow(
    db: AsyncSession,
    workflow_id: UUID,
    user_id: UUID,
    *,
    is_admin: bool | None = None,
) -> Workflow | None:
    """Return a workflow reached through ownership, sharing, or instance administration."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            workflow_access_clause(user_id, is_admin=is_admin),
        )
    )
    return result.scalar_one_or_none()


async def user_has_workflow_access(
    db: AsyncSession, workflow: Workflow, user_id: UUID, *, is_admin: bool | None = None
) -> bool:
    """Return whether ``user_id`` can reach ``workflow``.

    Goes through ``workflow_access_clause``'s ``IN`` subqueries rather than joining
    ``WorkflowTeamShare`` to ``TeamMember`` directly. A direct join produces one row per
    team a user shares the workflow through, so a user reachable via two teams made a
    two-argument JOIN return two rows and ``scalar_one_or_none()`` raise
    ``MultipleResultsFound``. The subquery form only ever matches the single ``workflow.id``
    row, however many paths grant access to it.
    """
    if workflow.owner_id == user_id:
        return True
    result = await db.execute(
        select(Workflow.id).where(
            Workflow.id == workflow.id, workflow_access_clause(user_id, is_admin=is_admin)
        )
    )
    return result.scalar_one_or_none() is not None


PERMISSION_READ = "read"
PERMISSION_WRITE = "write"


async def get_workflow_permission(
    db: AsyncSession, workflow: Workflow, user_id: UUID, *, is_admin: bool | None = None
) -> str | None:
    """Return the highest permission ``user_id`` holds on ``workflow``.

    Instance administrators, the owner, and anyone with write access to a dashboard
    hosting the workflow as a widget get ``"write"``. Otherwise the highest permission
    across the user's direct share and every
    team share wins, so a write grant through one path is never weakened by a read grant
    through another. ``None`` means the user has no access at all. ``is_admin`` works as
    in ``workflow_access_clause``.
    """
    if workflow.owner_id == user_id:
        return PERMISSION_WRITE

    if is_admin is None:
        from app.services.instance_admin import is_instance_admin_id

        is_admin = await is_instance_admin_id(db, user_id)
    if is_admin:
        return PERMISSION_WRITE

    permissions: list[str] = []

    direct_result = await db.execute(
        select(WorkflowShare.permission).where(
            WorkflowShare.workflow_id == workflow.id,
            WorkflowShare.user_id == user_id,
            WorkflowShare.is_explicit_share.is_(True),
        )
    )
    permissions.extend(direct_result.scalars().all())

    team_result = await db.execute(
        select(WorkflowTeamShare.permission).where(
            WorkflowTeamShare.workflow_id == workflow.id,
            WorkflowTeamShare.team_id.in_(
                select(TeamMember.team_id).where(TeamMember.user_id == user_id)
            ),
        )
    )
    permissions.extend(team_result.scalars().all())

    if getattr(workflow, "kind", None) == "dashboard_widget":
        widget_result = await db.execute(
            select(Workflow.id).where(
                Workflow.id == workflow.id,
                Workflow.id.in_(writable_shared_widget_workflow_ids(user_id)),
            )
        )
        if widget_result.scalar_one_or_none() is not None:
            permissions.append(PERMISSION_WRITE)

    if not permissions:
        return None
    return PERMISSION_WRITE if PERMISSION_WRITE in permissions else PERMISSION_READ


async def user_can_write_workflow(
    db: AsyncSession, workflow: Workflow, user_id: UUID, *, is_admin: bool | None = None
) -> bool:
    """Return whether ``user_id`` may edit ``workflow`` (owner or a write share)."""
    permission = await get_workflow_permission(db, workflow, user_id, is_admin=is_admin)
    return permission == PERMISSION_WRITE


async def revoke_execution_tokens_without_access(db: AsyncSession, workflow: Workflow) -> None:
    """Revoke execution tokens whose minter can no longer access ``workflow``.

    Call after a share, team share, team membership, or team itself has been removed and
    the change flushed. ``validate_workflow_auth`` rechecks access on every use regardless,
    so this is defense in depth: it keeps the stored token state honest and lets the
    workflow owner see revoked tokens as revoked rather than merely unusable.
    """
    result = await db.execute(
        select(WorkflowExecutionToken).where(
            WorkflowExecutionToken.workflow_id == workflow.id,
            WorkflowExecutionToken.revoked.is_(False),
        )
    )
    for token in result.scalars().all():
        if not await user_has_workflow_access(db, workflow, token.user_id):
            token.revoked = True


async def disable_alerts_without_access(db: AsyncSession, workflow: Workflow) -> list[Alert]:
    """Disable alerts watching ``workflow`` whose owner can no longer access it.

    Call after a share, team share, team membership, or team itself has been removed and the
    change flushed. An alert reads the workflow's execution metrics on every check, so leaving
    it enabled keeps reporting data its owner can no longer open. Alerts that only name
    ``workflow`` as their notify target are left alone: the notify runner rechecks access
    before every run. Returns the disabled alerts so the calling router can audit them.
    """
    result = await db.execute(
        select(Alert).where(
            Alert.workflow_id == workflow.id,
            Alert.enabled.is_(True),
            Alert.owner_id != workflow.owner_id,
        )
    )
    access_by_owner: dict[UUID, bool] = {}
    disabled: list[Alert] = []
    for alert in result.scalars().all():
        if alert.owner_id not in access_by_owner:
            access_by_owner[alert.owner_id] = await user_has_workflow_access(
                db, workflow, alert.owner_id
            )
        if not access_by_owner[alert.owner_id]:
            alert.enabled = False
            disabled.append(alert)
    return disabled
