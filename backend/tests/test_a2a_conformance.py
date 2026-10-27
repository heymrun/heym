"""Every payload Heym sends parses as the official A2A SDK's 1.0 type, unknown fields refused."""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import a2a.types as sdk
from fastapi import FastAPI
from google.protobuf import json_format
from starlette.testclient import TestClient

from app.api import a2a
from app.services.a2a.agent_card import (
    CardWorkflow,
    extended_card,
    global_endpoint_url,
    public_card,
)
from app.services.heym_agent.links import WorkflowLink
from app.services.heym_agent.settings import AgentSettings
from app.services.heym_agent.turn import AgentOutcome, AgentTurnResult
from tests.a2a_fixtures import MemoryTaskStore

SETTINGS = AgentSettings(enabled=True, credential_id=None, model=None, a2a_enabled=True)
BASE = "https://heym.test"
SEND = {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "hi"}]}}


def _parse(cls: Any, payload: dict[str, Any]) -> Any:
    return json_format.ParseDict(payload, cls(), ignore_unknown_fields=False)


def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


class A2AConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="o@example.com")
        self.store = MemoryTaskStore()
        conversation_id = uuid.uuid4()
        self.outcome = AgentOutcome.COMPLETED

        async def create_conversation(user_id: uuid.UUID) -> uuid.UUID:
            self.store.conversations[conversation_id] = user_id
            return conversation_id

        async def run_turn(request: Any, on_progress: Any) -> AgentTurnResult:
            return AgentTurnResult(
                request.conversation_id,
                "Done.",
                [],
                outcome=self.outcome,
                verified=True,
                workflow_links=(WorkflowLink("Invoice", f"{BASE}/workflows/{uuid.uuid4()}"),),
            )

        app = FastAPI()
        app.include_router(a2a.router, prefix="/api/a2a")
        app.dependency_overrides[a2a.get_a2a_user] = lambda: user
        app.dependency_overrides[a2a.get_task_store] = lambda: self.store
        self.client = TestClient(app)
        for item in (
            patch("app.api.a2a._load_global_settings", AsyncMock(return_value=SETTINGS)),
            patch("app.services.a2a.executor._run_turn", run_turn),
            patch("app.services.a2a.executor._create_conversation", create_conversation),
            patch("app.api.a2a.build_public_base_url", return_value=BASE),
            patch("app.api.a2a.build_default_public_base_url", return_value=BASE),
            patch("app.api.a2a.audit"),
        ):
            item.start()
            self.addCleanup(item.stop)

    def _result(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = self.client.post("/api/a2a", json=_rpc(method, params)).json()
        self.assertNotIn("error", body, body)
        return body["result"]

    def test_agent_cards(self) -> None:
        _parse(
            sdk.AgentCard,
            public_card(endpoint_url=global_endpoint_url(BASE), public_base_url=BASE).wire(),
        )
        _parse(
            sdk.AgentCard,
            extended_card(
                endpoint_url=global_endpoint_url(BASE),
                public_base_url=BASE,
                server_name="Finance",
                workflows=[CardWorkflow(uuid.uuid4(), "Invoice Parser", "Parse invoices.")],
            ).wire(),
        )

    def test_send_get_list(self) -> None:
        sent = self._result("SendMessage", SEND)
        _parse(sdk.SendMessageResponse, sent)
        task_id = sent["task"]["id"]
        _parse(sdk.Task, self._result("GetTask", {"id": task_id}))
        _parse(sdk.ListTasksResponse, self._result("ListTasks", {"includeArtifacts": True}))

    def test_an_interrupted_task_and_its_cancel(self) -> None:
        self.outcome = AgentOutcome.INPUT_REQUIRED
        sent = self._result("SendMessage", SEND)
        _parse(sdk.SendMessageResponse, sent)

        canceled = self._result("CancelTask", {"id": sent["task"]["id"]})

        _parse(sdk.Task, canceled)
        self.assertEqual(canceled["status"]["state"], "TASK_STATE_CANCELED")

    def test_stream_events(self) -> None:
        with self.client.stream(
            "POST", "/api/a2a", json=_rpc("SendStreamingMessage", SEND)
        ) as response:
            events = [
                json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")
            ]

        self.assertGreaterEqual(len(events), 4)
        for event in events:
            _parse(sdk.StreamResponse, event["result"])
