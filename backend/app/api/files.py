"""API endpoints for generated file management and downloads."""

import base64
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import FileAccessToken, GeneratedFile, User
from app.db.session import get_db
from app.models.schemas import (
    CreateFileShareRequest,
    FileAccessTokenResponse,
    FileListResponse,
    GeneratedFileResponse,
)
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

router = APIRouter()


def _file_to_response(f: GeneratedFile, base_url: str) -> GeneratedFileResponse:
    default_token = next((t for t in f.access_tokens if t.basic_auth_password_hash is None), None)
    download_url = ""
    if default_token:
        download_url = build_download_url(base_url, default_token.token)
    return GeneratedFileResponse(
        id=f.id,
        filename=f.filename,
        mime_type=f.mime_type,
        size_bytes=f.size_bytes,
        workflow_id=f.workflow_id,
        source_node_label=f.source_node_label,
        download_url=download_url,
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
    query = select(GeneratedFile).where(GeneratedFile.owner_id == user.id)
    count_query = select(func.count(GeneratedFile.id)).where(GeneratedFile.owner_id == user.id)

    if workflow_id:
        query = query.where(GeneratedFile.workflow_id == workflow_id)
        count_query = count_query.where(GeneratedFile.workflow_id == workflow_id)
    if mime_type:
        query = query.where(GeneratedFile.mime_type.ilike(f"%{mime_type}%"))
        count_query = count_query.where(GeneratedFile.mime_type.ilike(f"%{mime_type}%"))

    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        (
            await db.execute(
                query.order_by(GeneratedFile.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )

    for row in rows:
        await db.refresh(row, ["access_tokens"])

    return FileListResponse(
        files=[_file_to_response(r, base_url) for r in rows],
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
    row = (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id, GeneratedFile.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    await db.refresh(row, ["access_tokens"])
    return _file_to_response(row, base_url)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_endpoint(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id, GeneratedFile.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
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
    for row in rows:
        await delete_file(db, row)
    await db.commit()


@router.post("/upload", response_model=GeneratedFileResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedFileResponse:
    """Upload a file manually to Drive."""
    base_url = build_public_base_url(request)
    file_bytes = await file.read()
    row = await store_file(
        db,
        owner_id=user.id,
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        mime_type=file.content_type,
        source_node_label="manual upload",
    )
    await create_access_token(db, file_id=row.id, created_by_id=user.id)
    await db.commit()
    await db.refresh(row, ["access_tokens"])
    return _file_to_response(row, base_url)


@router.post("/{file_id}/share", response_model=FileAccessTokenResponse)
async def create_share(
    file_id: uuid.UUID,
    payload: CreateFileShareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileAccessTokenResponse:
    base_url = build_public_base_url(request)
    row = (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id, GeneratedFile.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
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
    return _token_to_response(token, base_url)


@router.get("/{file_id}/share", response_model=list[FileAccessTokenResponse])
async def list_shares(
    file_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FileAccessTokenResponse]:
    base_url = build_public_base_url(request)
    row = (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id, GeneratedFile.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
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
    row = (
        await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id, GeneratedFile.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
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

    await db.delete(token)
    await db.commit()


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
