"""Service for storing, retrieving, and sharing generated files."""

import mimetypes
import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import FileAccessToken, GeneratedFile


def _storage_root() -> Path:
    return Path(settings.file_storage_dir)


def _normalize_storage_filename(filename: str) -> str:
    normalized = filename.strip()
    if not normalized:
        raise ValueError("Filename cannot be empty")
    if "\x00" in normalized:
        raise ValueError("Filename cannot contain NUL bytes")

    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(normalized)
    path_parts = list(posix_path.parts) + list(windows_path.parts)
    if (
        normalized in {".", ".."}
        or any(part == ".." for part in path_parts)
        or posix_path.name != normalized
        or windows_path.name != normalized
        or windows_path.drive
        or windows_path.root
    ):
        raise ValueError("Filename cannot contain path components")

    return normalized


def _safe_storage_path(relative_path: str) -> Path:
    storage_root = _storage_root().resolve()
    candidate = (storage_root / relative_path).resolve()
    if not candidate.is_relative_to(storage_root):
        raise ValueError("File path escapes storage root")
    return candidate


async def store_file(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
    mime_type: str | None = None,
    workflow_id: uuid.UUID | None = None,
    execution_history_id: uuid.UUID | None = None,
    source_node_id: str | None = None,
    source_node_label: str | None = None,
    metadata: dict | None = None,
) -> GeneratedFile:
    filename = _normalize_storage_filename(filename)

    if not mime_type:
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    max_bytes = settings.file_max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(
            f"File size ({len(file_bytes)} bytes) exceeds limit ({settings.file_max_size_mb} MB)"
        )

    file_uuid = uuid.uuid4()
    relative_path = f"{owner_id}/{file_uuid}/{filename}"
    absolute_path = _safe_storage_path(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(file_bytes)

    row = GeneratedFile(
        id=file_uuid,
        owner_id=owner_id,
        workflow_id=workflow_id,
        execution_history_id=execution_history_id,
        filename=filename,
        storage_path=relative_path,
        mime_type=mime_type,
        size_bytes=len(file_bytes),
        source_node_id=source_node_id,
        source_node_label=source_node_label,
        metadata_json=metadata or {},
    )
    db.add(row)
    await db.flush()
    return row


def get_file_path(generated_file: GeneratedFile) -> Path:
    return _safe_storage_path(generated_file.storage_path)


def load_readable_file_sync(
    db: object,
    *,
    file_id: uuid.UUID,
    owner_id: uuid.UUID,
    context: str = "File",
) -> tuple[GeneratedFile, bytes]:
    """Read a Drive file the user owns or a teammate shared with them.

    Uses the synchronous session the workflow executor runs on. Read access
    mirrors the Drive node's ``get`` rule: own files always,
    team-shared files when the user belongs to a team the file is shared with.
    """
    from app.db.models import FileTeamShare, TeamMember

    row = (
        db.query(GeneratedFile)
        .filter(GeneratedFile.id == file_id, GeneratedFile.owner_id == owner_id)
        .first()
    )
    if not row:
        row = (
            db.query(GeneratedFile)
            .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
            .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
            .filter(GeneratedFile.id == file_id, TeamMember.user_id == owner_id)
            .first()
        )
    if not row:
        raise ValueError(f"{context}: file not found or access denied: {file_id}")

    disk_path = get_file_path(row)
    if not disk_path.exists():
        raise ValueError(f"{context}: file content is missing on disk: {row.filename}")
    return row, disk_path.read_bytes()


def store_file_sync(
    db: object,
    *,
    owner_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    workflow_id: uuid.UUID | None = None,
    source_node_id: str | None = None,
    source_node_label: str | None = None,
    context: str = "File",
) -> tuple[GeneratedFile, str]:
    """Write a new Drive file plus its default access token, synchronously.

    Mirrors :func:`store_file` for the executor's synchronous session. Returns the
    row and the raw token string, which is what a download URL is built from.
    """
    from app.db.models import FileAccessToken

    filename = _normalize_storage_filename(filename)

    max_bytes = settings.file_max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"{context}: file exceeds the size limit ({settings.file_max_size_mb} MB)")

    file_uuid = uuid.uuid4()
    relative_path = f"{owner_id}/{file_uuid}/{filename}"
    absolute_path = _safe_storage_path(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(file_bytes)

    row = GeneratedFile(
        id=file_uuid,
        owner_id=owner_id,
        workflow_id=workflow_id,
        filename=filename,
        storage_path=relative_path,
        mime_type=mime_type,
        size_bytes=len(file_bytes),
        source_node_id=source_node_id,
        source_node_label=source_node_label,
        metadata_json={},
    )
    db.add(row)
    db.flush()

    token = secrets.token_urlsafe(32)
    db.add(FileAccessToken(file_id=file_uuid, token=token, created_by_id=owner_id))
    return row, token


async def delete_file(db: AsyncSession, generated_file: GeneratedFile) -> None:
    disk_path = get_file_path(generated_file)
    if disk_path.exists():
        disk_path.unlink()
        parent = disk_path.parent
        if parent.exists() and not any(parent.iterdir()):
            shutil.rmtree(parent, ignore_errors=True)

    await db.delete(generated_file)
    await db.flush()


async def create_access_token(
    db: AsyncSession,
    *,
    file_id: uuid.UUID,
    created_by_id: uuid.UUID,
    expires_hours: int | None = None,
    basic_auth_password: str | None = None,
    max_downloads: int | None = None,
) -> FileAccessToken:
    token_str = secrets.token_urlsafe(32)

    password_hash: str | None = None
    username: str | None = None
    if basic_auth_password:
        username = "file"
        password_hash = bcrypt.hashpw(basic_auth_password.encode(), bcrypt.gensalt()).decode()

    expires_at = None
    if expires_hours is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

    row = FileAccessToken(
        file_id=file_id,
        token=token_str,
        basic_auth_username=username,
        basic_auth_password_hash=password_hash,
        expires_at=expires_at,
        max_downloads=max_downloads,
        created_by_id=created_by_id,
    )
    db.add(row)
    await db.flush()
    return row


async def validate_access_token(db: AsyncSession, token: str) -> FileAccessToken | None:
    stmt = select(FileAccessToken).where(FileAccessToken.token == token)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at and row.expires_at < now:
        return None
    if row.max_downloads is not None and row.download_count >= row.max_downloads:
        return None
    return row


async def validate_basic_auth(
    db: AsyncSession,
    file_id: uuid.UUID,
    username: str,
    password: str,
) -> FileAccessToken | None:
    stmt = (
        select(FileAccessToken)
        .where(FileAccessToken.file_id == file_id)
        .where(FileAccessToken.basic_auth_username == username)
        .where(FileAccessToken.basic_auth_password_hash.isnot(None))
    )
    rows = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.expires_at and row.expires_at < now:
            continue
        if row.max_downloads is not None and row.download_count >= row.max_downloads:
            continue
        if bcrypt.checkpw(password.encode(), row.basic_auth_password_hash.encode()):
            return row
    return None


async def increment_download_count(db: AsyncSession, access_token: FileAccessToken) -> None:
    access_token.download_count += 1
    await db.flush()


def build_download_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/api/files/dl/{token}"
