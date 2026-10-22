"""Let Chat and the AI assistant call models that OpenCode serves off Chat Completions.

Those surfaces build an OpenAI client and call ``chat.completions.create`` themselves, so the
transports ``LLMService`` picks per model never see them. ``completion_caller`` hands back
``client.chat.completions.create`` untouched for every credential and model that works there. Only
an OpenCode model served on Responses, Messages or generateContent goes through the matching
transport, and its answer is reshaped into the Chat Completions objects the callers already read.

Thinking blocks (Claude), thought signatures (Gemini) and reasoning items (GPT, Grok) must come back
verbatim on the next tool round, but the callers keep a plain OpenAI message list. Each answer's raw
items are remembered by tool call id and replayed when that call shows up in the history again.
"""

from __future__ import annotations

import functools
import json
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app.services.llm_transport import (
    ChatCompletionsTransport,
    LLMTransport,
    ModelProtocolError,
    RequestOpts,
    ResponsesTransport,
    ResponsesTransportError,
    ToolCall,
    ToolResult,
    TurnResult,
    provider_detail,
)
from app.services.llm_transport_gemini import GeminiTransport
from app.services.llm_transport_messages import AnthropicMessagesTransport
from app.services.opencode_catalog import is_opencode_base_url, opencode_model_protocol

_TRANSPORTS: dict[str, Callable[[], LLMTransport]] = {
    "responses": ResponsesTransport,
    "messages": AnthropicMessagesTransport,
    "google": GeminiTransport,
}

# Google's documented opt-out for a function call whose signature was not kept.
GEMINI_SKIP_SIGNATURE = "skip_thought_signature_validator"

_RAW_TURN_LIMIT = 512


@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Message:
    content: str | None
    tool_calls: list[_ToolCall] | None = None
    role: str = "assistant"


@dataclass
class _Choice:
    message: _Message
    finish_reason: str | None = None
    index: int = 0


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class _Completion:
    choices: list[_Choice]
    usage: _Usage
    model: str


@dataclass
class _Delta:
    content: str | None = None


@dataclass
class _ChunkChoice:
    delta: _Delta


@dataclass
class _Chunk:
    choices: list[_ChunkChoice]
    usage: _Usage | None = None


@dataclass(frozen=True)
class _RawTurn:
    protocol: str
    call_ids: frozenset[str]
    items: tuple[Any, ...]


_raw_turns: OrderedDict[str, _RawTurn] = OrderedDict()
_raw_lock = threading.Lock()


def gateway_protocol(client: Any, model: str) -> str | None:
    """The non-Chat-Completions API OpenCode serves ``model`` on, else None."""
    try:
        if not is_opencode_base_url(str(getattr(client, "base_url", "") or "")):
            return None
    except ValueError:
        return None
    protocol = opencode_model_protocol(model)
    return protocol if protocol in _TRANSPORTS else None


def completion_caller(client: Any, model: str) -> Callable[..., Any]:
    """``client.chat.completions.create``, or its stand-in for a model on another protocol."""
    protocol = gateway_protocol(client, model)
    if protocol is None:
        return client.chat.completions.create
    return functools.partial(_complete, client, protocol)


async def skip_compression(
    messages: list[dict[str, Any]], **_kwargs: Any
) -> tuple[list[dict[str, Any]], None]:
    """Stand-in for the context compressor, which summarises over Chat Completions."""
    return messages, None


def _remember(protocol: str, turn: TurnResult) -> None:
    if not turn.tool_calls or not turn.raw_items:
        return
    record = _RawTurn(
        protocol=protocol,
        call_ids=frozenset(call.id for call in turn.tool_calls),
        items=tuple(turn.raw_items),
    )
    with _raw_lock:
        for call_id in record.call_ids:
            _raw_turns[call_id] = record
            _raw_turns.move_to_end(call_id)
        while len(_raw_turns) > _RAW_TURN_LIMIT:
            _raw_turns.popitem(last=False)


def _recall(protocol: str, call_ids: list[str]) -> list[Any] | None:
    if not call_ids:
        return None
    with _raw_lock:
        record = _raw_turns.get(call_ids[0])
    if record is None or record.protocol != protocol or record.call_ids != frozenset(call_ids):
        return None
    return list(record.items)


def forget_remembered_turns() -> None:
    """Drop every remembered turn; tests start from a clean slate."""
    with _raw_lock:
        _raw_turns.clear()


def _arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _synthesized_items(protocol: str, text: str, calls: list[ToolCall]) -> list[Any]:
    """Provider items for an assistant turn whose raw answer was not kept."""
    if protocol == "messages":
        blocks: list[Any] = [{"type": "text", "text": text}] if text else []
        blocks.extend(
            {"type": "tool_use", "id": c.id, "name": c.name, "input": _arguments(c.arguments)}
            for c in calls
        )
        return blocks
    if protocol == "google":
        parts: list[Any] = [{"text": text}] if text else []
        parts.extend(
            {
                "functionCall": {"id": c.id, "name": c.name, "args": _arguments(c.arguments)},
                "thoughtSignature": GEMINI_SKIP_SIGNATURE,
            }
            for c in calls
        )
        return parts
    items: list[Any] = (
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ]
        if text
        else []
    )
    items.extend(
        {
            "type": "function_call",
            "call_id": c.id,
            "name": c.name,
            "arguments": c.arguments or "{}",
        }
        for c in calls
    )
    return items


def _flatten(content: Any) -> tuple[str, str | None]:
    """Text of a message body, and its first image; other part types are dropped."""
    if isinstance(content, str):
        return content, None
    if not isinstance(content, list):
        return "", None
    texts: list[str] = []
    image: str | None = None
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            texts.append(str(part["text"]))
        elif part.get("type") == "image_url" and image is None:
            target = part.get("image_url")
            image = target.get("url") if isinstance(target, dict) else target
    return "\n\n".join(texts), image


def _native_user_item(transport: LLMTransport, text: str, image: str) -> Any:
    seed = transport.start(
        system_instruction=None, conversation_history=None, user_message=text, image_input=image
    )
    return transport.dump(seed)[-1]


def _native_assistant_item(transport: LLMTransport, text: str) -> Any:
    seed = transport.start(
        system_instruction=None,
        conversation_history=[{"role": "assistant", "content": text}],
        user_message="",
        image_input=None,
    )
    return transport.dump(seed)[0]


def build_history(transport: LLMTransport, protocol: str, messages: list[dict[str, Any]]) -> Any:
    """Turn an OpenAI message list into the transport's own history."""
    system = "\n\n".join(
        text
        for message in messages
        if message.get("role") == "system"
        for text, _image in [_flatten(message.get("content"))]
        if text
    )
    history = transport.load([], system or None)
    pending: list[ToolResult] = []

    def flush() -> None:
        if pending:
            transport.append_tool_results(history, list(pending))
            pending.clear()

    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "tool":
            content = message.get("content")
            pending.append(
                ToolResult(
                    call_id=str(message.get("tool_call_id") or ""),
                    output=content if isinstance(content, str) else json.dumps(content),
                )
            )
            continue
        flush()
        text, image = _flatten(message.get("content"))
        if role == "user":
            if image:
                transport.dump(history).append(_native_user_item(transport, text, image))
            elif text:
                transport.append_user(history, text)
        elif role == "assistant":
            calls = [
                ToolCall(
                    id=str(call.get("id") or ""),
                    name=str((call.get("function") or {}).get("name") or ""),
                    arguments=str((call.get("function") or {}).get("arguments") or "{}"),
                )
                for call in message.get("tool_calls") or []
            ]
            if calls:
                raw = _recall(protocol, [call.id for call in calls])
                if raw is None:
                    raw = _synthesized_items(protocol, text, calls)
                transport.append_turn(
                    history, TurnResult(text=text, tool_calls=calls, raw_items=raw)
                )
            elif text:
                transport.dump(history).append(_native_assistant_item(transport, text))
    flush()
    return history


def _request_opts(kwargs: dict[str, Any]) -> RequestOpts:
    tool_choice = kwargs.get("tool_choice")
    return RequestOpts(
        temperature=kwargs.get("temperature"),
        tool_choice=tool_choice if isinstance(tool_choice, str) else None,
        reasoning_effort=kwargs.get("reasoning_effort"),
        max_tokens=kwargs.get("max_tokens") or kwargs.get("max_completion_tokens"),
        response_format=kwargs.get("response_format"),
    )


def _to_completion(model: str, turn: TurnResult) -> _Completion:
    tool_calls = [
        _ToolCall(id=call.id, function=_Function(name=call.name, arguments=call.arguments))
        for call in turn.tool_calls
    ]
    return _Completion(
        choices=[
            _Choice(
                message=_Message(content=turn.text or None, tool_calls=tool_calls or None),
                finish_reason=turn.finish_reason,
            )
        ],
        usage=_Usage(turn.prompt_tokens, turn.completion_tokens, turn.total_tokens),
        model=model,
    )


def _single_chunk_stream(completion: _Completion) -> Iterator[_Chunk]:
    """These APIs are called without streaming, so the whole answer arrives as one chunk."""
    text = completion.choices[0].message.content
    if text:
        yield _Chunk(choices=[_ChunkChoice(_Delta(content=text))])
    yield _Chunk(choices=[], usage=completion.usage)


def _create_turn(
    protocol: str,
    *,
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    opts: RequestOpts,
) -> TurnResult:
    """Send an OpenAI message list to ``model`` on ``protocol``'s own API."""
    transport = _TRANSPORTS[protocol]()
    history = build_history(transport, protocol, messages)
    try:
        turn = transport.create(client=client, model=model, history=history, tools=tools, opts=opts)
    except ResponsesTransportError as exc:
        raise ModelProtocolError(
            f"The gateway did not accept {model} on the Responses API: "
            f"{provider_detail(exc.__cause__ or exc)}"
        ) from exc
    _remember(protocol, turn)
    return turn


def _complete(client: Any, protocol: str, **kwargs: Any) -> Any:
    """Run one Chat Completions style request on ``protocol``'s transport.

    Request fields with no equivalent there (``stream_options``, ``extra_body``) are dropped.
    """
    model = str(kwargs["model"])
    turn = _create_turn(
        protocol,
        client=client,
        model=model,
        messages=kwargs.get("messages") or [],
        tools=kwargs.get("tools") or None,
        opts=_request_opts(kwargs),
    )
    completion = _to_completion(model, turn)
    if kwargs.get("stream"):
        return _single_chunk_stream(completion)
    return completion


class BridgedChatTransport(ChatCompletionsTransport):
    """A Chat shaped history sent to a model on another API, for Model Router turns.

    A routed run can change model every turn, so its history stays a plain message list and
    each request is translated onto the chosen model's API. The trace stays Chat shaped for the
    Steps view; `gateway_protocol` names the API that answered.
    """

    def __init__(self, protocol: str) -> None:
        super().__init__()
        self.protocol = protocol
        # Whether the JSON contract rides in a request field is the native API's property.
        self.carries_response_format = _TRANSPORTS[protocol]().carries_response_format

    def create(
        self,
        *,
        client: Any,
        model: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> TurnResult:
        return _create_turn(
            self.protocol,
            client=client,
            model=model,
            messages=history,
            tools=tools,
            opts=opts,
        )

    def final_text(self, turn: TurnResult) -> str:
        return turn.text

    async def compress(
        self,
        history: list[dict[str, Any]],
        *,
        model: str,
        client: Any,
        context_limit_tokens: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """The shared compressor summarises over Chat Completions, which these models refuse."""
        return history, None

    def trace_request(
        self, history: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {**super().trace_request(history, tools), "gateway_protocol": self.protocol}
