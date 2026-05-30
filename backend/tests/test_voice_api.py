import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.voice import (
    TtsRequest,
    _resolve_credential,
    synthesize,
    synthesize_stream,
    transcribe,
)
from app.db.models import CredentialType


def _user(cred_id=None, voice_id="user_voice"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.tts_credential_id = cred_id
    user.tts_voice_id = voice_id
    return user


def _credential(ctype=CredentialType.elevenlabs):
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.type = ctype
    credential.encrypted_config = "enc"
    return credential


class VoiceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_credential_uses_user_default(self) -> None:
        cred_id = uuid.uuid4()
        user = _user(cred_id=cred_id)
        credential = _credential()
        db = AsyncMock()
        with (
            patch("app.api.voice.get_accessible_credential", AsyncMock(return_value=credential)),
            patch("app.api.voice.decrypt_config", return_value={"api_key": "sk"}),
        ):
            api_key, _ = await _resolve_credential(db, user, None)
        self.assertEqual(api_key, "sk")

    async def test_resolve_credential_404_when_none_selected(self) -> None:
        user = _user(cred_id=None)
        db = AsyncMock()
        with self.assertRaises(HTTPException) as ctx:
            await _resolve_credential(db, user, None)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_resolve_credential_rejects_wrong_type(self) -> None:
        user = _user(cred_id=uuid.uuid4())
        db = AsyncMock()
        with patch(
            "app.api.voice.get_accessible_credential",
            AsyncMock(return_value=_credential(CredentialType.openai)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await _resolve_credential(db, user, None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_synthesize_returns_audio(self) -> None:
        user = _user(cred_id=uuid.uuid4(), voice_id="v1")
        db = AsyncMock()
        with (
            patch(
                "app.api.voice._resolve_credential",
                AsyncMock(return_value=("sk", _credential())),
            ),
            patch("app.api.voice.text_to_speech", AsyncMock(return_value=b"AUDIO")),
        ):
            response = await synthesize(TtsRequest(text="hi"), current_user=user, db=db)
        self.assertEqual(response.body, b"AUDIO")
        self.assertEqual(response.media_type, "audio/mpeg")

    async def test_synthesize_400_when_no_voice(self) -> None:
        user = _user(cred_id=uuid.uuid4(), voice_id=None)
        db = AsyncMock()
        with patch(
            "app.api.voice._resolve_credential",
            AsyncMock(return_value=("sk", _credential())),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await synthesize(TtsRequest(text="hi"), current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_synthesize_stream_returns_audio_stream(self) -> None:
        user = _user(cred_id=uuid.uuid4(), voice_id="v1")
        db = AsyncMock()

        async def fake_stream(*_args, **_kwargs):
            yield b"a"
            yield b"b"

        with (
            patch(
                "app.api.voice._resolve_credential",
                AsyncMock(return_value=("sk", _credential())),
            ),
            patch("app.api.voice.stream_text_to_speech", fake_stream),
        ):
            response = await synthesize_stream(
                text="hi", voice_id=None, credential_id=None, current_user=user, db=db
            )
        self.assertEqual(response.media_type, "audio/mpeg")
        chunks = [chunk async for chunk in response.body_iterator]
        self.assertEqual(chunks, [b"a", b"b"])

    async def test_synthesize_stream_400_when_no_voice(self) -> None:
        user = _user(cred_id=uuid.uuid4(), voice_id=None)
        db = AsyncMock()
        with patch(
            "app.api.voice._resolve_credential",
            AsyncMock(return_value=("sk", _credential())),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await synthesize_stream(
                    text="hi", voice_id=None, credential_id=None, current_user=user, db=db
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_transcribe_returns_text(self) -> None:
        user = _user(cred_id=uuid.uuid4())
        db = AsyncMock()
        upload = MagicMock()
        upload.filename = "a.webm"
        upload.content_type = "audio/webm"
        upload.read = AsyncMock(return_value=b"AUDIO")
        with (
            patch(
                "app.api.voice._resolve_credential",
                AsyncMock(return_value=("sk", _credential())),
            ),
            patch(
                "app.api.voice.speech_to_text",
                AsyncMock(return_value={"text": "hello", "language_code": "en"}),
            ),
        ):
            result = await transcribe(file=upload, credential_id=None, current_user=user, db=db)
        self.assertEqual(result, {"text": "hello", "language_code": "en"})
