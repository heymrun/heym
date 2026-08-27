"""API endpoints for generated file management and downloads."""

import base64
import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import FileAccessToken, FileTeamShare, GeneratedFile, Team, TeamMember, User
from app.db.session import get_db
from app.models.schemas import (
    BulkCreateFileShareRequest,
    BulkFileDeleteRequest,
    BulkFileDownloadRequest,
    BulkFileOperationResponse,
    BulkFileTeamSharingRequest,
    CreateFileShareRequest,
    FileAccessTokenResponse,
    FileListResponse,
    FileTeamSharingRequest,
    FileTeamSharingResponse,
    GeneratedFileResponse,
)
from app.services.audit_log import audit
from app.services.file_storage import (
    build_download_url,
    create_access_token,
    delete_file,
    get_file_path,
    increment_download_count,
    store_file,
    validate_access_token,
    validate_basic_auth,
)
from app.services.hitl_service import build_public_base_url
from app.services.upload_limits import read_upload_file_limited

router = APIRouter()


def _build_authenticated_download_url(base_url: str, file_id: uuid.UUID) -> str:
    return f"{base_url.rstrip('/')}/api/files/{file_id}/download"


def _file_to_response(
    f: GeneratedFile,
    base_url: str,
    *,
    is_shared: bool = False,
    shared_by: str | None = None,
    shared_by_team: str | None = None,
) -> GeneratedFileResponse:
    default_token = next((t for t in f.access_tokens if t.basic_auth_password_hash is None), None)
    download_url = ""
    if default_token:
        download_url = build_download_url(base_url, default_token.token)
    team_shares = getattr(f, "team_shares", None) or []
    return GeneratedFileResponse(
        id=f.id,
        filename=f.filename,
        mime_type=f.mime_type,
        size_bytes=f.size_bytes,
        workflow_id=f.workflow_id,
        source_node_label=f.source_node_label,
        download_url=download_url,
        authenticated_download_url=_build_authenticated_download_url(base_url, f.id),
        is_shared=is_shared,
        shared_by=shared_by,
        shared_by_team=shared_by_team,
        shared_with_my_teams=len(team_shares) > 0,
        created_at=f.created_at,
    )


def _build_basic_auth_url(base_url: str, file_id: uuid.UUID) -> str:
    return f"{base_url.rstrip('/')}/api/files/ba/{file_id}"


def _token_to_response(t: FileAccessToken, base_url: str) -> FileAccessTokenResponse:
    if t.basic_auth_password_hash is not None:
        download_url = _build_basic_auth_url(base_url, t.file_id)
    else:
        download_url = build_download_url(base_url, t.token)
    return FileAccessTokenResponse(
        id=t.id,
        token=t.token,
        download_url=download_url,
        basic_auth_enabled=t.basic_auth_password_hash is not None,
        expires_at=t.expires_at,
        download_count=t.download_count,
        max_downloads=t.max_downloads,
        created_at=t.created_at,
    )


async def _refresh_file_response_relations(db: AsyncSession, row: GeneratedFile) -> None:
    await db.refresh(row, ["access_tokens", "team_shares"])


async def _get_owned_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GeneratedFile | None:
    return (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id,
                GeneratedFile.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def _get_accessible_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    user: User,
) -> tuple[GeneratedFile, bool, str | None, str | None] | None:
    owned = await _get_owned_file(db, file_id, user.id)
    if owned is not None:
        return owned, False, None, None

    shared_result = await db.execute(
        select(GeneratedFile, User.email, Team.name)
        .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
        .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
        .join(Team, Team.id == FileTeamShare.team_id)
        .join(User, User.id == GeneratedFile.owner_id)
        .where(GeneratedFile.id == file_id, TeamMember.user_id == user.id)
        .order_by(Team.name.asc())
    )
    shared = shared_result.first()
    if shared is None:
        return None
    row, owner_email, team_name = shared
    return row, True, owner_email, team_name


async def _current_user_team_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(Team.id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
    )
    return list(result.scalars().all())


async def _set_file_team_sharing(
    db: AsyncSession,
    *,
    file_id: uuid.UUID,
    owner_id: uuid.UUID,
    enabled: bool,
) -> int:
    if not enabled:
        await db.execute(delete(FileTeamShare).where(FileTeamShare.file_id == file_id))
        await db.flush()
        return 0

    team_ids = await _current_user_team_ids(db, owner_id)
    if not team_ids:
        count_result = await db.execute(
            select(func.count(FileTeamShare.id)).where(FileTeamShare.file_id == file_id)
        )
        return int(count_result.scalar() or 0)

    existing_result = await db.execute(
        select(FileTeamShare.team_id).where(FileTeamShare.file_id == file_id)
    )
    existing_team_ids = set(existing_result.scalars().all())
    for team_id in team_ids:
        if team_id not in existing_team_ids:
            db.add(FileTeamShare(file_id=file_id, team_id=team_id))
    await db.flush()

    count_result = await db.execute(
        select(func.count(FileTeamShare.id)).where(FileTeamShare.file_id == file_id)
    )
    return int(count_result.scalar() or 0)


# ---- Authenticated endpoints ----


@router.get("", response_model=FileListResponse)
async def list_files(
    request: Request,
    workflow_id: uuid.UUID | None = None,
    mime_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileListResponse:
    base_url = build_public_base_url(request)
    owned_query = select(GeneratedFile).where(GeneratedFile.owner_id == user.id)
    shared_query = (
        select(GeneratedFile, User.email, Team.name)
        .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
        .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
        .join(Team, Team.id == FileTeamShare.team_id)
        .join(User, User.id == GeneratedFile.owner_id)
        .where(TeamMember.user_id == user.id)
    )

    if workflow_id:
        owned_query = owned_query.where(GeneratedFile.workflow_id == workflow_id)
        shared_query = shared_query.where(GeneratedFile.workflow_id == workflow_id)
    if mime_type:
        owned_query = owned_query.where(GeneratedFile.mime_type.ilike(f"%{mime_type}%"))
        shared_query = shared_query.where(GeneratedFile.mime_type.ilike(f"%{mime_type}%"))

    owned_rows = (await db.execute(owned_query)).scalars().all()
    shared_rows = (await db.execute(shared_query)).all()

    response_rows: list[tuple[GeneratedFile, bool, str | None, str | None]] = []
    seen_ids: set[uuid.UUID] = set()
    for row in owned_rows:
        seen_ids.add(row.id)
        response_rows.append((row, False, None, None))
    for row, owner_email, team_name in shared_rows:
        if row.id in seen_ids:
            continue
        seen_ids.add(row.id)
        response_rows.append((row, True, owner_email, team_name))

    response_rows.sort(key=lambda item: item[0].created_at, reverse=True)
    total = len(response_rows)
    paginated_rows = response_rows[offset : offset + limit]

    for row, _is_shared, _shared_by, _shared_by_team in paginated_rows:
        await _refresh_file_response_relations(db, row)

    return FileListResponse(
        files=[
            _file_to_response(
                row,
                base_url,
                is_shared=is_shared,
                shared_by=shared_by,
                shared_by_team=shared_by_team,
            )
            for row, is_shared, shared_by, shared_by_team in paginated_rows
        ],
        total=total,
    )


@router.get("/{file_id}", response_model=GeneratedFileResponse)
async def get_file_metadata(
    file_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedFileResponse:
    base_url = build_public_base_url(request)
    access = await _get_accessible_file(db, file_id, user)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    row, is_shared, shared_by, shared_by_team = access
    await _refresh_file_response_relations(db, row)
    return _file_to_response(
        row,
        base_url,
        is_shared=is_shared,
        shared_by=shared_by,
        shared_by_team=shared_by_team,
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_endpoint(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_owned_file(db, file_id, user.id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    audit(
        action="drive.delete",
        actor=user,
        target_type="file",
        target_id=row.id,
        target_name=row.filename,
    )
    await delete_file(db, row)
    await db.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_files_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all generated files (and their share tokens) for the current user."""

    query = select(GeneratedFile).where(GeneratedFile.owner_id == user.id)
    rows = (await db.execute(query)).scalars().all()
    audit(action="drive.delete_all", actor=user, target_type="file", count=len(rows))
    for row in rows:
        await delete_file(db, row)
    await db.commit()


@router.post("/delete/bulk", response_model=BulkFileOperationResponse)
async def bulk_delete_files(
    payload: BulkFileDeleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkFileOperationResponse:
    """Delete multiple owned files (and their share tokens) in one request."""
    succeeded: list[uuid.UUID] = []
    failed: list[uuid.UUID] = []
    for file_id in payload.file_ids:
        row = await _get_owned_file(db, file_id, user.id)
        if not row:
            failed.append(file_id)
            continue
        await delete_file(db, row)
        succeeded.append(file_id)
    await db.commit()
    audit(
        action="drive.bulk_delete",
        actor=user,
        target_type="file",
        deleted=len(succeeded),
        failed=len(failed),
    )
    return BulkFileOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/upload", response_model=GeneratedFileResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    share_with_my_teams: bool = Form(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedFileResponse:
    """Upload a file manually to Drive."""
    base_url = build_public_base_url(request)
    file_bytes = await read_upload_file_limited(file)
    try:
        row = await store_file(
            db,
            owner_id=user.id,
            file_bytes=file_bytes,
            filename=file.filename or "upload",
            mime_type=file.content_type,
            source_node_label="manual upload",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await create_access_token(db, file_id=row.id, created_by_id=user.id)
    if share_with_my_teams:
        await _set_file_team_sharing(db, file_id=row.id, owner_id=user.id, enabled=True)
    await db.commit()
    audit(
        action="drive.upload",
        actor=user,
        target_type="file",
        target_id=row.id,
        target_name=row.filename,
        file_size=len(file_bytes),
        mime=row.mime_type,
        team_shared=share_with_my_teams,
    )
    await _refresh_file_response_relations(db, row)
    return _file_to_response(row, base_url)


@router.patch("/{file_id}/team-sharing", response_model=FileTeamSharingResponse)
async def update_file_team_sharing(
    file_id: uuid.UUID,
    payload: FileTeamSharingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileTeamSharingResponse:
    row = await _get_owned_file(db, file_id, user.id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    shared_team_count = await _set_file_team_sharing(
        db,
        file_id=file_id,
        owner_id=user.id,
        enabled=payload.enabled,
    )
    await db.commit()
    audit(
        action="drive.team_sharing_update",
        actor=user,
        target_type="file",
        target_id=file_id,
        target_name=row.filename,
        enabled=payload.enabled,
        shared_team_count=shared_team_count,
    )
    return FileTeamSharingResponse(
        enabled=shared_team_count > 0,
        shared_team_count=shared_team_count,
    )


@router.patch("/team-sharing/bulk", response_model=BulkFileOperationResponse)
async def bulk_update_file_team_sharing(
    payload: BulkFileTeamSharingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkFileOperationResponse:
    """Enable or disable team sharing for multiple owned files in one request."""
    succeeded: list[uuid.UUID] = []
    failed: list[uuid.UUID] = []
    for file_id in payload.file_ids:
        row = await _get_owned_file(db, file_id, user.id)
        if not row:
            failed.append(file_id)
            continue
        await _set_file_team_sharing(
            db,
            file_id=file_id,
            owner_id=user.id,
            enabled=payload.enabled,
        )
        succeeded.append(file_id)
    await db.commit()
    audit(
        action="drive.bulk_team_sharing_update",
        actor=user,
        target_type="file",
        enabled=payload.enabled,
        updated=len(succeeded),
        failed=len(failed),
    )
    return BulkFileOperationResponse(succeeded=succeeded, failed=failed)


@router.post("/{file_id}/share", response_model=FileAccessTokenResponse)
async def create_share(
    file_id: uuid.UUID,
    payload: CreateFileShareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileAccessTokenResponse:
    base_url = build_public_base_url(request)
    row = await _get_owned_file(db, file_id, user.id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    token = await create_access_token(
        db,
        file_id=file_id,
        created_by_id=user.id,
        expires_hours=payload.expires_hours,
        basic_auth_password=payload.basic_auth_password,
        max_downloads=payload.max_downloads,
    )
    await db.commit()
    audit(
        action="drive.share_create",
        actor=user,
        target_type="file",
        target_id=file_id,
        target_name=row.filename,
        share_id=token.id,
        expires_hours=payload.expires_hours,
        max_downloads=payload.max_downloads,
        password_protected=payload.basic_auth_password is not None,
    )
    return _token_to_response(token, base_url)


@router.post("/share/bulk", response_model=BulkFileOperationResponse)
async def bulk_create_share(
    payload: BulkCreateFileShareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkFileOperationResponse:
    """Create a share link with the same settings for multiple owned files."""
    succeeded: list[uuid.UUID] = []
    failed: list[uuid.UUID] = []
    for file_id in payload.file_ids:
        row = await _get_owned_file(db, file_id, user.id)
        if not row:
            failed.append(file_id)
            continue
        await create_access_token(
            db,
            file_id=file_id,
            created_by_id=user.id,
            expires_hours=payload.expires_hours,
            basic_auth_password=payload.basic_auth_password,
            max_downloads=payload.max_downloads,
        )
        succeeded.append(file_id)
    await db.commit()
    return BulkFileOperationResponse(succeeded=succeeded, failed=failed)


def _unique_zip_name(name: str, used: set[str]) -> str:
    """Return a filename that does not collide with names already in the archive."""
    candidate = name or "file"
    if candidate not in used:
        used.add(candidate)
        return candidate
    stem, dot, ext = candidate.rpartition(".")
    base = stem if dot else candidate
    suffix = f".{ext}" if dot else ""
    counter = 1
    while True:
        candidate = f"{base} ({counter}){suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


@router.post("/download/bulk")
async def bulk_download_files(
    payload: BulkFileDownloadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Bundle multiple accessible files into a single ZIP archive for download."""
    buffer = io.BytesIO()
    used_names: set[str] = set()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_id in payload.file_ids:
            access = await _get_accessible_file(db, file_id, user)
            if access is None:
                continue
            file_row = access[0]
            disk_path = get_file_path(file_row)
            if not disk_path.exists():
                continue
            archive.write(disk_path, arcname=_unique_zip_name(file_row.filename, used_names))
            added += 1

    if added == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No files to download")

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="heym-drive-files.zip"'},
    )


@router.get("/{file_id}/share", response_model=list[FileAccessTokenResponse])
async def list_shares(
    file_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FileAccessTokenResponse]:
    base_url = build_public_base_url(request)
    row = await _get_owned_file(db, file_id, user.id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    tokens = (
        (await db.execute(select(FileAccessToken).where(FileAccessToken.file_id == file_id)))
        .scalars()
        .all()
    )
    return [_token_to_response(t, base_url) for t in tokens]


@router.delete("/{file_id}/share/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    file_id: uuid.UUID,
    token_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_owned_file(db, file_id, user.id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    token = (
        await db.execute(
            select(FileAccessToken).where(
                FileAccessToken.id == token_id, FileAccessToken.file_id == file_id
            )
        )
    ).scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share token not found")

    audit(
        action="drive.share_revoke",
        actor=user,
        target_type="file",
        target_id=file_id,
        target_name=row.filename,
        share_id=token_id,
    )
    await db.delete(token)
    await db.commit()


@router.get("/{file_id}/download")
async def download_authenticated_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    access = await _get_accessible_file(db, file_id, user)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    file_row = access[0]

    disk_path = get_file_path(file_row)
    if not disk_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File missing from storage"
        )

    audit(
        action="drive.download",
        actor=user,
        target_type="file",
        target_id=file_row.id,
        target_name=file_row.filename,
        owned=file_row.owner_id == user.id,
    )
    return FileResponse(
        path=str(disk_path),
        media_type=file_row.mime_type,
        filename=file_row.filename,
    )


# ---- Public endpoints (no JWT) ----


@router.get("/dl/{access_token}")
async def download_via_token(
    access_token: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    token_row = await validate_access_token(db, access_token)
    if not token_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired link")

    file_row = (
        await db.execute(select(GeneratedFile).where(GeneratedFile.id == token_row.file_id))
    ).scalar_one_or_none()
    if not file_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    disk_path = get_file_path(file_row)
    if not disk_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File missing from storage"
        )

    await increment_download_count(db, token_row)
    await db.commit()

    return FileResponse(
        path=str(disk_path),
        media_type=file_row.mime_type,
        filename=file_row.filename,
    )


@router.get("/ba/{file_id}")
async def download_via_basic_auth(
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Basic auth required",
            headers={"WWW-Authenticate": 'Basic realm="file"'},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="file"'},
        )

    token_row = await validate_basic_auth(db, file_id, username, password)
    if not token_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="file"'},
        )

    file_row = (
        await db.execute(select(GeneratedFile).where(GeneratedFile.id == file_id))
    ).scalar_one_or_none()
    if not file_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    disk_path = get_file_path(file_row)
    if not disk_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File missing from storage"
        )

    await increment_download_count(db, token_row)
    await db.commit()

    return FileResponse(
        path=str(disk_path),
        media_type=file_row.mime_type,
        filename=file_row.filename,
    )
