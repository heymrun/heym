"""Runs A2A tasks on the Heym Agent.

A task is one client message, the agent turn it starts, and, after an interruption (a
clarifying question or an open credential form), the turns the client's answers start.
The task's state follows the turn's outcome. Turns run on their own asyncio tasks, so a
dropped stream or a `returnImmediately` request never stops the work; the client follows
up with GetTask or SubscribeToTask.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any

from app.services.a2a import errors
from app.services.a2a.models import (
    INTERRUPTED_STATES,
    TERMINAL_STATES,
    Artifact,
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from app.services.a2a.task_store import (
    HistoryEntry,
    SqlTaskStore,
    TaskQuery,
    TaskRecord,
    TaskScope,
    TaskStore,
)
from app.services.heym_agent.errors import AgentError
from app.services.heym_agent.links import absolutize_workflow_links, strip_hidden_markers
from app.services.heym_agent.progress import AgentProgress, ProgressCallback, step_message
from app.services.heym_agent.settings import AgentSettings
from app.services.heym_agent.turn import (
    AgentOutcome,
    AgentTurnRequest,
    AgentTurnResult,
    run_agent_turn,
)

logger = logging.getLogger(__name__)

A2A_SOURCE = "a2a"
MAX_MESSAGE_LENGTH = 20000
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_HISTORY = 100
RESPONSE_ARTIFACT_ID = "response"
# How long CancelTask and the end of a subscription wait for a turn to record its outcome.
SETTLE_SECONDS = 10.0
_SETTLE_POLL_SECONDS = 0.25

TurnRunner = Callable[[AgentTurnRequest, ProgressCallback], Awaitable[AgentTurnResult]]
ConversationFactory = Callable[[uuid.UUID], Awaitable[uuid.UUID]]
FormWaiter = Callable[[uuid.UUID, uuid.UUID, str], Awaitable[list[str]]]
TurnCanceller = Callable[[str], bool]
EventSubscriber = Callable[[str], AbstractAsyncContextManager[Any]]

# Turns that outlive the request that started them (returnImmediately, streams).
_background_turns: set[asyncio.Task[None]] = set()


async def _run_turn(request: AgentTurnRequest, on_progress: ProgressCallback) -> AgentTurnResult:
    return await run_agent_turn(request, on_progress=on_progress)


async def _create_conversation(user_id: uuid.UUID) -> uuid.UUID:
    from app.api.chats import create_agent_conversation

    return await create_agent_conversation(user_id, A2A_SOURCE)


async def _wait_for_forms(
    user_id: uuid.UUID, conversation_id: uuid.UUID, public_base_url: str
) -> list[str]:
    from app.services.credential_setup import wait_for_conversation_forms

    return await wait_for_conversation_forms(
        user_id=user_id, conversation_id=conversation_id, public_base_url=public_base_url
    )


def _cancel_turn(conversation_id: str) -> bool:
    from app.api.chats import request_chat_cancel

    return request_chat_cancel(conversation_id)


def _subscribe_events(conversation_id: str) -> AbstractAsyncContextManager[Any]:
    from app.services import chat_task_registry

    return chat_task_registry.subscribe(conversation_id)


async def _ignore_progress(_progress: AgentProgress) -> None:
    return None


def message_text(message: Message) -> str:
    """The text the agent reads: text parts as written, data parts as JSON."""
    chunks: list[str] = []
    for part in message.parts:
        if part.raw is not None or part.url is not None:
            raise errors.content_type_not_supported()
        if part.text is not None:
            chunks.append(part.text.strip())
        elif part.data is not None:
            chunks.append(json.dumps(part.data, ensure_ascii=False))
    text = "\n\n".join(chunk for chunk in chunks if chunk)
    if not text:
        raise errors.invalid_params("The message needs at least one text or data part.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise errors.invalid_params(
            f"The message is too long (max {MAX_MESSAGE_LENGTH} characters)."
        )
    return text


def _uuid_or_none(value: str | None, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise errors.invalid_params(f"{field} must be an id Heym issued.") from exc


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _auth_message(text: str, urls: tuple[str, ...]) -> str:
    lines = [text.strip() or "The Heym Agent needs a credential."]
    for url in urls:
        if url not in text:
            lines.append(
                "Open this Heym page in a browser signed in to Heym to enter the credential; "
                f"its values never pass through this client: {url}"
            )
    lines.append("When the form is saved, send a message on this task to continue.")
    return "\n\n".join(lines)


def outcome_to_task(
    result: AgentTurnResult,
) -> tuple[TaskState, str | None, dict[str, Any] | None]:
    """The task state, status message and stored artifact for one turn result."""
    if result.outcome is AgentOutcome.CANCELED:
        return TaskState.CANCELED, "Canceled.", None
    if result.outcome is AgentOutcome.AUTH_REQUIRED:
        return (
            TaskState.AUTH_REQUIRED,
            _auth_message(result.text, result.credential_form_urls),
            None,
        )
    if result.outcome is AgentOutcome.INPUT_REQUIRED:
        return TaskState.INPUT_REQUIRED, result.text, None
    artifact: dict[str, Any] = {"text": result.text, "verified": result.verified}
    if result.workflow_links:
        artifact["workflows"] = [
            {"name": link.name, "url": link.url} for link in result.workflow_links
        ]
    if result.eval_suite_links:
        artifact["evalSuites"] = [
            {"name": link.name, "url": link.url} for link in result.eval_suite_links
        ]
    return TaskState.COMPLETED, None, artifact


def response_artifact(stored: dict[str, Any]) -> Artifact:
    parts = [Part(text=str(stored.get("text") or ""))]
    data = {key: stored[key] for key in ("workflows", "evalSuites") if stored.get(key)}
    if data or stored.get("verified"):
        parts.append(Part(data={**data, "verified": bool(stored.get("verified"))}))
    return Artifact(artifact_id=RESPONSE_ARTIFACT_ID, name="Heym Agent reply", parts=parts)


class A2AExecutor:
    """A2A methods for one user's surface, on top of the Heym Agent turn."""

    def __init__(
        self,
        *,
        scope: TaskScope,
        settings: AgentSettings,
        public_base_url: str,
        store: TaskStore | None = None,
        run_turn: TurnRunner | None = None,
        create_conversation: ConversationFactory | None = None,
        wait_for_forms: FormWaiter | None = None,
        cancel_turn: TurnCanceller | None = None,
        subscribe_events: EventSubscriber | None = None,
    ) -> None:
        self.scope = scope
        self.settings = settings
        self.public_base_url = public_base_url
        self.store = store or SqlTaskStore()
        self._run_turn = run_turn or _run_turn
        self._create_conversation = create_conversation or _create_conversation
        self._wait_for_forms = wait_for_forms or _wait_for_forms
        self._cancel_turn = cancel_turn or _cancel_turn
        self._subscribe_events = subscribe_events or _subscribe_events

    # -- public methods -------------------------------------------------------------

    async def send_message(self, request: SendMessageRequest) -> Task:
        text = message_text(request.message)
        record = await self._accept(request.message)
        await self._begin(record)
        history_length = request.configuration.history_length if request.configuration else None
        if request.configuration is not None and request.configuration.return_immediately:
            self._spawn(self._execute(record, text, _ignore_progress))
            working = await self._require(str(record.id))
            return await self._wire(working, history_length=history_length)
        await self._execute(record, text, _ignore_progress)
        return await self._wire(await self._require(str(record.id)), history_length=history_length)

    async def stream_message(self, request: SendMessageRequest) -> AsyncIterator[StreamResponse]:
        """Validate and start the task, then return its event stream."""
        text = message_text(request.message)
        record = await self._accept(request.message)
        await self._begin(record)
        queue: asyncio.Queue[StreamResponse | None] = asyncio.Queue()

        async def on_progress(progress: AgentProgress) -> None:
            await queue.put(self._status_event(record, TaskState.WORKING, progress.message))

        async def run() -> None:
            try:
                await self._execute(record, text, on_progress)
            finally:
                await queue.put(None)

        self._spawn(run())
        return self._stream(record, queue)

    async def get_task(self, request: GetTaskRequest) -> Task:
        record = await self._require(request.id)
        return await self._wire(record, history_length=request.history_length)

    async def list_tasks(self, request: ListTasksRequest) -> ListTasksResponse:
        size = min(max(request.page_size or DEFAULT_PAGE_SIZE, 1), MAX_PAGE_SIZE)
        offset = self._page_offset(request.page_token)
        updated_after = self._parse_time(request.status_timestamp_after)
        page = await self.store.list(
            self.scope,
            TaskQuery(
                context_id=_uuid_or_none(request.context_id, "contextId"),
                state=request.status,
                updated_after=updated_after,
                offset=offset,
                limit=size,
            ),
        )
        tasks = [
            await self._wire(
                record,
                history_length=request.history_length or 0,
                include_artifacts=bool(request.include_artifacts),
            )
            for record in page.tasks
        ]
        next_offset = offset + len(page.tasks)
        return ListTasksResponse(
            tasks=tasks,
            next_page_token=str(next_offset) if next_offset < page.total else None,
            page_size=size,
            total_size=page.total,
        )

    async def cancel_task(self, request: CancelTaskRequest) -> Task:
        record = await self._require(request.id)
        if record.state in TERMINAL_STATES:
            raise errors.task_not_cancelable()
        if record.state is TaskState.WORKING and self._cancel_turn(str(record.context_id)):
            settled = await self._settle(record.id)
            if settled.state in TERMINAL_STATES:
                return await self._wire(settled, history_length=0)
        canceled = await self.store.cancel(self.scope, record.id)
        if canceled is None:
            latest = await self._require(request.id)
            if latest.state is not TaskState.CANCELED:
                raise errors.task_not_cancelable()
            canceled = latest
        return await self._wire(canceled, history_length=0)

    async def subscribe(self, request: SubscribeToTaskRequest) -> AsyncIterator[StreamResponse]:
        """Validate, then return the stream that follows a task still in progress."""
        record = await self._require(request.id)
        if record.state in TERMINAL_STATES:
            raise errors.unsupported("This task is finished. Read it with GetTask.")
        return self._follow(record)

    # -- lifecycle ------------------------------------------------------------------

    async def _accept(self, message: Message) -> TaskRecord:
        if message.role is Role.AGENT:
            raise errors.invalid_params("Messages to the agent must have role ROLE_USER.")
        context_id = _uuid_or_none(message.context_id, "contextId")
        if message.task_id:
            record = await self._require(message.task_id)
            if context_id is not None and context_id != record.context_id:
                raise errors.invalid_params("contextId does not match the task's context.")
            if record.state in TERMINAL_STATES:
                raise errors.unsupported(
                    "This task is finished. Send a new message with the same contextId and no "
                    "taskId to continue the conversation."
                )
            if record.state not in INTERRUPTED_STATES:
                raise errors.unsupported(
                    "This task is still working. Use SubscribeToTask to follow it."
                )
            return record
        if context_id is None:
            context_id = await self._create_conversation(self.scope.user_id)
        elif not await self.store.owns_conversation(self.scope.user_id, context_id):
            raise errors.invalid_params(
                "contextId does not match a conversation Heym started for you."
            )
        return await self.store.create(self.scope, context_id)

    async def _begin(self, record: TaskRecord) -> None:
        if not await self.store.start(self.scope, record.id):
            raise errors.unsupported(
                "This task is still working. Use SubscribeToTask to follow it."
            )

    async def _execute(self, record: TaskRecord, text: str, on_progress: ProgressCallback) -> None:
        """Run the turn for a task this executor just started, and record the outcome."""
        try:
            if record.state is TaskState.AUTH_REQUIRED:
                still_open = await self._wait_for_forms(
                    self.scope.user_id, record.context_id, self.public_base_url
                )
                if still_open:
                    await self.store.finish(
                        record.id,
                        TaskState.AUTH_REQUIRED,
                        _auth_message("The credential form is still open.", tuple(still_open)),
                        None,
                    )
                    return
            result = await self._run_turn(
                AgentTurnRequest(
                    user_id=self.scope.user_id,
                    settings=self.settings,
                    message=text,
                    conversation_id=record.context_id,
                    public_base_url=self.public_base_url,
                    source=A2A_SOURCE,
                    a2a_task_id=record.id,
                ),
                on_progress,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self.store.finish(record.id, TaskState.FAILED, "The turn was interrupted.", None)
            )
            raise
        except AgentError as exc:
            await self.store.finish(record.id, TaskState.FAILED, str(exc), None)
            return
        except Exception:
            logger.exception("A2A task %s failed", record.id)
            await self.store.finish(
                record.id, TaskState.FAILED, "The Heym Agent failed. Try again.", None
            )
            return
        state, status_message, artifacts = outcome_to_task(result)
        await self.store.finish(record.id, state, status_message, artifacts)

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        _background_turns.add(task)
        task.add_done_callback(_background_turns.discard)

    async def _settle(self, task_id: uuid.UUID) -> TaskRecord:
        """The task once its turn has recorded an outcome, or as it is after SETTLE_SECONDS."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_SECONDS
        record = await self._require(str(task_id))
        while record.state is TaskState.WORKING and loop.time() < deadline:
            await asyncio.sleep(_SETTLE_POLL_SECONDS)
            record = await self._require(str(task_id))
        return record

    # -- streams --------------------------------------------------------------------

    async def _stream(
        self, record: TaskRecord, queue: asyncio.Queue[StreamResponse | None]
    ) -> AsyncIterator[StreamResponse]:
        yield StreamResponse(task=await self._wire(record, history_length=0))
        yield self._status_event(record, TaskState.WORKING, None)
        while (event := await queue.get()) is not None:
            yield event
        async for event in self._final_events(await self._require(str(record.id))):
            yield event

    async def _follow(self, record: TaskRecord) -> AsyncIterator[StreamResponse]:
        yield StreamResponse(task=await self._wire(record, history_length=0))
        if record.state in INTERRUPTED_STATES:
            return
        async with self._subscribe_events(str(record.context_id)) as queue:
            if queue is not None:
                while (item := await queue.get()) is not None:
                    message = step_message(_event_payload(item))
                    if message is not None:
                        yield self._status_event(record, TaskState.WORKING, message)
        async for event in self._final_events(await self._settle(record.id)):
            yield event

    async def _final_events(self, record: TaskRecord) -> AsyncIterator[StreamResponse]:
        if record.state is TaskState.COMPLETED and record.artifacts:
            yield StreamResponse(
                artifact_update=TaskArtifactUpdateEvent(
                    task_id=str(record.id),
                    context_id=str(record.context_id),
                    artifact=response_artifact(record.artifacts),
                    last_chunk=True,
                )
            )
        yield self._status_event(record, record.state, record.status_message)

    def _status_event(
        self, record: TaskRecord, state: TaskState, text: str | None
    ) -> StreamResponse:
        return StreamResponse(
            status_update=TaskStatusUpdateEvent(
                task_id=str(record.id),
                context_id=str(record.context_id),
                status=TaskStatus(
                    state=state,
                    message=self._agent_message(record, text),
                    timestamp=_timestamp(datetime.now(timezone.utc)),
                ),
            )
        )

    # -- wire -----------------------------------------------------------------------

    async def _require(self, task_id: str) -> TaskRecord:
        try:
            parsed = uuid.UUID(str(task_id))
        except ValueError as exc:
            raise errors.task_not_found() from exc
        record = await self.store.get(self.scope, parsed)
        if record is None:
            raise errors.task_not_found()
        return record

    async def _wire(
        self, record: TaskRecord, *, history_length: int | None, include_artifacts: bool = True
    ) -> Task:
        limit = MAX_HISTORY if history_length is None else max(0, min(history_length, MAX_HISTORY))
        history = await self.store.history(record.id, limit) if limit else None
        return Task(
            id=str(record.id),
            context_id=str(record.context_id),
            status=TaskStatus(
                state=record.state,
                message=self._agent_message(record, record.status_message),
                timestamp=_timestamp(record.updated_at),
            ),
            artifacts=(
                [response_artifact(record.artifacts)]
                if include_artifacts and record.artifacts
                else None
            ),
            history=(
                [self._history_message(record, entry) for entry in history]
                if history is not None
                else None
            ),
        )

    def _agent_message(self, record: TaskRecord, text: str | None) -> Message | None:
        if not text:
            return None
        return Message(
            message_id=str(uuid.uuid4()),
            context_id=str(record.context_id),
            task_id=str(record.id),
            role=Role.AGENT,
            parts=[Part(text=text)],
        )

    def _history_message(self, record: TaskRecord, entry: HistoryEntry) -> Message:
        is_agent = entry.role == "assistant"
        text = (
            absolutize_workflow_links(strip_hidden_markers(entry.content), self.public_base_url)
            if is_agent
            else entry.content
        )
        return Message(
            message_id=str(entry.id),
            context_id=str(record.context_id),
            task_id=str(record.id),
            role=Role.AGENT if is_agent else Role.USER,
            parts=[Part(text=text)],
        )

    @staticmethod
    def _page_offset(token: str | None) -> int:
        if token in (None, ""):
            return 0
        if not str(token).isdigit():
            raise errors.invalid_params("pageToken must be a value a previous ListTasks returned.")
        return int(token)

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise errors.invalid_params("statusTimestampAfter must be an ISO 8601 time.") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _event_payload(item: Any) -> dict[str, Any]:
    """A chat stream event as a dict; the registry stores SSE-formatted strings."""
    if isinstance(item, dict):
        return item
    if isinstance(item, str) and item.startswith("data: "):
        try:
            payload = json.loads(item[6:].strip())
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}
