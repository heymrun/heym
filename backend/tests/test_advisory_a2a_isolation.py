"""A2A tasks stay inside one user's surface, and public cards say nothing about the user."""

import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import update

from app.api import a2a
from app.db.models import MCPServer
from app.db.session import async_session_maker
from app.services.a2a import errors
from app.services.a2a.executor import A2AExecutor
from app.services.a2a.models import CancelTaskRequest, GetTaskRequest, ListTasksRequest
from app.services.a2a.task_store import SqlTaskStore, TaskScope
from app.services.heym_agent.settings import AgentSettings
from tests.a2a_fixtures import A2APostgresCase

SETTINGS = AgentSettings(enabled=True, credential_id=None, model=None, a2a_enabled=True)


class A2AIsolationAdvisoryTests(A2APostgresCase):
    def _executor(self, scope: TaskScope) -> A2AExecutor:
        return A2AExecutor(
            scope=scope,
            settings=SETTINGS,
            public_base_url="https://heym.test",
            store=SqlTaskStore(),
        )

    async def test_foreign_tasks_look_like_missing_ones(self) -> None:
        task = await SqlTaskStore().create(
            TaskScope(self.user_id, self.server_id), self.conversation_id
        )
        outsiders = [
            TaskScope(self.user_id, None),
            TaskScope(self.other_user_id, None),
            TaskScope(self.other_user_id, self.server_id),
        ]
        for scope in outsiders:
            executor = self._executor(scope)
            for name, call in (
                ("GetTask", lambda: executor.get_task(GetTaskRequest(id=str(task.id)))),
                ("CancelTask", lambda: executor.cancel_task(CancelTaskRequest(id=str(task.id)))),
            ):
                with self.subTest(scope=scope, method=name):
                    with self.assertRaises(errors.A2AError) as caught:
                        await call()
                    self.assertEqual(caught.exception.code, errors.TASK_NOT_FOUND)
            listed = await executor.list_tasks(ListTasksRequest())
            self.assertEqual(listed.total_size, 0)

    async def _get_card(self, server_id: uuid.UUID) -> httpx.Response:
        app = FastAPI()
        app.include_router(a2a.router, prefix="/api/a2a")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://heym.test"
        ) as client:
            return await client.get(f"/api/a2a/servers/{server_id}/agent-card.json")

    async def test_the_public_server_card_names_nothing_of_the_owner(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                update(MCPServer)
                .where(MCPServer.id == self.server_id)
                .values(chat_enabled=True, a2a_enabled=True)
            )
            await db.commit()

        response = await self._get_card(self.server_id)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Acme payroll", response.text)
        self.assertNotIn("@example.com", response.text)

    async def test_a_card_is_not_served_while_a2a_is_off(self) -> None:
        response = await self._get_card(self.server_id)

        self.assertEqual(response.status_code, 404)

    async def test_an_unknown_server_has_no_card(self) -> None:
        response = await self._get_card(uuid.uuid4())

        self.assertEqual(response.status_code, 404)
