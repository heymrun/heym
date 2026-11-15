"""A trigger webhook keeps working when another workflow has a node with the same id.

Node ids are unique only inside a workflow: the AI builder names triggers "n1" and "Use
template" copies node ids. The webhook URL carries only the node id.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import delete
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.api import telegram as telegram_api
from app.db.models import Credential, CredentialType, User, Workflow
from app.db.session import async_session_maker
from app.services.encryption import encrypt_config

UPDATE = {
    "update_id": 912345001,
    "message": {
        "message_id": 77,
        "chat": {"id": 4242, "type": "private"},
        "date": 1763200000,
        "text": "/status 42",
    },
}


class SharedTriggerNodeIdTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.node_id = "n1-" + uuid.uuid4().hex[:8]
        self.other_user = uuid.uuid4()
        self.rows: list[tuple[type, uuid.UUID]] = []
        self.addAsyncCleanup(self._remove_rows)
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.other_user,
                    email=f"shared-node-{self.other_user.hex}@example.com",
                    hashed_password="test-only",
                    name="Other owner",
                )
            )
            await db.commit()
        self.rows.append((User, self.other_user))

    async def _remove_rows(self) -> None:
        async with async_session_maker() as db:
            for model in (Workflow, Credential, User):
                ids = [row_id for kind, row_id in self.rows if kind is model]
                if ids:
                    await db.execute(delete(model).where(model.id.in_(ids)))
            await db.commit()

    async def _bot(self, owner: uuid.UUID, name: str, secret: str) -> None:
        credential_id, workflow_id = uuid.uuid4(), uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                Credential(
                    id=credential_id,
                    owner_id=owner,
                    name=name,
                    type=CredentialType.telegram,
                    encrypted_config=encrypt_config({"bot_token": "1:a", "secret_token": secret}),
                )
            )
            db.add(
                Workflow(
                    id=workflow_id,
                    owner_id=owner,
                    name=name,
                    nodes=[
                        {
                            "id": self.node_id,
                            "type": "telegramTrigger",
                            "data": {"label": "telegramEvent", "credentialId": str(credential_id)},
                        }
                    ],
                    edges=[],
                )
            )
            await db.commit()
        self.rows += [(Workflow, workflow_id), (Credential, credential_id)]

    async def _other_workflow(self, nodes: list[dict[str, Any]]) -> None:
        workflow_id = uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                Workflow(
                    id=workflow_id, owner_id=self.other_user, name="Digest", nodes=nodes, edges=[]
                )
            )
            await db.commit()
        self.rows.append((Workflow, workflow_id))

    async def _deliver(self, secret: str) -> tuple[int, list[str]]:
        started: list[str] = []

        def record(coro: Any) -> None:
            started.append(coro.cr_frame.f_locals["workflow"].name)
            coro.close()

        app = FastAPI()
        app.include_router(telegram_api.router, prefix="/api/telegram")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        with patch.object(telegram_api, "spawn_background_task", record):
            async with httpx.AsyncClient(transport=transport, base_url="http://heym") as client:
                response = await client.post(
                    f"/api/telegram/webhook/{self.node_id}",
                    json=UPDATE,
                    headers={"X-Telegram-Bot-Api-Secret-Token": secret},
                )
        return response.status_code, started

    async def test_another_workflows_node_with_the_same_id_is_ignored(self) -> None:
        await self._bot(self.user_id, "Support bot", "secret-support")
        await self._other_workflow([{"id": self.node_id, "type": "cron", "data": {}}])

        self.assertEqual(await self._deliver("secret-support"), (200, ["Support bot"]))

    async def test_two_bots_with_the_same_trigger_id_each_get_their_own_updates(self) -> None:
        await self._bot(self.user_id, "Support bot", "secret-support")
        await self._bot(self.other_user, "Sales bot", "secret-sales")

        self.assertEqual(await self._deliver("secret-support"), (200, ["Support bot"]))
        self.assertEqual(await self._deliver("secret-sales"), (200, ["Sales bot"]))

    async def test_an_update_no_bot_verifies_is_still_rejected(self) -> None:
        await self._bot(self.user_id, "Support bot", "secret-support")
        await self._bot(self.other_user, "Sales bot", "secret-sales")

        self.assertEqual(await self._deliver("forged"), (403, []))
