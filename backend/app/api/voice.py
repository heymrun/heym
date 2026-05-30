import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.credential_access import get_accessible_credential
from app.services.elevenlabs_service import (
    ElevenLabsError,
    list_voices,
    speech_to_text,
    stream_text_to_speech,
    text_to_speech,
)
from app.services.encryption import decrypt_config

router = APIRouter()


class VoiceInfo(BaseModel):
    voice_id: str
    name: str


class TtsRequest(BaseModel):
    text: str
    voice_id: str | None = None
    credential_id: uuid.UUID | None = None


class SttResponse(BaseModel):
    text: str
    language_code: str


async def _resolve_credential(
    db: AsyncSession, user: User, credential_id: uuid.UUID | None
) -> tuple[str, Credential]:
    """Return (api_key, credential) for the request override or the user default."""
    target_id = credential_id or user.tts_credential_id
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ElevenLabs credential selected",
        )
    credential = await get_accessible_credential(db, target_id, user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type != CredentialType.elevenlabs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an ElevenLabs credential",
        )
    config = decrypt_config(credential.encrypted_config)
    return config["api_key"], credential


@router.get("/voices", response_model=list[VoiceInfo])
async def get_voices(
    credential_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VoiceInfo]:
    api_key, _ = await _resolve_credential(db, current_user, credential_id)
    try:
        voices = await list_voices(api_key)
    except ElevenLabsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [VoiceInfo(**v) for v in voices]


@router.post("/tts")
async def synthesize(
    body: TtsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    api_key, _ = await _resolve_credential(db, current_user, body.credential_id)
    voice_id = body.voice_id or current_user.tts_voice_id
    if not voice_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No voice selected")
    try:
        audio = await text_to_speech(api_key, text, voice_id)
    except ElevenLabsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/tts/stream")
async def synthesize_stream(
    text: str,
    voice_id: str | None = None,
    credential_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream synthesized audio so playback can start before the full clip is ready.

    Served as GET so a browser ``<audio>`` element can play it progressively;
    auth is resolved from the access-token cookie like every other endpoint.
    """
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    api_key, _ = await _resolve_credential(db, current_user, credential_id)
    resolved_voice = voice_id or current_user.tts_voice_id
    if not resolved_voice:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No voice selected")
    return StreamingResponse(
        stream_text_to_speech(api_key, cleaned, resolved_voice),
        media_type="audio/mpeg",
    )


@router.post("/stt", response_model=SttResponse)
async def transcribe(
    file: UploadFile = File(...),
    credential_id: uuid.UUID | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    api_key, _ = await _resolve_credential(db, current_user, credential_id)
    audio = await file.read()
    try:
        return await speech_to_text(
            api_key, audio, file.filename or "audio.webm", file.content_type or "audio/webm"
        )
    except ElevenLabsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
