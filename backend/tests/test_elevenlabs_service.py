import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.elevenlabs_service import (
    ElevenLabsError,
    list_voices,
    speech_to_text,
    stream_text_to_speech,
    text_to_speech,
)


def _fake_stream_client(*, chunks=(), status_code=200):
    response = MagicMock()
    response.status_code = status_code

    def raise_for_status() -> None:
        if status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=MagicMock(), response=response)

    response.raise_for_status = MagicMock(side_effect=raise_for_status)

    async def aiter_bytes():
        for c in chunks:
            yield c

    response.aiter_bytes = aiter_bytes

    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=response)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.stream = MagicMock(return_value=stream_ctx)
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)
    return client_ctx


def _fake_client(*, json_data=None, content=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.content = content

    def raise_for_status() -> None:
        if status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=MagicMock(), response=response)

    response.raise_for_status.side_effect = raise_for_status

    client = AsyncMock()
    client.get.return_value = response
    client.post.return_value = response
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


class ElevenLabsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_voices_maps_id_and_name(self) -> None:
        ctx, _ = _fake_client(
            json_data={"voices": [{"voice_id": "v1", "name": "Rachel", "extra": 1}]}
        )
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            voices = await list_voices("sk_key")
        self.assertEqual(voices, [{"voice_id": "v1", "name": "Rachel"}])

    async def test_text_to_speech_returns_bytes(self) -> None:
        ctx, client = _fake_client(content=b"AUDIO")
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            audio = await text_to_speech("sk_key", "hello", "v1")
        self.assertEqual(audio, b"AUDIO")
        self.assertIn("/v1/text-to-speech/v1", client.post.call_args.args[0])

    async def test_speech_to_text_returns_text_and_language(self) -> None:
        ctx, _ = _fake_client(json_data={"text": "merhaba", "language_code": "tr"})
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            result = await speech_to_text("sk_key", b"AUDIO", "a.webm", "audio/webm")
        self.assertEqual(result, {"text": "merhaba", "language_code": "tr"})

    async def test_upstream_error_raises_elevenlabs_error(self) -> None:
        ctx, _ = _fake_client(json_data={"voices": []}, status_code=401)
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            with self.assertRaises(ElevenLabsError):
                await list_voices("sk_bad")

    async def test_stream_text_to_speech_yields_chunks(self) -> None:
        ctx = _fake_stream_client(chunks=[b"a", b"b", b"c"])
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            out = [chunk async for chunk in stream_text_to_speech("sk", "hi", "v1")]
        self.assertEqual(out, [b"a", b"b", b"c"])

    async def test_stream_raises_on_upstream_error(self) -> None:
        ctx = _fake_stream_client(chunks=[], status_code=401)
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            with self.assertRaises(ElevenLabsError):
                async for _ in stream_text_to_speech("sk", "hi", "v1"):
                    pass
