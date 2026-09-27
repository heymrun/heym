"""One canvas AI Assistant turn in YOLO mode.

The editor runs the YOLO loop: it applies the workflow, runs it on the canvas and sends
the run report back as the next message. This module handles a single model turn inside
that loop. During the turn the model may run the user's other workflows through the
``execute_workflow`` tool before it answers.
"""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from openai import OpenAI

from app.services.agent_tool_observability import summarize_tool_calls
from app.services.llm_provider import is_reasoning_model
from app.services.llm_trace import LLMTraceContext, record_llm_trace
from app.services.run_history import record_run_history

YOLO_TRIGGER_SOURCE = "ai_assistant"
YOLO_TRACE_NODE_LABEL = "AI Builder (YOLO)"
YOLO_TEMPERATURE = 0.1
MAX_YOLO_TOOL_CALLS_PER_TURN = 6
EXECUTE_WORKFLOW_TOOL_NAME = "execute_workflow"
EDITED_WORKFLOW_MESSAGE = (
    "This is the workflow being edited. Test it with a heym-yolo run block; it runs on the canvas."
)
TOOL_BUDGET_MESSAGE = "The tool budget for this turn is used up. Answer now without calling tools."

YOLO_EXECUTE_WORKFLOW_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": EXECUTE_WORKFLOW_TOOL_NAME,
        "description": (
            "Run one of the user's other workflows, listed under 'Available Workflows for "
            "Execute Node', and get its outputs. Use it when the task depends on what that "
            "workflow returns or does. Runs are real. Never use it for the workflow being "
            "edited: test that one with a heym-yolo run block."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "UUID of the workflow to run",
                },
                "inputs": {
                    "type": "object",
                    "description": 'Input values keyed by field name (e.g. {"text": "hello"})',
                },
            },
            "required": ["workflow_id", "inputs"],
        },
    },
}


@dataclass(frozen=True)
class YoloToolOutcome:
    """One tool call's result, shaped for the model and for the step row."""

    llm_content: str
    summary: str
    status: str


YoloWorkflowRunner = Callable[[str, dict[str, Any]], Awaitable[YoloToolOutcome]]


def run_step_label(workflow_name: str | None) -> str:
    """Label of the step row shown while another workflow runs."""
    if workflow_name:
        return f'Running workflow "{workflow_name}"...'
    return "Running workflow..."


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _error_outcome(message: str) -> YoloToolOutcome:
    return YoloToolOutcome(
        llm_content=json.dumps({"status": "error", "error": message}),
        summary=f"Error: {message}",
        status="error",
    )


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _assistant_tool_call_message(content: str | None, tool_calls: list[Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ],
    }


@dataclass
class _TurnRecord:
    """What one turn did, for its trace and its run history entry."""

    started: float
    text_parts: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def add_usage(self, usage: Any) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, key, None)
            if isinstance(value, int):
                self.usage[key] = self.usage.get(key, 0) + value

    def add_tool(
        self,
        *,
        call_id: str,
        name: str,
        args: dict[str, Any],
        status: str,
        elapsed_ms: float,
        summary: str,
        label: str,
    ) -> None:
        self.tools.append(
            {
                "tool_call_id": call_id,
                "name": name,
                "arguments": args,
                "status": status,
                "elapsed_ms": elapsed_ms,
            }
        )
        self.steps.append(
            {
                "label": label,
                "tool": name,
                "request": args,
                "response_summary": summary,
                "execution_time_ms": elapsed_ms,
            }
        )


def _save_turn(
    record: _TurnRecord,
    *,
    trace_context: LLMTraceContext | None,
    model: str,
    provider: str,
    request: dict[str, Any],
    last_user_message: str,
    cancelled: bool,
) -> None:
    """Write the turn's single trace and its run history entry."""
    if trace_context is None:
        return
    elapsed_ms = round((time.time() - record.started) * 1000, 2)
    text = "".join(record.text_parts)
    if cancelled:
        status = "cancelled"
    elif record.error:
        status = "error"
    else:
        status = "success"
    response: dict[str, Any] = {
        "text": text,
        "model": model,
        "usage": dict(record.usage),
        "elapsed_ms": elapsed_ms,
    }
    if record.tools:
        response["tool_calls"] = record.tools
        response["tool_metrics"] = summarize_tool_calls(record.tools)
    if cancelled:
        response["cancelled"] = True
    record_llm_trace(
        context=trace_context,
        request_type="chat.completions",
        request=request,
        response=response,
        model=model,
        provider=provider,
        error=record.error,
        elapsed_ms=elapsed_ms,
        prompt_tokens=record.usage.get("prompt_tokens"),
        completion_tokens=record.usage.get("completion_tokens"),
        total_tokens=record.usage.get("total_tokens"),
    )
    record_run_history(
        user_id=trace_context.user_id,
        run_type="workflow_assistant",
        workflow_id=trace_context.workflow_id,
        inputs={"message": last_user_message},
        outputs={"text": text},
        status=status,
        execution_time_ms=elapsed_ms,
        trigger_source=trace_context.source,
        steps=record.steps,
    )


async def stream_yolo_assistant_turn(
    *,
    client: OpenAI,
    model: str,
    provider: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    run_workflow: YoloWorkflowRunner,
    workflow_names: Mapping[str, str],
    editing_workflow_id: str | None,
    cancel_event: Event,
    trace_context: LLMTraceContext | None = None,
) -> AsyncGenerator[str, None]:
    """Stream one YOLO turn as SSE lines: tool steps, the model's answer, then ``done``.

    Rounds are non-streaming completions, as in Dashboard Chat, because tool calling is
    more reliable across providers that way. The workflow being edited is refused: the
    editor tests it on the canvas.
    """
    request_kwargs: dict[str, Any] = {
        "model": model,
        "tools": [YOLO_EXECUTE_WORKFLOW_TOOL],
        "stream": False,
    }
    if not is_reasoning_model(model):
        request_kwargs["temperature"] = YOLO_TEMPERATURE
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]
    last_user_message = str(messages[-1].get("content", "")) if messages else ""
    record = _TurnRecord(started=time.time())
    tool_calls_run = 0
    try:
        while not cancel_event.is_set():
            response = await asyncio.to_thread(
                client.chat.completions.create, messages=conversation, **request_kwargs
            )
            if cancel_event.is_set():
                return
            record.add_usage(getattr(response, "usage", None))
            choice = response.choices[0] if response.choices else None
            if choice is None:
                record.error = "No response from the model"
                yield _sse({"type": "error", "message": record.error})
                return
            message = choice.message
            if message.content:
                record.text_parts.append(message.content)
                yield _sse({"type": "content", "text": message.content})
            tool_calls = list(message.tool_calls or [])
            if not tool_calls:
                yield _sse({"type": "done"})
                return
            conversation.append(_assistant_tool_call_message(message.content, tool_calls))
            for tool_call in tool_calls:
                name = tool_call.function.name
                args = _parse_tool_arguments(tool_call.function.arguments)
                target_id = str(args.get("workflow_id") or "")
                label = run_step_label(workflow_names.get(target_id))
                yield _sse(
                    {
                        "type": "tool_start",
                        "id": tool_call.id,
                        "name": name,
                        "label": label,
                        "args": args,
                    }
                )
                tool_started = time.time()
                if name != EXECUTE_WORKFLOW_TOOL_NAME:
                    outcome = _error_outcome(f"Unknown tool: {name}")
                elif tool_calls_run >= MAX_YOLO_TOOL_CALLS_PER_TURN:
                    outcome = _error_outcome(TOOL_BUDGET_MESSAGE)
                elif editing_workflow_id is not None and target_id == editing_workflow_id:
                    outcome = _error_outcome(EDITED_WORKFLOW_MESSAGE)
                else:
                    tool_calls_run += 1
                    inputs = args.get("inputs")
                    outcome = await run_workflow(
                        target_id, inputs if isinstance(inputs, dict) else {}
                    )
                elapsed_ms = round((time.time() - tool_started) * 1000, 2)
                status = "cancelled" if cancel_event.is_set() else outcome.status
                record.add_tool(
                    call_id=tool_call.id,
                    name=name,
                    args=args,
                    status=status,
                    elapsed_ms=elapsed_ms,
                    summary=outcome.summary,
                    label=label,
                )
                yield _sse(
                    {
                        "type": "tool_end",
                        "id": tool_call.id,
                        "response_summary": outcome.summary,
                        "elapsed_ms": elapsed_ms,
                        "status": status,
                    }
                )
                if cancel_event.is_set():
                    return
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": outcome.llm_content,
                    }
                )
    except Exception as exc:
        record.error = str(exc)
        yield _sse({"type": "error", "message": str(exc)})
    finally:
        _save_turn(
            record,
            trace_context=trace_context,
            model=model,
            provider=provider,
            request={**request_kwargs, "messages": conversation},
            last_user_message=last_user_message,
            cancelled=cancel_event.is_set(),
        )


async def stream_until_disconnect(
    source: AsyncGenerator[str, None],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    cancel_event: Event,
    heartbeat_seconds: float,
    poll_seconds: float = 0.1,
) -> AsyncGenerator[str, None]:
    """Forward SSE lines with keepalives, and cancel the source when the client leaves.

    The source runs on the request's event loop, so it may use the request's database
    session. ``_stream_sse_with_heartbeat`` runs its source on another loop and cannot.
    """
    queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()

    async def watch_disconnect() -> None:
        while not cancel_event.is_set():
            if await is_disconnected():
                cancel_event.set()
                return
            await asyncio.sleep(poll_seconds)

    async def produce() -> None:
        try:
            async for chunk in source:
                await queue.put(chunk)
        except Exception as exc:
            await queue.put(exc)
        finally:
            await queue.put(None)

    watcher = asyncio.create_task(watch_disconnect())
    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                if cancel_event.is_set():
                    break
                yield ": ping\n\n"
                continue
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        cancel_event.set()
        producer.cancel()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
