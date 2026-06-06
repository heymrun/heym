"""Workflow access control, credential context, and sub-workflow resolution."""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import (
    Credential,
    CredentialShare,
    CredentialType,
    TeamMember,
    Workflow,
    WorkflowShare,
    WorkflowTeamShare,
)
from app.services.encryption import decrypt_config


def accessible_workflow_filter(
    user_id: uuid.UUID,
    *,
    include_team_shares: bool = True,
) -> ColumnElement[bool]:
    """SQLAlchemy filter for workflows owned by or shared with the user."""
    conditions: list[ColumnElement[bool]] = [
        Workflow.owner_id == user_id,
        Workflow.id.in_(select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)),
    ]
    if include_team_shares:
        conditions.append(
            Workflow.id.in_(
                select(WorkflowTeamShare.workflow_id).where(
                    WorkflowTeamShare.team_id.in_(
                        select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                    )
                )
            )
        )
    return or_(*conditions)


def accessible_workflow_ids_subquery(
    user_id: uuid.UUID,
    *,
    include_team_shares: bool = True,
) -> Any:
    """Subquery of workflow IDs accessible to the user."""
    return select(Workflow.id).where(
        accessible_workflow_filter(user_id, include_team_shares=include_team_shares)
    )


async def get_accessible_workflow_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_team_shares: bool = True,
) -> list[uuid.UUID]:
    """Return workflow IDs the user owns or that have been shared with them."""
    result = await db.execute(
        accessible_workflow_ids_subquery(user_id, include_team_shares=include_team_shares)
    )
    return [row[0] for row in result.all()]


async def list_accessible_workflows(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_team_shares: bool = True,
    order_by: Any | None = None,
) -> list[Workflow]:
    """Return workflows accessible to the user, optionally ordered."""
    query = select(Workflow).where(
        accessible_workflow_filter(user_id, include_team_shares=include_team_shares)
    )
    if order_by is not None:
        query = query.order_by(order_by)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_workflow_for_user(
    db: AsyncSession, workflow_id: uuid.UUID, user_id: uuid.UUID
) -> Workflow | None:
    """Return a workflow the user owns or that has been shared with them."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            accessible_workflow_filter(user_id),
        )
    )
    return result.scalar_one_or_none()


async def user_has_workflow_access(
    db: AsyncSession, workflow: Workflow, user_id: uuid.UUID
) -> bool:
    """Return whether the user may access the given workflow."""
    if workflow.owner_id == user_id:
        return True
    share_result = await db.execute(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow.id,
            WorkflowShare.user_id == user_id,
        )
    )
    if share_result.scalar_one_or_none() is not None:
        return True

    team_share_result = await db.execute(
        select(WorkflowTeamShare)
        .join(TeamMember, TeamMember.team_id == WorkflowTeamShare.team_id)
        .where(
            WorkflowTeamShare.workflow_id == workflow.id,
            TeamMember.user_id == user_id,
        )
    )
    return team_share_result.scalar_one_or_none() is not None


async def get_credentials_context(
    db: AsyncSession, user_id: uuid.UUID, include_shared: bool = True
) -> dict[str, str]:
    """Load and decrypt owned (and optionally directly shared) credentials for execution."""
    owned_result = await db.execute(select(Credential).where(Credential.owner_id == user_id))
    owned_credentials = owned_result.scalars().all()

    shared_credentials = []
    if include_shared:
        shared_result = await db.execute(
            select(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .where(CredentialShare.user_id == user_id)
        )
        shared_credentials = shared_result.scalars().all()

    all_credentials = list(owned_credentials) + list(shared_credentials)

    context: dict[str, str] = {}
    for cred in all_credentials:
        try:
            config = decrypt_config(cred.encrypted_config)
            if cred.type == CredentialType.bearer:
                token = config.get("bearer_token", "")
                context[cred.name] = f"Bearer {token}" if token else ""
            elif cred.type == CredentialType.header:
                header_key = config.get("header_key", "")
                header_value = config.get("header_value", "")
                context[cred.name] = f"{header_key}: {header_value}" if header_key else header_value
            elif cred.type == CredentialType.slack:
                context[cred.name] = config.get("webhook_url", "")
            else:
                context[cred.name] = config.get("api_key", "")
        except Exception:
            pass
    return context


async def _add_referenced_workflow_to_cache(
    db: AsyncSession,
    target_id: str,
    collected: dict[str, dict],
    actor_user_id: uuid.UUID | None,
) -> None:
    from app.api.workflows import extract_input_fields_from_workflow

    if not target_id or target_id in collected:
        return

    try:
        target_uuid = uuid.UUID(target_id)
    except ValueError:
        return

    result = await db.execute(select(Workflow).where(Workflow.id == target_uuid))
    target_workflow = result.scalar_one_or_none()
    if not target_workflow or not target_workflow.nodes:
        return

    if actor_user_id is not None and not await user_has_workflow_access(
        db,
        target_workflow,
        actor_user_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referenced workflow access denied",
        )

    input_fields = extract_input_fields_from_workflow(target_workflow)
    collected[target_id] = {
        "nodes": target_workflow.nodes,
        "edges": target_workflow.edges,
        "name": target_workflow.name or "",
        "input_fields": [f.model_dump(by_alias=True) for f in input_fields],
    }
    await collect_referenced_workflows(
        db,
        target_workflow.nodes,
        collected,
        actor_user_id=actor_user_id,
    )


async def collect_referenced_workflows(
    db: AsyncSession,
    nodes: list[dict],
    collected: dict[str, dict] | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> dict[str, dict]:
    """Recursively collect execute/agent sub-workflows into a cache dict."""
    if collected is None:
        collected = {}

    for node in nodes:
        if node.get("type") == "execute":
            target_id = node.get("data", {}).get("executeWorkflowId", "")
            await _add_referenced_workflow_to_cache(db, target_id, collected, actor_user_id)

        if node.get("type") == "agent":
            for target_id in node.get("data", {}).get("subWorkflowIds") or []:
                await _add_referenced_workflow_to_cache(db, target_id, collected, actor_user_id)

    return collected
