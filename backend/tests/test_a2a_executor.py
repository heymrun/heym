"""A2A task lifecycle on the Heym Agent, with an in-memory store and a scripted agent."""

import asyncio
import unittest
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.services.a2a import errors
from app.services.a2a.executor import A2AExecutor
from app.services.a2a.models import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    SubscribeToTaskRequest,
    TaskState,
)
from app.services.a2a.task_store import TaskScope
from app.services.heym_agent.errors import AgentError
from app.services.heym_agent.links import WorkflowLink
from app.services.heym_agent.progress import AgentProgress
from app.services.heym_agent.settings import AgentSettings
from app.services.heym_agent.turn import AgentOutcome, AgentTurnRequest, AgentTurnResult
from tests.a2a_fixtures import MemoryTaskStore

BASE = "https://heym.test"


def _message(text: str = "hi", **kwargs: Any) -> Message:
    return Message(message_id=str(uuid.uuid4()), role=Role.USER, parts=[Part(text=text)], **kwargs)


def _immediately(message: Message) -> SendMessageRequest:
    return SendMessageRequest(
        message=message, configuration=SendMessageConfiguration(return_immediately=True)
    )


class ScriptedAgent:
    """Answers each turn with the next scripted result and records the requests."""

    def __init__(self, *results: AgentTurnResult | Exception, steps: tuple[str, ...] = ()) -> None:
        self.results = list(results)
        self.requests: list[AgentTurnRequest] = []
        self.steps = steps
        self.release = asyncio.Event()
        self.release.set()

    async def __call__(self, request: AgentTurnRequest, on_progress: Any) -> AgentTurnResult:
        self.requests.append(request)
        for number, step in enumerate(self.steps, start=1):
            await on_progress(AgentProgress(number, step))
        await self.release.wait()
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _reply(conversation_id: uuid.UUID, text: str = "Done.", **kwargs: Any) -> AgentTurnResult:
    return AgentTurnResult(conversation_id=conversation_id, text=text, tool_names=[], **kwargs)


class ExecutorCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.scope = TaskScope(self.user_id, None)
        self.store = MemoryTaskStore()
        self.conversation_id = uuid.uuid4()
        self.store.conversations[self.conversation_id] = self.user_id
        self.cancelled: list[str] = []
        self.forms_open: list[str] = []

    def executor(self, agent: ScriptedAgent, **kwargs: Any) -> A2AExecutor:
        async def create_conversation(user_id: uuid.UUID) -> uuid.UUID:
            self.store.conversations[self.conversation_id] = user_id
            return self.conversation_id

        async def wait_for_forms(
            user_id: uuid.UUID, conversation_id: uuid.UUID, base: str
        ) -> list[str]:
            return list(self.forms_open)

        def cancel_turn(conversation_id: str) -> bool:
            self.cancelled.append(conversation_id)
            agent.release.set()
            return True

        return A2AExecutor(
            scope=self.scope,
            settings=AgentSettings(enabled=True, credential_id=None, model=None, a2a_enabled=True),
            public_base_url=BASE,
            store=self.store,
            run_turn=agent,
            create_conversation=create_conversation,
            wait_for_forms=wait_for_forms,
            cancel_turn=kwargs.get("cancel_turn", cancel_turn),
            subscribe_events=kwargs.get("subscribe_events"),
        )


class SendMessageTests(ExecutorCase):
    async def test_a_reply_completes_the_task_with_an_artifact(self) -> None:
        link = WorkflowLink("Invoice", f"{BASE}/workflows/{uuid.uuid4()}")
        agent = ScriptedAgent(_reply(self.conversation_id, workflow_links=(link,), verified=True))

        task = await self.executor(agent).send_message(SendMessageRequest(message=_message()))

        self.assertEqual(task.status.state, TaskState.COMPLETED)
        self.assertEqual(task.context_id, str(self.conversation_id))
        parts = task.artifacts[0].parts
        self.assertEqual(parts[0].text, "Done.")
        self.assertEqual(
            parts[1].data,
            {"workflows": [{"name": "Invoice", "url": link.url}], "verified": True},
        )
        request = agent.requests[0]
        self.assertEqual(request.source, "a2a")
        self.assertEqual(request.conversation_id, self.conversation_id)
        self.assertEqual(str(request.a2a_task_id), task.id)

    async def test_a_question_waits_for_input_on_the_same_task(self) -> None:
        agent = ScriptedAgent(
            _reply(self.conversation_id, "Which channel?", outcome=AgentOutcome.INPUT_REQUIRED),
            _reply(self.conversation_id, "Posted."),
        )
        executor = self.executor(agent)

        first = await executor.send_message(SendMessageRequest(message=_message("post it")))
        self.assertEqual(first.status.state, TaskState.INPUT_REQUIRED)
        self.assertEqual(first.status.message.parts[0].text, "Which channel?")

        second = await executor.send_message(
            SendMessageRequest(
                message=_message("#general", task_id=first.id, context_id=first.context_id)
            )
        )
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.status.state, TaskState.COMPLETED)
        self.assertEqual(agent.requests[1].message, "#general")

    async def test_an_open_form_asks_for_auth_and_waits_before_continuing(self) -> None:
        url = f"{BASE}/credentials/setup/{uuid.uuid4()}"
        agent = ScriptedAgent(
            _reply(
                self.conversation_id,
                "Open the form.",
                outcome=AgentOutcome.AUTH_REQUIRED,
                credential_form_urls=(url,),
            ),
            _reply(self.conversation_id, "Connected."),
        )
        executor = self.executor(agent)

        first = await executor.send_message(SendMessageRequest(message=_message()))
        self.assertEqual(first.status.state, TaskState.AUTH_REQUIRED)
        self.assertIn(url, first.status.message.parts[0].text)

        self.forms_open = [url]
        still = await executor.send_message(
            SendMessageRequest(message=_message("saved", task_id=first.id))
        )
        self.assertEqual(still.status.state, TaskState.AUTH_REQUIRED)
        self.assertEqual(len(agent.requests), 1)

        self.forms_open = []
        done = await executor.send_message(
            SendMessageRequest(message=_message("saved", task_id=first.id))
        )
        self.assertEqual(done.status.state, TaskState.COMPLETED)

    async def test_an_agent_error_fails_the_task(self) -> None:
        agent = ScriptedAgent(AgentError("No model is configured for the Heym Agent."))

        task = await self.executor(agent).send_message(SendMessageRequest(message=_message()))

        self.assertEqual(task.status.state, TaskState.FAILED)
        self.assertIn("No model", task.status.message.parts[0].text)

    async def test_return_immediately_answers_while_the_turn_runs(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id))
        agent.release.clear()
        executor = self.executor(agent)

        task = await executor.send_message(_immediately(_message()))
        self.assertEqual(task.status.state, TaskState.WORKING)

        agent.release.set()
        for _ in range(50):
            await asyncio.sleep(0)
        latest = await executor.get_task(GetTaskRequest(id=task.id))
        self.assertEqual(latest.status.state, TaskState.COMPLETED)

    async def test_refusals(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id))
        executor = self.executor(agent)
        done = await executor.send_message(SendMessageRequest(message=_message()))

        cases = [
            (_message(task_id=done.id), errors.UNSUPPORTED_OPERATION),
            (_message(task_id=str(uuid.uuid4())), errors.TASK_NOT_FOUND),
            (_message(context_id=str(uuid.uuid4())), errors.INVALID_PARAMS),
            (_message(context_id="not-a-uuid"), errors.INVALID_PARAMS),
            (_message(task_id=done.id, context_id=str(uuid.uuid4())), errors.INVALID_PARAMS),
            (
                Message(message_id="m", role=Role.USER, parts=[Part(url="https://x/y.pdf")]),
                errors.CONTENT_TYPE_NOT_SUPPORTED,
            ),
            (Message(message_id="m", role=Role.USER, parts=[]), errors.INVALID_PARAMS),
            (_message("x" * 20001), errors.INVALID_PARAMS),
            (
                Message(message_id="m", role=Role.AGENT, parts=[Part(text="hi")]),
                errors.INVALID_PARAMS,
            ),
        ]
        for message, code in cases:
            with (
                self.subTest(code=code, message=message.model_dump()),
                self.assertRaises(errors.A2AError) as caught,
            ):
                await executor.send_message(SendMessageRequest(message=message))
            self.assertEqual(caught.exception.code, code)

    async def test_a_working_task_refuses_another_message(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id))
        agent.release.clear()
        executor = self.executor(agent)
        task = await executor.send_message(_immediately(_message()))

        with self.assertRaises(errors.A2AError) as caught:
            await executor.send_message(SendMessageRequest(message=_message(task_id=task.id)))

        self.assertEqual(caught.exception.code, errors.UNSUPPORTED_OPERATION)
        self.assertIn("SubscribeToTask", caught.exception.message)
        agent.release.set()

    async def test_data_parts_reach_the_agent_as_json(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id))
        message = Message(
            message_id="m", role=Role.USER, parts=[Part(text="Run it"), Part(data={"rows": 3})]
        )

        await self.executor(agent).send_message(SendMessageRequest(message=message))

        self.assertEqual(agent.requests[0].message, 'Run it\n\n{"rows": 3}')


class CancelTests(ExecutorCase):
    async def test_cancel_a_working_task(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id, outcome=AgentOutcome.CANCELED))
        agent.release.clear()
        executor = self.executor(agent)
        task = await executor.send_message(_immediately(_message()))

        canceled = await executor.cancel_task(CancelTaskRequest(id=task.id))

        self.assertEqual(canceled.status.state, TaskState.CANCELED)
        self.assertEqual(self.cancelled, [str(self.conversation_id)])

    async def test_cancel_an_interrupted_task(self) -> None:
        agent = ScriptedAgent(
            _reply(self.conversation_id, "Which?", outcome=AgentOutcome.INPUT_REQUIRED)
        )
        executor = self.executor(agent)
        task = await executor.send_message(SendMessageRequest(message=_message()))

        canceled = await executor.cancel_task(CancelTaskRequest(id=task.id))

        self.assertEqual(canceled.status.state, TaskState.CANCELED)
        self.assertEqual(self.cancelled, [])

    async def test_a_finished_task_cannot_be_canceled(self) -> None:
        executor = self.executor(ScriptedAgent(_reply(self.conversation_id)))
        task = await executor.send_message(SendMessageRequest(message=_message()))

        with self.assertRaises(errors.A2AError) as caught:
            await executor.cancel_task(CancelTaskRequest(id=task.id))

        self.assertEqual(caught.exception.code, errors.TASK_NOT_CANCELABLE)


class StreamTests(ExecutorCase):
    async def _collect(self, events: AsyncIterator[Any]) -> list[dict]:
        return [event.wire() async for event in events]

    async def test_stream_events_in_order(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id), steps=("Listing workflows",))

        events = await self._collect(
            await self.executor(agent).stream_message(SendMessageRequest(message=_message()))
        )

        kinds = [next(iter(event)) for event in events]
        self.assertEqual(
            kinds, ["task", "statusUpdate", "statusUpdate", "artifactUpdate", "statusUpdate"]
        )
        self.assertEqual(events[0]["task"]["status"]["state"], "TASK_STATE_SUBMITTED")
        self.assertEqual(
            events[2]["statusUpdate"]["status"]["message"]["parts"],
            [{"text": "Listing workflows"}],
        )
        self.assertTrue(events[3]["artifactUpdate"]["lastChunk"])
        self.assertEqual(events[4]["statusUpdate"]["status"]["state"], "TASK_STATE_COMPLETED")

    async def test_subscribe_follows_a_working_task(self) -> None:
        agent = ScriptedAgent(_reply(self.conversation_id))
        agent.release.clear()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        @asynccontextmanager
        async def subscribe_events(conversation_id: str) -> AsyncIterator[asyncio.Queue[Any]]:
            yield queue

        executor = self.executor(agent, subscribe_events=subscribe_events)
        task = await executor.send_message(_immediately(_message()))
        await queue.put(
            'data: {"type": "tool_start", "name": "x", "label": "Saving the workflow..."}\n\n'
        )
        await queue.put(None)
        agent.release.set()

        events = await self._collect(await executor.subscribe(SubscribeToTaskRequest(id=task.id)))

        self.assertEqual(next(iter(events[0])), "task")
        self.assertEqual(
            events[1]["statusUpdate"]["status"]["message"]["parts"],
            [{"text": "Saving the workflow"}],
        )
        self.assertEqual(events[-1]["statusUpdate"]["status"]["state"], "TASK_STATE_COMPLETED")

    async def test_subscribe_to_a_finished_task_is_refused(self) -> None:
        executor = self.executor(ScriptedAgent(_reply(self.conversation_id)))
        task = await executor.send_message(SendMessageRequest(message=_message()))

        with self.assertRaises(errors.A2AError) as caught:
            await executor.subscribe(SubscribeToTaskRequest(id=task.id))

        self.assertEqual(caught.exception.code, errors.UNSUPPORTED_OPERATION)


class ListTests(ExecutorCase):
    async def test_pages_and_filters(self) -> None:
        agent = ScriptedAgent(*[_reply(self.conversation_id) for _ in range(3)])
        executor = self.executor(agent)
        for _ in range(3):
            await executor.send_message(SendMessageRequest(message=_message()))

        first = await executor.list_tasks(ListTasksRequest(page_size=2))
        second = await executor.list_tasks(
            ListTasksRequest(page_size=2, page_token=first.next_page_token)
        )
        filtered = await executor.list_tasks(ListTasksRequest(status=TaskState.FAILED))

        self.assertEqual((len(first.tasks), first.total_size, first.next_page_token), (2, 3, "2"))
        self.assertEqual((len(second.tasks), second.next_page_token), (1, None))
        self.assertEqual(filtered.total_size, 0)
        self.assertIsNone(first.tasks[0].artifacts)

    async def test_a_bad_page_token_is_invalid(self) -> None:
        with self.assertRaises(errors.A2AError) as caught:
            await self.executor(ScriptedAgent()).list_tasks(ListTasksRequest(page_token="abc"))

        self.assertEqual(caught.exception.code, errors.INVALID_PARAMS)
