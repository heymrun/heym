"""Gemini generateContent transport for gateways that serve Gemini on Google's own API only.

OpenCode Go answers 400 `ModelProtocolUnsupported` for Gemini on Chat Completions, Responses and
Messages; the model lives at `.../google/v1beta/models/<id>:generateContent`. The request goes
through the OpenAI client's generic `post`, so the guarded HTTP client, the Heym User-Agent and the
`x-opencode-session` header apply as they do on every other path.
"""

from __future__ import annotations

import copy
import json
import mimetypes
import re
import uuid
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

# The gateway path for Google's API; the credential's own base URL points at /v1.
GOOGLE_PATH = "/inference/go/google/v1beta/models"
_DATA_URI = re.compile(r"^data:([^;,]+);base64,(.*)$", re.DOTALL)
_TOOL_MODES = {"auto": "AUTO", "none": "NONE", "required": "ANY"}
# Declarations are an OpenAPI subset; the rest of JSON Schema is answered with 400.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {"additionalProperties", "$schema", "default", "examples", "title", "$defs", "definitions"}
)


@dataclass
class GeminiHistory:
    """`system` is a request field on this API, so it stays out of the contents."""

    system: str | None = None
    contents: list[dict[str, Any]] = field(default_factory=list)


def _clean_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean_schema(v) for k, v in value.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(value, list):
        return [_clean_schema(item) for item in value]
    return value


def _image_part(image: str) -> dict[str, Any]:
    match = _DATA_URI.match(image)
    if match:
        return {"inlineData": {"mimeType": match.group(1), "data": match.group(2)}}
    mime = mimetypes.guess_type(image.split("?", 1)[0])[0] or "image/jpeg"
    return {"fileData": {"mimeType": mime, "fileUri": image}}


def _redact_images(contents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted = copy.deepcopy(contents)
    for content in redacted:
        for part in content.get("parts") or []:
            inline = part.get("inlineData") if isinstance(part, dict) else None
            if isinstance(inline, dict):
                inline["data"] = "[base64]"
    return redacted


def _response_object(output: str) -> dict[str, Any]:
    """A function response must be a JSON object; a JSON object result passes through."""
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    return parsed if isinstance(parsed, dict) else {"result": output}


class GeminiTransport:
    """POST generateContent. Stateless: the full conversation goes out every turn."""

    name = "generateContent"
    carries_response_format = False

    def new_history(self) -> GeminiHistory:
        return GeminiHistory()

    def start(
        self,
        *,
        system_instruction: str | None,
        conversation_history: list[dict[str, str]] | None,
        user_message: str,
        image_input: str | None,
    ) -> GeminiHistory:
        history = GeminiHistory(system=system_instruction or None)
        for msg in conversation_history or []:
            if not msg.get("content"):
                continue
            role = "model" if msg["role"] == "assistant" else "user"
            history.contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        parts: list[dict[str, Any]] = [{"text": user_message}]
        if image_input:
            parts.append(_image_part(image_input))
        history.contents.append({"role": "user", "parts": parts})
        return history

    def load(self, raw: list[dict[str, Any]], system_instruction: str | None) -> GeminiHistory:
        return GeminiHistory(system=system_instruction or None, contents=copy.deepcopy(raw))

    def dump(self, history: GeminiHistory) -> list[dict[str, Any]]:
        return history.contents

    @staticmethod
    def _translate_tool(tool: dict[str, Any]) -> dict[str, Any]:
        fn = tool.get("function") or {}
        return {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": _clean_schema(
                fn.get("parameters") or {"type": "object", "properties": {}}
            ),
        }

    def build_kwargs(
        self,
        *,
        model: str,
        history: GeminiHistory,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> dict[str, Any]:
        system = history.system
        instruction = json_instruction(opts.response_format)
        if instruction:
            system = f"{system}\n\n{instruction}" if system else instruction
        body: dict[str, Any] = {"contents": history.contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": [self._translate_tool(t) for t in tools]}]
            mode = _TOOL_MODES.get(opts.tool_choice or "auto", "AUTO")
            body["toolConfig"] = {"functionCallingConfig": {"mode": mode}}
        generation: dict[str, Any] = {}
        if opts.temperature is not None:
            generation["temperature"] = min(max(opts.temperature, 0.0), 2.0)
        if opts.max_tokens:
            generation["maxOutputTokens"] = opts.max_tokens
        if generation:
            body["generationConfig"] = generation
        if opts.extra_body is not None:
            body.update(copy.deepcopy(opts.extra_body))
        return body

    @staticmethod
    def _endpoint(client: Any, model: str) -> str:
        base = httpx.URL(str(client.base_url))
        return f"{base.scheme}://{base.netloc.decode()}{GOOGLE_PATH}/{model}:generateContent"

    def create(
        self,
        *,
        client: Any,
        model: str,
        history: GeminiHistory,
        tools: list[dict[str, Any]] | None,
        opts: RequestOpts,
    ) -> TurnResult:
        body = self.build_kwargs(model=model, history=history, tools=tools, opts=opts)
        try:
            response = client.post(self._endpoint(client, model), cast_to=httpx.Response, body=body)
        except Exception as exc:
            if is_protocol_unsupported(exc):
                raise ModelProtocolError(
                    f"The gateway does not serve {model} over Google's generateContent API. "
                    f"Pick a model it serves over Chat Completions or the Responses API."
                ) from exc
            raise
        turn = self.to_turn(response.json())
        if json_instruction(opts.response_format):
            turn.text = unwrap_json_fence(turn.text)
        return turn

    def to_turn(self, payload: dict[str, Any]) -> TurnResult:
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason") or "no candidates"
            raise ValueError(f"Gemini returned no answer ({reason}).")
        candidate = candidates[0]
        parts = list((candidate.get("content") or {}).get("parts") or [])
        text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
        tool_calls: list[ToolCall] = []
        for part in parts:
            call = part.get("functionCall")
            if not isinstance(call, dict):
                continue
            # The id goes back into the stored part so the result can name its function.
            call.setdefault("id", f"call_{uuid.uuid4().hex[:12]}")
            tool_calls.append(
                ToolCall(
                    id=call["id"],
                    name=call.get("name", ""),
                    arguments=json.dumps(call.get("args") or {}),
                )
            )
        usage = payload.get("usageMetadata") or {}
        prompt_tokens = usage.get("promptTokenCount") or 0
        completion_tokens = (usage.get("candidatesTokenCount") or 0) + (
            usage.get("thoughtsTokenCount") or 0
        )
        return TurnResult(
            text=text,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            finish_reason=candidate.get("finishReason"),
            raw_items=parts,
        )

    def final_text(self, turn: TurnResult) -> str:
        return turn.text

    def last_item_is_tool_result(self, history: GeminiHistory) -> bool:
        if not history.contents:
            return False
        last = history.contents[-1]
        return last.get("role") == "user" and any(
            "functionResponse" in part for part in last.get("parts") or []
        )

    def append_turn(self, history: GeminiHistory, turn: TurnResult) -> None:
        """Parts go back verbatim: Gemini rejects a function call that lost its thought signature."""
        if turn.raw_items:
            history.contents.append({"role": "model", "parts": copy.deepcopy(turn.raw_items)})

    def _function_name(self, history: GeminiHistory, call_id: str) -> str:
        for content in reversed(history.contents):
            for part in content.get("parts") or []:
                call = part.get("functionCall")
                if isinstance(call, dict) and call.get("id") == call_id:
                    return str(call.get("name", ""))
        return ""

    def append_tool_results(self, history: GeminiHistory, results: list[ToolResult]) -> None:
        """Results for one model turn must share one user content."""
        parts = [
            {
                "functionResponse": {
                    "id": r.call_id,
                    "name": self._function_name(history, r.call_id),
                    "response": _response_object(r.output),
                }
            }
            for r in results
        ]
        if self.last_item_is_tool_result(history):
            history.contents[-1]["parts"].extend(parts)
        else:
            history.contents.append({"role": "user", "parts": parts})

    def append_user(self, history: GeminiHistory, text: str) -> None:
        history.contents.append({"role": "user", "parts": [{"text": text}]})

    async def compress(
        self, history: GeminiHistory, *, model: str, client: Any, context_limit_tokens: int
    ) -> tuple[GeminiHistory, dict[str, Any] | None]:
        """The shared compressor summarises over Chat Completions, which this model refuses."""
        return history, None

    def trace_request(
        self, history: GeminiHistory, tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {
            "system": history.system,
            "contents": _redact_images(history.contents),
            "tools": [self._translate_tool(t) for t in tools or []],
        }
