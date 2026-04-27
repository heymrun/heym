from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialShare, CredentialTeamShare, TeamMember


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
        select(Credential)
        .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
        .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
        .where(
            Credential.id == credential_id,
            TeamMember.user_id == user_id,
        )
    )
    return team_result.scalar_one_or_none()
