"""Template service – CRUD/query for workflow and node templates."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import NodeTemplate, TeamMember, TemplateVisibility, User, WorkflowTemplate


async def _get_user_team_ids(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    """Return set of team IDs (as strings) the user is a member of."""
    result = await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == user_id))
    return {str(row[0]) for row in result.all()}


async def list_workflow_templates(
    db: AsyncSession,
    user: User,
    search: str | None = None,
) -> list[WorkflowTemplate]:
    """Return all workflow templates visible to this user.

    Visibility rules:
    - always include own templates
    - include templates with visibility='everyone'
    - include templates with visibility='specific_users' when the user's email is in shared_with
    """
    stmt = select(WorkflowTemplate).options(selectinload(WorkflowTemplate.author))

    if search:
        term = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                WorkflowTemplate.name.ilike(term),
                WorkflowTemplate.description.ilike(term),
            )
        )
    stmt = stmt.order_by(WorkflowTemplate.created_at.desc())
    result = await db.execute(stmt)
    templates = list(result.scalars().all())

    user_team_ids = await _get_user_team_ids(db, user.id)
    visible: list[WorkflowTemplate] = []
    user_email = getattr(user, "email", None)
    for template in templates:
        if template.author_id == user.id:
            visible.append(template)
        elif template.visibility == TemplateVisibility.everyone:
            visible.append(template)
        elif (
            template.visibility == TemplateVisibility.specific_users
            and user_email
            and isinstance(template.shared_with, list)
            and user_email in template.shared_with
        ):
            visible.append(template)
        elif (
            template.visibility == TemplateVisibility.specific_users
            and isinstance(template.shared_with_teams, list)
            and user_team_ids
            and any(str(tid) in user_team_ids for tid in template.shared_with_teams)
        ):
            visible.append(template)

    return visible


async def list_node_templates(
    db: AsyncSession,
    user: User,
    search: str | None = None,
) -> list[NodeTemplate]:
    """Return all node templates visible to this user (same rules as workflows)."""
    stmt = select(NodeTemplate).options(selectinload(NodeTemplate.author))

    if search:
        term = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                NodeTemplate.name.ilike(term),
                NodeTemplate.description.ilike(term),
            )
        )
    stmt = stmt.order_by(NodeTemplate.created_at.desc())
    result = await db.execute(stmt)
    templates = list(result.scalars().all())

    user_team_ids = await _get_user_team_ids(db, user.id)
    visible: list[NodeTemplate] = []
    user_email = getattr(user, "email", None)
    for template in templates:
        if template.author_id == user.id:
            visible.append(template)
        elif template.visibility == TemplateVisibility.everyone:
            visible.append(template)
        elif (
            template.visibility == TemplateVisibility.specific_users
            and user_email
            and isinstance(template.shared_with, list)
            and user_email in template.shared_with
        ):
            visible.append(template)
        elif (
            template.visibility == TemplateVisibility.specific_users
            and isinstance(template.shared_with_teams, list)
            and user_team_ids
            and any(str(tid) in user_team_ids for tid in template.shared_with_teams)
        ):
            visible.append(template)

    return visible


async def get_workflow_template(
    db: AsyncSession, template_id: uuid.UUID
) -> WorkflowTemplate | None:
    result = await db.execute(
        select(WorkflowTemplate)
        .where(WorkflowTemplate.id == template_id)
        .options(selectinload(WorkflowTemplate.author))
    )
    return result.scalar_one_or_none()


async def get_node_template(db: AsyncSession, template_id: uuid.UUID) -> NodeTemplate | None:
    result = await db.execute(
        select(NodeTemplate)
        .where(NodeTemplate.id == template_id)
        .options(selectinload(NodeTemplate.author))
    )
    return result.scalar_one_or_none()


async def create_workflow_template(
    db: AsyncSession,
    author_id: uuid.UUID,
    name: str,
    description: str | None,
    tags: list[str],
    nodes: list[dict],
    edges: list[dict],
    canvas_snapshot: str | None,
    visibility: str,
    shared_with: list[str],
    shared_with_teams: list[str] | None = None,
) -> WorkflowTemplate:
    template = WorkflowTemplate(
        id=uuid.uuid4(),
        author_id=author_id,
        name=name,
        description=description,
        tags=tags,
        nodes=nodes,
        edges=edges,
        canvas_snapshot=canvas_snapshot,
        visibility=visibility,
        shared_with=shared_with,
        shared_with_teams=shared_with_teams or [],
        use_count=0,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def create_node_template(
    db: AsyncSession,
    author_id: uuid.UUID,
    name: str,
    description: str | None,
    tags: list[str],
    node_type: str,
    node_data: dict,
    visibility: str,
    shared_with: list[str],
    shared_with_teams: list[str] | None = None,
) -> NodeTemplate:
    template = NodeTemplate(
        id=uuid.uuid4(),
        author_id=author_id,
        name=name,
        description=description,
        tags=tags,
        node_type=node_type,
        node_data=node_data,
        visibility=visibility,
        shared_with=shared_with,
        shared_with_teams=shared_with_teams or [],
        use_count=0,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def increment_workflow_template_use(
    db: AsyncSession, template: WorkflowTemplate
) -> WorkflowTemplate:
    template.use_count += 1
    await db.commit()
    await db.refresh(template)
    return template


async def increment_node_template_use(db: AsyncSession, template: NodeTemplate) -> NodeTemplate:
    template.use_count += 1
    await db.commit()
    await db.refresh(template)
    return template


async def update_workflow_template(
    db: AsyncSession,
    template: WorkflowTemplate,
    *,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    visibility: str | None = None,
    shared_with: list[str] | None = None,
    shared_with_teams: list[str] | None = None,
) -> WorkflowTemplate:
    """Update editable metadata of a workflow template (author only)."""
    if name is not None:
        template.name = name
    if description is not None:
        template.description = description
    if tags is not None:
        template.tags = tags
    if visibility is not None:
        template.visibility = visibility
    if shared_with is not None:
        template.shared_with = shared_with
    if shared_with_teams is not None:
        template.shared_with_teams = shared_with_teams
    await db.commit()
    await db.refresh(template)
    return template


async def update_node_template(
    db: AsyncSession,
    template: NodeTemplate,
    *,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    visibility: str | None = None,
    shared_with: list[str] | None = None,
    shared_with_teams: list[str] | None = None,
) -> NodeTemplate:
    """Update editable metadata of a node template (author only)."""
    if name is not None:
        template.name = name
    if description is not None:
        template.description = description
    if tags is not None:
        template.tags = tags
    if visibility is not None:
        template.visibility = visibility
    if shared_with is not None:
        template.shared_with = shared_with
    if shared_with_teams is not None:
        template.shared_with_teams = shared_with_teams
    await db.commit()
    await db.refresh(template)
    return template


async def delete_workflow_template(db: AsyncSession, template: WorkflowTemplate) -> None:
    await db.delete(template)
    await db.commit()


async def delete_node_template(db: AsyncSession, template: NodeTemplate) -> None:
    await db.delete(template)
    await db.commit()
