import uuid

from fastapi import APIRouter, Depends, HTTPException, status
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
)
from app.db.session import get_db
from app.models.schemas import (
    CredentialCreate,
    CredentialForIntellisense,
    CredentialListResponse,
    CredentialResponse,
    CredentialShareRequest,
    CredentialShareResponse,
    CredentialUpdate,
    LLMModel,
    TeamShareRequest,
    TeamShareResponse,
)
from app.services.encryption import decrypt_config, encrypt_config, mask_api_key

router = APIRouter()


def get_masked_value(credential_type: CredentialType, config: dict) -> str | None:
    if credential_type == CredentialType.header:
        header_value = config.get("header_value", "")
        return mask_api_key(header_value)
    if credential_type == CredentialType.telegram:
        bot_token = config.get("bot_token", "")
        return mask_api_key(bot_token)
    if credential_type == CredentialType.slack:
        webhook_url = config.get("webhook_url", "")
        return mask_api_key(webhook_url)
    if credential_type == CredentialType.slack_trigger:
        signing_secret = config.get("signing_secret", "")
        return mask_api_key(signing_secret)
    if credential_type == CredentialType.imap:
        imap_username = str(config.get("imap_username", "")).strip()
        imap_host = str(config.get("imap_host", "")).strip()
        mailbox = str(config.get("imap_mailbox", "INBOX")).strip() or "INBOX"
        if imap_username and imap_host:
            return f"{imap_username}@{imap_host} ({mailbox})"
        if imap_host:
            return imap_host
        return None
    elif credential_type in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        api_key = config.get("api_key", "")
        return mask_api_key(api_key)
    elif credential_type == CredentialType.qdrant:
        openai_api_key = config.get("openai_api_key", "")
        return mask_api_key(openai_api_key)
    elif credential_type == CredentialType.grist:
        api_key = config.get("api_key", "")
        return mask_api_key(api_key)
    elif credential_type == CredentialType.flaresolverr:
        flaresolverr_url = config.get("flaresolverr_url", "")
        return mask_api_key(flaresolverr_url)
    elif credential_type == CredentialType.google_sheets:
        if config.get("refresh_token", "").strip():
            return "connected"
        client_id = config.get("client_id", "")
        return mask_api_key(client_id) if client_id else None
    elif credential_type == CredentialType.bigquery:
        if config.get("refresh_token", "").strip():
            return "connected"
        client_id = config.get("client_id", "")
        return mask_api_key(client_id) if client_id else None
    return None


def get_header_key(credential_type: CredentialType, config: dict) -> str | None:
    if credential_type == CredentialType.header:
        return config.get("header_key")
    return None


@router.get("", response_model=list[CredentialListResponse])
async def list_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialListResponse]:
    owned_result = await db.execute(
        select(Credential)
        .where(Credential.owner_id == current_user.id)
        .order_by(Credential.created_at.desc())
    )
    owned_credentials = owned_result.scalars().all()

    shared_result = await db.execute(
        select(Credential, User.email)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .join(User, User.id == Credential.owner_id)
        .where(CredentialShare.user_id == current_user.id)
        .order_by(Credential.created_at.desc())
    )
    shared_credentials = shared_result.all()

    shared_team_result = await db.execute(
        select(Credential, Team.name)
        .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
        .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
        .join(Team, Team.id == CredentialTeamShare.team_id)
        .where(TeamMember.user_id == current_user.id)
        .order_by(Credential.created_at.desc())
    )
    shared_team_credentials = shared_team_result.all()

    seen_ids: set[uuid.UUID] = set()
    responses = []
    for cred in owned_credentials:
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=False,
                shared_by=None,
                shared_by_team=None,
            )
        )
        seen_ids.add(cred.id)

    for cred, owner_email in shared_credentials:
        if cred.id in seen_ids:
            continue
        seen_ids.add(cred.id)
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=True,
                shared_by=owner_email,
                shared_by_team=None,
            )
        )

    for cred, team_name in shared_team_credentials:
        if cred.id in seen_ids:
            continue
        seen_ids.add(cred.id)
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=True,
                shared_by=None,
                shared_by_team=team_name,
            )
        )

    return responses


@router.get("/available", response_model=list[CredentialForIntellisense])
async def list_available_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialForIntellisense]:
    owned_result = await db.execute(
        select(Credential.name, Credential.type).where(Credential.owner_id == current_user.id)
    )
    owned_rows = owned_result.all()

    shared_result = await db.execute(
        select(Credential.name, Credential.type)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .where(CredentialShare.user_id == current_user.id)
    )
    shared_rows = shared_result.all()

    shared_team_result = await db.execute(
        select(Credential.name, Credential.type)
        .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
        .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
        .where(TeamMember.user_id == current_user.id)
    )
    shared_team_rows = shared_team_result.all()

    seen = set()
    credentials = []
    for row in owned_rows:
        if row.name not in seen:
            seen.add(row.name)
            credentials.append(CredentialForIntellisense(name=row.name, type=row.type))
    for row in shared_rows:
        if row.name not in seen:
            seen.add(row.name)
            credentials.append(CredentialForIntellisense(name=row.name, type=row.type))
    for row in shared_team_rows:
        if row.name not in seen:
            seen.add(row.name)
            credentials.append(CredentialForIntellisense(name=row.name, type=row.type))

    return credentials


@router.get("/by-type/{credential_type}", response_model=list[CredentialListResponse])
async def list_credentials_by_type(
    credential_type: CredentialType,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialListResponse]:
    owned_result = await db.execute(
        select(Credential)
        .where(Credential.owner_id == current_user.id, Credential.type == credential_type)
        .order_by(Credential.name.asc())
    )
    owned_credentials = owned_result.scalars().all()

    shared_result = await db.execute(
        select(Credential, User.email)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .join(User, User.id == Credential.owner_id)
        .where(CredentialShare.user_id == current_user.id, Credential.type == credential_type)
        .order_by(Credential.name.asc())
    )
    shared_credentials = shared_result.all()

    shared_team_result = await db.execute(
        select(Credential, Team.name)
        .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
        .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
        .join(Team, Team.id == CredentialTeamShare.team_id)
        .where(TeamMember.user_id == current_user.id, Credential.type == credential_type)
        .order_by(Credential.name.asc())
    )
    shared_team_credentials = shared_team_result.all()

    seen_ids: set[uuid.UUID] = set()
    responses = []
    for cred in owned_credentials:
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=False,
                shared_by=None,
                shared_by_team=None,
            )
        )
        seen_ids.add(cred.id)

    for cred, owner_email in shared_credentials:
        if cred.id in seen_ids:
            continue
        seen_ids.add(cred.id)
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=True,
                shared_by=owner_email,
                shared_by_team=None,
            )
        )

    for cred, team_name in shared_team_credentials:
        if cred.id in seen_ids:
            continue
        seen_ids.add(cred.id)
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=True,
                shared_by=None,
                shared_by_team=team_name,
            )
        )

    return responses


@router.get("/llm", response_model=list[CredentialListResponse])
async def list_llm_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialListResponse]:
    llm_types = [CredentialType.openai, CredentialType.google, CredentialType.custom]

    owned_result = await db.execute(
        select(Credential)
        .where(
            Credential.owner_id == current_user.id,
            Credential.type.in_(llm_types),
        )
        .order_by(Credential.name.asc())
    )
    owned_credentials = owned_result.scalars().all()

    shared_result = await db.execute(
        select(Credential, User.email)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .join(User, User.id == Credential.owner_id)
        .where(
            CredentialShare.user_id == current_user.id,
            Credential.type.in_(llm_types),
        )
        .order_by(Credential.name.asc())
    )
    shared_credentials = shared_result.all()

    shared_team_result = await db.execute(
        select(Credential, Team.name)
        .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
        .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
        .join(Team, Team.id == CredentialTeamShare.team_id)
        .where(
            TeamMember.user_id == current_user.id,
            Credential.type.in_(llm_types),
        )
        .order_by(Credential.name.asc())
    )
    shared_team_credentials = shared_team_result.all()

    seen_ids_llm: set[uuid.UUID] = set()
    responses = []
    for cred in owned_credentials:
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=False,
                shared_by=None,
                shared_by_team=None,
            )
        )
        seen_ids_llm.add(cred.id)

    for cred, owner_email in shared_credentials:
        if cred.id in seen_ids_llm:
            continue
        seen_ids_llm.add(cred.id)
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=True,
                shared_by=owner_email,
                shared_by_team=None,
            )
        )

    for cred, team_name in shared_team_credentials:
        if cred.id in seen_ids_llm:
            continue
        seen_ids_llm.add(cred.id)
        config = decrypt_config(cred.encrypted_config)
        masked = get_masked_value(cred.type, config)
        header_key = get_header_key(cred.type, config)
        responses.append(
            CredentialListResponse(
                id=cred.id,
                name=cred.name,
                type=cred.type,
                masked_value=masked,
                header_key=header_key,
                created_at=cred.created_at,
                is_shared=True,
                shared_by=None,
                shared_by_team=team_name,
            )
        )

    return responses


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    credential_data: CredentialCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialResponse:
    existing = await db.execute(
        select(Credential).where(
            Credential.owner_id == current_user.id, Credential.name == credential_data.name
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential with this name already exists",
        )

    validate_credential_config(credential_data.type, credential_data.config)
    encrypted = encrypt_config(credential_data.config)

    credential = Credential(
        owner_id=current_user.id,
        name=credential_data.name,
        type=credential_data.type,
        encrypted_config=encrypted,
    )
    db.add(credential)
    await db.flush()
    await db.refresh(credential)

    masked = get_masked_value(credential.type, credential_data.config)
    header_key = get_header_key(credential.type, credential_data.config)

    return CredentialResponse(
        id=credential.id,
        name=credential.name,
        type=credential.type,
        masked_value=masked,
        header_key=header_key,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.get("/{credential_id}", response_model=CredentialResponse)
async def get_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialResponse:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        shared_result = await db.execute(
            select(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .where(Credential.id == credential_id, CredentialShare.user_id == current_user.id)
        )
        credential = shared_result.scalar_one_or_none()

    if credential is None:
        team_result = await db.execute(
            select(Credential)
            .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
            .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
            .where(
                Credential.id == credential_id,
                TeamMember.user_id == current_user.id,
            )
        )
        credential = team_result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    config = decrypt_config(credential.encrypted_config)
    masked = get_masked_value(credential.type, config)
    header_key = get_header_key(credential.type, config)

    return CredentialResponse(
        id=credential.id,
        name=credential.name,
        type=credential.type,
        masked_value=masked,
        header_key=header_key,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.put("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: uuid.UUID,
    credential_data: CredentialUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialResponse:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if credential_data.name is not None:
        existing = await db.execute(
            select(Credential).where(
                Credential.owner_id == current_user.id,
                Credential.name == credential_data.name,
                Credential.id != credential_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential with this name already exists",
            )
        credential.name = credential_data.name

    config = decrypt_config(credential.encrypted_config)

    if credential_data.config is not None:
        validate_credential_config(credential.type, credential_data.config)
        config = credential_data.config
        credential.encrypted_config = encrypt_config(config)

    await db.flush()
    await db.refresh(credential)

    masked = get_masked_value(credential.type, config)
    header_key = get_header_key(credential.type, config)

    return CredentialResponse(
        id=credential.id,
        name=credential.name,
        type=credential.type,
        masked_value=masked,
        header_key=header_key,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    await db.delete(credential)


@router.get("/{credential_id}/models", response_model=list[LLMModel])
async def get_credential_models(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LLMModel]:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        shared_result = await db.execute(
            select(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .where(Credential.id == credential_id, CredentialShare.user_id == current_user.id)
        )
        credential = shared_result.scalar_one_or_none()

    if credential is None:
        team_result = await db.execute(
            select(Credential)
            .join(CredentialTeamShare, CredentialTeamShare.credential_id == Credential.id)
            .join(TeamMember, TeamMember.team_id == CredentialTeamShare.team_id)
            .where(
                Credential.id == credential_id,
                TeamMember.user_id == current_user.id,
            )
        )
        credential = team_result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This credential type does not support model listing",
        )

    config = decrypt_config(credential.encrypted_config)

    from app.services.llm_provider import fetch_models

    models = await fetch_models(credential.type, config)
    return models


def validate_credential_config(credential_type: CredentialType, config: dict) -> None:
    if credential_type == CredentialType.openai:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OpenAI credential requires api_key",
            )
    elif credential_type == CredentialType.google:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google credential requires api_key",
            )
    elif credential_type == CredentialType.custom:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Custom credential requires api_key",
            )
        if "base_url" not in config or not config["base_url"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Custom credential requires base_url",
            )
    elif credential_type == CredentialType.header:
        if "header_value" not in config or not config["header_value"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Header credential requires header_value",
            )
    elif credential_type == CredentialType.telegram:
        if "bot_token" not in config or not config["bot_token"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Telegram credential requires bot_token",
            )
    elif credential_type == CredentialType.slack:
        if "webhook_url" not in config or not config["webhook_url"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack credential requires webhook_url",
            )
    elif credential_type == CredentialType.slack_trigger:
        if "signing_secret" not in config or not config["signing_secret"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack Trigger credential requires signing_secret",
            )
    elif credential_type == CredentialType.imap:
        if "imap_host" not in config or not config["imap_host"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IMAP credential requires imap_host",
            )
        if "imap_port" not in config or not config["imap_port"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IMAP credential requires imap_port",
            )
        if "imap_username" not in config or not config["imap_username"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IMAP credential requires imap_username",
            )
        if "imap_password" not in config or not config["imap_password"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IMAP credential requires imap_password",
            )
    elif credential_type == CredentialType.qdrant:
        if "qdrant_host" not in config or not config["qdrant_host"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QDrant credential requires qdrant_host",
            )
        if "openai_api_key" not in config or not config["openai_api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QDrant credential requires openai_api_key",
            )
    elif credential_type == CredentialType.grist:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Grist credential requires api_key",
            )
        if "server_url" not in config or not config["server_url"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Grist credential requires server_url",
            )
    elif credential_type == CredentialType.rabbitmq:
        if "rabbitmq_host" not in config or not config["rabbitmq_host"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RabbitMQ credential requires rabbitmq_host",
            )
        if "rabbitmq_username" not in config or not config["rabbitmq_username"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RabbitMQ credential requires rabbitmq_username",
            )
        if "rabbitmq_password" not in config or not config["rabbitmq_password"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="RabbitMQ credential requires rabbitmq_password",
            )
    elif credential_type == CredentialType.google_sheets:
        if "client_id" not in config or not config["client_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google Sheets credential requires client_id",
            )
        if "client_secret" not in config or not config["client_secret"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google Sheets credential requires client_secret",
            )
    elif credential_type == CredentialType.bigquery:
        if "client_id" not in config or not config["client_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="BigQuery credential requires client_id",
            )
        if "client_secret" not in config or not config["client_secret"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="BigQuery credential requires client_secret",
            )
    elif credential_type == CredentialType.flaresolverr:
        if "flaresolverr_url" not in config or not config["flaresolverr_url"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="FlareSolverr credential requires flaresolverr_url",
            )


@router.get("/{credential_id}/shares", response_model=list[CredentialShareResponse])
async def list_credential_shares(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialShareResponse]:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    shares_result = await db.execute(
        select(CredentialShare, User)
        .join(User, CredentialShare.user_id == User.id)
        .where(CredentialShare.credential_id == credential_id)
    )
    rows = shares_result.all()

    return [
        CredentialShareResponse(
            id=share.id,
            user_id=user.id,
            email=user.email,
            name=user.name,
            shared_at=share.created_at,
        )
        for share, user in rows
    ]


@router.post("/{credential_id}/shares", response_model=CredentialShareResponse)
async def create_credential_share(
    credential_id: uuid.UUID,
    share_data: CredentialShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialShareResponse:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
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
        select(CredentialShare).where(
            CredentialShare.credential_id == credential_id,
            CredentialShare.user_id == target_user.id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        return CredentialShareResponse(
            id=existing.id,
            user_id=target_user.id,
            email=target_user.email,
            name=target_user.name,
            shared_at=existing.created_at,
        )

    share = CredentialShare(credential_id=credential_id, user_id=target_user.id)
    db.add(share)
    await db.flush()
    await db.refresh(share)

    return CredentialShareResponse(
        id=share.id,
        user_id=target_user.id,
        email=target_user.email,
        name=target_user.name,
        shared_at=share.created_at,
    )


@router.delete("/{credential_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_share(
    credential_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()

    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    share_result = await db.execute(
        select(CredentialShare).where(
            CredentialShare.credential_id == credential_id,
            CredentialShare.user_id == user_id,
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


@router.get("/{credential_id}/team-shares", response_model=list[TeamShareResponse])
async def list_credential_team_shares(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamShareResponse]:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    shares_result = await db.execute(
        select(CredentialTeamShare, Team)
        .join(Team, Team.id == CredentialTeamShare.team_id)
        .where(CredentialTeamShare.credential_id == credential_id)
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


@router.post("/{credential_id}/team-shares", response_model=TeamShareResponse)
async def create_credential_team_share(
    credential_id: uuid.UUID,
    payload: TeamShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamShareResponse:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
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
        select(CredentialTeamShare).where(
            CredentialTeamShare.credential_id == credential_id,
            CredentialTeamShare.team_id == payload.team_id,
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
    share = CredentialTeamShare(credential_id=credential_id, team_id=payload.team_id)
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


@router.delete("/{credential_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_team_share(
    credential_id: uuid.UUID,
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id, Credential.owner_id == current_user.id
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    share_result = await db.execute(
        select(CredentialTeamShare).where(
            CredentialTeamShare.credential_id == credential_id,
            CredentialTeamShare.team_id == team_id,
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
