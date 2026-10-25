from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialShare, CredentialTeamShare, TeamMember


def team_shared_credential_clause(user_id: UUID):
    """WHERE clause for credentials shared with any team the user belongs to.

    Uses IN subqueries rather than a join to ``TeamMember`` so a user who is in two teams that
    both hold the share still matches a single row.
    """
    return Credential.id.in_(
        select(CredentialTeamShare.credential_id).where(
            CredentialTeamShare.team_id.in_(
                select(TeamMember.team_id).where(TeamMember.user_id == user_id)
            )
        )
    )


def accessible_credential_clause(user_id: UUID):
    """WHERE clause for credentials the user owns or that were shared with them or their teams.

    A credential shared with another user or with a team this user is not in never matches.
    """
    return or_(
        Credential.owner_id == user_id,
        Credential.id.in_(
            select(CredentialShare.credential_id).where(CredentialShare.user_id == user_id)
        ),
        team_shared_credential_clause(user_id),
    )


async def load_accessible_credential_ids(db: AsyncSession, user_id: UUID) -> set[str]:
    """Ids of every credential the user may use, by the rules `get_accessible_credential` applies."""
    result = await db.execute(select(Credential.id).where(accessible_credential_clause(user_id)))
    return {str(credential_id) for credential_id in result.scalars().all()}


async def get_accessible_credential(
    db: AsyncSession,
    credential_id: UUID,
    user_id: UUID,
) -> Credential | None:
    """Return a credential the user owns or that has been shared with them."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.owner_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is not None:
        return credential

    shared_result = await db.execute(
        select(Credential)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .where(
            Credential.id == credential_id,
            CredentialShare.user_id == user_id,
        )
    )
    credential = shared_result.scalar_one_or_none()
    if credential is not None:
        return credential

    team_result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            team_shared_credential_clause(user_id),
        )
    )
    return team_result.scalar_one_or_none()
