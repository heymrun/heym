"""Long operations emit heartbeats and survive a listener disconnect."""

import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.services import result_stream


class ResultStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeats_arrive_before_the_result_and_repeat_during_silence(self) -> None:
        ready = asyncio.Event()

        async def run() -> dict:
            await ready.wait()
            return {"status": "success", "output": {"total": 42}}

        with patch.object(result_stream, "HEARTBEAT_SECONDS", 0.001):
            response = result_stream.stream_result(run())
            events = response.body_iterator
            self.assertEqual(await anext(events), ": heartbeat\n\n")
            self.assertEqual(await anext(events), ": heartbeat\n\n")
            self.assertFalse(ready.is_set())
            ready.set()
            frame = await anext(events)
            self.assertEqual(json.loads(frame[6:])["result"]["output"], {"total": 42})
            await events.aclose()
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertIn("no-transform", response.headers["cache-control"])

    async def test_disconnect_does_not_cancel_execution_or_its_persistence(self) -> None:
        ready = asyncio.Event()
        persisted = asyncio.Event()

        async def run() -> dict:
            await ready.wait()
            persisted.set()
            return {}

        response = result_stream.stream_result(run())
        events = response.body_iterator
        await anext(events)
        tasks = set(result_stream._RUNNING)
        await events.aclose()
        self.assertTrue(tasks)
        self.assertTrue(all(not task.cancelled() for task in tasks))
        ready.set()
        await asyncio.wait_for(persisted.wait(), 1)
        await asyncio.gather(*tasks)

    async def test_refusals_and_internal_failures_have_terminal_error_frames(self) -> None:
        async def refuse() -> None:
            raise HTTPException(403, "No access")

        async def fail() -> None:
            raise RuntimeError("private credentials")

        for operation, status, detail in [
            (refuse, 403, "No access"),
            (fail, 500, "The run could not complete."),
        ]:
            with self.subTest(status=status), patch.object(result_stream.logger, "exception"):
                response = result_stream.stream_result(operation())
                frames = [frame async for frame in response.body_iterator]
                event = json.loads(frames[-1][6:])
                self.assertEqual(event, {"type": "error", "status": status, "detail": detail})
