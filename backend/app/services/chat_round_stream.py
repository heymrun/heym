"""One model round of a chat turn, streamed so the turn shows what the model is writing.

Chat used to wait for each round's whole answer, so a turn showed only "Thinking" until the
model had finished, which in a build turn means a whole workflow. A round now streams: text
comes out as `RoundDraft`s and a tool call being written as `RoundProgress` lines, both
throttled. It still ends with one answer shaped like a non-streaming completion, so the tool
loop reads it as before. Models that cannot stream there answer in one piece, as before.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from threading import Event
from types import SimpleNamespace
from typing import Any

from app.services.chat_progress import tool_draft_message
from app.services.llm_chat_bridge import completion_caller, is_completion, open_chat_round

DRAFT_FLUSH_SECONDS = 0.25
PROGRESS_REFRESH_SECONDS = 0.3


@dataclass(frozen=True)
class RoundDraft:
    """Text the model wrote since the previous draft."""

    text: str


@dataclass(frozen=True)
class RoundProgress:
    """What the tool call being written will do, e.g. the workflow and its nodes so far."""

    message: str


@dataclass(frozen=True)
class RoundAnswer:
    """The whole answer, shaped like a non-streaming completion; None when the turn stopped."""

    completion: Any


@dataclass
class _DraftCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


class _RoundAccumulator:
    """Builds the round's answer from its chunks."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.text: list[str] = []
        self.calls: list[_DraftCall] = []
        self._by_index: dict[int, _DraftCall] = {}
        self.usage: Any = None
        self.finish_reason: str | None = None
        self.saw_choice = False

    def add(self, chunk: Any) -> str:
        """Take one chunk in; returns the text it adds."""
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self.usage = usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        self.saw_choice = True
        choice = choices[0]
        self.finish_reason = getattr(choice, "finish_reason", None) or self.finish_reason
        delta = getattr(choice, "delta", None)
        if delta is None:
            return ""
        for part in getattr(delta, "tool_calls", None) or []:
            self._add_call_part(part)
        text = getattr(delta, "content", None)
        if isinstance(text, str) and text:
            self.text.append(text)
            return text
        return ""

    def _call_for(self, index: Any, call_id: str) -> _DraftCall:
        # Some gateways reuse one index, or send none, for every call; a new id is a new call.
        if isinstance(index, int):
            call = self._by_index.get(index)
            if call is not None and not (call_id and call.id and call_id != call.id):
                return call
        elif self.calls and call_id in ("", self.calls[-1].id):
            return self.calls[-1]
        call = _DraftCall()
        self.calls.append(call)
        if isinstance(index, int):
            self._by_index[index] = call
        return call

    def _add_call_part(self, part: Any) -> None:
        call_id = getattr(part, "id", None) or ""
        call = self._call_for(getattr(part, "index", None), call_id)
        function = getattr(part, "function", None)
        if call_id and not call.id:
            call.id = call_id
        name = getattr(function, "name", None) if function is not None else None
        if name and not call.name:
            call.name = name
        arguments = getattr(function, "arguments", None) if function is not None else None
        if arguments:
            call.arguments += arguments

    def drafting_message(self) -> str | None:
        """The progress line for the tool call being written now, if it has one."""
        if not self.calls or not self.calls[-1].name:
            return None
        call = self.calls[-1]
        return tool_draft_message(call.name, call.arguments)

    def completion(self) -> SimpleNamespace:
        tool_calls = [
            SimpleNamespace(
                id=call.id or f"call_{uuid.uuid4().hex[:24]}",
                type="function",
                function=SimpleNamespace(name=call.name, arguments=call.arguments or "{}"),
            )
            for call in self.calls
            if call.name
        ]
        message = SimpleNamespace(
            role="assistant", content="".join(self.text) or None, tool_calls=tool_calls or None
        )
        choices = (
            [SimpleNamespace(message=message, finish_reason=self.finish_reason, index=0)]
            if self.saw_choice
            else []
        )
        return SimpleNamespace(choices=choices, usage=self.usage, model=self.model)


async def stream_round(
    client: Any, cancel_event: Event | None, **kwargs: Any
) -> AsyncIterator[RoundDraft | RoundProgress | RoundAnswer]:
    """Run one model request, yielding drafts and progress as it streams, then its answer."""
    if cancel_event is not None and cancel_event.is_set():
        yield RoundAnswer(None)
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    stop = threading.Event()

    def stopped() -> bool:
        return stop.is_set() or (cancel_event is not None and cancel_event.is_set())

    def put(kind: str, value: Any) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, value))
        except RuntimeError:
            pass

    def produce() -> None:
        try:
            response = open_chat_round(client, **kwargs)
            if is_completion(response):
                put("answer", response)
                return
            received = False
            try:
                for chunk in response:
                    if stopped():
                        break
                    received = True
                    put("chunk", chunk)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if not received and not stopped():
                # A gateway that ignores `stream` sends plain JSON, which reads as no events.
                model = str(kwargs.get("model") or "")
                put("answer", completion_caller(client, model)(**{**kwargs, "stream": False}))
                return
            put("end", None)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the event loop
            put("error", exc)

    threading.Thread(target=produce, daemon=True).start()

    answer = _RoundAccumulator(str(kwargs.get("model") or ""))
    unsent: list[str] = []
    flushed_at = time.monotonic()
    refreshed_at = 0.0
    shown_progress: str | None = None
    try:
        while True:
            kind, value = await queue.get()
            if kind == "error":
                raise value
            if kind == "answer":
                yield RoundAnswer(None if stopped() else value)
                return
            if kind == "end":
                if stopped():
                    yield RoundAnswer(None)
                    return
                if unsent:
                    yield RoundDraft("".join(unsent))
                yield RoundAnswer(answer.completion())
                return
            text = answer.add(value)
            now = time.monotonic()
            if text:
                unsent.append(text)
            if unsent and now - flushed_at >= DRAFT_FLUSH_SECONDS:
                yield RoundDraft("".join(unsent))
                unsent.clear()
                flushed_at = now
            if answer.calls and now - refreshed_at >= PROGRESS_REFRESH_SECONDS:
                refreshed_at = now
                message = answer.drafting_message()
                if message and message != shown_progress:
                    shown_progress = message
                    yield RoundProgress(message)
    finally:
        stop.set()


async def complete_round(
    client: Any,
    cancel_event: Event | None,
    *,
    on_text: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> Any | None:
    """One streamed round's whole answer; `on_text` sees the text written so far."""
    written: list[str] = []
    async for event in stream_round(client, cancel_event, **kwargs):
        if isinstance(event, RoundDraft):
            written.append(event.text)
            if on_text is not None:
                on_text("".join(written))
        elif isinstance(event, RoundAnswer):
            return event.completion
    return None
