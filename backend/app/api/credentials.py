import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

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
    ClickHouseColumnsResponse,
    CredentialCreate,
    CredentialForIntellisense,
    CredentialListResponse,
    CredentialResponse,
    CredentialShareRequest,
    CredentialShareResponse,
    CredentialTestRequest,
    CredentialTestResponse,
    CredentialUpdate,
    LLMModel,
    NotionDataSourcesResponse,
    NotionPagesResponse,
    SupabaseColumnsResponse,
    SupabaseTablesResponse,
    TeamShareRequest,
    TeamShareResponse,
)
from app.services.encryption import decrypt_config, encrypt_config, mask_api_key

router = APIRouter()


def merge_credential_config_for_update(
    credential_type: CredentialType,
    existing_config: dict,
    incoming_config: dict,
) -> dict:
    """Merge update payload into an existing credential config when needed."""
    if credential_type == CredentialType.notion:
        merged_config = dict(existing_config)
        incoming_auth_mode = str(incoming_config.get("auth_mode", "") or "").strip()
        if incoming_auth_mode == "oauth":
            merged_config.pop("api_token", None)
        elif str(incoming_config.get("api_token", "") or "").strip():
            merged_config.pop("access_token", None)
            incoming_auth_mode = "token"
        for key in ("api_token", "client_id", "client_secret", "access_token", "auth_mode"):
            incoming_value = str(incoming_config.get(key, "") or "").strip()
            if incoming_value:
                merged_config[key] = incoming_value
        if incoming_auth_mode:
            merged_config["auth_mode"] = incoming_auth_mode
        return merged_config

    if credential_type == CredentialType.linear:
        merged_config = dict(existing_config)
        incoming_auth_mode = str(incoming_config.get("auth_mode", "") or "").strip()
        if incoming_auth_mode == "oauth":
            merged_config.pop("api_key", None)
        elif str(incoming_config.get("api_key", "") or "").strip():
            merged_config.pop("access_token", None)
            merged_config.pop("refresh_token", None)
            merged_config.pop("token_expiry", None)
            incoming_auth_mode = "api_key"
        for key in (
            "api_key",
            "client_id",
            "client_secret",
            "access_token",
            "refresh_token",
            "token_expiry",
            "auth_mode",
        ):
            incoming_value = str(incoming_config.get(key, "") or "").strip()
            if incoming_value:
                merged_config[key] = incoming_value
        if incoming_auth_mode:
            merged_config["auth_mode"] = incoming_auth_mode
        return merged_config

    if credential_type != CredentialType.github:
        return incoming_config

    merged_config = dict(existing_config)

    incoming_api_key = str(incoming_config.get("api_key", "") or "").strip()
    if incoming_api_key:
        merged_config["api_key"] = incoming_api_key

    if "base_url" in incoming_config:
        incoming_base_url = str(incoming_config.get("base_url", "") or "").strip()
        if incoming_base_url:
            merged_config["base_url"] = incoming_base_url

    return merged_config


def get_masked_value(credential_type: CredentialType, config: dict) -> str | None:
    if credential_type == CredentialType.header:
        header_value = config.get("header_value", "")
        return mask_api_key(header_value)
    if credential_type == CredentialType.telegram:
        bot_token = config.get("bot_token", "")
        return mask_api_key(bot_token)
    if credential_type == CredentialType.discord:
        webhook_url = config.get("webhook_url", "")
        return mask_api_key(webhook_url)
    if credential_type == CredentialType.discord_trigger:
        public_key = config.get("public_key", "")
        return mask_api_key(public_key)
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
    elif credential_type in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.github,
        CredentialType.custom,
        CredentialType.elevenlabs,
    ):
        api_key = config.get("api_key", "")
        return mask_api_key(api_key)
    elif credential_type == CredentialType.qdrant:
        openai_api_key = config.get("openai_api_key", "")
        return mask_api_key(openai_api_key)
    elif credential_type == CredentialType.pgvector:
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
    elif credential_type == CredentialType.supabase:
        supabase_url = str(config.get("supabase_url", "")).strip()
        supabase_schema = str(config.get("supabase_schema", "public")).strip() or "public"
        if supabase_url:
            return f"{supabase_url} ({supabase_schema})"
        return None
    elif credential_type == CredentialType.notion:
        auth_mode = str(config.get("auth_mode", "")).strip()
        access_token = str(config.get("access_token", "")).strip()
        api_token = str(config.get("api_token", "")).strip()
        if access_token:
            workspace_name = str(config.get("workspace_name", "")).strip()
            if workspace_name:
                return f"connected ({workspace_name})"
            return "connected"
        if auth_mode == "oauth":
            return "Not connected"
        return mask_api_key(api_token)
    elif credential_type == CredentialType.linear:
        auth_mode = str(config.get("auth_mode", "")).strip()
        access_token = str(config.get("access_token", "")).strip()
        if access_token:
            return "connected"
        if auth_mode == "oauth":
            return "Not connected"
        return mask_api_key(str(config.get("api_key", "") or ""))
    elif credential_type == CredentialType.s3:
        access_key = str(config.get("aws_access_key_id", "")).strip()
        region = str(config.get("aws_region", "")).strip()
        if access_key and region:
            return f"{mask_api_key(access_key)} ({region})"
        return mask_api_key(access_key) if access_key else None
    elif credential_type == CredentialType.clickhouse:
        host = str(config.get("host", "")).strip()
        database = str(config.get("database", "default")).strip() or "default"
        if host:
            return f"{host} ({database})"
        return None
    return None


def get_header_key(credential_type: CredentialType, config: dict) -> str | None:
    if credential_type == CredentialType.header:
        return config.get("header_key")
    return None


def get_public_credential_fields(
    credential_type: CredentialType, config: dict
) -> dict[str, str | None]:
    """Return non-secret credential fields that the UI may safely hydrate for editing."""
    if credential_type == CredentialType.supabase:
        supabase_url = str(config.get("supabase_url", "")).strip() or None
        supabase_schema = str(config.get("supabase_schema", "public")).strip() or "public"
        return {
            "supabase_url": supabase_url,
            "supabase_schema": supabase_schema,
        }
    if credential_type == CredentialType.notion:
        auth_mode = str(config.get("auth_mode", "token")).strip() or "token"
        fields: dict[str, str | None] = {"auth_mode": auth_mode}
        if auth_mode == "oauth":
            workspace_name = str(config.get("workspace_name", "")).strip()
            fields["workspace_name"] = workspace_name or None
        return fields
    if credential_type == CredentialType.linear:
        auth_mode = str(config.get("auth_mode", "api_key")).strip() or "api_key"
        return {"auth_mode": auth_mode}
    return {}


async def _get_accessible_credential(
    db: AsyncSession,
    credential_id: uuid.UUID,
    current_user: User,
) -> Credential | None:
    """Return a credential the user owns or has been shared."""
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_id,
            Credential.owner_id == current_user.id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is not None:
        return credential

    shared_result = await db.execute(
        select(Credential)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .where(Credential.id == credential_id, CredentialShare.user_id == current_user.id)
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
            TeamMember.user_id == current_user.id,
        )
    )
    return team_result.scalar_one_or_none()


def _merge_supabase_test_config(
    inline_config: dict,
    stored_config: dict,
) -> dict[str, str]:
    """Merge inline form values with stored secrets for connection tests."""
    merged = dict(stored_config)
    for key in ("supabase_url", "supabase_key", "supabase_schema"):
        inline_value = str(inline_config.get(key, "")).strip()
        if inline_value:
            merged[key] = inline_value
    return merged


def _merge_clickhouse_test_config(
    inline_config: dict,
    stored_config: dict,
) -> dict:
    """Merge inline ClickHouse form values with stored secrets for connection tests."""
    merged = dict(stored_config)
    for key in ("host", "port", "username", "database", "secure"):
        if key in inline_config and inline_config.get(key) not in (None, ""):
            merged[key] = inline_config[key]
    inline_password = str(inline_config.get("password", "") or "")
    if inline_password:
        merged["password"] = inline_password
    return merged


def _merge_supabase_update_config(
    inline_config: dict,
    stored_config: dict,
) -> dict[str, str]:
    """Merge edited Supabase fields while preserving the stored API key when left blank."""
    merged = dict(stored_config)
    if "supabase_url" in inline_config:
        merged["supabase_url"] = str(inline_config.get("supabase_url", "")).strip()
    if "supabase_schema" in inline_config:
        merged["supabase_schema"] = (
            str(inline_config.get("supabase_schema", "")).strip() or "public"
        )

    inline_key = str(inline_config.get("supabase_key", "")).strip()
    if inline_key:
        merged["supabase_key"] = inline_key
    return merged


def _merge_linear_test_config(
    inline_config: dict,
    stored_config: dict,
) -> dict:
    """Merge inline form values with stored secrets for Linear connection tests."""
    merged = dict(stored_config)
    incoming_auth_mode = str(inline_config.get("auth_mode", "") or "").strip()
    if incoming_auth_mode:
        merged["auth_mode"] = incoming_auth_mode
    for key in ("api_key", "client_id", "client_secret", "access_token", "refresh_token"):
        inline_value = str(inline_config.get(key, "") or "").strip()
        if inline_value:
            merged[key] = inline_value
    return merged


def _merge_notion_test_config(inline_config: dict, stored_config: dict) -> dict:
    """Merge inline form values with stored secrets for Notion connection tests."""
    merged = dict(inline_config)
    for key in ("api_token", "client_id", "client_secret", "access_token", "auth_mode"):
        if not str(merged.get(key, "")).strip():
            stored_value = stored_config.get(key, "")
            if stored_value:
                merged[key] = stored_value
    return merged


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

    validate_credential_config(
        credential_data.type,
        credential_data.config,
        allow_pending_oauth=True,
    )
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
        public_fields=get_public_credential_fields(credential.type, credential_data.config),
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.post("/test", response_model=CredentialTestResponse)
async def run_credential_connection_test(
    test_data: CredentialTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CredentialTestResponse:
    """Test whether a credential configuration can reach the external service."""
    if test_data.type not in {
        CredentialType.supabase,
        CredentialType.linear,
        CredentialType.notion,
        CredentialType.clickhouse,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection test is not supported for this credential type",
        )

    config = dict(test_data.config or {})
    if test_data.credential_id is not None:
        credential = await _get_accessible_credential(db, test_data.credential_id, current_user)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.type != test_data.type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential type does not match the requested test",
            )
        stored_config = decrypt_config(credential.encrypted_config)
        if test_data.type == CredentialType.supabase:
            config = _merge_supabase_test_config(config, stored_config)
        elif test_data.type == CredentialType.linear:
            config = _merge_linear_test_config(config, stored_config)
        elif test_data.type == CredentialType.clickhouse:
            config = _merge_clickhouse_test_config(config, stored_config)
        else:
            config = _merge_notion_test_config(config, stored_config)

    validate_credential_config(test_data.type, config)

    try:
        if test_data.type == CredentialType.supabase:
            from app.services.supabase_service import SupabaseService

            SupabaseService(config).test_connection()
            return CredentialTestResponse(success=True, message="Connection successful")

        if test_data.type == CredentialType.linear:
            from app.services.linear_service import LinearService

            service = LinearService(config)
            try:
                viewer = service.test_connection()
            finally:
                service.close()
            viewer_name = str(
                viewer.get("displayName") or viewer.get("name") or viewer.get("email") or ""
            )
            if viewer_name:
                return CredentialTestResponse(
                    success=True,
                    message=f"Connected as {viewer_name}",
                )
            return CredentialTestResponse(success=True, message="Connection successful")

        if test_data.type == CredentialType.clickhouse:
            from app.services.clickhouse_service import ClickHouseService

            await run_in_threadpool(ClickHouseService(config).test_connection)
            return CredentialTestResponse(success=True, message="Connection successful")

        from app.services.notion_service import NotionService

        with NotionService(config) as service:
            await run_in_threadpool(service.test_connection)
        return CredentialTestResponse(success=True, message="Connection successful")
    except ValueError as exc:
        return CredentialTestResponse(success=False, message=str(exc))


@router.get(
    "/{credential_id}/notion/data-sources",
    response_model=NotionDataSourcesResponse,
)
async def list_notion_data_sources(
    credential_id: uuid.UUID,
    query: str = "",
    start_cursor: str | None = None,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotionDataSourcesResponse:
    """List Notion data sources available to an accessible credential."""
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.notion:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential type does not support Notion data source discovery",
        )

    from app.services.notion_service import NotionService

    try:
        with NotionService(decrypt_config(credential.encrypted_config)) as service:
            result = await run_in_threadpool(
                service.list_data_sources,
                query,
                start_cursor=start_cursor,
                page_size=page_size,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return NotionDataSourcesResponse(**result)


@router.get(
    "/{credential_id}/notion/pages",
    response_model=NotionPagesResponse,
)
async def list_notion_pages(
    credential_id: uuid.UUID,
    query: str = "",
    start_cursor: str | None = None,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotionPagesResponse:
    """List ordinary Notion pages available as page parents."""
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.notion:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential type does not support Notion page discovery",
        )

    from app.services.notion_service import NotionService

    try:
        with NotionService(decrypt_config(credential.encrypted_config)) as service:
            result = await run_in_threadpool(
                service.list_pages,
                query,
                start_cursor=start_cursor,
                page_size=page_size,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return NotionPagesResponse(**result)


@router.get("/{credential_id}/supabase/tables", response_model=SupabaseTablesResponse)
async def list_supabase_tables(
    credential_id: uuid.UUID,
    schema: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupabaseTablesResponse:
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.supabase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential type does not support Supabase table discovery",
        )

    config = decrypt_config(credential.encrypted_config)
    from app.services.supabase_service import SupabaseService

    try:
        result = SupabaseService(config).list_tables(
            schema=schema or config.get("supabase_schema", "public")
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SupabaseTablesResponse(**result)


@router.get("/{credential_id}/supabase/columns", response_model=SupabaseColumnsResponse)
async def list_supabase_columns(
    credential_id: uuid.UUID,
    table: str,
    schema: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupabaseColumnsResponse:
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.supabase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential type does not support Supabase column discovery",
        )

    config = decrypt_config(credential.encrypted_config)
    from app.services.supabase_service import SupabaseService

    try:
        result = SupabaseService(config).list_columns(
            table,
            schema=schema or config.get("supabase_schema", "public"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SupabaseColumnsResponse(**result)


@router.get("/{credential_id}/clickhouse/columns", response_model=ClickHouseColumnsResponse)
async def list_clickhouse_columns(
    credential_id: uuid.UUID,
    table: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClickHouseColumnsResponse:
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.clickhouse:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential type does not support ClickHouse column discovery",
        )

    config = decrypt_config(credential.encrypted_config)
    from app.services.clickhouse_service import ClickHouseService

    try:
        result = await run_in_threadpool(ClickHouseService(config).list_columns, table)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ClickHouseColumnsResponse(**result)


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
        public_fields=get_public_credential_fields(credential.type, config),
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
        config = (
            _merge_supabase_update_config(credential_data.config, config)
            if credential.type == CredentialType.supabase
            else merge_credential_config_for_update(
                credential.type,
                config,
                credential_data.config,
            )
        )
        validate_credential_config(
            credential.type,
            config,
            allow_pending_oauth=credential.type in {CredentialType.linear, CredentialType.notion},
        )
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
        public_fields=get_public_credential_fields(credential.type, config),
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

    from app.services.context_compressor import KNOWN_LIMITS
    from app.services.llm_provider import fetch_models

    models = await fetch_models(credential.type, config)
    for m in models:
        model_lower = m.id.lower()
        for key, limit in KNOWN_LIMITS.items():
            if key in model_lower:
                m.context_window = limit
                break
    return models


def validate_credential_config(
    credential_type: CredentialType,
    config: dict,
    *,
    allow_pending_oauth: bool = False,
) -> None:
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
    elif credential_type == CredentialType.github:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub credential requires api_key",
            )
        github_base_url = str(config.get("base_url", "") or "").strip()
        if github_base_url:
            parsed = urlparse(github_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="GitHub credential base_url must be a valid http(s) URL",
                )
    elif credential_type == CredentialType.linear:
        has_token = bool(str(config.get("api_key") or config.get("access_token") or "").strip())
        uses_oauth = str(config.get("auth_mode", "")).strip() == "oauth"
        has_oauth_client = bool(
            str(config.get("client_id", "")).strip()
            and str(config.get("client_secret", "")).strip()
        )
        if uses_oauth and not has_oauth_client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linear OAuth requires client_id and client_secret",
            )
        if not has_token and not uses_oauth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linear credential requires api_key or OAuth client credentials",
            )
        if uses_oauth and not has_token and not allow_pending_oauth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linear OAuth credential requires a completed authorization",
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
    elif credential_type == CredentialType.elevenlabs:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ElevenLabs credential requires api_key",
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
    elif credential_type == CredentialType.discord:
        if "webhook_url" not in config or not config["webhook_url"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Discord credential requires webhook_url",
            )
    elif credential_type == CredentialType.discord_trigger:
        if "public_key" not in config or not str(config["public_key"]).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Discord Trigger credential requires public_key",
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
    elif credential_type == CredentialType.pgvector:
        if "openai_api_key" not in config or not config["openai_api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Postgres vector credential requires openai_api_key",
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
    elif credential_type == CredentialType.supabase:
        if "supabase_url" not in config or not str(config["supabase_url"]).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supabase credential requires supabase_url",
            )
        if "supabase_key" not in config or not str(config["supabase_key"]).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Supabase credential requires supabase_key",
            )
    elif credential_type == CredentialType.notion:
        has_token = bool(str(config.get("api_token") or config.get("access_token") or "").strip())
        uses_oauth = str(config.get("auth_mode", "")).strip() == "oauth"
        has_oauth_client = bool(
            str(config.get("client_id", "")).strip()
            and str(config.get("client_secret", "")).strip()
        )
        if uses_oauth and not has_oauth_client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Notion OAuth requires client_id and client_secret",
            )
        if not has_token and not uses_oauth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Notion credential requires api_token or OAuth client credentials",
            )
        if uses_oauth and not has_token and not allow_pending_oauth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Notion OAuth credential requires a completed authorization",
            )
    elif credential_type == CredentialType.s3:
        if "aws_access_key_id" not in config or not str(config["aws_access_key_id"]).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amazon S3 credential requires aws_access_key_id",
            )
        if (
            "aws_secret_access_key" not in config
            or not str(config["aws_secret_access_key"]).strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amazon S3 credential requires aws_secret_access_key",
            )
        if "aws_region" not in config or not str(config["aws_region"]).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amazon S3 credential requires aws_region",
            )
    elif credential_type == CredentialType.flaresolverr:
        if "flaresolverr_url" not in config or not config["flaresolverr_url"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="FlareSolverr credential requires flaresolverr_url",
            )
    elif credential_type == CredentialType.clickhouse:
        if "host" not in config or not str(config["host"]).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ClickHouse credential requires host",
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
