"""The A2A router: credentials from headers, JSON-RPC dispatch, errors, SSE and cards."""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from app.api import a2a
from app.services.heym_agent.settings import AgentSettings
from app.services.heym_agent.turn import AgentTurnResult
from tests.a2a_fixtures import MemoryTaskStore

ON = AgentSettings(enabled=True, credential_id=None, model=None, a2a_enabled=True)
OFF = AgentSettings(enabled=True, credential_id=None, model=None, a2a_enabled=False)


def _rpc(method: str, params: dict[str, Any] | None = None, request_id: Any = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def _send(text: str = "hi") -> dict[str, Any]:
    return {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": text}]}}


class RouterCase(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com")
        self.store = MemoryTaskStore()
        self.conversation_id = uuid.uuid4()
        self.settings = ON
        app = FastAPI()
        app.include_router(a2a.router, prefix="/api/a2a")
        app.include_router(a2a.well_known_router)
        app.dependency_overrides[a2a.get_a2a_user] = lambda: self.user
        app.dependency_overrides[a2a.get_task_store] = lambda: self.store
        self.client = TestClient(app)

        async def run_turn(request: Any, on_progress: Any) -> AgentTurnResult:
            return AgentTurnResult(request.conversation_id, "Done.", [])

        async def create_conversation(user_id: uuid.UUID) -> uuid.UUID:
            self.store.conversations[self.conversation_id] = user_id
            return self.conversation_id

        for item in (
            patch(
                "app.api.a2a._load_global_settings",
                AsyncMock(side_effect=lambda user_id: self.settings),
            ),
            patch("app.services.a2a.executor._run_turn", run_turn),
            patch("app.services.a2a.executor._create_conversation", create_conversation),
            patch("app.api.a2a.build_public_base_url", return_value="https://heym.test"),
            patch("app.api.a2a.build_default_public_base_url", return_value="https://heym.test"),
            patch("app.api.a2a.audit"),
        ):
            item.start()
            self.addCleanup(item.stop)

    def post(self, body: Any, **kwargs: Any) -> dict[str, Any]:
        response = self.client.post("/api/a2a", json=body, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class DispatchTests(RouterCase):
    def test_send_message_returns_the_task_wrapped(self) -> None:
        body = self.post(_rpc("SendMessage", _send()), headers={"A2A-Version": "1.0"})

        task = body["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(task["artifacts"][0]["parts"][0]["text"], "Done.")

    def test_get_and_list_and_cancel(self) -> None:
        task_id = self.post(_rpc("SendMessage", _send()))["result"]["task"]["id"]

        got = self.post(_rpc("GetTask", {"id": task_id}))["result"]
        listed = self.post(_rpc("ListTasks", {}))["result"]
        canceled = self.post(_rpc("CancelTask", {"id": task_id}))

        self.assertEqual(got["id"], task_id)
        self.assertEqual(listed["totalSize"], 1)
        self.assertEqual(canceled["error"]["code"], -32002)

    def test_protocol_errors(self) -> None:
        cases = [
            (_rpc("Nope"), -32601),
            (_rpc("message/send", _send()), -32009),
            (_rpc("CreateTaskPushNotificationConfig", {}), -32003),
            (_rpc("GetTask", {}), -32602),
            ({"id": 1, "method": "GetTask"}, -32600),
        ]
        for body, code in cases:
            with self.subTest(body=body):
                self.assertEqual(self.post(body)["error"]["code"], code)

    def test_unsupported_version_header(self) -> None:
        body = self.post(_rpc("GetTask", {"id": "x"}), headers={"A2A-Version": "0.3"})

        self.assertEqual(body["error"]["code"], -32009)

    def test_parse_error(self) -> None:
        response = self.client.post(
            "/api/a2a", content=b"{not json", headers={"content-type": "application/json"}
        )

        self.assertEqual(response.json()["error"]["code"], -32700)

    def test_a2a_off_is_an_unsupported_operation(self) -> None:
        self.settings = OFF

        body = self.post(_rpc("SendMessage", _send()))

        self.assertEqual(body["error"]["code"], -32004)
        self.assertIn("MCP / A2A", body["error"]["message"])

    def test_extended_card(self) -> None:
        card = self.post(_rpc("GetExtendedAgentCard"))["result"]

        self.assertEqual(card["name"], "Heym Agent")

    def test_streaming_sends_json_rpc_events(self) -> None:
        with self.client.stream(
            "POST", "/api/a2a", json=_rpc("SendStreamingMessage", _send(), 9)
        ) as response:
            self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
            lines = [line for line in response.iter_lines() if line.startswith("data: ")]

        events = [json.loads(line[6:]) for line in lines]
        self.assertTrue(all(event["id"] == 9 for event in events))
        self.assertEqual(next(iter(events[0]["result"])), "task")
        self.assertEqual(
            events[-1]["result"]["statusUpdate"]["status"]["state"], "TASK_STATE_COMPLETED"
        )


class CredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(a2a.router, prefix="/api/a2a")
        self.client = TestClient(app)

    def test_no_credentials_is_401(self) -> None:
        with patch(
            "app.api.a2a.get_mcp_user", AsyncMock(side_effect=HTTPException(status_code=401))
        ):
            response = self.client.post("/api/a2a", json=_rpc("GetTask", {"id": "x"}))

        self.assertEqual(response.status_code, 401)

    def test_a_session_query_parameter_is_refused(self) -> None:
        get_user = AsyncMock()
        with patch("app.api.a2a.get_mcp_user", get_user):
            response = self.client.post(
                "/api/a2a?session=abc",
                json=_rpc("GetTask", {"id": "x"}),
                headers={"X-MCP-Key": "k"},
            )

        self.assertEqual(response.status_code, 401)
        get_user.assert_not_awaited()


class CardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(a2a.router, prefix="/api/a2a")
        app.include_router(a2a.well_known_router)
        self.client = TestClient(app)
        base = patch("app.api.a2a.build_default_public_base_url", return_value="https://heym.test")
        base.start()
        self.addCleanup(base.stop)

    def test_domain_card_exists_only_while_someone_enabled_global_a2a(self) -> None:
        with patch(
            "app.api.a2a.agent_settings.any_global_a2a_enabled", AsyncMock(return_value=False)
        ):
            self.assertEqual(self.client.get("/.well-known/agent-card.json").status_code, 404)
        with patch(
            "app.api.a2a.agent_settings.any_global_a2a_enabled", AsyncMock(return_value=True)
        ):
            card = self.client.get("/.well-known/agent-card.json").json()

        self.assertEqual(card["supportedInterfaces"][0]["url"], "https://heym.test/api/a2a")

    def test_server_card_exists_only_while_its_a2a_is_on(self) -> None:
        server_id = uuid.uuid4()
        path = f"/api/a2a/servers/{server_id}/agent-card.json"
        with patch("app.api.a2a.agent_settings.server_a2a_enabled", AsyncMock(return_value=False)):
            self.assertEqual(self.client.get(path).status_code, 404)
        with patch("app.api.a2a.agent_settings.server_a2a_enabled", AsyncMock(return_value=True)):
            card = self.client.get(path).json()

        self.assertEqual(
            card["supportedInterfaces"][0]["url"], f"https://heym.test/api/a2a/servers/{server_id}"
        )
