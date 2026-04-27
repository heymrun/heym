import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, get_db
from app.db.models import (
    Credential,
    CredentialTeamShare,
    GlobalVariable,
    GlobalVariableTeamShare,
    NodeTemplate,
    Team,
    TeamMember,
    User,
    VectorStore,
    VectorStoreTeamShare,
    Workflow,
    WorkflowTeamShare,
    WorkflowTemplate,
)
from app.models.schemas import (
    TeamCreate,
    TeamDetailResponse,
    TeamMemberAddRequest,
    TeamMemberResponse,
    TeamResponse,
    TeamSharedEntitiesResponse,
    TeamSharedEntityItem,
    TeamUpdate,
)

router = APIRouter(tags=["teams"])


async def _ensure_team_member(
    db: AsyncSession,
    team: Team,
    user_id: uuid.UUID,
) -> TeamMember:
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member:
        return member

    member = TeamMember(team_id=team.id, user_id=user_id, added_by_id=user_id)
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member


@router.post("", response_model=TeamDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamDetailResponse:
    team = Team(name=data.name, description=data.description, creator_id=current_user.id)
    db.add(team)
    await db.flush()
    await db.refresh(team)

    # Creator is always a member
    await _ensure_team_member(db, team, current_user.id)
    await db.commit()
    await db.refresh(team)

    members_result = await db.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team.id)
    )
    member_rows = members_result.all()

    members = [
        TeamMemberResponse(
            id=tm.id,
            user_id=u.id,
            email=u.email,
            name=u.name,
            added_by=None,
            joined_at=tm.created_at,
        )
        for tm, u in member_rows
    ]

    return TeamDetailResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        creator_id=team.creator_id,
        creator_email=current_user.email,
        creator_name=current_user.name,
        member_count=len(members),
        created_at=team.created_at,
        members=members,
    )


@router.get("", response_model=list[TeamResponse])
async def list_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TeamResponse]:
    result = await db.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == current_user.id)
        .order_by(Team.created_at.desc())
    )
    teams = result.scalars().all()

    if not teams:
        return []

    # Preload member counts and creator info
    team_ids = [t.id for t in teams]
    counts_result = await db.execute(
        select(TeamMember.team_id, func.count(TeamMember.id))
        .where(TeamMember.team_id.in_(team_ids))
        .group_by(TeamMember.team_id)
    )
    counts_map = {row[0]: row[1] for row in counts_result.all()}

    creators_result = await db.execute(
        select(User.id, User.email, User.name).where(
            User.id.in_({t.creator_id for t in teams}),
        )
    )
    creators_map = {row[0]: (row[1], row[2]) for row in creators_result.all()}

    responses: list[TeamResponse] = []
    for team in teams:
        creator_email, creator_name = creators_map.get(team.creator_id, ("", ""))
        responses.append(
            TeamResponse(
                id=team.id,
                name=team.name,
                description=team.description,
                creator_id=team.creator_id,
                creator_email=creator_email,
                creator_name=creator_name,
                member_count=counts_map.get(team.id, 0),
                created_at=team.created_at,
            )
        )
    return responses


async def _get_team_for_member(
    db: AsyncSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Team | None:
    result = await db.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.id == team_id, TeamMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamDetailResponse:
    team = await _get_team_for_member(db, team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    added_by_user_alias = aliased(User)
    members_result = await db.execute(
        select(TeamMember, User, added_by_user_alias)
        .join(User, User.id == TeamMember.user_id)
        .join(added_by_user_alias, TeamMember.added_by_id == added_by_user_alias.id, isouter=True)
        .where(TeamMember.team_id == team.id)
    )
    member_rows = members_result.all()

    members: list[TeamMemberResponse] = []
    for tm, u, added_by in member_rows:
        added_by_email: str | None = added_by.email if added_by is not None else None
        members.append(
            TeamMemberResponse(
                id=tm.id,
                user_id=u.id,
                email=u.email,
                name=u.name,
                added_by=added_by_email,
                joined_at=tm.created_at,
            )
        )

    creator_email = current_user.email if team.creator_id == current_user.id else ""
    creator_name = current_user.name if team.creator_id == current_user.id else ""

    if not creator_email:
        creator_result = await db.execute(select(User).where(User.id == team.creator_id))
        creator = creator_result.scalar_one_or_none()
        if creator:
            creator_email = creator.email
            creator_name = creator.name

    return TeamDetailResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        creator_id=team.creator_id,
        creator_email=creator_email,
        creator_name=creator_name,
        member_count=len(members),
        created_at=team.created_at,
        members=members,
    )


@router.get("/{team_id}/shared-entities", response_model=TeamSharedEntitiesResponse)
async def get_team_shared_entities(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamSharedEntitiesResponse:
    team = await _get_team_for_member(db, team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    team_id_val = team.id
    team_id_str = str(team_id_val)

    # Workflows
    wf_result = await db.execute(
        select(Workflow.id, Workflow.name)
        .join(WorkflowTeamShare, WorkflowTeamShare.workflow_id == Workflow.id)
        .where(WorkflowTeamShare.team_id == team_id_val)
    )
    workflows = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in wf_result.all()]

    # Credentials
    cred_result = await db.execute(
        select(Credential.id, Credential.name)
        .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
        .where(CredentialTeamShare.team_id == team_id_val)
    )
    credentials = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in cred_result.all()]

    # Global variables
    gv_result = await db.execute(
        select(GlobalVariable.id, GlobalVariable.name)
        .join(
            GlobalVariableTeamShare,
            GlobalVariableTeamShare.global_variable_id == GlobalVariable.id,
        )
        .where(GlobalVariableTeamShare.team_id == team_id_val)
    )
    global_variables = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in gv_result.all()]

    # Vector stores
    vs_result = await db.execute(
        select(VectorStore.id, VectorStore.name)
        .join(VectorStoreTeamShare, VectorStoreTeamShare.vector_store_id == VectorStore.id)
        .where(VectorStoreTeamShare.team_id == team_id_val)
    )
    vector_stores = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in vs_result.all()]

    # Workflow templates (shared_with_teams JSON array contains team_id)
    wft_result = await db.execute(
        select(WorkflowTemplate.id, WorkflowTemplate.name).where(
            cast(WorkflowTemplate.shared_with_teams, JSONB).contains([team_id_str])
        )
    )
    workflow_templates = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in wft_result.all()]

    # Node templates (shared_with_teams JSON array contains team_id)
    ndt_result = await db.execute(
        select(NodeTemplate.id, NodeTemplate.name).where(
            cast(NodeTemplate.shared_with_teams, JSONB).contains([team_id_str])
        )
    )
    node_templates = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in ndt_result.all()]

    # Data tables
    from app.db.models import DataTable, DataTableTeamShare

    dt_result = await db.execute(
        select(DataTable.id, DataTable.name)
        .join(DataTableTeamShare, DataTableTeamShare.table_id == DataTable.id)
        .where(DataTableTeamShare.team_id == team_id_val)
    )
    data_tables = [TeamSharedEntityItem(id=r[0], name=r[1]) for r in dt_result.all()]

    return TeamSharedEntitiesResponse(
        workflows=workflows,
        credentials=credentials,
        global_variables=global_variables,
        vector_stores=vector_stores,
        data_tables=data_tables,
        workflow_templates=workflow_templates,
        node_templates=node_templates,
    )


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: uuid.UUID,
    data: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamResponse:
    team = await _get_team_for_member(db, team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    if data.name is not None:
        team.name = data.name
    if data.description is not None:
        team.description = data.description

    await db.commit()
    await db.refresh(team)

    count_result = await db.execute(
        select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)
    )
    member_count = count_result.scalar() or 0

    creator_result = await db.execute(select(User).where(User.id == team.creator_id))
    creator = creator_result.scalar_one_or_none()

    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        creator_id=team.creator_id,
        creator_email=creator.email if creator else "",
        creator_name=creator.name if creator else "",
        member_count=member_count,
        created_at=team.created_at,
    )


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.creator_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator can delete")

    await db.delete(team)
    await db.commit()


@router.post("/{team_id}/members", response_model=TeamDetailResponse)
async def add_team_member(
    team_id: uuid.UUID,
    payload: TeamMemberAddRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamDetailResponse:
    team = await _get_team_for_member(db, team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    user_result = await db.execute(select(User).where(User.email == payload.email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        member = TeamMember(
            team_id=team.id,
            user_id=user.id,
            added_by_id=current_user.id,
        )
        db.add(member)
        await db.flush()

    await db.commit()
    return await get_team(team.id, db, current_user)


@router.delete("/{team_id}/members/{user_id}", response_model=TeamDetailResponse)
async def remove_team_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamDetailResponse:
    team = await _get_team_for_member(db, team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    if user_id == team.creator_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Creator cannot be removed from the team",
        )

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    await db.delete(member)
    await db.commit()
    return await get_team(team.id, db, current_user)
