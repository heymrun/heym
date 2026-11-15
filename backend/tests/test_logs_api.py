import asyncio
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api.logs import get_docker_logs, stream_docker_logs
from app.config import settings


class DockerLogsFeatureFlagTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_enabled = settings.docker_logs_enabled
        self.original_allowed_emails = settings.docker_logs_allowed_emails
        settings.docker_logs_enabled = False
        settings.docker_logs_allowed_emails = ""

    async def asyncTearDown(self) -> None:
        settings.docker_logs_enabled = self.original_enabled
        settings.docker_logs_allowed_emails = self.original_allowed_emails

    async def test_get_docker_logs_rejects_before_docker_client_when_disabled(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())

        with patch("app.api.logs.get_docker_client") as get_client:
            with self.assertRaises(HTTPException) as ctx:
                await get_docker_logs("heym-backend", current_user=user, db=AsyncMock())

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Docker log access is disabled", ctx.exception.detail)
        get_client.assert_not_called()

    async def test_get_docker_logs_rejects_before_docker_client_without_allowed_emails(
        self,
    ) -> None:
        settings.docker_logs_enabled = True
        user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")

        with patch("app.api.logs.get_docker_client") as get_client:
            with self.assertRaises(HTTPException) as ctx:
                await get_docker_logs("heym-backend", current_user=user, db=AsyncMock())

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("no allowed user emails", ctx.exception.detail)
        get_client.assert_not_called()

    async def test_get_docker_logs_rejects_before_docker_client_for_unlisted_user(
        self,
    ) -> None:
        settings.docker_logs_enabled = True
        settings.docker_logs_allowed_emails = "admin@example.com"
        user = SimpleNamespace(id=uuid.uuid4(), email="viewer@example.com")

        with patch("app.api.logs.get_docker_client") as get_client:
            with self.assertRaises(HTTPException) as ctx:
                await get_docker_logs("heym-backend", current_user=user, db=AsyncMock())

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("not allowed", ctx.exception.detail)
        get_client.assert_not_called()

    async def test_get_docker_logs_allows_configured_user_to_reach_docker_client(
        self,
    ) -> None:
        settings.docker_logs_enabled = True
        settings.docker_logs_allowed_emails = "Admin@Example.com, ops@example.com"
        user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")

        with patch("app.api.logs.get_docker_client", return_value=None) as get_client:
            with self.assertRaises(HTTPException) as ctx:
                await get_docker_logs("heym-backend", current_user=user, db=AsyncMock())

        self.assertEqual(ctx.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        get_client.assert_called_once()

    async def test_stream_docker_logs_rejects_before_docker_client_when_disabled(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())

        with patch("app.api.logs.get_docker_client") as get_client:
            with self.assertRaises(HTTPException) as ctx:
                await stream_docker_logs("heym-backend", current_user=user, db=AsyncMock())

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Docker log access is disabled", ctx.exception.detail)
        get_client.assert_not_called()


class DockerLogStreamTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, lines):
        self.closed = False
        test = self

        class _Stream:
            def __init__(self) -> None:
                self._lines = iter(lines)

            def __iter__(self):
                return self

            def __next__(self):
                return next(self._lines)()

            def close(self) -> None:
                test.closed = True

        container = SimpleNamespace(logs=lambda **_kwargs: _Stream())
        return SimpleNamespace(containers=SimpleNamespace(get=lambda _name: container))

    async def _read(self, response) -> list[str]:
        return [chunk async for chunk in response.body_iterator]

    async def test_waiting_for_the_next_line_does_not_block_the_event_loop(self) -> None:
        release = threading.Event()
        outcome: dict[str, bool] = {}

        def waiting_line() -> bytes:
            outcome["released_by_loop"] = release.wait(timeout=5)
            return b"backend ready\n"

        user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
        with (
            patch("app.api.logs.require_docker_logs_access"),
            patch("app.api.logs.get_docker_client", return_value=self._client([waiting_line])),
        ):
            response = await stream_docker_logs("heym-backend", current_user=user, db=AsyncMock())
            reader = asyncio.create_task(self._read(response))
            await asyncio.sleep(0.05)
            release.set()
            chunks = await reader

        self.assertTrue(outcome["released_by_loop"])
        self.assertEqual(chunks, ["data: backend ready\n\n\n"])
        self.assertTrue(self.closed)

    async def test_lines_are_streamed_in_order_and_the_stream_is_closed(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
        lines = [lambda: b"one\n", lambda: b"two \xff\n"]
        with (
            patch("app.api.logs.require_docker_logs_access"),
            patch("app.api.logs.get_docker_client", return_value=self._client(lines)),
        ):
            response = await stream_docker_logs("heym-backend", current_user=user, db=AsyncMock())
            chunks = await self._read(response)

        self.assertEqual(chunks, ["data: one\n\n\n", "data: two \ufffd\n\n\n"])
        self.assertTrue(self.closed)


if __name__ == "__main__":
    unittest.main()
