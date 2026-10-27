"""A2A credentials: the stored digest never authenticates, and nothing is read from URLs.

These tests talk to a real database, so they call the app through `httpx.ASGITransport` on
the test's own event loop: Starlette's sync `TestClient` runs each request on another loop,
and asyncpg connections cannot cross loops.
"""

import httpx
from fastapi import FastAPI

from app.api import a2a
from app.services.secret_tokens import hash_secret
from tests.a2a_fixtures import A2APostgresCase

BODY = {"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}}


class A2ACredentialAdvisoryTests(A2APostgresCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        app = FastAPI()
        app.include_router(a2a.router, prefix="/api/a2a")
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://heym.test"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_the_global_key_authenticates(self) -> None:
        response = await self.client.post(
            "/api/a2a", json=BODY, headers={"X-MCP-Key": self.global_key}
        )

        self.assertEqual(response.status_code, 200)
        # A2A is off for the fixture user, which proves the request got past authentication.
        self.assertEqual(response.json()["error"]["code"], -32004)

    async def test_the_stored_digest_of_the_global_key_does_not(self) -> None:
        response = await self.client.post(
            "/api/a2a", json=BODY, headers={"X-MCP-Key": hash_secret(self.global_key)}
        )

        self.assertEqual(response.status_code, 401)

    async def test_the_server_key_authenticates_its_own_server(self) -> None:
        response = await self.client.post(
            f"/api/a2a/servers/{self.server_id}", json=BODY, headers={"X-MCP-Key": self.server_key}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"]["code"], -32004)

    async def test_the_stored_digest_of_a_server_key_does_not(self) -> None:
        response = await self.client.post(
            f"/api/a2a/servers/{self.server_id}",
            json=BODY,
            headers={"X-MCP-Key": hash_secret(self.server_key)},
        )

        self.assertEqual(response.status_code, 401)

    async def test_a_key_in_the_query_string_is_ignored(self) -> None:
        response = await self.client.post(f"/api/a2a?X-MCP-Key={self.global_key}", json=BODY)

        self.assertEqual(response.status_code, 401)

    async def test_a_session_token_in_the_query_string_is_refused(self) -> None:
        response = await self.client.post(
            "/api/a2a?session=anything", json=BODY, headers={"X-MCP-Key": self.global_key}
        )

        self.assertEqual(response.status_code, 401)

    async def test_a_server_key_does_not_open_another_server(self) -> None:
        other = "00000000-0000-0000-0000-000000000000"
        response = await self.client.post(
            f"/api/a2a/servers/{other}", json=BODY, headers={"X-MCP-Key": self.server_key}
        )

        self.assertEqual(response.status_code, 401)
