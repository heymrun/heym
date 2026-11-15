"""Service for loading and persisting global variables (used by workflow executor)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GlobalVariable, GlobalVariableShare, GlobalVariableTeamShare, TeamMember


def _extract_value(raw: object) -> object:
    if isinstance(raw, dict) and "v" in raw:
        return raw["v"]
    return raw


async def get_global_variables_context(db: AsyncSession, owner_id: uuid.UUID) -> dict[str, object]:
    """Load all global variables accessible by a user as name->value dict.

    Includes owned variables, user-shared variables, and team-shared variables.
    Priority order (highest wins): owned > user-shared > team-shared.
    """
    out: dict[str, object] = {}

    # Fetch team-shared variables (lowest priority)
    team_shared_result = await db.execute(
        select(GlobalVariable)
        .join(
            GlobalVariableTeamShare,
            GlobalVariableTeamShare.global_variable_id == GlobalVariable.id,
        )
        .join(TeamMember, TeamMember.team_id == GlobalVariableTeamShare.team_id)
        .where(TeamMember.user_id == owner_id)
        .order_by(
            GlobalVariable.name.asc(),
            GlobalVariableTeamShare.created_at.asc(),
            GlobalVariable.id.asc(),
        )
    )
    for v in team_shared_result.scalars().all():
        out[v.name] = _extract_value(v.value)

    # Fetch user-shared variables (override team-shared)
    shared_result = await db.execute(
        select(GlobalVariable)
        .join(GlobalVariableShare, GlobalVariableShare.global_variable_id == GlobalVariable.id)
        .where(GlobalVariableShare.user_id == owner_id)
        .order_by(
            GlobalVariable.name.asc(),
            GlobalVariableShare.created_at.asc(),
            GlobalVariable.id.asc(),
        )
    )
    for v in shared_result.scalars().all():
        out[v.name] = _extract_value(v.value)

    # Fetch owned variables (override everything)
    owned_result = await db.execute(
        select(GlobalVariable)
        .where(GlobalVariable.owner_id == owner_id)
        .order_by(GlobalVariable.name.asc())
    )
    for v in owned_result.scalars().all():
        out[v.name] = _extract_value(v.value)

    return out


async def upsert_global_variable(
    db: AsyncSession,
    owner_id: uuid.UUID,
    name: str,
    value: object,
    value_type: str = "string",
) -> None:
    """Create or update a global variable by name.

    One INSERT ... ON CONFLICT DO UPDATE: with a read then an insert, two runs that set
    the same new variable at once both inserted, and the second commit failed on
    uq_global_variable_name, losing that run's whole persistence transaction.
    """
    stored = {"v": value}
    await db.execute(
        pg_insert(GlobalVariable)
        .values(id=uuid.uuid4(), owner_id=owner_id, name=name, value=stored, value_type=value_type)
        .on_conflict_do_update(
            constraint="uq_global_variable_name",
            set_={"value": stored, "value_type": value_type, "updated_at": func.now()},
        )
    )
