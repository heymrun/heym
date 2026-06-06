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


async def persist_global_variables_from_execution(
    db: AsyncSession,
    owner_id: uuid.UUID,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    node_results: list[dict],
    sub_workflow_executions: list,
) -> None:
    """Extract isGlobal variable node outputs and upsert to global variables."""

    async def _upsert_from_results(nodes: list[dict], results: list[dict]) -> None:
        nodes_by_id = {n.get("id"): n for n in nodes if n.get("id")}
        for nr in results:
            if not isinstance(nr, dict) or nr.get("node_type") != "variable":
                continue
            node_id = nr.get("node_id")
            node = nodes_by_id.get(node_id) if node_id else None
            if not node or not node.get("data", {}).get("isGlobal"):
                continue
            output = nr.get("output") or {}
            name = output.get("name")
            value = output.get("value")
            value_type = output.get("type", "string")
            if name is not None:
                await upsert_global_variable(db, owner_id, name, value, value_type)

    await _upsert_from_results(workflow_nodes, node_results)

    for sub in sub_workflow_executions:
        sub_node_results = (
            sub.node_results if hasattr(sub, "node_results") else sub.get("node_results", [])
        )
        sub_wf_id = sub.workflow_id if hasattr(sub, "workflow_id") else sub.get("workflow_id", "")
        sub_wf = workflow_cache.get(str(sub_wf_id), {})
        sub_nodes = sub_wf.get("nodes", [])
        await _upsert_from_results(sub_nodes, sub_node_results)
