import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.minimax_speech_service import (
    DEFAULT_MODEL,
    SPEECH_ENDPOINTS,
    SPEECH_MODELS,
    MiniMaxSpeechError,
    MiniMaxSpeechOptions,
    create_async_speech,
    query_async_speech,
    stream_text_to_speech,
    text_to_speech,
)


def _response(data=None, *, content=b"", status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.json.return_value = data
    response.raise_for_status.return_value = None
    return response


def _client(*responses):
    client = AsyncMock()
    client.post.side_effect = list(responses)
    client.get.side_effect = list(responses[1:])
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, client


class MiniMaxSpeechServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_synthesis_uses_global_endpoint_and_options(self) -> None:
        context, client = _client(
            _response(
                {
                    "data": {"audio": "0001ff", "status": 2},
                    "base_resp": {"status_code": 0},
                }
            )
        )
        options = MiniMaxSpeechOptions(
            voice_setting={"voice_id": "English_expressive_narrator"},
            language_boost="English",
            pronunciation_dict={"tone": ["hello/hello"]},
            audio_setting={"sample_rate": 32000},
            voice_modify={"pitch": 1},
            subtitle_enable=True,
        )
        with patch("app.services.minimax_speech_service.httpx.AsyncClient", return_value=context):
            audio = await text_to_speech("test-key", "hello", options=options)

        self.assertEqual(audio, b"\x00\x01\xff")
        self.assertEqual(client.post.call_args.args[0], SPEECH_ENDPOINTS["global_en"])
        self.assertEqual(
            client.post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )
        self.assertEqual(
            client.post.call_args.kwargs["json"],
            {
                "model": DEFAULT_MODEL,
                "text": "hello",
                "voice_setting": {"voice_id": "English_expressive_narrator"},
                "audio_setting": {"sample_rate": 32000, "format": "mp3"},
                "language_boost": "English",
                "pronunciation_dict": {"tone": ["hello/hello"]},
                "voice_modify": {"pitch": 1},
                "stream": False,
                "output_format": "hex",
                "subtitle_enable": True,
            },
        )

    async def test_url_synthesis_uses_china_endpoint_and_downloads_audio(self) -> None:
        context, client = _client(
            _response(
                {
                    "data": {"audio": "https://cdn.example.com/audio.wav", "status": 2},
                    "base_resp": {"status_code": 0},
                }
            ),
            _response(content=b"AUDIO"),
        )
        client.get.return_value = _response(content=b"AUDIO")
        options = MiniMaxSpeechOptions(output_format="url", audio_format="wav")
        with patch("app.services.minimax_speech_service.httpx.AsyncClient", return_value=context):
            audio = await text_to_speech("test-key", "hello", region="cn_zh", options=options)

        self.assertEqual(audio, b"AUDIO")
        self.assertEqual(client.post.call_args.args[0], SPEECH_ENDPOINTS["cn_zh"])

    async def test_async_create_and_query_use_regional_operations(self) -> None:
        create_context, create_client = _client(
            _response({"task_id": "task-1", "base_resp": {"status_code": 0}})
        )
        query_context, query_client = _client(
            _response({"task_id": "task-1", "status": "success", "base_resp": {"status_code": 0}})
        )
        with patch(
            "app.services.minimax_speech_service.httpx.AsyncClient",
            side_effect=[create_context, query_context],
        ):
            created = await create_async_speech("test-key", "hello", region="cn_zh")
            queried = await query_async_speech("test-key", "task-1", region="cn_zh")

        self.assertEqual(created["task_id"], "task-1")
        self.assertEqual(queried["status"], "success")
        self.assertEqual(
            create_client.post.call_args.args[0], "https://api.minimaxi.com/v1/t2a_async_v2"
        )
        self.assertEqual(
            query_client.post.call_args.args[0],
            "https://api.minimaxi.com/v1/query/t2a_async_query_v2",
        )
        self.assertEqual(query_client.post.call_args.kwargs["json"], {"task_id": "task-1"})

    async def test_websocket_stream_follows_event_protocol(self) -> None:
        websocket = MagicMock()
        websocket.send = AsyncMock()

        async def messages():
            for message in (
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {"event": "task_started", "base_resp": {"status_code": 0}},
                {
                    "event": "task_continued",
                    "data": {"audio": "0001ff"},
                    "base_resp": {"status_code": 0},
                },
                {"event": "task_finished", "base_resp": {"status_code": 0}},
            ):
                yield json.dumps(message)

        websocket.__aiter__.side_effect = messages
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=websocket)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch("app.services.minimax_speech_service.websockets.connect", return_value=context):
            chunks = [chunk async for chunk in stream_text_to_speech("test-key", "hello")]

        self.assertEqual(chunks, [b"\x00\x01\xff"])
        events = [json.loads(call.args[0])["event"] for call in websocket.send.call_args_list]
        self.assertEqual(events, ["task_start", "task_continue", "task_finish"])

    async def test_api_error_and_unsupported_model_are_rejected(self) -> None:
        context, _ = _client(
            _response({"base_resp": {"status_code": 1004, "status_msg": "invalid key"}})
        )
        with patch("app.services.minimax_speech_service.httpx.AsyncClient", return_value=context):
            with self.assertRaisesRegex(MiniMaxSpeechError, "invalid key"):
                await text_to_speech("bad-key", "hello")
        self.assertEqual(len(SPEECH_MODELS), 8)
        with self.assertRaisesRegex(MiniMaxSpeechError, "Unsupported"):
            await text_to_speech("test-key", "hello", options=MiniMaxSpeechOptions(model="old"))
