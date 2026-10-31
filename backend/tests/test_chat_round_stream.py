"""A chat round streams its text and the tool call being written, then answers in one piece."""

import json
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from app.services import chat_round_stream
from app.services.chat_round_stream import (
    RoundAnswer,
    RoundDraft,
    RoundProgress,
    complete_round,
    stream_round,
)


def _chunk(
    text: str | None = None,
    calls: list[dict[str, Any]] | None = None,
    usage: Any = None,
    finish: str | None = None,
) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(
            index=call.get("index"),
            id=call.get("id"),
            function=SimpleNamespace(name=call.get("name"), arguments=call.get("arguments")),
        )
        for call in calls or []
    ]
    delta = SimpleNamespace(content=text, tool_calls=tool_calls or None)
    choices = [] if usage is not None else [SimpleNamespace(delta=delta, finish_reason=finish)]
    return SimpleNamespace(choices=choices, usage=usage)


def _client(*responses: Any) -> MagicMock:
    client = MagicMock()
    client.base_url = "https://llm.example/v1"
    client.chat.completions.create.side_effect = list(responses)
    return client


async def _collect(client: Any, cancel_event: Event | None = None) -> list[Any]:
    return [
        event
        async for event in stream_round(
            client, cancel_event, model="gpt-5.5", messages=[], stream=False
        )
    ]


class StreamRoundTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.multiple(
            chat_round_stream, DRAFT_FLUSH_SECONDS=0, PROGRESS_REFRESH_SECONDS=0
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_text_arrives_as_drafts_and_the_answer_joins_it(self) -> None:
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13)
        client = _client(
            iter([_chunk("Here "), _chunk("are "), _chunk("runs."), _chunk(usage=usage)])
        )

        events = await _collect(client)

        drafts = [e.text for e in events if isinstance(e, RoundDraft)]
        self.assertEqual("".join(drafts), "Here are runs.")
        self.assertGreater(len(drafts), 1)
        answer = events[-1]
        self.assertIsInstance(answer, RoundAnswer)
        message = answer.completion.choices[0].message
        self.assertEqual(message.content, "Here are runs.")
        self.assertIsNone(message.tool_calls)
        self.assertIs(answer.completion.usage, usage)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["stream_options"], {"include_usage": True})

    async def test_a_tool_call_in_pieces_becomes_one_call_with_progress(self) -> None:
        arguments = json.dumps(
            {
                "workflow": {
                    "name": "Lead intake",
                    "nodes": [
                        {"id": "a", "type": "textInput", "data": {"label": "start"}},
                        {"id": "b", "type": "output", "data": {"label": "result"}},
                    ],
                    "edges": [],
                }
            }
        )
        cut = arguments.index('{"id": "b"')
        client = _client(
            iter(
                [
                    _chunk(calls=[{"index": 0, "id": "call_1", "name": "save_workflow"}]),
                    _chunk(calls=[{"index": 0, "arguments": arguments[:cut]}]),
                    _chunk(calls=[{"index": 0, "arguments": arguments[cut:]}], finish="tool_calls"),
                ]
            )
        )

        events = await _collect(client)

        progress = [e.message for e in events if isinstance(e, RoundProgress)]
        self.assertEqual(
            progress,
            [
                "Writing the workflow",
                'Writing "Lead intake" · 1 node (start)',
                'Writing "Lead intake" · 2 nodes (start, result)',
            ],
        )
        self.assertFalse([e for e in events if isinstance(e, RoundDraft)])
        calls = events[-1].completion.choices[0].message.tool_calls
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].id, "call_1")
        self.assertEqual(calls[0].function.name, "save_workflow")
        self.assertEqual(json.loads(calls[0].function.arguments)["workflow"]["name"], "Lead intake")

    async def test_calls_without_an_index_are_told_apart_by_id(self) -> None:
        client = _client(
            iter(
                [
                    _chunk(calls=[{"id": "c1", "name": "list_workflows", "arguments": "{}"}]),
                    _chunk(calls=[{"id": "c2", "name": "get_teams", "arguments": "{}"}]),
                ]
            )
        )

        events = await _collect(client)

        calls = events[-1].completion.choices[0].message.tool_calls
        self.assertEqual([c.id for c in calls], ["c1", "c2"])
        self.assertEqual([c.function.name for c in calls], ["list_workflows", "get_teams"])

    async def test_a_whole_answer_passes_through(self) -> None:
        whole = MagicMock(choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))])
        client = _client(whole)

        events = await _collect(client)

        self.assertEqual(len(events), 1)
        self.assertIs(events[0].completion, whole)

    async def test_an_empty_stream_asks_again_without_streaming(self) -> None:
        whole = MagicMock(choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))])
        client = _client(iter([]), whole)

        events = await _collect(client)

        self.assertIs(events[-1].completion, whole)
        second = client.chat.completions.create.call_args_list[1].kwargs
        self.assertFalse(second["stream"])

    async def test_a_cancel_mid_stream_answers_nothing(self) -> None:
        cancel_event = Event()

        def chunks() -> Any:
            yield _chunk("Half")
            cancel_event.set()
            yield _chunk(" an answer")

        events = await _collect(_client(chunks()), cancel_event)

        self.assertIsInstance(events[-1], RoundAnswer)
        self.assertIsNone(events[-1].completion)

    async def test_a_provider_error_is_raised(self) -> None:
        client = _client(RuntimeError("rate limited"))

        with self.assertRaisesRegex(RuntimeError, "rate limited"):
            await _collect(client)

    async def test_complete_round_reports_the_text_so_far(self) -> None:
        seen: list[str] = []
        client = _client(iter([_chunk('{"name": "A",'), _chunk(' "nodes": []}')]))

        completion = await complete_round(
            client, None, on_text=seen.append, model="gpt-5.5", messages=[]
        )

        self.assertEqual(completion.choices[0].message.content, '{"name": "A", "nodes": []}')
        self.assertEqual(seen[-1], '{"name": "A", "nodes": []}')
