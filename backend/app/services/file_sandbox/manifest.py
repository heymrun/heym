"""Drive files the file sandbox may open, resolved through the one Drive access rule.

Every lookup goes through ``drive_file_access_rows``: a user reaches a file they
own or one shared with a team they belong to. Ids and names that arrive from a
model are never trusted; each is resolved again here for the actor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import GeneratedFile
from app.services.drive_file_access import GRANT_SHARED, drive_file_access_rows
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_storage import get_file_path


class FileAccessError(ValueError):
    """A requested file is missing or the actor cannot reach it."""


@dataclass(frozen=True)
class DriveFileRef:
    """One Drive file the actor reaches. ``storage_path`` never leaves the backend."""

    id: uuid.UUID
    name: str
    mime: str | None
    size: int | None
    created_at: datetime | None
    source: str | None
    workflow_id: uuid.UUID | None
    shared: bool
    # None when the stored path is unusable; such a file is listed but cannot be opened.
    storage_path: Path | None

    def public(self) -> dict[str, object]:
        """Metadata safe to show a model or the sandbox: no paths, URLs or tokens."""
        return {
            "id": str(self.id),
            "name": self.name,
            "mime": self.mime,
            "size": self.size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source,
            "shared": self.shared,
        }


def _accessible(user_id: uuid.UUID, scope: RunFileScope | None = None) -> Select:
    """Files the user reaches; with a run scope, only the files that scope covers."""
    grants = drive_file_access_rows(user_id).subquery()
    stmt = select(GeneratedFile, grants.c.grant).join(grants, grants.c.file_id == GeneratedFile.id)
    if scope is not None:
        stmt = stmt.where(
            or_(
                GeneratedFile.id.in_(list(scope.file_ids)),
                GeneratedFile.workflow_id.in_(list(scope.workflow_ids)),
            )
        )
    return stmt


def _storage_path(row: GeneratedFile) -> Path | None:
    try:
        return get_file_path(row)
    except ValueError:
        return None


def _to_ref(row: GeneratedFile, grant: str) -> DriveFileRef:
    return DriveFileRef(
        id=row.id,
        name=row.filename,
        mime=row.mime_type,
        size=row.size_bytes,
        created_at=row.created_at,
        source=row.source_node_label,
        workflow_id=row.workflow_id,
        shared=grant == GRANT_SHARED,
        storage_path=_storage_path(row),
    )


def list_accessible_files(
    db: Session,
    user_id: uuid.UUID,
    *,
    query: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    scope: RunFileScope | None = None,
) -> tuple[list[DriveFileRef], int]:
    """Files the user reaches (within ``scope`` when given), newest first, with the total."""
    stmt = _accessible(user_id, scope)
    if query and query.strip():
        stmt = stmt.where(GeneratedFile.filename.ilike(f"%{query.strip()}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(GeneratedFile.created_at.desc(), GeneratedFile.id).offset(max(0, offset))
    if limit is not None:
        stmt = stmt.limit(limit)
    return [_to_ref(row, grant) for row, grant in db.execute(stmt).all()], int(total)


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def resolve_files(
    db: Session, user_id: uuid.UUID, refs: list[str], *, scope: RunFileScope | None = None
) -> list[DriveFileRef]:
    """Resolve ids or exact filenames (newest match wins) for the user, in order.

    With ``scope`` only the files a workflow run may open resolve; the rest fail like
    a missing file.

    Raises:
        FileAccessError: with one message for missing and unreachable files alike, so
            the answer never tells whether someone else's id exists.
    """
    resolved: list[DriveFileRef] = []
    seen: set[uuid.UUID] = set()
    for raw in refs:
        ref = str(raw or "").strip()
        if not ref:
            continue
        file_id = _parse_uuid(ref)
        stmt = _accessible(user_id, scope)
        if file_id is not None:
            stmt = stmt.where(GeneratedFile.id == file_id)
        else:
            stmt = stmt.where(GeneratedFile.filename == ref)
        row = db.execute(stmt.order_by(GeneratedFile.created_at.desc()).limit(1)).first()
        if row is None:
            raise FileAccessError(f"File not found or not accessible: {ref}")
        file_ref = _to_ref(row[0], row[1])
        if file_ref.storage_path is None or not file_ref.storage_path.is_file():
            raise FileAccessError(f"File content is missing from storage: {file_ref.name}")
        if file_ref.id not in seen:
            seen.add(file_ref.id)
            resolved.append(file_ref)
    return resolved


def accessible_files_by_id(
    db: Session,
    user_id: uuid.UUID,
    file_ids: set[uuid.UUID],
    *,
    scope: RunFileScope | None = None,
) -> list[DriveFileRef]:
    """The files among ``file_ids`` the user reaches (within ``scope``); others are dropped."""
    if not file_ids:
        return []
    stmt = _accessible(user_id, scope).where(GeneratedFile.id.in_(file_ids))
    rows = db.execute(stmt.order_by(GeneratedFile.created_at.desc(), GeneratedFile.id)).all()
    return [_to_ref(row, grant) for row, grant in rows]


def still_accessible(db: Session, user_id: uuid.UUID, file_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The subset of ``file_ids`` the user still reaches (shares can be revoked)."""
    if not file_ids:
        return set()
    grants = drive_file_access_rows(user_id).subquery()
    rows = db.execute(select(grants.c.file_id).where(grants.c.file_id.in_(file_ids))).all()
    return {row[0] for row in rows}
