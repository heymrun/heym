"""spawn_background_task keeps a running task alive until it finishes."""

import asyncio
import gc
import unittest
import weakref

from app.services import background_tasks
from app.services.background_tasks import spawn_background_task


class SpawnBackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_suspended_task_survives_garbage_collection(self) -> None:
        refs: list[weakref.ref[asyncio.Task[None]]] = []

        async def work() -> None:
            refs.append(weakref.ref(asyncio.current_task()))  # type: ignore[arg-type]
            # Nothing else references this future, like a run awaiting a callback.
            await asyncio.get_running_loop().create_future()

        spawn_background_task(work())
        await asyncio.sleep(0)
        gc.collect()
        try:
            self.assertEqual(len(refs), 1)
            self.assertIsNotNone(refs[0]())
        finally:
            for task in list(background_tasks._BACKGROUND_TASKS):
                task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)
        self.assertEqual(background_tasks._BACKGROUND_TASKS, set())

    async def test_the_returned_task_yields_the_coroutine_result(self) -> None:
        async def work() -> str:
            return "done"

        self.assertEqual(await spawn_background_task(work()), "done")

    async def test_a_failed_task_is_forgotten_too(self) -> None:
        async def boom() -> None:
            raise ValueError("expected")

        task = spawn_background_task(boom())
        with self.assertRaises(ValueError):
            await task
        await asyncio.sleep(0)
        self.assertNotIn(task, background_tasks._BACKGROUND_TASKS)
