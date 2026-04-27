"""Service for loading and persisting global variables (used by workflow executor)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GlobalVariable, GlobalVariableShare


def _extract_value(raw: object) -> object:
    if isinstance(raw, dict) and "v" in raw:
        return raw["v"]
    return raw


async def get_global_variables_context(db: AsyncSession, owner_id: uuid.UUID) -> dict[str, object]:
    """Load all global variables accessible by a user as name->value dict.

    Includes both owned variables and variables shared with this user.
    When a name collision occurs between an owned and a shared variable,
    the user's own variable takes precedence.
    """
    # Fetch variables shared with this user first (lower priority)
    shared_result = await db.execute(
        select(GlobalVariable)
        .join(GlobalVariableShare, GlobalVariableShare.global_variable_id == GlobalVariable.id)
        .where(GlobalVariableShare.user_id == owner_id)
        .order_by(GlobalVariable.name.asc())
    )
    shared_variables = shared_result.scalars().all()

    out: dict[str, object] = {}
    for v in shared_variables:
        out[v.name] = _extract_value(v.value)

    # Fetch owned variables and let them override shared ones with the same name
    owned_result = await db.execute(
        select(GlobalVariable)
        .where(GlobalVariable.owner_id == owner_id)
        .order_by(GlobalVariable.name.asc())
    )
    owned_variables = owned_result.scalars().all()
    for v in owned_variables:
        out[v.name] = _extract_value(v.value)

    return out


async def upsert_global_variable(
    db: AsyncSession,
    owner_id: uuid.UUID,
    name: str,
    value: object,
    value_type: str = "string",
) -> None:
    """Create or update a global variable by name."""
    result = await db.execute(
        select(GlobalVariable).where(
            GlobalVariable.owner_id == owner_id,
            GlobalVariable.name == name,
        )
    )
    existing = result.scalar_one_or_none()
    stored = {"v": value}
    if existing:
        existing.value = stored
        existing.value_type = value_type
    else:
        new_var = GlobalVariable(
            owner_id=owner_id,
            name=name,
            value=stored,
            value_type=value_type,
        )
        db.add(new_var)
