"""Keep `credentials` rows (never values) in line with the labelled Secrets.

Only the leader applies changes, so one process writes at a time. The admin view runs
the same planning read-only, from whichever process serves the request.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Credential,
    CredentialShare,
    CredentialTeamShare,
    CredentialType,
    Team,
    User,
)
from app.services.k8s_credentials.store import POINTER_PREFIX, SecretCredential

logger = logging.getLogger("k8s_credentials")

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"
STATUS_INVALID = "invalid"
STATUS_OWNER_MISSING = "owner_missing"
STATUS_NAME_CONFLICT = "name_conflict"


@dataclass
class SecretStatus:
    """One Secret-backed credential as the admin view shows it."""

    namespace: str
    secret_name: str
    credential_id: uuid.UUID
    name: str
    type: str
    owner_email: str
    status: str
    detail: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Desired:
    item: SecretCredential
    owner_id: uuid.UUID
    user_ids: set[uuid.UUID]
    team_ids: set[uuid.UUID]


def _status(item: SecretCredential, status: str, detail: str | None = None) -> SecretStatus:
    return SecretStatus(
        namespace=item.namespace,
        secret_name=item.secret_name,
        credential_id=item.credential_id,
        name=item.name,
        type=item.type,
        owner_email=item.owner_email,
        status=status,
        detail=detail,
    )


async def _users_by_email(db: AsyncSession, emails: set[str]) -> dict[str, uuid.UUID]:
    if not emails:
        return {}
    rows = await db.execute(
        select(func.lower(User.email), User.id).where(func.lower(User.email).in_(emails))
    )
    return {email: user_id for email, user_id in rows.all()}


async def _teams_by_name(db: AsyncSession, names: set[str]) -> dict[str, list[uuid.UUID]]:
    if not names:
        return {}
    rows = await db.execute(select(Team.name, Team.id).where(Team.name.in_(names)))
    teams: dict[str, list[uuid.UUID]] = {}
    for name, team_id in rows.all():
        teams.setdefault(name, []).append(team_id)
    return teams


async def plan(
    db: AsyncSession, items: list[SecretCredential]
) -> tuple[list[SecretStatus], list[_Desired]]:
    """What each Secret should become, and the status the admin view shows for it."""
    emails = {i.owner_email for i in items} | {e for i in items for e in i.share_users}
    users = await _users_by_email(db, emails)
    teams = await _teams_by_name(db, {t for i in items for t in i.share_teams})
    existing = {
        row.id: row
        for row in (
            await db.execute(select(Credential).where(Credential.source.is_not(None)))
        ).scalars()
    }

    statuses: list[SecretStatus] = []
    desired: list[_Desired] = []
    claimed_names: set[tuple[uuid.UUID, str]] = set()
    for item in sorted(items, key=lambda i: (i.namespace, i.secret_name)):
        if item.problem:
            statuses.append(_status(item, STATUS_INVALID, item.problem))
            continue
        owner_id = users.get(item.owner_email)
        if owner_id is None:
            statuses.append(
                _status(item, STATUS_OWNER_MISSING, f"no user with email {item.owner_email}")
            )
            continue
        clash = (
            await db.execute(
                select(Credential.id).where(
                    Credential.owner_id == owner_id,
                    Credential.name == item.name,
                    Credential.id != item.credential_id,
                )
            )
        ).first()
        if clash is not None or (owner_id, item.name) in claimed_names:
            statuses.append(
                _status(
                    item,
                    STATUS_NAME_CONFLICT,
                    f"{item.owner_email} already has a credential named {item.name!r}",
                )
            )
            continue
        claimed_names.add((owner_id, item.name))

        status = _status(item, STATUS_AVAILABLE)
        user_ids: set[uuid.UUID] = set()
        for email in item.share_users:
            if email in users:
                if users[email] != owner_id:
                    user_ids.add(users[email])
            else:
                status.warnings.append(f"share-users: no user with email {email}")
        team_ids: set[uuid.UUID] = set()
        for team in item.share_teams:
            matches = teams.get(team, [])
            if len(matches) == 1:
                team_ids.add(matches[0])
            elif matches:
                status.warnings.append(f"share-teams: {len(matches)} teams are named {team!r}")
            else:
                status.warnings.append(f"share-teams: no team named {team!r}")
        statuses.append(status)
        desired.append(_Desired(item, owner_id, user_ids, team_ids))

    present = {i.credential_id for i in items}
    for row in existing.values():
        if row.id not in present:
            source = (row.source or "").removeprefix(POINTER_PREFIX)
            namespace, _, secret_name = source.partition("/")
            statuses.append(
                SecretStatus(
                    namespace=namespace,
                    secret_name=secret_name,
                    credential_id=row.id,
                    name=row.name,
                    type=row.type.value,
                    owner_email="",
                    status=STATUS_UNAVAILABLE,
                    detail=f"Secret {source} not found",
                )
            )
    return statuses, desired


async def _sync_shares(db: AsyncSession, want: _Desired) -> bool:
    credential_id = want.item.credential_id
    have_users = set(
        (
            await db.execute(
                select(CredentialShare.user_id).where(
                    CredentialShare.credential_id == credential_id
                )
            )
        ).scalars()
    )
    have_teams = set(
        (
            await db.execute(
                select(CredentialTeamShare.team_id).where(
                    CredentialTeamShare.credential_id == credential_id
                )
            )
        ).scalars()
    )
    for user_id in want.user_ids - have_users:
        db.add(CredentialShare(credential_id=credential_id, user_id=user_id))
    for team_id in want.team_ids - have_teams:
        db.add(CredentialTeamShare(credential_id=credential_id, team_id=team_id))
    if have_users - want.user_ids:
        await db.execute(
            delete(CredentialShare).where(
                CredentialShare.credential_id == credential_id,
                CredentialShare.user_id.in_(have_users - want.user_ids),
            )
        )
    if have_teams - want.team_ids:
        await db.execute(
            delete(CredentialTeamShare).where(
                CredentialTeamShare.credential_id == credential_id,
                CredentialTeamShare.team_id.in_(have_teams - want.team_ids),
            )
        )
    return have_users != want.user_ids or have_teams != want.team_ids


async def reconcile(db: AsyncSession, items: list[SecretCredential]) -> list[SecretStatus]:
    """Create and update rows and shares to match the Secrets. Never deletes a row.

    A row whose Secret is gone stays, unavailable, keeping its id and shares: if the
    Secret comes back, workflows that reference it work again unchanged. An admin
    removes it from the admin view when it is really gone.
    """
    statuses, desired = await plan(db, items)
    for want in desired:
        item = want.item
        row = await db.get(Credential, item.credential_id)
        credential_type = CredentialType(item.type)
        if row is None:
            db.add(
                Credential(
                    id=item.credential_id,
                    owner_id=want.owner_id,
                    name=item.name,
                    type=credential_type,
                    source=item.pointer,
                    encrypted_config=item.pointer,
                )
            )
            logger.info("Created credential %r from Secret %s", item.name, item.pointer)
        elif (row.owner_id, row.name, row.type) != (want.owner_id, item.name, credential_type):
            row.owner_id, row.name, row.type = want.owner_id, item.name, credential_type
            logger.info("Updated credential %r from Secret %s", item.name, item.pointer)
        await db.flush()
        await _sync_shares(db, want)
    await db.commit()
    return statuses
