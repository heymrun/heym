"""The Heym Work channel: key check, handshake, sign-in, refresh, audit."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.work_channel import (
    channel_audit,
    channel_login,
    channel_refresh,
    handshake,
    require_work_channel,
)
from app.models.schemas import UserLogin
from app.models.work_integration_schemas import (
    WorkAuditRequest,
    WorkHandshakeRequest,
    WorkRefreshRequest,
)
from app.services.auth import create_refresh_token, decode_token
from app.services.secret_tokens import hash_secret
from app.services.work_integration import WorkTokens, key_version

KEY = "hwi_" + "k" * 43


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Request:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.client = SimpleNamespace(host="203.0.113.7")
        self.cookies: dict[str, str] = {}


def _row(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = dict(
        enabled=True,
        work_url="https://work.acme.example",
        key_hash=hash_secret(KEY),
        handshake_nonce=None,
        handshake_at=None,
        last_seen_at=None,
        last_work_version="",
        last_license_status="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class ChannelKeyTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, row: SimpleNamespace, headers: dict[str, str]) -> object:
        with patch("app.api.work_channel.get_work_integration", AsyncMock(return_value=row)):
            return await require_work_channel(_Request(headers), db=AsyncMock())

    async def test_valid_key_passes(self) -> None:
        row = _row()
        self.assertIs(await self._check(row, {"X-Heym-Work-Key": KEY}), row)

    async def test_stored_digest_is_refused(self) -> None:
        row = _row()
        with self.assertRaises(HTTPException) as ctx:
            await self._check(row, {"X-Heym-Work-Key": row.key_hash})
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_missing_key_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._check(_row(), {})
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_disabled_integration_refuses_a_valid_key(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._check(_row(enabled=False), {"X-Heym-Work-Key": KEY})
        self.assertEqual(ctx.exception.status_code, 401)


class HandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_records_the_nonce_and_reports_policy(self) -> None:
        row = _row()
        db = AsyncMock()
        sso = SimpleNamespace(
            enabled=True,
            issuer="https://idp.acme.example",
            client_id="heym",
            password_login_disabled=True,
            button_label="Sign in with Acme",
        )
        body = WorkHandshakeRequest(
            nonce="n" * 20,
            work_version="1.0.0",
            install_id=str(uuid.uuid4()),
            license_status="active",
        )
        with (
            patch("app.api.work_channel.get_sso_settings", AsyncMock(return_value=sso)),
            patch("app.api.work_channel.settings") as settings,
        ):
            settings.resolved_version = "0.0.131"
            settings.allow_register = True
            response = await handshake(body, row=row, db=db)

        self.assertEqual(row.handshake_nonce, "n" * 20)
        self.assertEqual(row.last_work_version, "1.0.0")
        self.assertEqual(response.password_login, "admins_only")
        self.assertFalse(response.registration_allowed)
        self.assertTrue(response.sso_enabled)
        self.assertEqual(response.heym_version, "0.0.131")
        db.commit.assert_awaited()


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def _login(self, headers: dict[str, str]) -> tuple[object, AsyncMock]:
        user = SimpleNamespace(id=uuid.uuid4(), email="ada@acme.example", name="Ada")
        sign_in = AsyncMock(return_value=user)
        with (
            patch("app.api.work_channel.password_sign_in", sign_in),
            patch(
                "app.api.work_channel.issue_work_tokens",
                AsyncMock(return_value=WorkTokens(access_token="a" * 20, refresh_token="r" * 20)),
            ),
        ):
            response = await channel_login(
                UserLogin(email="ada@acme.example", password="hunter2"),
                _Request(headers),
                row=_row(),
                db=AsyncMock(),
            )
        return response, sign_in

    async def test_login_uses_the_forwarded_ip_and_returns_bound_tokens(self) -> None:
        response, sign_in = await self._login({"X-Heym-Work-Client-IP": "198.51.100.9"})

        self.assertEqual(sign_in.await_args.args[2], "198.51.100.9")
        self.assertEqual(sign_in.await_args.kwargs["client"], "work")
        self.assertEqual(response.user.email, "ada@acme.example")
        self.assertEqual(response.access_token, "a" * 20)

    async def test_invalid_forwarded_ip_falls_back_to_the_peer(self) -> None:
        _, sign_in = await self._login({"X-Heym-Work-Client-IP": "not-an-ip"})
        self.assertEqual(sign_in.await_args.args[2], "203.0.113.7")


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_refresh_token_is_refused(self) -> None:
        token = create_refresh_token(uuid.uuid4())
        with self.assertRaises(HTTPException) as ctx:
            await channel_refresh(
                WorkRefreshRequest(refresh_token=token), row=_row(), db=AsyncMock()
            )
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_token_from_a_rotated_key_is_refused(self) -> None:
        token = create_refresh_token(uuid.uuid4(), client="work", key_version="000000000000")
        with self.assertRaises(HTTPException) as ctx:
            await channel_refresh(
                WorkRefreshRequest(refresh_token=token), row=_row(), db=AsyncMock()
            )
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_refresh_rotates_and_returns_a_bound_pair(self) -> None:
        row = _row()
        user = SimpleNamespace(
            id=uuid.uuid4(),
            email="ada@acme.example",
            name="Ada",
            is_active=True,
            hashed_password="x",
            sso_subject=None,
        )
        token = create_refresh_token(user.id, client="work", key_version=key_version(row.key_hash))
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(user))
        with patch("app.api.work_channel.rotate_refresh_token", AsyncMock(return_value=True)):
            response = await channel_refresh(
                WorkRefreshRequest(refresh_token=token), row=row, db=db
            )

        payload = decode_token(response.access_token)
        self.assertEqual(payload["cli"], "work")
        self.assertEqual(payload["ckv"], key_version(row.key_hash))


class AuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_audit_is_emitted_with_source_work(self) -> None:
        with patch("app.api.work_channel.audit") as audit:
            await channel_audit(
                WorkAuditRequest(
                    action="work.role_change", actor_id="u-1", detail={"new_role": "editor"}
                ),
                row=_row(),
            )

        kwargs = audit.call_args.kwargs
        self.assertEqual(kwargs["action"], "work.role_change")
        self.assertEqual(kwargs["source"], "work")
        self.assertEqual(kwargs["new_role"], "editor")

    def test_non_work_actions_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            WorkAuditRequest(action="auth.login")

    def test_reserved_detail_keys_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            WorkAuditRequest(action="work.setup_change", detail={"action": "spoof"})
