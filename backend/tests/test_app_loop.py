import asyncio
import threading
import unittest

from app.services import app_loop


class AppLoopSubmitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        app_loop.set_app_loop(asyncio.get_running_loop())

    async def asyncTearDown(self) -> None:
        app_loop.set_app_loop(None)

    async def test_submit_from_thread_runs_on_registered_loop(self) -> None:
        loop = asyncio.get_running_loop()

        async def which_loop() -> asyncio.AbstractEventLoop:
            return asyncio.get_running_loop()

        result = await asyncio.to_thread(lambda: app_loop.submit(which_loop()).result(timeout=5))
        self.assertIs(result, loop)

    async def test_submit_from_the_loop_itself_is_refused(self) -> None:
        async def nothing() -> None:
            return None

        with self.assertRaises(RuntimeError):
            app_loop.submit(nothing())


class AppLoopMissingTests(unittest.TestCase):
    def test_submit_without_registered_loop_raises(self) -> None:
        app_loop.set_app_loop(None)

        async def nothing() -> None:
            return None

        with self.assertRaises(RuntimeError):
            app_loop.submit(nothing())


class ChatTurnDepthTests(unittest.IsolatedAsyncioTestCase):
    def test_default_depth_is_zero(self) -> None:
        self.assertEqual(app_loop.chat_turn_depth(), 0)

    def test_scope_sets_and_restores_depth(self) -> None:
        with app_loop.chat_turn_depth_scope(3):
            self.assertEqual(app_loop.chat_turn_depth(), 3)
        self.assertEqual(app_loop.chat_turn_depth(), 0)

    async def test_tasks_and_threads_started_inside_scope_inherit_depth(self) -> None:
        seen: dict[str, int] = {}

        async def in_task() -> None:
            seen["task"] = app_loop.chat_turn_depth()

        def in_thread() -> None:
            seen["thread"] = app_loop.chat_turn_depth()

        with app_loop.chat_turn_depth_scope(2):
            await asyncio.create_task(in_task())
            await asyncio.to_thread(in_thread)

        def plain_thread() -> None:
            seen["plain"] = app_loop.chat_turn_depth()

        worker = threading.Thread(target=plain_thread)
        worker.start()
        worker.join()
        self.assertEqual(seen, {"task": 2, "thread": 2, "plain": 0})


if __name__ == "__main__":
    unittest.main()
