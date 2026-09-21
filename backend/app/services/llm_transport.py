"""Transport seam between LLMService's loops and the OpenAI SDK.

`ChatCompletionsTransport` carries the historical behaviour. `ResponsesTransport`
translates the same loop onto `client.responses.create`, where reasoning items
must survive every turn. The loop never inspects a history's contents.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.llm_provider import is_reasoning_model


@dataclass(eq=False)
class ToolCall:
    """eq=False: the agent loop partitions tool calls with `tc not in [...]`."""

    id: str
    name: str
    arguments: str


@dataclass
class ToolResult:
    call_id: str
    output: str


@dataclass
class TurnResult:
    text: str
    tool_calls: list[ToolCall]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    raw_items: list[Any] = field(default_factory=list)


@dataclass
class RequestOpts:
    temperature: float | None = None
    tool_choice: str | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None
    extra_body: dict[str, Any] | None = None


class LLMTransport(Protocol):
    name: str

    def start(
        self,
        *,
        system_instruction: str | None,
        conversation_history: list[dict[str, str]] | None,
        user_message: str,
        image_input: str | None,
    ) -> Any: ...

    def load(self, raw: list[dict[str, Any]], system_instruction: str | None) -> Any: ...

    def dump(self, history: Any) -> list[dict[str, Any]]: ...

    def build_kwargs(
        self,
        *,
        model: str,
        history: Any,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> dict[str, Any]: ...

    def create(
        self,
        *,
        client: Any,
        model: str,
        history: Any,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> TurnResult: ...

    def final_text(self, turn: TurnResult) -> str: ...

    def last_item_is_tool_result(self, history: Any) -> bool: ...

    def append_turn(self, history: Any, turn: TurnResult) -> None: ...

    def append_tool_results(self, history: Any, results: list[ToolResult]) -> None: ...

    def append_user(self, history: Any, text: str) -> None: ...

    async def compress(
        self, history: Any, *, model: str, client: Any, context_limit_tokens: int
    ) -> tuple[Any, dict[str, Any] | None]: ...

    def trace_request(self, history: Any, tools: list[dict[str, Any]] | None) -> dict[str, Any]: ...


class ChatCompletionsTransport:
    """Today's behaviour, unchanged. History is the familiar message list."""

    name = "chat.completions"

    def start(
        self,
        *,
        system_instruction: str | None,
        conversation_history: list[dict[str, str]] | None,
        user_message: str,
        image_input: str | None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        for msg in conversation_history or []:
            messages.append({"role": msg["role"], "content": msg["content"]})
        if image_input:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {"type": "image_url", "image_url": {"url": image_input}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user_message})
        return messages

    def load(
        self, raw: list[dict[str, Any]], system_instruction: str | None
    ) -> list[dict[str, Any]]:
        messages = copy.deepcopy(raw)
        if system_instruction:
            if messages and messages[0].get("role") == "system":
                messages[0] = {"role": "system", "content": system_instruction}
            else:
                messages.insert(0, {"role": "system", "content": system_instruction})
        return messages

    def dump(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return history

    def build_kwargs(
        self,
        *,
        model: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": model, "messages": history}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = opts.tool_choice or "auto"
        is_reasoning = is_reasoning_model(model)
        if opts.max_tokens is not None:
            kwargs["max_completion_tokens" if is_reasoning else "max_tokens"] = opts.max_tokens
        if is_reasoning and opts.reasoning_effort:
            kwargs["reasoning_effort"] = opts.reasoning_effort
        elif opts.temperature is not None:
            kwargs["temperature"] = opts.temperature
        if opts.response_format is not None:
            kwargs["response_format"] = opts.response_format
        if opts.extra_body is not None:
            kwargs["extra_body"] = copy.deepcopy(opts.extra_body)
        return kwargs

    def create(
        self,
        *,
        client: Any,
        model: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> TurnResult:
        kwargs = self.build_kwargs(model=model, history=history, tools=tools, opts=opts)
        response = client.chat.completions.create(**kwargs)
        return self.to_turn(response)

    def to_turn(self, response: Any) -> TurnResult:
        choice = response.choices[0]
        message = choice.message
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        usage = getattr(response, "usage", None)
        return TurnResult(
            text=message.content if isinstance(message.content, str) else "",
            tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
                for tc in raw_tool_calls
            ],
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0 if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0 if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0 if usage else 0,
            finish_reason=getattr(choice, "finish_reason", None),
            raw_items=[response],
        )

    def last_item_is_tool_result(self, history: list[dict[str, Any]]) -> bool:
        return bool(history) and history[-1].get("role") == "tool"

    def final_text(self, turn: TurnResult) -> str:
        """`turn.text` is message.content only; the final answer also falls back to
        the `reasoning` field some providers use."""
        from app.services.llm_service import _extract_text_from_response

        if not turn.raw_items:
            return turn.text
        return _extract_text_from_response(turn.raw_items[0])

    def append_turn(self, history: list[dict[str, Any]], turn: TurnResult) -> None:
        history.append(
            {
                "role": "assistant",
                "content": turn.text or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in turn.tool_calls
                ],
            }
        )

    def append_tool_results(self, history: list[dict[str, Any]], results: list[ToolResult]) -> None:
        for result in results:
            history.append(
                {"role": "tool", "tool_call_id": result.call_id, "content": result.output}
            )

    def append_user(self, history: list[dict[str, Any]], text: str) -> None:
        history.append({"role": "user", "content": text})

    async def compress(
        self,
        history: list[dict[str, Any]],
        *,
        model: str,
        client: Any,
        context_limit_tokens: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        from app.services.context_compressor import maybe_compress_messages

        return await maybe_compress_messages(
            history, model=model, client=client, context_limit_tokens=context_limit_tokens
        )

    def trace_request(
        self, history: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        from app.services.llm_service import _sanitize_messages

        return {"messages": _sanitize_messages(history), "tools": tools or []}


@dataclass
class ResponsesHistory:
    items: list[dict[str, Any]] = field(default_factory=list)


class ResponsesTransportError(RuntimeError):
    """Raised when the endpoint is unavailable, with actionable text for the node."""


class ResponsesTransport:
    """OpenAI Responses API. Stateless: full input each turn, reasoning items
    carried back as encrypted blobs so a tool loop keeps its chain of thought."""

    name = "responses"

    def new_history(self) -> ResponsesHistory:
        return ResponsesHistory()

    def start(
        self,
        *,
        system_instruction: str | None,
        conversation_history: list[dict[str, str]] | None,
        user_message: str,
        image_input: str | None,
    ) -> ResponsesHistory:
        history = ResponsesHistory()
        if system_instruction:
            history.items.append(
                {"type": "message", "role": "system", "content": system_instruction}
            )
        for msg in conversation_history or []:
            history.items.append(
                {"type": "message", "role": msg["role"], "content": msg["content"]}
            )
        if image_input:
            history.items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_message},
                        {"type": "input_image", "image_url": image_input},
                    ],
                }
            )
        else:
            history.items.append({"type": "message", "role": "user", "content": user_message})
        return history

    def load(self, raw: list[dict[str, Any]], system_instruction: str | None) -> ResponsesHistory:
        items = copy.deepcopy(raw)
        if system_instruction:
            replacement = {"type": "message", "role": "system", "content": system_instruction}
            if items and items[0].get("role") == "system":
                items[0] = replacement
            else:
                items.insert(0, replacement)
        return ResponsesHistory(items=items)

    def dump(self, history: ResponsesHistory) -> list[dict[str, Any]]:
        return history.items

    @staticmethod
    def _translate_tool(tool: dict[str, Any]) -> dict[str, Any]:
        fn = tool.get("function") or {}
        return {
            "type": "function",
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        }

    @staticmethod
    def _translate_response_format(
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not response_format:
            return None
        if response_format.get("type") == "json_schema":
            schema = response_format.get("json_schema") or {}
            return {
                "format": {
                    "type": "json_schema",
                    "name": schema.get("name", "output"),
                    "schema": schema.get("schema") or {},
                    "strict": schema.get("strict", True),
                }
            }
        return {"format": dict(response_format)}

    def build_kwargs(
        self,
        *,
        model: str,
        history: ResponsesHistory,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": history.items,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if tools:
            kwargs["tools"] = [self._translate_tool(t) for t in tools]
            kwargs["tool_choice"] = opts.tool_choice or "auto"
        if opts.max_tokens is not None:
            kwargs["max_output_tokens"] = opts.max_tokens
        if is_reasoning_model(model) and opts.reasoning_effort:
            kwargs["reasoning"] = {"effort": opts.reasoning_effort}
        elif opts.temperature is not None:
            kwargs["temperature"] = opts.temperature
        text_format = self._translate_response_format(opts.response_format)
        if text_format is not None:
            kwargs["text"] = text_format
        if opts.extra_body is not None:
            kwargs["extra_body"] = copy.deepcopy(opts.extra_body)
        return kwargs

    def create(
        self,
        *,
        client: Any,
        model: str,
        history: ResponsesHistory,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> TurnResult:
        kwargs = self.build_kwargs(model=model, history=history, tools=tools, opts=opts)
        try:
            response = client.responses.create(**kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (400, 404) or "404" in str(exc):
                raise ResponsesTransportError(
                    f"Responses API is not available for this credential/model "
                    f'(provider returned {status or 404}). Turn off "Use Responses API" '
                    f"on this node, or switch to a credential that supports it."
                ) from exc
            raise
        return self.to_turn(response)

    @staticmethod
    def _item_get(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def to_turn(self, response: Any) -> TurnResult:
        items = list(getattr(response, "output", None) or [])
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in items:
            item_type = self._item_get(item, "type")
            if item_type == "message":
                for part in self._item_get(item, "content", []) or []:
                    if self._item_get(part, "type") == "output_text":
                        text_parts.append(self._item_get(part, "text", "") or "")
            elif item_type == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=self._item_get(item, "call_id", "") or "",
                        name=self._item_get(item, "name", "") or "",
                        arguments=self._item_get(item, "arguments", "") or "{}",
                    )
                )
        usage = getattr(response, "usage", None)
        return TurnResult(
            text="".join(text_parts),
            tool_calls=tool_calls,
            prompt_tokens=getattr(usage, "input_tokens", 0) or 0 if usage else 0,
            completion_tokens=getattr(usage, "output_tokens", 0) or 0 if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0 if usage else 0,
            finish_reason=getattr(response, "status", None),
            raw_items=items,
        )

    async def compress(
        self,
        history: ResponsesHistory,
        *,
        model: str,
        client: Any,
        context_limit_tokens: int,
    ) -> tuple[ResponsesHistory, dict[str, Any] | None]:
        """Reuse the one compressor. Encrypted reasoning blobs cannot be summarised,
        so they are withheld from it and dropped when compression happens."""
        from app.services.context_compressor import maybe_compress_messages

        chat_like = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in history.items
            if item.get("type") == "message"
        ]
        compressed, info = await maybe_compress_messages(
            chat_like, model=model, client=client, context_limit_tokens=context_limit_tokens
        )
        if info is None:
            return history, None
        return (
            ResponsesHistory(
                items=[
                    {"type": "message", "role": m["role"], "content": m["content"]}
                    for m in compressed
                ]
            ),
            info,
        )

    def final_text(self, turn: TurnResult) -> str:
        return turn.text

    def last_item_is_tool_result(self, history: ResponsesHistory) -> bool:
        return bool(history.items) and history.items[-1].get("type") == "function_call_output"

    def append_turn(self, history: ResponsesHistory, turn: TurnResult) -> None:
        """The only writer. Reasoning items go back verbatim."""
        for item in turn.raw_items:
            history.items.append(item if isinstance(item, dict) else item.model_dump())

    def append_tool_results(self, history: ResponsesHistory, results: list[ToolResult]) -> None:
        for result in results:
            history.items.append(
                {
                    "type": "function_call_output",
                    "call_id": result.call_id,
                    "output": result.output,
                }
            )

    def append_user(self, history: ResponsesHistory, text: str) -> None:
        history.items.append({"type": "message", "role": "user", "content": text})

    def trace_request(
        self, history: ResponsesHistory, tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        from app.services.llm_service import _sanitize_messages

        return {
            "input": _sanitize_messages(history.items),
            "tools": [self._translate_tool(t) for t in tools or []],
        }
