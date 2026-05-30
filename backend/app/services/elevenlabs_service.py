"""Async client helpers for the ElevenLabs API (voices, TTS, STT)."""

from collections.abc import AsyncIterator

import httpx

_BASE_URL = "https://api.elevenlabs.io"
_TTS_MODEL_ID = "eleven_multilingual_v2"
_STT_MODEL_ID = "scribe_v1"
_TIMEOUT = httpx.Timeout(60.0)


class ElevenLabsError(Exception):
    """Raised when an ElevenLabs API call fails."""


def _headers(api_key: str) -> dict[str, str]:
    return {"xi-api-key": api_key}


async def list_voices(api_key: str) -> list[dict[str, str]]:
    """Return the account's voices as ``[{voice_id, name}]``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{_BASE_URL}/v1/voices", headers=_headers(api_key))
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to list voices: {exc}") from exc
    return [{"voice_id": v["voice_id"], "name": v.get("name", "")} for v in data.get("voices", [])]


async def text_to_speech(
    api_key: str, text: str, voice_id: str, model_id: str = _TTS_MODEL_ID
) -> bytes:
    """Synthesize ``text`` with ``voice_id`` and return MP3 bytes."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_BASE_URL}/v1/text-to-speech/{voice_id}",
                headers={**_headers(api_key), "Accept": "audio/mpeg"},
                json={"text": text, "model_id": model_id},
            )
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to synthesize speech: {exc}") from exc


async def stream_text_to_speech(
    api_key: str, text: str, voice_id: str, model_id: str = _TTS_MODEL_ID
) -> AsyncIterator[bytes]:
    """Yield MP3 chunks from the ElevenLabs streaming endpoint as they arrive."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{_BASE_URL}/v1/text-to-speech/{voice_id}/stream",
                headers={**_headers(api_key), "Accept": "audio/mpeg"},
                json={"text": text, "model_id": model_id},
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to stream speech: {exc}") from exc


async def speech_to_text(
    api_key: str, audio: bytes, filename: str, content_type: str
) -> dict[str, str]:
    """Transcribe ``audio`` with Scribe; returns ``{text, language_code}``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_BASE_URL}/v1/speech-to-text",
                headers=_headers(api_key),
                # tag_audio_events=false keeps non-speech sounds (laughs, clicks,
                # lip smacks) out of the transcript so they are not sent as chat.
                data={"model_id": _STT_MODEL_ID, "tag_audio_events": "false"},
                files={"file": (filename, audio, content_type)},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to transcribe audio: {exc}") from exc
    return {
        "text": data.get("text", ""),
        "language_code": data.get("language_code", ""),
    }
