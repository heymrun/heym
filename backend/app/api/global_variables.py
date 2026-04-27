"""Global variables API - CRUD for user-scoped persistent variables."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    GlobalVariable,
    GlobalVariableShare,
    GlobalVariableTeamShare,
    Team,
    TeamMember,
    User,
)
from app.db.session import get_db
from app.models.schemas import (
    GlobalVariableBulkDeleteRequest,
    GlobalVariableCreate,
    GlobalVariableListResponse,
    GlobalVariableResponse,
    GlobalVariableShareRequest,
    GlobalVariableShareResponse,
    GlobalVariableUpdate,
    TeamShareRequest,
    TeamShareResponse,
)

router = APIRouter()


def _coerce_value(value: object, value_type: str) -> object:
    """Coerce value to the specified type."""
    if value_type == "auto":
        return value
    if value_type == "string":
        return str(value)
    if value_type == "number":
        if isinstance(value, str):
            try:
                return int(value) if "." not in value else float(value)
            except ValueError:
                return float(value) if value else 0
        return float(value) if isinstance(value, (int, float)) else 0
    if value_type == "boolean":
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    if value_type == "array":
        if isinstance(value, list):
            return value
        return [value]
    if value_type == "object":
        if isinstance(value, dict):
            return value
        return {"value": value}
    return value


def _stored_value(raw: object) -> dict:
    """Wrap value for JSON column (always store as dict)."""
    return {"v": raw}


def _unwrap_value(stored: dict) -> object:
    """Unwrap value from stored dict."""
    if isinstance(stored, dict) and "v" in stored:
        return stored["v"]
    return stored


@router.get("", response_model=list[GlobalVariableListResponse])
async def list_global_variables(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GlobalVariableListResponse]:
    owned_result = await db.execute(
        select(GlobalVariable)
        .where(GlobalVariable.owner_id == current_user.id)
        .order_by(GlobalVariable.name.asc())
    )
    owned_variables = owned_result.scalars().all()

    shared_result = await db.execute(
        select(GlobalVariable, User.email)
        .join(GlobalVariableShare, GlobalVariableShare.global_variable_id == GlobalVariable.id)
        .join(User, User.id == GlobalVariable.owner_id)
        .where(GlobalVariableShare.user_id == current_user.id)
        .order_by(GlobalVariable.name.asc())
    )
    shared_variables = shared_result.all()

    shared_team_result = await db.execute(
        select(GlobalVariable, Team.name)
        .join(
            GlobalVariableTeamShare, GlobalVariableTeamShare.global_variable_id == GlobalVariable.id
        )
        .join(TeamMember, TeamMember.team_id == GlobalVariableTeamShare.team_id)
        .join(Team, Team.id == GlobalVariableTeamShare.team_id)
        .where(TeamMember.user_id == current_user.id)
        .order_by(GlobalVariable.name.asc())
    )
    shared_team_variables = shared_team_result.all()

    seen_ids: set[uuid.UUID] = set()
    responses = []
    for v in owned_variables:
        responses.append(
            GlobalVariableListResponse(
                id=v.id,
                name=v.name,
                value=_unwrap_value(v.value),
                value_type=v.value_type,
                created_at=v.created_at,
                updated_at=v.updated_at,
                is_shared=False,
                shared_by=None,
                shared_by_team=None,
            )
        )
        seen_ids.add(v.id)

    for v, owner_email in shared_variables:
        if v.id in seen_ids:
            continue
        seen_ids.add(v.id)
        responses.append(
            GlobalVariableListResponse(
                id=v.id,
                name=v.name,
                value=_unwrap_value(v.value),
                value_type=v.value_type,
                created_at=v.created_at,
                updated_at=v.updated_at,
                is_shared=True,
                shared_by=owner_email,
                shared_by_team=None,
            )
        )

    for v, team_name in shared_team_variables:
        if v.id in seen_ids:
            continue
        seen_ids.add(v.id)
        responses.append(
            GlobalVariableListResponse(
                id=v.id,
                name=v.name,
                value=_unwrap_value(v.value),
                value_type=v.value_type,
                created_at=v.created_at,
                updated_at=v.updated_at,
                is_shared=True,
                shared_by=None,
                shared_by_team=team_name,
            )
        )

    return responses


@router.post("", response_model=GlobalVariableResponse, status_code=status.HTTP_201_CREATED)
async def create_global_variable(
    data: GlobalVariableCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GlobalVariableResponse:
    existing = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.owner_id == current_user.id,
            GlobalVariable.name == data.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Variable with this name already exists",
        )

    value_type = data.value_type if data.value_type != "auto" else _infer_type(data.value)
    coerced = _coerce_value(data.value, value_type)

    variable = GlobalVariable(
        owner_id=current_user.id,
        name=data.name,
        value=_stored_value(coerced),
        value_type=value_type,
    )
    db.add(variable)
    await db.flush()
    await db.refresh(variable)

    return GlobalVariableResponse(
        id=variable.id,
        name=variable.name,
        value=coerced,
        value_type=variable.value_type,
        created_at=variable.created_at,
        updated_at=variable.updated_at,
    )


def _infer_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


@router.get("/{variable_id}", response_model=GlobalVariableResponse)
async def get_global_variable(
    variable_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GlobalVariableResponse:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        shared_result = await db.execute(
            select(GlobalVariable)
            .join(GlobalVariableShare, GlobalVariableShare.global_variable_id == GlobalVariable.id)
            .where(
                GlobalVariable.id == variable_id,
                GlobalVariableShare.user_id == current_user.id,
            )
        )
        variable = shared_result.scalar_one_or_none()
    if variable is None:
        team_result = await db.execute(
            select(GlobalVariable)
            .join(
                GlobalVariableTeamShare,
                GlobalVariableTeamShare.global_variable_id == GlobalVariable.id,
            )
            .join(TeamMember, TeamMember.team_id == GlobalVariableTeamShare.team_id)
            .where(
                GlobalVariable.id == variable_id,
                TeamMember.user_id == current_user.id,
            )
        )
        variable = team_result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )
    return GlobalVariableResponse(
        id=variable.id,
        name=variable.name,
        value=_unwrap_value(variable.value),
        value_type=variable.value_type,
        created_at=variable.created_at,
        updated_at=variable.updated_at,
    )


async def _get_editable_variable(
    db: AsyncSession, variable_id: uuid.UUID, user_id: uuid.UUID
) -> GlobalVariable | None:
    """Return variable if user can edit it (owner, user share, or team share)."""
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == user_id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is not None:
        return variable

    shared_result = await db.execute(
        select(GlobalVariable)
        .join(GlobalVariableShare, GlobalVariableShare.global_variable_id == GlobalVariable.id)
        .where(
            GlobalVariable.id == variable_id,
            GlobalVariableShare.user_id == user_id,
        )
    )
    variable = shared_result.scalar_one_or_none()
    if variable is not None:
        return variable

    team_result = await db.execute(
        select(GlobalVariable)
        .join(
            GlobalVariableTeamShare,
            GlobalVariableTeamShare.global_variable_id == GlobalVariable.id,
        )
        .join(TeamMember, TeamMember.team_id == GlobalVariableTeamShare.team_id)
        .where(
            GlobalVariable.id == variable_id,
            TeamMember.user_id == user_id,
        )
    )
    return team_result.scalar_one_or_none()


@router.patch("/{variable_id}", response_model=GlobalVariableResponse)
async def update_global_variable(
    variable_id: uuid.UUID,
    data: GlobalVariableUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GlobalVariableResponse:
    variable = await _get_editable_variable(db, variable_id, current_user.id)
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )

    if data.name is not None:
        if data.name != variable.name:
            existing = await db.execute(
                select(GlobalVariable).where(
                    GlobalVariable.owner_id == variable.owner_id,
                    GlobalVariable.name == data.name,
                    GlobalVariable.id != variable_id,
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Variable with this name already exists",
                )
        variable.name = data.name

    if data.value is not None:
        value_type = data.value_type or variable.value_type
        if value_type == "auto":
            value_type = _infer_type(data.value)
        coerced = _coerce_value(data.value, value_type)
        variable.value = _stored_value(coerced)
        variable.value_type = value_type

    if data.value_type is not None and data.value is None:
        variable.value_type = data.value_type

    await db.flush()
    await db.refresh(variable)

    return GlobalVariableResponse(
        id=variable.id,
        name=variable.name,
        value=_unwrap_value(variable.value),
        value_type=variable.value_type,
        created_at=variable.created_at,
        updated_at=variable.updated_at,
    )


@router.delete("/{variable_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_global_variable(
    variable_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )
    await db.delete(variable)
    await db.flush()


@router.post("/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_delete_global_variables(
    body: GlobalVariableBulkDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id.in_(body.ids),
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variables = result.scalars().all()
    for v in variables:
        await db.delete(v)
    await db.flush()


@router.get("/{variable_id}/shares", response_model=list[GlobalVariableShareResponse])
async def list_global_variable_shares(
    variable_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GlobalVariableShareResponse]:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )

    shares_result = await db.execute(
        select(GlobalVariableShare, User)
        .join(User, GlobalVariableShare.user_id == User.id)
        .where(GlobalVariableShare.global_variable_id == variable_id)
    )
    rows = shares_result.all()

    return [
        GlobalVariableShareResponse(
            id=share.id,
            user_id=user.id,
            email=user.email,
            name=user.name,
            shared_at=share.created_at,
        )
        for share, user in rows
    ]


@router.post("/{variable_id}/shares", response_model=GlobalVariableShareResponse)
async def create_global_variable_share(
    variable_id: uuid.UUID,
    share_data: GlobalVariableShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GlobalVariableShareResponse:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )

    user_result = await db.execute(select(User).where(User.email == share_data.email))
    target_user = user_result.scalar_one_or_none()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share with yourself",
        )

    existing_result = await db.execute(
        select(GlobalVariableShare).where(
            GlobalVariableShare.global_variable_id == variable_id,
            GlobalVariableShare.user_id == target_user.id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        return GlobalVariableShareResponse(
            id=existing.id,
            user_id=target_user.id,
            email=target_user.email,
            name=target_user.name,
            shared_at=existing.created_at,
        )

    share = GlobalVariableShare(global_variable_id=variable_id, user_id=target_user.id)
    db.add(share)
    await db.flush()
    await db.refresh(share)

    return GlobalVariableShareResponse(
        id=share.id,
        user_id=target_user.id,
        email=target_user.email,
        name=target_user.name,
        shared_at=share.created_at,
    )


@router.delete("/{variable_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_global_variable_share(
    variable_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )

    share_result = await db.execute(
        select(GlobalVariableShare).where(
            GlobalVariableShare.global_variable_id == variable_id,
            GlobalVariableShare.user_id == user_id,
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found",
        )

    await db.delete(share)
    await db.commit()


@router.get("/{variable_id}/team-shares", response_model=list[TeamShareResponse])
async def list_global_variable_team_shares(
    variable_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamShareResponse]:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )
    shares_result = await db.execute(
        select(GlobalVariableTeamShare, Team)
        .join(Team, Team.id == GlobalVariableTeamShare.team_id)
        .where(GlobalVariableTeamShare.global_variable_id == variable_id)
        .order_by(Team.name.asc())
    )
    return [
        TeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            shared_at=share.created_at,
        )
        for share, team in shares_result.all()
    ]


@router.post("/{variable_id}/team-shares", response_model=TeamShareResponse)
async def create_global_variable_team_share(
    variable_id: uuid.UUID,
    payload: TeamShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamShareResponse:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )
    team_result = await db.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.id == payload.team_id, TeamMember.user_id == current_user.id)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found or you are not a member",
        )
    existing = await db.execute(
        select(GlobalVariableTeamShare).where(
            GlobalVariableTeamShare.global_variable_id == variable_id,
            GlobalVariableTeamShare.team_id == payload.team_id,
        )
    )
    share = existing.scalar_one_or_none()
    if share:
        return TeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            shared_at=share.created_at,
        )
    share = GlobalVariableTeamShare(global_variable_id=variable_id, team_id=payload.team_id)
    db.add(share)
    await db.flush()
    await db.refresh(share)
    await db.commit()
    return TeamShareResponse(
        id=share.id,
        team_id=team.id,
        team_name=team.name,
        shared_at=share.created_at,
    )


@router.delete("/{variable_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_global_variable_team_share(
    variable_id: uuid.UUID,
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.id == variable_id,
            GlobalVariable.owner_id == current_user.id,
        )
    )
    variable = result.scalar_one_or_none()
    if variable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variable not found",
        )
    share_result = await db.execute(
        select(GlobalVariableTeamShare).where(
            GlobalVariableTeamShare.global_variable_id == variable_id,
            GlobalVariableTeamShare.team_id == team_id,
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team share not found",
        )
    await db.delete(share)
    await db.commit()
