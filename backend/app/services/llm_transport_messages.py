"""Anthropic Messages transport for gateways that serve some models on /messages only.

OpenCode Go offers Claude Haiku and MiniMax M2.7 on `/messages` and answers 400
`ModelProtocolUnsupported` on every other endpoint. The request goes through the OpenAI client's
generic `post`, so the guarded HTTP client, the Heym User-Agent and the `x-opencode-session`
header apply exactly as they do for Chat Completions and Responses.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.json_output import json_instruction, unwrap_json_fence
from app.services.llm_transport import (
    ModelProtocolError,
    RequestOpts,
    ToolCall,
    ToolResult,
    TurnResult,
    is_protocol_unsupported,
)

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192

_DATA_URI = re.compile(r"^data:([^;,]+);base64,(.*)$", re.DOTALL)
_TOOL_CHOICES = {"auto": "auto", "none": "none", "required": "any"}
# Claude 5 answers 400 "`temperature` is deprecated for this model" for any non-default value.
_NO_TEMPERATURE_PREFIXES = ("claude-",)


@dataclass
class MessagesHistory:
    """`system` is a request field on this API, so it stays out of the message list."""

    system: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)


def _image_block(image: str) -> dict[str, Any]:
    match = _DATA_URI.match(image)
    if match:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": match.group(1), "data": match.group(2)},
        }
    return {"type": "image", "source": {"type": "url", "url": image}}


def is_thinking_binding_error(exc: Exception) -> bool:
    text = str(exc)
    return "`thinking` block" in text and (
        "signature" in text or "bound to a different conversation" in text
    )


def drop_thinking_blocks(messages: list[dict[str, Any]]) -> bool:
    """Remove thinking blocks in place, and assistant turns left empty; True when any went."""
    dropped = False
    for message in messages:
        content = message.get("content")
        if message.get("role") != "assistant" or not isinstance(content, list):
            continue
        kept = [b for b in content if b.get("type") not in ("thinking", "redacted_thinking")]
        if len(kept) != len(content):
            dropped = True
            message["content"] = kept
    messages[:] = [m for m in messages if m.get("role") != "assistant" or m.get("content")]
    return dropped


def _redact_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted = copy.deepcopy(messages)
    for message in redacted:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            source = block.get("source") if isinstance(block, dict) else None
            if isinstance(source, dict) and source.get("type") == "base64":
                source["data"] = "[base64]"
    return redacted


class AnthropicMessagesTransport:
    """POST /messages. Stateless: the full conversation goes out every turn."""

    name = "messages"
    carries_response_format = False

    def new_history(self) -> MessagesHistory:
        return MessagesHistory()

    def start(
        self,
        *,
        system_instruction: str | None,
        conversation_history: list[dict[str, str]] | None,
        user_message: str,
        image_input: str | None,
    ) -> MessagesHistory:
        history = MessagesHistory(system=system_instruction or None)
        for msg in conversation_history or []:
            if not msg.get("content"):
                continue
            role = msg["role"] if msg["role"] in ("user", "assistant") else "user"
            history.messages.append({"role": role, "content": msg["content"]})
        if image_input:
            content: str | list[dict[str, Any]] = [
                {"type": "text", "text": user_message},
                _image_block(image_input),
            ]
        else:
            content = user_message
        history.messages.append({"role": "user", "content": content})
        return history

    def load(self, raw: list[dict[str, Any]], system_instruction: str | None) -> MessagesHistory:
        return MessagesHistory(system=system_instruction or None, messages=copy.deepcopy(raw))

    def dump(self, history: MessagesHistory) -> list[dict[str, Any]]:
        return history.messages

    @staticmethod
    def _translate_tool(tool: dict[str, Any]) -> dict[str, Any]:
        fn = tool.get("function") or {}
        return {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        }

    def build_kwargs(
        self,
        *,
        model: str,
        history: MessagesHistory,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> dict[str, Any]:
        system = history.system
        instruction = json_instruction(opts.response_format)
        if instruction:
            system = f"{system}\n\n{instruction}" if system else instruction
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": opts.max_tokens or DEFAULT_MAX_TOKENS,
            "messages": history.messages,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [self._translate_tool(t) for t in tools]
            choice = _TOOL_CHOICES.get(opts.tool_choice or "auto", "auto")
            body["tool_choice"] = {"type": choice}
        if opts.temperature is not None and not model.lower().startswith(_NO_TEMPERATURE_PREFIXES):
            body["temperature"] = min(max(opts.temperature, 0.0), 1.0)
        if opts.extra_body is not None:
            body.update(copy.deepcopy(opts.extra_body))
        return body

    def create(
        self,
        *,
        client: Any,
        model: str,
        history: MessagesHistory,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> TurnResult:
        body = self.build_kwargs(model=model, history=history, tools=tools, opts=opts)
        return self._post(client, model, body, opts)

    def _post(self, client: Any, model: str, body: dict[str, Any], opts: RequestOpts) -> TurnResult:
        try:
            response = self._send(client, body)
        except Exception as exc:
            if is_thinking_binding_error(exc) and drop_thinking_blocks(body["messages"]):
                # Claude signs a thinking block for one conversation prefix; the error says to drop it.
                try:
                    response = self._send(client, body)
                except Exception as retry_exc:
                    raise self._explain(model, retry_exc) from retry_exc
            else:
                raise self._explain(model, exc) from exc
        turn = self.to_turn(response.json())
        if json_instruction(opts.response_format):
            turn.text = unwrap_json_fence(turn.text)
        return turn

    @staticmethod
    def _send(client: Any, body: dict[str, Any]) -> Any:
        # OpenCode Go reads the key from x-api-key here, as Anthropic does, and answers 401
        # "Go requires a credential" to the Bearer header alone.
        return client.post(
            "/messages",
            cast_to=httpx.Response,
            body=body,
            options={
                "headers": {"anthropic-version": ANTHROPIC_VERSION, "x-api-key": client.api_key}
            },
        )

    @staticmethod
    def _explain(model: str, exc: Exception) -> Exception:
        if is_protocol_unsupported(exc):
            return ModelProtocolError(
                f"The gateway does not serve {model} over the Anthropic Messages API. "
                f"Pick a model it serves over Chat Completions or the Responses API."
            )
        return exc

    def to_turn(self, payload: dict[str, Any]) -> TurnResult:
        blocks = list(payload.get("content") or [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tool_calls = [
            ToolCall(
                id=b.get("id", ""),
                name=b.get("name", ""),
                arguments=json.dumps(b.get("input") or {}),
            )
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        usage = payload.get("usage") or {}
        prompt_tokens = (
            (usage.get("input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
        )
        completion_tokens = usage.get("output_tokens") or 0
        return TurnResult(
            text=text,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            finish_reason=payload.get("stop_reason"),
            raw_items=blocks,
        )

    def final_text(self, turn: TurnResult) -> str:
        return turn.text

    def last_item_is_tool_result(self, history: MessagesHistory) -> bool:
        if not history.messages:
            return False
        last = history.messages[-1]
        content = last.get("content")
        return (
            last.get("role") == "user"
            and isinstance(content, list)
            and any(b.get("type") == "tool_result" for b in content)
        )

    def append_turn(self, history: MessagesHistory, turn: TurnResult) -> None:
        """Content blocks go back verbatim, which keeps any thinking blocks intact."""
        if turn.raw_items:
            history.messages.append({"role": "assistant", "content": copy.deepcopy(turn.raw_items)})

    def append_tool_results(self, history: MessagesHistory, results: list[ToolResult]) -> None:
        """Results for one assistant turn must share one user message."""
        blocks = [
            {"type": "tool_result", "tool_use_id": r.call_id, "content": r.output} for r in results
        ]
        if self.last_item_is_tool_result(history):
            history.messages[-1]["content"].extend(blocks)
        else:
            history.messages.append({"role": "user", "content": blocks})

    def append_user(self, history: MessagesHistory, text: str) -> None:
        history.messages.append({"role": "user", "content": text})

    async def compress(
        self, history: MessagesHistory, *, model: str, client: Any, context_limit_tokens: int
    ) -> tuple[MessagesHistory, dict[str, Any] | None]:
        """The shared compressor summarises over Chat Completions, which this model refuses."""
        return history, None

    def trace_request(
        self, history: MessagesHistory, tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {
            "system": history.system,
            "messages": _redact_images(history.messages),
            "tools": [self._translate_tool(t) for t in tools or []],
        }
