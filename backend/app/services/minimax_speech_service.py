"""Async client helpers for the MiniMax speech APIs."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import websockets

MiniMaxRegion = Literal["global_en", "cn_zh"]
MiniMaxAudioFormat = Literal["mp3", "wav", "flac", "pcm"]
MiniMaxOutputFormat = Literal["hex", "url"]

DEFAULT_MODEL = "speech-2.8-hd"
SPEECH_MODELS = (
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
)
SPEECH_ENDPOINTS: dict[MiniMaxRegion, str] = {
    "global_en": "https://api.minimax.io/v1/t2a_v2",
    "cn_zh": "https://api.minimaxi.com/v1/t2a_v2",
}
_ASYNC_PATH = "/v1/t2a_async_v2"
_ASYNC_QUERY_PATH = "/v1/query/t2a_async_query_v2"
_WEBSOCKET_PATH = "/ws/v1/t2a_v2"
_TIMEOUT = httpx.Timeout(60.0)


class MiniMaxSpeechError(Exception):
    """Raised when a MiniMax speech operation fails."""


@dataclass(frozen=True, slots=True)
class MiniMaxSpeechOptions:
    """Options shared by synchronous, asynchronous, and WebSocket synthesis."""

    model: str = DEFAULT_MODEL
    language_boost: str | None = None
    output_format: MiniMaxOutputFormat = "hex"
    audio_format: MiniMaxAudioFormat = "mp3"
    voice_setting: dict[str, Any] = field(default_factory=dict)
    pronunciation_dict: dict[str, Any] | None = None
    audio_setting: dict[str, Any] = field(default_factory=dict)
    voice_modify: dict[str, Any] | None = None
    subtitle_enable: bool = False


def _host(region: MiniMaxRegion) -> str:
    return "api.minimaxi.com" if region == "cn_zh" else "api.minimax.io"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _request_body(text: str, options: MiniMaxSpeechOptions) -> dict[str, Any]:
    if options.model not in SPEECH_MODELS:
        raise MiniMaxSpeechError(f"Unsupported MiniMax speech model: {options.model}")
    body: dict[str, Any] = {
        "model": options.model,
        "text": text,
        "voice_setting": options.voice_setting,
        "audio_setting": {**options.audio_setting, "format": options.audio_format},
    }
    if options.language_boost is not None:
        body["language_boost"] = options.language_boost
    if options.pronunciation_dict is not None:
        body["pronunciation_dict"] = options.pronunciation_dict
    if options.voice_modify is not None:
        body["voice_modify"] = options.voice_modify
    return body


def _check_response(data: dict[str, Any], operation: str) -> None:
    base_response = data.get("base_resp") or {}
    if base_response.get("status_code") != 0:
        message = base_response.get("status_msg") or "unknown error"
        raise MiniMaxSpeechError(f"MiniMax {operation} failed: {message}")


async def text_to_speech(
    api_key: str,
    text: str,
    *,
    region: MiniMaxRegion = "global_en",
    options: MiniMaxSpeechOptions | None = None,
) -> bytes:
    """Synthesize speech with the regional HTTP endpoint and return audio bytes."""
    resolved = options or MiniMaxSpeechOptions()
    body = {
        **_request_body(text, resolved),
        "stream": False,
        "output_format": resolved.output_format,
        "subtitle_enable": resolved.subtitle_enable,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                SPEECH_ENDPOINTS[region], headers=_headers(api_key), json=body
            )
            response.raise_for_status()
            data = response.json()
            _check_response(data, "synthesis")
            audio_data = (data.get("data") or {}).get("audio")
            status = (data.get("data") or {}).get("status")
            if status != 2 or not audio_data:
                raise MiniMaxSpeechError("MiniMax synthesis completed without audio output")
            if resolved.output_format == "url":
                audio_response = await client.get(audio_data)
                audio_response.raise_for_status()
                return audio_response.content
            try:
                return bytes.fromhex(audio_data)
            except ValueError as exc:
                raise MiniMaxSpeechError("MiniMax synthesis returned invalid hex audio") from exc
    except httpx.HTTPError as exc:
        raise MiniMaxSpeechError(f"MiniMax synthesis request failed: {exc}") from exc


async def create_async_speech(
    api_key: str,
    text: str,
    *,
    region: MiniMaxRegion = "global_en",
    options: MiniMaxSpeechOptions | None = None,
) -> dict[str, Any]:
    """Create an asynchronous speech task and return its task metadata."""
    resolved = options or MiniMaxSpeechOptions()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"https://{_host(region)}{_ASYNC_PATH}",
                headers=_headers(api_key),
                json=_request_body(text, resolved),
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise MiniMaxSpeechError(f"MiniMax async request failed: {exc}") from exc
    _check_response(data, "async synthesis")
    return data


async def query_async_speech(
    api_key: str, task_id: str, *, region: MiniMaxRegion = "global_en"
) -> dict[str, Any]:
    """Query an asynchronous speech task."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"https://{_host(region)}{_ASYNC_QUERY_PATH}",
                headers=_headers(api_key),
                json={"task_id": task_id},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise MiniMaxSpeechError(f"MiniMax async query failed: {exc}") from exc
    _check_response(data, "async query")
    return data


async def stream_text_to_speech(
    api_key: str,
    text: str,
    *,
    region: MiniMaxRegion = "global_en",
    options: MiniMaxSpeechOptions | None = None,
) -> AsyncIterator[bytes]:
    """Yield hex-decoded audio chunks from the MiniMax WebSocket protocol."""
    resolved = options or MiniMaxSpeechOptions()
    url = f"wss://{_host(region)}{_WEBSOCKET_PATH}"
    try:
        async with websockets.connect(url, additional_headers=_headers(api_key)) as websocket:
            async for raw_message in websocket:
                data = json.loads(raw_message)
                _check_response(data, "WebSocket synthesis")
                event = data.get("event")
                if event == "connected_success":
                    await websocket.send(
                        json.dumps({"event": "task_start", **_request_body("", resolved)})
                    )
                elif event == "task_started":
                    await websocket.send(json.dumps({"event": "task_continue", "text": text}))
                    await websocket.send(json.dumps({"event": "task_finish"}))
                elif event == "task_continued" and (data.get("data") or {}).get("audio"):
                    try:
                        yield bytes.fromhex(data["data"]["audio"])
                    except ValueError as exc:
                        raise MiniMaxSpeechError(
                            "MiniMax WebSocket returned invalid hex audio"
                        ) from exc
                elif event == "task_finished":
                    return
                elif event == "task_failed":
                    raise MiniMaxSpeechError("MiniMax WebSocket synthesis failed")
    except (OSError, websockets.WebSocketException) as exc:
        raise MiniMaxSpeechError(f"MiniMax WebSocket request failed: {exc}") from exc
