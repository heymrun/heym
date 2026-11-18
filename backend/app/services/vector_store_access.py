"""Who can reach a vector store, and how far.

A user reaches a store by owning it, by a direct share, or through a team the store is
shared with; the strongest grant wins. A ``read`` share can list, search and clone the store
and use it in a RAG search. A ``write`` share can also add documents, delete them, and run RAG
insert, upsert and delete operations. Renaming or deleting the store and changing its shares
stay with the owner. Heym's vector store routes, the RAG node and Heym Work all read access
through this module.
"""

import uuid

from sqlalchemy import Select, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TeamMember, VectorStore, VectorStoreShare, VectorStoreTeamShare

GRANT_OWNER = "owner"
GRANT_SHARED = "shared"

PERMISSION_OWNER = "owner"
PERMISSION_WRITE = "write"
PERMISSION_READ = "read"
_RANK = {PERMISSION_READ: 1, PERMISSION_WRITE: 2, PERMISSION_OWNER: 3}

# RAG node operations that change a store's documents.
WRITE_OPERATIONS = frozenset({"insert", "upsert", "delete"})


def strongest_share_permission(permissions: list[str]) -> str | None:
    """Collapse share grants into one permission: any ``write`` wins over ``read``."""
    if not permissions:
        return None
    return PERMISSION_WRITE if PERMISSION_WRITE in permissions else PERMISSION_READ


def can_write(permission: str) -> bool:
    """Whether ``permission`` lets a user change the store's documents."""
    return permission in (PERMISSION_OWNER, PERMISSION_WRITE)


async def get_vector_store_with_permission(
    db: AsyncSession, vector_store_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[VectorStore, str] | None:
    """The store and the user's strongest permission on it, or None when unreachable."""
    owned = (
        await db.execute(
            select(VectorStore).where(
                VectorStore.id == vector_store_id,
                VectorStore.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned is not None:
        return owned, PERMISSION_OWNER

    user_permissions = (
        (
            await db.execute(
                select(VectorStoreShare.permission).where(
                    VectorStoreShare.vector_store_id == vector_store_id,
                    VectorStoreShare.user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    team_permissions = (
        (
            await db.execute(
                select(VectorStoreTeamShare.permission).where(
                    VectorStoreTeamShare.vector_store_id == vector_store_id,
                    VectorStoreTeamShare.team_id.in_(
                        select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    permission = strongest_share_permission([*user_permissions, *team_permissions])
    if permission is None:
        return None
    store = (
        await db.execute(select(VectorStore).where(VectorStore.id == vector_store_id))
    ).scalar_one_or_none()
    if store is None:
        return None
    return store, permission


def vector_store_access_rows(user_id: uuid.UUID) -> Select:
    """One ``(vector_store_id, grant, permission)`` row per store ``user_id`` reaches.

    ``grant`` is ``owner`` or ``shared``; ``permission`` is the strongest of ``owner``,
    ``write`` and ``read``.
    """
    team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    grants = union_all(
        select(
            VectorStore.id.label("vector_store_id"),
            literal(PERMISSION_OWNER).label("permission"),
        ).where(VectorStore.owner_id == user_id),
        select(
            VectorStoreShare.vector_store_id.label("vector_store_id"),
            VectorStoreShare.permission.label("permission"),
        ).where(VectorStoreShare.user_id == user_id),
        select(
            VectorStoreTeamShare.vector_store_id.label("vector_store_id"),
            VectorStoreTeamShare.permission.label("permission"),
        ).where(VectorStoreTeamShare.team_id.in_(team_ids)),
    ).subquery()
    rank = case(
        {permission: value for permission, value in _RANK.items()},
        value=grants.c.permission,
        else_=0,
    )
    best = func.max(rank)
    return select(
        grants.c.vector_store_id,
        case((best == _RANK[PERMISSION_OWNER], GRANT_OWNER), else_=GRANT_SHARED).label("grant"),
        case(
            (best == _RANK[PERMISSION_OWNER], PERMISSION_OWNER),
            (best == _RANK[PERMISSION_WRITE], PERMISSION_WRITE),
            else_=PERMISSION_READ,
        ).label("permission"),
    ).group_by(grants.c.vector_store_id)
