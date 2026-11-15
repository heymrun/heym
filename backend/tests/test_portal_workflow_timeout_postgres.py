"""Portal runs stop at the workflow's timeout, like API and editor runs do."""

import json
import time

import httpx
from sqlalchemy import update
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import Workflow
from app.db.session import async_session_maker
from app.main import app

TIMEOUT_SECONDS = 1
WAIT_MS = 4000
NODES = [
    {
        "id": "s",
        "type": "textInput",
        "position": {"x": 0, "y": 0},
        "data": {"label": "start", "inputFields": [{"key": "text"}]},
    },
    {
        "id": "w",
        "type": "wait",
        "position": {"x": 200, "y": 0},
        "data": {"label": "slowStep", "duration": WAIT_MS},
    },
]
EDGES = [{"id": "e1", "source": "s", "target": "w"}]


class PortalWorkflowTimeoutTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.slug = f"timeout-{self.workflow_id.hex[:12]}"
        async with async_session_maker() as db:
            await db.execute(
                update(Workflow)
                .where(Workflow.id == self.workflow_id)
                .values(
                    nodes=NODES,
                    edges=EDGES,
                    workflow_timeout_seconds=TIMEOUT_SECONDS,
                    portal_enabled=True,
                    portal_slug=self.slug,
                )
            )
            await db.commit()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30
        )

    async def test_the_plain_portal_endpoint_stops_at_the_timeout(self) -> None:
        started = time.monotonic()
        async with self._client() as client:
            response = await client.post(
                f"/api/portal/{self.slug}/execute", json={"inputs": {"text": "hi"}}
            )
        elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "error")
        self.assertLess(elapsed, WAIT_MS / 1000 - 1)

    async def test_the_streaming_portal_endpoint_stops_at_the_timeout(self) -> None:
        final: dict = {}
        started = time.monotonic()
        async with self._client() as client:
            async with client.stream(
                "POST", f"/api/portal/{self.slug}/execute/stream", json={"inputs": {"text": "hi"}}
            ) as stream:
                async for line in stream.aiter_lines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        if event.get("type") == "execution_complete":
                            final = event
        elapsed = time.monotonic() - started

        self.assertEqual(final.get("status"), "error", final)
        self.assertLess(elapsed, WAIT_MS / 1000 - 1)
