"""Who can reach a vector store.

A user reaches a store by owning it, by a direct share, or through a team the store is
shared with. Shares carry no permission level: anyone a store is shared with can read,
search, clone and upload to it, while changing or deleting the store, its items and its
shares stays with the owner. Heym's vector store routes and Heym Work both read access
through this module.
"""

import uuid

from sqlalchemy import Select, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TeamMember, VectorStore, VectorStoreShare, VectorStoreTeamShare

GRANT_OWNER = "owner"
GRANT_SHARED = "shared"


async def get_vector_store_with_grant(
    db: AsyncSession, vector_store_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[VectorStore, str] | None:
    """The store and how the user reaches it (``owner`` or ``shared``), or None."""
    owned = (
        await db.execute(
            select(VectorStore).where(
                VectorStore.id == vector_store_id,
                VectorStore.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned is not None:
        return owned, GRANT_OWNER

    shared = (
        await db.execute(
            select(VectorStore)
            .join(VectorStoreShare, VectorStoreShare.vector_store_id == VectorStore.id)
            .where(
                VectorStore.id == vector_store_id,
                VectorStoreShare.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if shared is None:
        shared = (
            await db.execute(
                select(VectorStore).where(
                    VectorStore.id == vector_store_id,
                    VectorStore.id.in_(
                        select(VectorStoreTeamShare.vector_store_id).where(
                            VectorStoreTeamShare.team_id.in_(
                                select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                            )
                        )
                    ),
                )
            )
        ).scalar_one_or_none()
    if shared is None:
        return None
    return shared, GRANT_SHARED


def vector_store_access_rows(user_id: uuid.UUID) -> Select:
    """One ``(vector_store_id, grant)`` row per store ``user_id`` reaches; owner beats shared."""
    team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    grants = union_all(
        select(VectorStore.id.label("vector_store_id"), literal(GRANT_OWNER).label("grant")).where(
            VectorStore.owner_id == user_id
        ),
        select(
            VectorStoreShare.vector_store_id.label("vector_store_id"),
            literal(GRANT_SHARED).label("grant"),
        ).where(VectorStoreShare.user_id == user_id),
        select(
            VectorStoreTeamShare.vector_store_id.label("vector_store_id"),
            literal(GRANT_SHARED).label("grant"),
        ).where(VectorStoreTeamShare.team_id.in_(team_ids)),
    ).subquery()
    is_owner = func.max(case((grants.c.grant == GRANT_OWNER, 1), else_=0))
    return select(
        grants.c.vector_store_id,
        case((is_owner == 1, GRANT_OWNER), else_=GRANT_SHARED).label("grant"),
    ).group_by(grants.c.vector_store_id)
