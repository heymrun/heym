import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Credential,
    CredentialShare,
    CredentialTeamShare,
    CredentialType,
    Team,
    TeamMember,
    User,
    VectorStore,
    VectorStoreShare,
    VectorStoreTeamShare,
)
from app.db.session import get_db
from app.models.schemas import (
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
    DuplicateFile,
    TeamShareRequest,
    TeamShareResponse,
    VectorStoreCreate,
    VectorStoreItem,
    VectorStoreItemsResponse,
    VectorStoreListResponse,
    VectorStoreResponse,
    VectorStoreShareRequest,
    VectorStoreShareResponse,
    VectorStoreSourceGroup,
    VectorStoreStatsResponse,
    VectorStoreUpdate,
    VectorStoreUploadResponse,
)
from app.services.encryption import decrypt_config
from app.services.file_processor import create_file_processor
from app.services.vector_store import create_vector_store_service

router = APIRouter()


async def get_credential_config(
    credential_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[Credential, dict]:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.owner_id == user_id,
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        shared_result = await db.execute(
            select(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .where(
                Credential.id == credential_id,
                CredentialShare.user_id == user_id,
            )
        )
        credential = shared_result.scalar_one_or_none()

    if credential is None:
        team_result = await db.execute(
            select(Credential)
            .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
            .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
            .where(
                Credential.id == credential_id,
                TeamMember.user_id == user_id,
            )
        )
        credential = team_result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if credential.type != CredentialType.qdrant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be of type 'qdrant'",
        )

    config = decrypt_config(credential.encrypted_config)
    return credential, config


def get_vector_store_service_from_config(config: dict):
    return create_vector_store_service(
        qdrant_host=config.get("qdrant_host", "localhost"),
        qdrant_port=int(config.get("qdrant_port", 6333)),
        qdrant_api_key=config.get("qdrant_api_key"),
        openai_api_key=config["openai_api_key"],
    )


@router.get("", response_model=list[VectorStoreListResponse])
async def list_vector_stores(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VectorStoreListResponse]:
    owned_result = await db.execute(
        select(VectorStore)
        .where(VectorStore.owner_id == current_user.id)
        .order_by(VectorStore.created_at.desc())
    )
    owned_stores = owned_result.scalars().all()

    shared_result = await db.execute(
        select(VectorStore, User.email)
        .join(VectorStoreShare, VectorStoreShare.vector_store_id == VectorStore.id)
        .join(User, User.id == VectorStore.owner_id)
        .where(VectorStoreShare.user_id == current_user.id)
        .order_by(VectorStore.created_at.desc())
    )
    shared_stores = shared_result.all()

    shared_team_result = await db.execute(
        select(VectorStore, Team.name)
        .join(VectorStoreTeamShare, VectorStoreTeamShare.vector_store_id == VectorStore.id)
        .join(TeamMember, TeamMember.team_id == VectorStoreTeamShare.team_id)
        .join(Team, Team.id == VectorStoreTeamShare.team_id)
        .where(TeamMember.user_id == current_user.id)
        .order_by(VectorStore.created_at.desc())
    )
    shared_team_stores = shared_team_result.all()

    seen_ids: set[uuid.UUID] = set()
    responses = []

    for store in owned_stores:
        stats = await _get_store_stats(store, db)
        responses.append(
            VectorStoreListResponse(
                id=store.id,
                name=store.name,
                description=store.description,
                collection_name=store.collection_name,
                created_at=store.created_at,
                updated_at=store.updated_at,
                is_shared=False,
                shared_by=None,
                shared_by_team=None,
                stats=stats,
            )
        )
        seen_ids.add(store.id)

    for store, owner_email in shared_stores:
        if store.id in seen_ids:
            continue
        seen_ids.add(store.id)
        stats = await _get_store_stats(store, db)
        responses.append(
            VectorStoreListResponse(
                id=store.id,
                name=store.name,
                description=store.description,
                collection_name=store.collection_name,
                created_at=store.created_at,
                updated_at=store.updated_at,
                is_shared=True,
                shared_by=owner_email,
                shared_by_team=None,
                stats=stats,
            )
        )

    for store, team_name in shared_team_stores:
        if store.id in seen_ids:
            continue
        seen_ids.add(store.id)
        stats = await _get_store_stats(store, db)
        responses.append(
            VectorStoreListResponse(
                id=store.id,
                name=store.name,
                description=store.description,
                collection_name=store.collection_name,
                created_at=store.created_at,
                updated_at=store.updated_at,
                is_shared=True,
                shared_by=None,
                shared_by_team=team_name,
                stats=stats,
            )
        )

    return responses


async def _get_store_stats(
    store: VectorStore,
    db: AsyncSession,
) -> VectorStoreStatsResponse | None:
    try:
        result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
        credential = result.scalar_one_or_none()
        if not credential:
            return None

        config = decrypt_config(credential.encrypted_config)
        service = get_vector_store_service_from_config(config)
        stats = service.get_collection_stats(store.collection_name)

        if stats:
            return VectorStoreStatsResponse(
                vector_count=stats.vector_count,
                points_count=stats.points_count,
                status=stats.status,
            )
    except Exception:
        pass
    return None


@router.post("", response_model=VectorStoreResponse, status_code=status.HTTP_201_CREATED)
async def create_vector_store(
    data: VectorStoreCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreResponse:
    existing = await db.execute(
        select(VectorStore).where(
            VectorStore.owner_id == current_user.id,
            VectorStore.name == data.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vector store with this name already exists",
        )

    credential, config = await get_credential_config(
        data.credential_id,
        current_user.id,
        db,
    )

    store_id = uuid.uuid4()
    collection_name = data.collection_name or f"heym_vs_{store_id.hex}"

    existing_collection = await db.execute(
        select(VectorStore).where(VectorStore.collection_name == collection_name)
    )
    if existing_collection.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Collection name already in use",
        )

    service = get_vector_store_service_from_config(config)

    try:
        service.create_collection(collection_name)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create QDrant collection: {e!s}",
        )

    store = VectorStore(
        id=store_id,
        name=data.name,
        description=data.description,
        collection_name=collection_name,
        owner_id=current_user.id,
        credential_id=data.credential_id,
    )
    db.add(store)
    await db.flush()
    await db.refresh(store)

    return VectorStoreResponse(
        id=store.id,
        name=store.name,
        description=store.description,
        collection_name=store.collection_name,
        owner_id=store.owner_id,
        credential_id=store.credential_id,
        created_at=store.created_at,
        updated_at=store.updated_at,
        stats=None,
    )


@router.get("/{vector_store_id}", response_model=VectorStoreResponse)
async def get_vector_store(
    vector_store_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreResponse:
    store = await _get_accessible_store(vector_store_id, current_user.id, db)
    stats = await _get_store_stats(store, db)

    return VectorStoreResponse(
        id=store.id,
        name=store.name,
        description=store.description,
        collection_name=store.collection_name,
        owner_id=store.owner_id,
        credential_id=store.credential_id,
        created_at=store.created_at,
        updated_at=store.updated_at,
        stats=stats,
    )


@router.put("/{vector_store_id}", response_model=VectorStoreResponse)
async def update_vector_store(
    vector_store_id: uuid.UUID,
    data: VectorStoreUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreResponse:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    if data.name is not None:
        existing = await db.execute(
            select(VectorStore).where(
                VectorStore.owner_id == current_user.id,
                VectorStore.name == data.name,
                VectorStore.id != vector_store_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vector store with this name already exists",
            )
        store.name = data.name

    if data.description is not None:
        store.description = data.description

    await db.flush()
    await db.refresh(store)

    stats = await _get_store_stats(store, db)

    return VectorStoreResponse(
        id=store.id,
        name=store.name,
        description=store.description,
        collection_name=store.collection_name,
        owner_id=store.owner_id,
        credential_id=store.credential_id,
        created_at=store.created_at,
        updated_at=store.updated_at,
        stats=stats,
    )


@router.delete("/{vector_store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vector_store(
    vector_store_id: uuid.UUID,
    delete_collection: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    if delete_collection:
        try:
            cred_result = await db.execute(
                select(Credential).where(Credential.id == store.credential_id)
            )
            credential = cred_result.scalar_one_or_none()
            if credential:
                config = decrypt_config(credential.encrypted_config)
                service = get_vector_store_service_from_config(config)
                service.delete_collection(store.collection_name)
        except Exception:
            pass

    await db.delete(store)


@router.post("/{vector_store_id}/clone", response_model=VectorStoreResponse)
async def clone_vector_store(
    vector_store_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreResponse:
    store = await _get_accessible_store(vector_store_id, current_user.id, db)

    new_id = uuid.uuid4()
    new_name = f"{store.name} (Copy)"
    new_collection = f"heym_vs_{new_id.hex}"

    count = 1
    while True:
        existing = await db.execute(
            select(VectorStore).where(
                VectorStore.owner_id == current_user.id,
                VectorStore.name == new_name,
            )
        )
        if not existing.scalar_one_or_none():
            break
        count += 1
        new_name = f"{store.name} (Copy {count})"

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config)

    try:
        service.clone_collection(store.collection_name, new_collection)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clone QDrant collection: {e!s}",
        )

    new_store = VectorStore(
        id=new_id,
        name=new_name,
        description=store.description,
        collection_name=new_collection,
        owner_id=current_user.id,
        credential_id=store.credential_id,
    )
    db.add(new_store)
    await db.flush()
    await db.refresh(new_store)

    stats = await _get_store_stats(new_store, db)

    return VectorStoreResponse(
        id=new_store.id,
        name=new_store.name,
        description=new_store.description,
        collection_name=new_store.collection_name,
        owner_id=new_store.owner_id,
        credential_id=new_store.credential_id,
        created_at=new_store.created_at,
        updated_at=new_store.updated_at,
        stats=stats,
    )


@router.post("/{vector_store_id}/check-duplicates", response_model=CheckDuplicatesResponse)
async def check_duplicate_files(
    vector_store_id: uuid.UUID,
    data: CheckDuplicatesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckDuplicatesResponse:
    store = await _get_accessible_store(vector_store_id, current_user.id, db)

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config)

    files_to_check = [(f.filename, f.file_size) for f in data.files]
    existing = service.find_existing_files(store.collection_name, files_to_check)

    duplicates = [
        DuplicateFile(
            filename=ef.source,
            file_size=ef.file_size,
            chunk_count=ef.chunk_count,
        )
        for ef in existing
    ]

    return CheckDuplicatesResponse(duplicates=duplicates)


@router.post("/{vector_store_id}/upload", response_model=VectorStoreUploadResponse)
async def upload_file_to_vector_store(
    vector_store_id: uuid.UUID,
    file: UploadFile = File(...),
    override_duplicates: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreUploadResponse:
    store = await _get_accessible_store(vector_store_id, current_user.id, db)

    allowed_extensions = {".pdf", ".md", ".markdown", ".txt", ".csv", ".json"}
    filename = file.filename or "unknown.txt"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed: {', '.join(allowed_extensions)}",
        )

    file_content = await file.read()
    file_size = len(file_content)

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config)

    if override_duplicates:
        service.delete_by_source(store.collection_name, filename)

    processor = create_file_processor()
    chunks = processor.process_file(file_content, filename, file_size)

    if not chunks:
        return VectorStoreUploadResponse(chunks_processed=0, points_inserted=0)

    texts = [chunk.text for chunk in chunks]
    metadata_list = [chunk.metadata for chunk in chunks]

    try:
        point_ids = service.insert_batch(store.collection_name, texts, metadata_list)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to insert vectors: {e!s}",
        )

    return VectorStoreUploadResponse(
        chunks_processed=len(chunks),
        points_inserted=len(point_ids),
    )


@router.get("/{vector_store_id}/shares", response_model=list[VectorStoreShareResponse])
async def list_vector_store_shares(
    vector_store_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VectorStoreShareResponse]:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    shares_result = await db.execute(
        select(VectorStoreShare, User)
        .join(User, VectorStoreShare.user_id == User.id)
        .where(VectorStoreShare.vector_store_id == vector_store_id)
    )
    rows = shares_result.all()

    return [
        VectorStoreShareResponse(
            id=share.id,
            user_id=user.id,
            email=user.email,
            name=user.name,
            shared_at=share.created_at,
        )
        for share, user in rows
    ]


@router.post("/{vector_store_id}/shares", response_model=VectorStoreShareResponse)
async def create_vector_store_share(
    vector_store_id: uuid.UUID,
    share_data: VectorStoreShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreShareResponse:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    user_result = await db.execute(select(User).where(User.email == share_data.email))
    target_user = user_result.scalar_one_or_none()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share with yourself",
        )

    existing_result = await db.execute(
        select(VectorStoreShare).where(
            VectorStoreShare.vector_store_id == vector_store_id,
            VectorStoreShare.user_id == target_user.id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        return VectorStoreShareResponse(
            id=existing.id,
            user_id=target_user.id,
            email=target_user.email,
            name=target_user.name,
            shared_at=existing.created_at,
        )

    share = VectorStoreShare(vector_store_id=vector_store_id, user_id=target_user.id)
    db.add(share)
    await db.flush()
    await db.refresh(share)

    return VectorStoreShareResponse(
        id=share.id,
        user_id=target_user.id,
        email=target_user.email,
        name=target_user.name,
        shared_at=share.created_at,
    )


@router.delete(
    "/{vector_store_id}/shares/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_vector_store_share(
    vector_store_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    share_result = await db.execute(
        select(VectorStoreShare).where(
            VectorStoreShare.vector_store_id == vector_store_id,
            VectorStoreShare.user_id == user_id,
        )
    )
    share = share_result.scalar_one_or_none()

    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found",
        )

    await db.delete(share)
    await db.commit()


@router.get("/{vector_store_id}/team-shares", response_model=list[TeamShareResponse])
async def list_vector_store_team_shares(
    vector_store_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamShareResponse]:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )
    shares_result = await db.execute(
        select(VectorStoreTeamShare, Team)
        .join(Team, Team.id == VectorStoreTeamShare.team_id)
        .where(VectorStoreTeamShare.vector_store_id == vector_store_id)
        .order_by(Team.name.asc())
    )
    return [
        TeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            shared_at=share.created_at,
        )
        for share, team in shares_result.all()
    ]


@router.post("/{vector_store_id}/team-shares", response_model=TeamShareResponse)
async def create_vector_store_team_share(
    vector_store_id: uuid.UUID,
    payload: TeamShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamShareResponse:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )
    team_result = await db.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.id == payload.team_id, TeamMember.user_id == current_user.id)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found or you are not a member",
        )
    existing = await db.execute(
        select(VectorStoreTeamShare).where(
            VectorStoreTeamShare.vector_store_id == vector_store_id,
            VectorStoreTeamShare.team_id == payload.team_id,
        )
    )
    share = existing.scalar_one_or_none()
    if share:
        return TeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            shared_at=share.created_at,
        )
    share = VectorStoreTeamShare(vector_store_id=vector_store_id, team_id=payload.team_id)
    db.add(share)
    await db.flush()
    await db.refresh(share)
    await db.commit()
    return TeamShareResponse(
        id=share.id,
        team_id=team.id,
        team_name=team.name,
        shared_at=share.created_at,
    )


@router.delete(
    "/{vector_store_id}/team-shares/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_vector_store_team_share(
    vector_store_id: uuid.UUID,
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )
    share_result = await db.execute(
        select(VectorStoreTeamShare).where(
            VectorStoreTeamShare.vector_store_id == vector_store_id,
            VectorStoreTeamShare.team_id == team_id,
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team share not found",
        )
    await db.delete(share)
    await db.commit()


@router.get("/{vector_store_id}/items", response_model=VectorStoreItemsResponse)
async def list_vector_store_items(
    vector_store_id: uuid.UUID,
    limit: int = 1000,
    text_truncate_length: int = 5000,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreItemsResponse:
    store = await _get_accessible_store(vector_store_id, current_user.id, db)

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config)

    source_groups, total_items = service.list_items(
        store.collection_name, limit=limit, text_truncate_length=text_truncate_length
    )

    return VectorStoreItemsResponse(
        sources=[
            VectorStoreSourceGroup(
                source=sg.source,
                file_size=sg.file_size,
                chunk_count=sg.chunk_count,
                items=[
                    VectorStoreItem(
                        id=item.id,
                        text=item.text,
                        source=item.source,
                        metadata=item.metadata,
                    )
                    for item in sg.items
                ],
            )
            for sg in source_groups
        ],
        total_items=total_items,
    )


@router.delete(
    "/{vector_store_id}/items/by-source",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_items_by_source(
    vector_store_id: uuid.UUID,
    source: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config)
    service.delete_by_source(store.collection_name, source)


@router.delete(
    "/{vector_store_id}/items/{point_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_item(
    vector_store_id: uuid.UUID,
    point_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == current_user.id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config)
    service.delete_point(store.collection_name, point_id)


async def _get_accessible_store(
    vector_store_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> VectorStore:
    result = await db.execute(
        select(VectorStore).where(
            VectorStore.id == vector_store_id,
            VectorStore.owner_id == user_id,
        )
    )
    store = result.scalar_one_or_none()

    if store is None:
        shared_result = await db.execute(
            select(VectorStore)
            .join(VectorStoreShare, VectorStoreShare.vector_store_id == VectorStore.id)
            .where(
                VectorStore.id == vector_store_id,
                VectorStoreShare.user_id == user_id,
            )
        )
        store = shared_result.scalar_one_or_none()

    if store is None:
        team_result = await db.execute(
            select(VectorStore)
            .join(VectorStoreTeamShare, VectorStoreTeamShare.vector_store_id == VectorStore.id)
            .join(TeamMember, TeamMember.team_id == VectorStoreTeamShare.team_id)
            .where(
                VectorStore.id == vector_store_id,
                TeamMember.user_id == user_id,
            )
        )
        store = team_result.scalar_one_or_none()

    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector store not found",
        )

    return store
