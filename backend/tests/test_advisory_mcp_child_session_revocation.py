"""Advisory tests for MCP child session revocation, credential rotation, and transport binding.

Ensures:
- OAuth-derived child sessions are revoked on sign-out-others, password-change, and admin-sign-out.
- Ordinary OAuth token refresh does NOT invalidate existing child sessions.
- MCP API-key regeneration rotates key_version and invalidates previous child sessions.
- Child session tokens are accepted only on /message routes, never on /sse or Streamable HTTP.
- Legacy child tokens without required claims fail closed.
- Account deactivation terminates child sessions immediately.
- Raw keys and digests are never exposed in child session JWTs.
"""

from __future__ import annotations

import re
import secrets
import time
import unittest
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
from fastapi import Response
from sqlalchemy import delete

from app.api import admin_users, auth
from app.api.mcp import regenerate_mcp_key
from app.api.mcp_servers import create_mcp_server, regenerate_server_key
from app.api.oauth import _handle_refresh_token_grant, _issue_tokens
from app.config import settings
from app.db.models import MCPServer, OAuthAccessToken, OAuthClient, User
from app.db.session import async_session_maker, engine
from app.main import app
from app.models.schemas import MCPServerCreate, PasswordChangeRequest
from app.services.auth import hash_password
from app.services.mcp_session import mcp_session_store, mcp_sse_channels
from app.services.secret_tokens import hash_secret

TEST_PASSWORD = "Correct-horse-battery-staple-99!"
PING_PAYLOAD = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def _request_stub(ip: str = "127.0.0.1") -> SimpleNamespace:
    return SimpleNamespace(headers={}, cookies={}, query_params={}, client=SimpleNamespace(host=ip))


class _BaseMCPChildSessionCase(unittest.IsolatedAsyncioTestCase):
    """Base test case providing PostgreSQL setup, cleanup, and helper factories."""

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.user_ids: list[uuid.UUID] = []
        self.server_ids: list[uuid.UUID] = []
        self.client_ids: list[str] = []
        self.transport = httpx.ASGITransport(app=app)
        self.http_client = httpx.AsyncClient(transport=self.transport, base_url="http://test")
        self._disconnect_patch = patch(
            "starlette.requests.Request.is_disconnected", AsyncMock(return_value=True)
        )
        self._disconnect_patch.start()

    @asynccontextmanager
    async def _stream_sse(
        self, path: str, headers: dict[str, str] | None = None
    ) -> AsyncIterator[httpx.Response]:
        async with self.http_client.stream("GET", path, headers=headers or {}) as res:
            yield res

    async def _handshake_sse(self, path: str, headers: dict[str, str] | None = None) -> str:
        """Establish a real /sse handshake and extract the child session token from the endpoint event."""
        async with self.http_client.stream("GET", path, headers=headers or {}) as res:
            self.assertEqual(res.status_code, 200)
            body = await res.aread()
            text = body.decode()
            match = re.search(r"session=([A-Za-z0-9_.-]+)", text)
            assert match is not None, f"Could not find session token in SSE response: {text}"
            token = match.group(1)
            mcp_sse_channels.register(token)
            return token

    async def asyncTearDown(self) -> None:
        self._disconnect_patch.stop()
        await self.http_client.aclose()
        async with async_session_maker() as session:
            if self.server_ids:
                await session.execute(delete(MCPServer).where(MCPServer.id.in_(self.server_ids)))
            if self.user_ids:
                await session.execute(
                    delete(OAuthAccessToken).where(OAuthAccessToken.user_id.in_(self.user_ids))
                )
                await session.execute(delete(User).where(User.id.in_(self.user_ids)))
            if self.client_ids:
                await session.execute(
                    delete(OAuthClient).where(OAuthClient.client_id.in_(self.client_ids))
                )
            await session.commit()
        await engine.dispose()

    async def _create_user(
        self,
        *,
        mcp_key: str | None = None,
        key_version: str | None = None,
        is_active: bool = True,
    ) -> User:
        user_id = uuid.uuid4()
        self.user_ids.append(user_id)
        raw_key = mcp_key or f"mcp-{uuid.uuid4().hex}"
        v = key_version or secrets.token_hex(16)
        async with async_session_maker() as session:
            user = User(
                id=user_id,
                email=f"mcp_user_{user_id.hex[:8]}@example.com",
                name="MCP User",
                hashed_password=hash_password(TEST_PASSWORD),
                mcp_api_key=hash_secret(raw_key),
                mcp_api_key_version=v,
                is_active=is_active,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            user._raw_mcp_key = raw_key  # type: ignore[attr-defined]
            return user

    async def _create_admin(self) -> User:
        admin = await self._create_user()
        return admin

    async def _create_named_server(self, user: User) -> MCPServer:
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            server_res = await create_mcp_server(
                body=MCPServerCreate(name=f"Server-{uuid.uuid4().hex[:6]}"),
                current_user=db_user,
                db=session,
            )
            await session.commit()
            server_id = server_res.id
            self.server_ids.append(server_id)
            server = await session.get(MCPServer, server_id)
            assert server is not None
            server._raw_api_key = server_res.api_key  # type: ignore[attr-defined]
            return server

    async def _create_oauth_tokens(self, user: User) -> dict[str, str]:
        client_id = f"client-{uuid.uuid4().hex[:8]}"
        self.client_ids.append(client_id)
        async with async_session_maker() as session:
            client = OAuthClient(
                client_id=client_id,
                client_name="Test Client",
                redirect_uris=["https://client.example/callback"],
                is_confidential=False,
            )
            session.add(client)
            await session.flush()
            tokens = await _issue_tokens(session, client_id, user.id, "mcp")
            await session.commit()
            return tokens


class TestOAuthRevocation(_BaseMCPChildSessionCase):
    """Section A: OAuth child-session revocation across lifecycle events."""

    async def test_default_server_sign_out_others_revokes_child_session(self) -> None:
        user = await self._create_user()
        tokens = await self._create_oauth_tokens(user)
        access_token = tokens["access_token"]

        # 1. Establish child session from real /sse handshake with OAuth bearer.
        # Patch time during handshake so token iat is in the past, ensuring deterministic revocation.
        past_time = time.time() - 30.0
        with patch("time.time", return_value=past_time):
            child_token = await self._handshake_sse(
                "/api/mcp/sse",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        # Verify child session initially works
        res = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # 2. User signs out other sessions
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            await auth.revoke_other_sessions(
                request=_request_stub(),
                response=Response(),
                current_user=db_user,
                db=session,
            )
            await session.commit()

        # 3. Child session returns HTTP 401
        res_after = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_after.status_code, 401)
        self.assertIn("Invalid or expired session token", res_after.text)

    async def test_named_server_sign_out_others_revokes_child_session(self) -> None:
        user = await self._create_user()
        server = await self._create_named_server(user)
        # Deterministic setup: token minted with issued_at in past
        child_token = mcp_session_store.create(
            str(user.id),
            server_id=str(server.id),
            auth_source="oauth",
            issued_at=time.time() - 30.0,
        )
        mcp_sse_channels.register(child_token)

        # 1. Child session initially works
        res = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # 2. User signs out other sessions
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            await auth.revoke_other_sessions(
                request=_request_stub(),
                response=Response(),
                current_user=db_user,
                db=session,
            )
            await session.commit()

        # 3. Child session returns HTTP 401
        res_after = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_after.status_code, 401)
        self.assertIn("Invalid or expired session token", res_after.text)

    async def test_default_server_password_change_revokes_child_session(self) -> None:
        user = await self._create_user()
        # Deterministic setup: token minted with issued_at in past
        child_token = mcp_session_store.create(
            str(user.id), auth_source="oauth", issued_at=time.time() - 30.0
        )
        mcp_sse_channels.register(child_token)

        res = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # Password change
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            await auth.change_password(
                password_data=PasswordChangeRequest(
                    current_password=TEST_PASSWORD,
                    new_password="Brand-new-password-1234!",
                ),
                request=_request_stub(),
                response=Response(),
                current_user=db_user,
                db=session,
            )
            await session.commit()

        # Child session returns HTTP 401
        res_after = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_after.status_code, 401)

    async def test_named_server_password_change_revokes_child_session(self) -> None:
        user = await self._create_user()
        server = await self._create_named_server(user)
        # Deterministic setup: token minted with issued_at in past
        child_token = mcp_session_store.create(
            str(user.id),
            server_id=str(server.id),
            auth_source="oauth",
            issued_at=time.time() - 30.0,
        )
        mcp_sse_channels.register(child_token)

        res = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # Password change
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            await auth.change_password(
                password_data=PasswordChangeRequest(
                    current_password=TEST_PASSWORD,
                    new_password="Brand-new-password-5678!",
                ),
                request=_request_stub(),
                response=Response(),
                current_user=db_user,
                db=session,
            )
            await session.commit()

        res_after = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_after.status_code, 401)

    async def test_default_server_admin_sign_out_revokes_child_session(self) -> None:
        user = await self._create_user()
        admin = await self._create_admin()
        # Deterministic setup: token minted with issued_at in past
        child_token = mcp_session_store.create(
            str(user.id), auth_source="oauth", issued_at=time.time() - 30.0
        )
        mcp_sse_channels.register(child_token)

        res = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # Admin signs out user
        with patch.object(settings, "admin_emails", admin.email):
            async with async_session_maker() as session:
                db_admin = await session.get(User, admin.id)
                assert db_admin is not None
                await admin_users.sign_out_user(
                    user_id=user.id,
                    current_user=db_admin,
                    db=session,
                )
                await session.commit()

        res_after = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_after.status_code, 401)

    async def test_named_server_admin_sign_out_revokes_child_session(self) -> None:
        user = await self._create_user()
        admin = await self._create_admin()
        server = await self._create_named_server(user)
        # Deterministic setup: token minted with issued_at in past
        child_token = mcp_session_store.create(
            str(user.id),
            server_id=str(server.id),
            auth_source="oauth",
            issued_at=time.time() - 30.0,
        )
        mcp_sse_channels.register(child_token)

        res = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # Admin signs out user
        with patch.object(settings, "admin_emails", admin.email):
            async with async_session_maker() as session:
                db_admin = await session.get(User, admin.id)
                assert db_admin is not None
                await admin_users.sign_out_user(
                    user_id=user.id,
                    current_user=db_admin,
                    db=session,
                )
                await session.commit()

        res_after = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_after.status_code, 401)


class TestMCPApiKeyRotation(_BaseMCPChildSessionCase):
    """Section B: MCP API-key rotation invalidates previous child sessions."""

    async def test_default_server_api_key_rotation(self) -> None:
        raw_key = f"mcp-{uuid.uuid4().hex}"
        initial_version = secrets.token_hex(16)
        user = await self._create_user(mcp_key=raw_key, key_version=initial_version)

        # 1. Take child token from endpoint event of a real /sse handshake
        child_token = await self._handshake_sse(
            "/api/mcp/sse",
            headers={"X-MCP-Key": raw_key},
        )

        # Verify child session initially works
        res = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # 2. Regenerate default API key
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            regen_res = await regenerate_mcp_key(current_user=db_user, db=session)
            await session.commit()
            new_raw_key = regen_res.mcp_api_key
            new_version = db_user.mcp_api_key_version

        self.assertNotEqual(initial_version, new_version)

        # 3. Old child session returns HTTP 401
        res_old_session = await self.http_client.post(
            f"/api/mcp/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_old_session.status_code, 401)

        # 4. Old API key cannot authenticate / establish session
        res_old_key = await self.http_client.get(
            "/api/mcp/sse",
            headers={"X-MCP-Key": raw_key},
        )
        self.assertEqual(res_old_key.status_code, 401)

        # 5. New API key works to establish a new session through real handshake
        new_child_token = await self._handshake_sse(
            "/api/mcp/sse",
            headers={"X-MCP-Key": new_raw_key},
        )
        res_new_session = await self.http_client.post(
            f"/api/mcp/message?session={new_child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_new_session.status_code, 202)

    async def test_named_server_api_key_rotation(self) -> None:
        user = await self._create_user()
        server = await self._create_named_server(user)
        raw_server_key = server._raw_api_key  # type: ignore[attr-defined]
        initial_version = server.api_key_version
        assert initial_version is not None

        # 1. Take child token from endpoint event of a real named server handshake
        child_token = await self._handshake_sse(
            f"/api/mcp/servers/{server.id}/sse",
            headers={"X-MCP-Key": raw_server_key},
        )

        # Child session works
        res = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 202)

        # 2. Regenerate named server key
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            regen_res = await regenerate_server_key(
                server_id=server.id, current_user=db_user, db=session
            )
            await session.commit()
            new_raw_server_key = regen_res.api_key
            db_server = await session.get(MCPServer, server.id)
            assert db_server is not None
            new_version = db_server.api_key_version

        self.assertNotEqual(initial_version, new_version)

        # 3. Old child session returns HTTP 401
        res_old_session = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_old_session.status_code, 401)

        # 4. Old server key cannot authenticate
        res_old_key = await self.http_client.get(
            f"/api/mcp/servers/{server.id}/sse",
            headers={"X-MCP-Key": raw_server_key},
        )
        self.assertEqual(res_old_key.status_code, 401)

        # 5. New server key and new child session work via real handshake
        new_child_token = await self._handshake_sse(
            f"/api/mcp/servers/{server.id}/sse",
            headers={"X-MCP-Key": new_raw_server_key},
        )
        res_new_session = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={new_child_token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res_new_session.status_code, 202)

    async def test_concurrent_handshakes_with_empty_version_agree(self) -> None:
        """With api_key_version NULL, concurrent handshakes agree on the same version via COALESCE."""
        import asyncio

        raw_key = f"mcp-{uuid.uuid4().hex}"
        user_id = uuid.uuid4()
        self.user_ids.append(user_id)
        async with async_session_maker() as session:
            user = User(
                id=user_id,
                email=f"mcp_user_{user_id.hex[:8]}@example.com",
                name="MCP User",
                hashed_password=hash_password(TEST_PASSWORD),
                mcp_api_key=hash_secret(raw_key),
                mcp_api_key_version=None,  # Empty version
                is_active=True,
            )
            session.add(user)
            await session.commit()

        # Run 4 concurrent handshakes
        tokens = await asyncio.gather(
            self._handshake_sse("/api/mcp/sse", headers={"X-MCP-Key": raw_key}),
            self._handshake_sse("/api/mcp/sse", headers={"X-MCP-Key": raw_key}),
            self._handshake_sse("/api/mcp/sse", headers={"X-MCP-Key": raw_key}),
            self._handshake_sse("/api/mcp/sse", headers={"X-MCP-Key": raw_key}),
        )

        decoded = [jwt.decode(t, options={"verify_signature": False}) for t in tokens]
        versions = [d.get("key_version") for d in decoded]
        self.assertTrue(all(v is not None for v in versions))
        # All 4 handshakes agreed on the exact same version
        self.assertEqual(len(set(versions)), 1)

        # All 4 sessions can successfully deliver messages without 401
        for token in tokens:
            res = await self.http_client.post(
                f"/api/mcp/message?session={token}",
                json=PING_PAYLOAD,
            )
            self.assertEqual(res.status_code, 202)


class TestTransportRestrictionsAndRenewal(_BaseMCPChildSessionCase):
    """Section C: Transport restrictions and session renewal."""

    async def test_transport_restrictions(self) -> None:
        user = await self._create_user()
        server = await self._create_named_server(user)
        default_child = mcp_session_store.create(str(user.id), auth_source="oauth")
        named_child = mcp_session_store.create(
            str(user.id), server_id=str(server.id), auth_source="oauth"
        )

        # GET /sse?session=<child-token> returns 401
        res_sse = await self.http_client.get(f"/api/mcp/sse?session={default_child}")
        self.assertEqual(res_sse.status_code, 401)

        # POST /api/mcp?session=<child-token> returns 401
        res_stream = await self.http_client.post(
            f"/api/mcp?session={default_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res_stream.status_code, 401)

        # Named server GET /sse?session=<child-token> returns 401
        res_named_sse = await self.http_client.get(
            f"/api/mcp/servers/{server.id}/sse?session={named_child}"
        )
        self.assertEqual(res_named_sse.status_code, 401)

        # Named server POST /api/mcp/servers/{id}/mcp?session=<child-token> returns 401
        res_named_stream = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/mcp?session={named_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res_named_stream.status_code, 401)

        # Child token cannot mint another child token via Bearer header
        res_bearer_mint = await self.http_client.get(
            "/api/mcp/sse",
            headers={"Authorization": f"Bearer {default_child}"},
        )
        self.assertEqual(res_bearer_mint.status_code, 401)

    async def test_handshake_refuses_when_auth_source_missing(self) -> None:
        from fastapi import HTTPException

        from app.api.mcp import mcp_sse_endpoint
        from app.api.mcp_servers import named_server_sse

        user = await self._create_user()
        server = await self._create_named_server(user)

        # 1. Plain GET without authentication fails
        res = await self.http_client.get("/api/mcp/sse")
        self.assertEqual(res.status_code, 401)

        res_named = await self.http_client.get(f"/api/mcp/servers/{server.id}/sse")
        self.assertEqual(res_named.status_code, 401)

        # 2. Handshake refuses to mint when auth_source is missing instead of defaulting to oauth
        req = MagicMock()
        req.state.mcp_auth_source = None
        req.headers.get = MagicMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await mcp_sse_endpoint(request=req, mcp_user=user)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Missing authentication source")

        with self.assertRaises(HTTPException) as ctx_named:
            await named_server_sse(server_id=server.id, request=req, server=(user, server))
        self.assertEqual(ctx_named.exception.status_code, 401)
        self.assertEqual(ctx_named.exception.detail, "Missing authentication source")

    async def test_original_credentials_can_establish_sessions(self) -> None:
        user = await self._create_user()
        server = await self._create_named_server(user)
        oauth_tokens = await self._create_oauth_tokens(user)
        raw_oauth_token = oauth_tokens["access_token"]
        raw_mcp_key = user._raw_mcp_key  # type: ignore[attr-defined]
        raw_server_key = server._raw_api_key  # type: ignore[attr-defined]

        # Default server with Bearer OAuth token
        async with self._stream_sse(
            "/api/mcp/sse",
            headers={"Authorization": f"Bearer {raw_oauth_token}"},
        ) as res_oauth:
            self.assertEqual(res_oauth.status_code, 200)

        # Default server with X-MCP-Key
        async with self._stream_sse(
            "/api/mcp/sse",
            headers={"X-MCP-Key": raw_mcp_key},
        ) as res_key:
            self.assertEqual(res_key.status_code, 200)

        # Named server with Bearer OAuth token
        async with self._stream_sse(
            f"/api/mcp/servers/{server.id}/sse",
            headers={"Authorization": f"Bearer {raw_oauth_token}"},
        ) as res_named_oauth:
            self.assertEqual(res_named_oauth.status_code, 200)

        # Named server with X-MCP-Key
        async with self._stream_sse(
            f"/api/mcp/servers/{server.id}/sse",
            headers={"X-MCP-Key": raw_server_key},
        ) as res_named_key:
            self.assertEqual(res_named_key.status_code, 200)


class TestOAuthRefreshCompatibility(_BaseMCPChildSessionCase):
    """Section D: Normal OAuth refresh does NOT invalidate existing child sessions."""

    async def test_child_session_survives_oauth_refresh(self) -> None:
        user = await self._create_user()
        server = await self._create_named_server(user)
        tokens = await self._create_oauth_tokens(user)
        refresh_token = tokens["refresh_token"]
        client_id = self.client_ids[-1]

        # Open child sessions for default and named servers
        default_child = mcp_session_store.create(str(user.id), auth_source="oauth")
        mcp_sse_channels.register(default_child)

        named_child = mcp_session_store.create(
            str(user.id), server_id=str(server.id), auth_source="oauth"
        )
        mcp_sse_channels.register(named_child)

        # Verify initial child sessions work
        res1 = await self.http_client.post(
            f"/api/mcp/message?session={default_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res1.status_code, 202)
        res2 = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={named_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res2.status_code, 202)

        # Perform OAuth refresh grant
        async with async_session_maker() as session:
            refreshed = await _handle_refresh_token_grant(
                request=_request_stub(),
                form={"refresh_token": refresh_token, "client_id": client_id},
                db=session,
            )
            await session.commit()
            self.assertIn("access_token", refreshed)

        # Verify user.sessions_revoked_at was NOT set
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            assert db_user is not None
            self.assertIsNone(db_user.sessions_revoked_at)

        # Verify both child sessions STILL work
        res_after1 = await self.http_client.post(
            f"/api/mcp/message?session={default_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res_after1.status_code, 202)

        res_after2 = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={named_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res_after2.status_code, 202)


class TestAccountDeactivation(_BaseMCPChildSessionCase):
    """Section E: Account deactivation terminates child sessions immediately."""

    async def test_deactivation_terminates_child_sessions(self) -> None:
        user = await self._create_user()
        admin = await self._create_admin()
        server = await self._create_named_server(user)

        default_child = mcp_session_store.create(str(user.id), auth_source="oauth")
        mcp_sse_channels.register(default_child)

        named_child = mcp_session_store.create(
            str(user.id),
            server_id=str(server.id),
            auth_source="api_key",
            key_version=server.api_key_version,
        )
        mcp_sse_channels.register(named_child)

        # Child sessions initially work
        self.assertEqual(
            (
                await self.http_client.post(
                    f"/api/mcp/message?session={default_child}", json=PING_PAYLOAD
                )
            ).status_code,
            202,
        )
        self.assertEqual(
            (
                await self.http_client.post(
                    f"/api/mcp/servers/{server.id}/message?session={named_child}", json=PING_PAYLOAD
                )
            ).status_code,
            202,
        )

        # Admin deactivates user
        with (
            patch.object(settings, "admin_emails", admin.email),
            patch("app.api.admin_users.set_owner_triggers_paused", return_value=0),
        ):
            async with async_session_maker() as session:
                db_admin = await session.get(User, admin.id)
                assert db_admin is not None
                await admin_users.deactivate_user(
                    user_id=user.id,
                    current_user=db_admin,
                    db=session,
                )
                await session.commit()

        # Both child sessions immediately return HTTP 401
        res1 = await self.http_client.post(
            f"/api/mcp/message?session={default_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res1.status_code, 401)

        res2 = await self.http_client.post(
            f"/api/mcp/servers/{server.id}/message?session={named_child}", json=PING_PAYLOAD
        )
        self.assertEqual(res2.status_code, 401)


class TestTokenClaimValidation(_BaseMCPChildSessionCase):
    """Section F: Strict token claim validation and failing closed."""

    def _encode_token(self, payload: dict[str, Any]) -> str:
        return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

    async def test_missing_iat_rejected(self) -> None:
        user = await self._create_user()
        token = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "source": "oauth",
                # "iat" omitted
            }
        )
        mcp_sse_channels.register(token)
        res = await self.http_client.post(f"/api/mcp/message?session={token}", json=PING_PAYLOAD)
        self.assertEqual(res.status_code, 401)

    async def test_missing_source_rejected(self) -> None:
        user = await self._create_user()
        token = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                # "source" omitted
            }
        )
        mcp_sse_channels.register(token)
        res = await self.http_client.post(f"/api/mcp/message?session={token}", json=PING_PAYLOAD)
        self.assertEqual(res.status_code, 401)

    async def test_api_key_missing_key_version_rejected(self) -> None:
        user = await self._create_user()
        token = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                "source": "api_key",
                # "key_version" omitted
            }
        )
        mcp_sse_channels.register(token)
        res = await self.http_client.post(f"/api/mcp/message?session={token}", json=PING_PAYLOAD)
        self.assertEqual(res.status_code, 401)

    async def test_api_key_incorrect_key_version_rejected(self) -> None:
        user = await self._create_user()
        token = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                "source": "api_key",
                "key_version": "completely-wrong-version",
            }
        )
        mcp_sse_channels.register(token)
        res = await self.http_client.post(f"/api/mcp/message?session={token}", json=PING_PAYLOAD)
        self.assertEqual(res.status_code, 401)

    async def test_expired_token_rejected(self) -> None:
        user = await self._create_user()
        token = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) - 60,  # Expired
                "iat": time.time() - 3600,
                "source": "oauth",
            }
        )
        mcp_sse_channels.register(token)
        res = await self.http_client.post(f"/api/mcp/message?session={token}", json=PING_PAYLOAD)
        self.assertEqual(res.status_code, 401)

    async def test_invalid_token_type_rejected(self) -> None:
        user = await self._create_user()
        token = self._encode_token(
            {
                "sub": str(user.id),
                "type": "access",  # Wrong type
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                "source": "oauth",
            }
        )
        mcp_sse_channels.register(token)
        res = await self.http_client.post(f"/api/mcp/message?session={token}", json=PING_PAYLOAD)
        self.assertEqual(res.status_code, 401)

    async def test_named_server_binding_mismatch_rejected(self) -> None:
        user = await self._create_user()
        server1 = await self._create_named_server(user)
        server2 = await self._create_named_server(user)

        # Token created for server1
        token = mcp_session_store.create(
            str(user.id), server_id=str(server1.id), auth_source="oauth"
        )
        mcp_sse_channels.register(token)

        # Presented on server2 message route -> must return HTTP 403
        res = await self.http_client.post(
            f"/api/mcp/servers/{server2.id}/message?session={token}",
            json=PING_PAYLOAD,
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("not valid for this server", res.text)

    async def test_no_secret_or_digest_in_child_token_payload(self) -> None:
        raw_key = f"mcp-super-secret-key-{uuid.uuid4().hex}"
        key_digest = hash_secret(raw_key)
        version = secrets.token_hex(16)
        user = await self._create_user(mcp_key=raw_key, key_version=version)

        token = mcp_session_store.create(str(user.id), auth_source="api_key", key_version=version)
        decoded = jwt.decode(token, options={"verify_signature": False})

        # Ensure raw key and key hash are completely absent from payload
        token_str = str(decoded)
        self.assertNotIn(raw_key, token_str)
        self.assertNotIn(key_digest, token_str)
        self.assertNotIn(user.hashed_password, token_str)
        self.assertEqual(decoded.get("key_version"), version)
        self.assertEqual(decoded.get("source"), "api_key")

    async def test_alias_claims_rejected(self) -> None:
        """Alias claims (src, auth_source, key_generation, kgid, ckv) are rejected; only source and key_version are accepted."""
        user = await self._create_user()

        # Token with 'src' instead of 'source'
        token_src = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                "src": "oauth",
            }
        )
        self.assertIsNone(mcp_session_store.resolve(token_src))

        # Token with 'auth_source' instead of 'source'
        token_auth_source = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                "auth_source": "oauth",
            }
        )
        self.assertIsNone(mcp_session_store.resolve(token_auth_source))

        # Token with 'key_generation' instead of 'key_version'
        token_key_gen = self._encode_token(
            {
                "sub": str(user.id),
                "type": "mcp_child_session",
                "jti": secrets.token_urlsafe(16),
                "exp": int(time.time()) + 3600,
                "iat": time.time(),
                "source": "api_key",
                "key_generation": "gen-123",
            }
        )
        self.assertIsNone(mcp_session_store.resolve(token_key_gen))
