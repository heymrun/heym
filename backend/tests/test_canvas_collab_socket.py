"""The canvas collaboration socket: origin, auth, permission, stamping and limits."""

import json
import time
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import collab
from app.db.models import User, Workflow
from app.services.collab.hub import CollabHub
from app.services.collab.protocol import RoutedMessage

WORKFLOW_ID = uuid.uuid4()
URL = f"/api/workflows/{WORKFLOW_ID}/collab"
SAME_ORIGIN = "http://testserver"


class _InProcessBus:
    """Delivers straight to the hub, as if Postgres had echoed the notification."""

    def __init__(self, hub: CollabHub) -> None:
        self.hub = hub

    async def ensure_started(self, timeout: float = 2.0) -> bool:
        return True

    async def publish(self, room: str, message: RoutedMessage) -> None:
        self.hub.deliver(room, message.to_wire())


class _FakeSession:
    def __init__(self, users: dict[uuid.UUID, Any], workflow: Any) -> None:
        self.users = users
        self.workflow = workflow

    async def get(self, model: Any, key: Any) -> Any:
        if model is User:
            return self.users.get(key)
        if model is Workflow:
            return self.workflow if key == self.workflow.id else None
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class CollabSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = SimpleNamespace(id=uuid.uuid4(), name="Ana")
        self.viewer = SimpleNamespace(id=uuid.uuid4(), name="Ben")
        self.workflow = SimpleNamespace(id=WORKFLOW_ID, owner_id=self.owner.id)
        self.tokens = {"owner": self.owner.id, "viewer": self.viewer.id}
        self.permissions: dict[uuid.UUID, list[str | None]] = {
            self.owner.id: ["write"],
            self.viewer.id: ["read"],
        }
        users = {self.owner.id: self.owner, self.viewer.id: self.viewer}
        hub = CollabHub()
        for target in (
            patch.object(collab, "collab_hub", hub),
            patch.object(collab, "collab_bus", _InProcessBus(hub)),
            patch.object(collab, "async_session_maker", lambda: _FakeSession(users, self.workflow)),
            patch.object(collab, "resolve_token_user_id", AsyncMock(side_effect=self._resolve)),
            patch.object(
                collab, "get_workflow_permission", AsyncMock(side_effect=self._permission)
            ),
        ):
            target.start()
            self.addCleanup(target.stop)
        app = FastAPI()
        app.include_router(collab.router, prefix="/api/workflows")
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    async def _resolve(self, _connection: Any, token: str) -> uuid.UUID | None:
        return self.tokens.get(token)

    async def _permission(self, _db: Any, _workflow: Any, user_id: uuid.UUID, **_kw: Any) -> Any:
        answers = self.permissions[user_id]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def _connect(self, token: str | None = "owner", origin: str = SAME_ORIGIN) -> Any:
        headers = {"origin": origin}
        if token is not None:
            headers["cookie"] = f"access_token={token}"
        return self.client.websocket_connect(URL, headers=headers)

    def _close_code(self, socket: Any) -> int:
        with self.assertRaises(WebSocketDisconnect) as caught:
            socket.receive_json()
        return caught.exception.code

    def test_a_foreign_origin_is_refused(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self._connect(origin="https://evil.example"):
                pass
        self.assertEqual(collab.CLOSE_FORBIDDEN, caught.exception.code)

    def test_no_cookie_closes_as_unauthenticated(self) -> None:
        with self._connect(token=None) as socket:
            self.assertEqual(collab.CLOSE_UNAUTHENTICATED, self._close_code(socket))

    def test_no_access_closes_as_forbidden(self) -> None:
        self.permissions[self.viewer.id] = [None]
        with self._connect(token="viewer") as socket:
            self.assertEqual(collab.CLOSE_FORBIDDEN, self._close_code(socket))

    def test_a_read_share_is_welcomed_but_cannot_send_ops(self) -> None:
        with self._connect(token="viewer") as socket:
            welcome = socket.receive_json()
            socket.send_text(json.dumps({"t": "ops", "seq": 1, "ops": []}))
            error = socket.receive_json()

        self.assertEqual("welcome", welcome["t"])
        self.assertEqual("read", welcome["permission"])
        self.assertEqual({"t": "error", "message": "ops needs write access"}, error)

    def test_the_server_stamps_the_sender(self) -> None:
        forged = {"sid": "x", "userId": "someone", "name": "Mallory", "permission": "write"}
        with self._connect(token="owner") as ana:
            ana_welcome = ana.receive_json()
            with self._connect(token="viewer") as ben:
                ben.receive_json()
                self.assertEqual("join", ana.receive_json()["t"])
                ana.send_text(json.dumps({"t": "presence", "state": {}, "from": forged}))
                frame = ben.receive_json()

        self.assertEqual("presence", frame["t"])
        self.assertEqual(ana_welcome["sid"], frame["from"]["sid"])
        self.assertEqual("Ana", frame["from"]["name"])

    def test_leaving_is_announced_to_the_room(self) -> None:
        with self._connect(token="owner") as ana:
            ana.receive_json()
            with self._connect(token="viewer") as ben:
                ben_sid = ben.receive_json()["sid"]
                ana.receive_json()
            leave = ana.receive_json()

        self.assertEqual("leave", leave["t"])
        self.assertEqual(ben_sid, leave["from"]["sid"])

    def test_revoked_access_closes_the_socket(self) -> None:
        self.permissions[self.owner.id] = ["write", None]
        with patch.object(collab, "PERMISSION_RECHECK_SECONDS", 0.05):
            with self._connect(token="owner") as socket:
                socket.receive_json()
                self.assertEqual(collab.CLOSE_FORBIDDEN, self._close_code(socket))

    def test_demotion_to_read_stops_ops(self) -> None:
        self.permissions[self.owner.id] = ["write", "read"]
        with patch.object(collab, "PERMISSION_RECHECK_SECONDS", 0.05):
            with self._connect(token="owner") as socket:
                self.assertEqual("write", socket.receive_json()["permission"])
                time.sleep(0.2)
                socket.send_text(json.dumps({"t": "ops", "seq": 1, "ops": []}))
                error = socket.receive_json()

        self.assertEqual("ops needs write access", error["message"])

    def test_an_oversized_frame_closes_the_socket(self) -> None:
        with patch.object(collab, "MAX_MESSAGE_BYTES", 64):
            with self._connect(token="owner") as socket:
                socket.receive_json()
                socket.send_text("x" * 100)
                self.assertEqual(collab.CLOSE_TOO_LARGE, self._close_code(socket))


class OriginTests(unittest.TestCase):
    def test_listed_or_same_host_origins_pass(self) -> None:
        allowed = ["http://localhost:4017"]
        cases = {
            ("http://localhost:4017", "backend:10105", None): True,
            ("https://heym.example.com", "heym.example.com", None): True,
            ("https://heym.example.com", "backend:10105", "heym.example.com"): True,
            ("https://evil.example", "heym.example.com", None): False,
            (None, "heym.example.com", None): False,
        }
        for (origin, host, forwarded), expected in cases.items():
            raw = {"host": host}
            if origin:
                raw["origin"] = origin
            if forwarded:
                raw["x-forwarded-host"] = forwarded
            self.assertEqual(expected, collab.origin_allowed(Headers(raw), allowed), raw)
