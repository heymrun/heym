"""A Discord command whose run the concurrency queue rejects still gets an answer.

The route defers the interaction; a run whose history was written elsewhere (queued, queue
full, another instance) used to return before the follow-up, leaving "thinking..." on.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import httpx
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.api import discord as discord_api
from app.db.models import Workflow
from app.db.session import async_session_maker
from app.services import workflow_concurrency

NODES = [
    {"id": "d1", "type": "discordTrigger", "data": {"label": "slash"}},
    {"id": "o1", "type": "output", "data": {"label": "reply", "message": "Pong"}},
]
EDGES = [{"id": "e1", "source": "d1", "target": "o1"}]


class DiscordQueueFullFollowUpTests(ConcurrencyPostgresCase):
    limit = None
    max_queue = 1

    async def _follow_ups(self, limit: int | None) -> list:
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            assert workflow is not None
            workflow.nodes, workflow.edges, workflow.concurrency_limit = NODES, EDGES, limit
            await db.commit()
        if limit is not None:
            await workflow_concurrency.admit(self.held_run())
            await workflow_concurrency.admit(self.held_run())
        sent: list = []

        async def record_post(_client, _url, json=None, **_kw):  # noqa: ANN001, A002
            sent.append(json)
            return httpx.Response(200, json={"id": "m1"})

        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
        interaction = {"type": 2, "application_id": "1111", "token": "itok-" + uuid.uuid4().hex}
        with patch.object(httpx.AsyncClient, "post", record_post):
            await discord_api._execute_workflow_background(workflow, "d1", interaction, {})
        return sent

    async def test_a_run_here_answers_with_its_output(self) -> None:
        self.assertEqual(await self._follow_ups(None), [{"content": "Pong"}])

    async def test_a_run_the_full_queue_rejects_answers_with_the_reason(self) -> None:
        self.assertEqual(
            await self._follow_ups(1),
            [{"content": workflow_concurrency.QUEUE_FULL_MESSAGE}],
        )
