"""Accepted second factors refund admission; failed factors retain the shared budget."""

import unittest
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.api import auth, auth_mfa, oauth
from app.models.schemas import MfaCodeRequest, MfaEnableRequest, MfaLoginRequest, MfaSetupRequest
from app.services import mfa
from app.services.shared_rate_limiter import SharedRateLimiter


class MfaRateLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(
            id=uuid.uuid4(), is_active=True, hashed_password="hash", email="test@example.com"
        )
        self.db = AsyncMock()
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=self.user))
        self.db.get.return_value = self.user
        self.limiter = SharedRateLimiter("test_mfa", 5, 300, 900)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch("app.services.shared_rate_limiter.time.time", return_value=1_700_000_000.0)
        )
        self.stack.enter_context(patch.object(mfa, "mfa_limiter", self.limiter))
        self.stack.enter_context(patch.object(auth_mfa.settings, "require_mfa", True))
        self.stack.enter_context(patch.object(auth_mfa, "verify_password", return_value=True))
        self.stack.enter_context(patch.object(mfa, "mfa_enabled", return_value=True))
        self.stack.enter_context(patch.object(mfa, "read_setup_secret", return_value="secret"))
        self.factor = self.stack.enter_context(
            patch.object(mfa, "verify_second_factor", new=AsyncMock(return_value="totp"))
        )
        self.enable = self.stack.enter_context(
            patch.object(mfa, "enable_mfa", new=AsyncMock(return_value=["recovery-code"]))
        )
        self.stack.enter_context(
            patch.object(mfa, "regenerate_recovery_codes", new=AsyncMock(return_value=["new-code"]))
        )
        self.stack.enter_context(
            patch.object(
                mfa,
                "create_setup_offer",
                return_value=SimpleNamespace(
                    setup_token="setup", secret="secret", otpauth_uri="uri", qr_code="qr"
                ),
            )
        )

    async def _call(self, path: str) -> object:
        if path in ("enroll", "verify", "consent"):
            claims = SimpleNamespace(
                user_id=self.user.id,
                client="oauth:client" if path == "consent" else None,
                purpose=mfa.PURPOSE_ENROLL if path == "enroll" else mfa.PURPOSE_VERIFY,
            )
            with patch.object(mfa, "read_challenge_token", return_value=claims):
                if path == "consent":
                    return await oauth._verify_consent_second_factor(
                        self.db, "challenge", "123456", "client"
                    )
                with patch.object(mfa, "mfa_enabled", return_value=path != "enroll"):
                    return await auth.mfa_sign_in(
                        self.db,
                        MfaLoginRequest(
                            challenge_token="challenge", code="123456", setup_token="setup"
                        ),
                        client=None,
                    )
        if path == "setup":
            return await auth_mfa.mfa_setup(
                MfaSetupRequest(password="password", code="123456"), self.user, self.db
            )
        if path == "enable":
            return await auth_mfa.mfa_enable(
                MfaEnableRequest(setup_token="setup", code="123456"), self.user, self.db
            )
        return await auth_mfa.mfa_regenerate_recovery_codes(
            MfaCodeRequest(code="123456"), self.user, self.db
        )

    async def test_accepted_factors_do_not_exhaust_budget(self) -> None:
        for path in ("enroll", "verify", "consent", "setup", "enable", "recovery"):
            with self.subTest(path=path):
                self.user.id = uuid.uuid4()
                for _ in range(6):
                    self.assertIsNotNone(await self._call(path))
                self.assertEqual(self.limiter.is_allowed(str(self.user.id)), (True, 0))

    async def test_recovery_factor_also_refunds(self) -> None:
        self.factor.return_value = "recovery"
        for _ in range(6):
            await self._call("verify")
        self.assertEqual(self.limiter.is_allowed(str(self.user.id)), (True, 0))

    async def test_wrong_factors_still_reach_ban_on_every_path(self) -> None:
        self.factor.return_value = None
        self.enable.return_value = None
        for path in ("enroll", "verify", "consent", "setup", "enable", "recovery"):
            with self.subTest(path=path):
                self.user.id = uuid.uuid4()
                for _ in range(5):
                    if path == "consent":
                        self.assertIsNone(await self._call(path))
                    else:
                        with self.assertRaises(HTTPException) as error:
                            await self._call(path)
                        self.assertIn(error.exception.status_code, (400, 401))
                if path == "consent":
                    self.assertIsNone(await self._call(path))
                else:
                    with self.assertRaises(HTTPException) as error:
                        await self._call(path)
                    self.assertEqual(error.exception.status_code, 429)
                    self.assertEqual(error.exception.headers["Retry-After"], "900")
                self.assertEqual(self.limiter.is_allowed(str(self.user.id)), (False, 900))

    async def test_password_only_setup_does_not_refund(self) -> None:
        with patch.object(mfa, "mfa_enabled", return_value=False):
            for _ in range(5):
                await self._call("setup")
            with self.assertRaises(HTTPException) as error:
                await self._call("setup")
        self.assertEqual(error.exception.status_code, 429)
        self.factor.assert_not_awaited()

    async def test_success_does_not_clear_previous_failures(self) -> None:
        self.factor.return_value = None
        for _ in range(4):
            with self.assertRaises(HTTPException):
                await self._call("verify")
        self.factor.return_value = "totp"
        await self._call("verify")
        self.factor.return_value = None
        with self.assertRaises(HTTPException) as error:
            await self._call("verify")
        self.assertEqual(error.exception.status_code, 401)
        with self.assertRaises(HTTPException) as error:
            await self._call("verify")
        self.assertEqual(error.exception.status_code, 429)
