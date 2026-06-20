import asyncio
import unittest
from threading import Event
from unittest.mock import MagicMock

from app.api import chats
from app.api.ai_assistant import _await_chat_completions


class TestRequestChatCancel(unittest.TestCase):
    def setUp(self) -> None:
        chats._cancel_events.clear()
        chats._chat_tasks.clear()

    def tearDown(self) -> None:
        chats._cancel_events.clear()
        chats._chat_tasks.clear()

    def test_returns_false_when_no_task_registered(self) -> None:
        self.assertFalse(chats.request_chat_cancel("missing-conv"))

    def test_sets_event_for_registered_task(self) -> None:
        conv_id = "conv-123"
        event = Event()
        chats._cancel_events[conv_id] = event

        self.assertFalse(event.is_set())
        result = chats.request_chat_cancel(conv_id)

        self.assertTrue(result)
        self.assertTrue(event.is_set())

    def test_cancel_is_idempotent(self) -> None:
        conv_id = "conv-456"
        event = Event()
        chats._cancel_events[conv_id] = event

        self.assertTrue(chats.request_chat_cancel(conv_id))
        # A second call still finds the task and leaves the event set.
        self.assertTrue(chats.request_chat_cancel(conv_id))
        self.assertTrue(event.is_set())


class TestRequestChatCancelTask(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        chats._cancel_events.clear()
        chats._chat_tasks.clear()

    async def asyncTearDown(self) -> None:
        chats._cancel_events.clear()
        chats._chat_tasks.clear()

    async def test_cancels_the_running_asyncio_task(self) -> None:
        conv_id = "conv-task"
        started = asyncio.Event()

        async def long_runner() -> None:
            started.set()
            await asyncio.sleep(60)

        task: asyncio.Task[None] = asyncio.create_task(long_runner())
        chats._chat_tasks[conv_id] = task
        await started.wait()

        result = chats.request_chat_cancel(conv_id)
        self.assertTrue(result)

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(task.cancelled())


class TestAwaitChatCompletions(unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_cancelled_before_call(self) -> None:
        client = MagicMock()
        cancel_event = Event()
        cancel_event.set()

        result = await _await_chat_completions(client, cancel_event, model="gpt-4o", messages=[])

        self.assertIsNone(result)
        client.chat.completions.create.assert_not_called()

    async def test_returns_none_when_cancelled_during_thread(self) -> None:
        client = MagicMock()
        cancel_event = Event()

        def slow_create(**_kwargs: object) -> MagicMock:
            cancel_event.set()
            return MagicMock()

        client.chat.completions.create.side_effect = slow_create

        result = await _await_chat_completions(client, cancel_event, model="gpt-4o", messages=[])

        self.assertIsNone(result)
        client.chat.completions.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
