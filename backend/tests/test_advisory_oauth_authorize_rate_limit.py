"""The OAuth consent form signs passwords in through the same gate as /api/auth/login.

POST /authorize used to check the email and password on its own, without the login
limiter, so one IP could guess a password without limit. Its password branch now goes
through ``password_sign_in()``: the two doors share one per-IP budget, the SSO-only rule
and the ``auth.login`` audit line. The code step after a correct password stays on the
per-user ``mfa_limiter`` alone.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

import bcrypt
from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from app.api import auth
from app.api.oauth import _generate_csrf_token, authorize_post
from app.db.models import OAuthAuthorizationCode, OAuthClient, SsoSettings, User
from app.models.schemas import UserLogin
from app.services import mfa
from app.services.account_status import DEACTIVATED_DETAIL
from app.services.shared_rate_limiter import SharedRateLimiter

CLIENT_ID = "confidential-client"
REDIRECT_URI = "https://client.example/callback"
VICTIM_EMAIL = "victim@example.com"
PASSWORD = "Correct1horse"
WRONG_PASSWORD = "Summer2024"
ATTACKER_IP = "203.0.113.7"
OTHER_IP = "198.51.100.20"
# The numbers of app.services.auth_rate_limiter.login_limiter.
LOGIN_MAX_ATTEMPTS = 10
# A real bcrypt hash at the lowest cost, so a dozen guesses per test stay fast while the
# real verify_password runs wherever the code under test calls it.
STORED_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


def _fresh_login_limiter() -> SharedRateLimiter:
    return SharedRateLimiter(
        namespace="auth_login",
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=60,
        ban_seconds=900,
    )


def _open_sso_row() -> SimpleNamespace:
    """An instance with SSO switched off, so password sign-in stays open."""
    return SimpleNamespace(enabled=False, issuer="", client_id="", password_login_disabled=False)


def _sso_only_row() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        issuer="https://idp.example/realms/heym",
        client_id="heym",
        password_login_disabled=True,
    )


def _victim(*, is_active: bool = True, mfa_on: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=VICTIM_EMAIL,
        hashed_password=STORED_HASH,
        is_active=is_active,
        mfa_enabled_at=datetime.now(timezone.utc) if mfa_on else None,
        mfa_secret="JBSWY3DPEHPK3PXP" if mfa_on else None,
    )


def _db(user: SimpleNamespace | None, sso_row: SimpleNamespace | None = None) -> AsyncMock:
    """A session that answers by the queried model, so the lookup order does not matter."""
    client = SimpleNamespace(
        client_id=CLIENT_ID,
        client_name="Client",
        redirect_uris=[REDIRECT_URI],
        is_confidential=True,
    )
    rows = {OAuthClient: client, SsoSettings: sso_row or _open_sso_row(), User: user}

    async def execute(statement: object, *_args: object, **_kwargs: object) -> MagicMock:
        entity = statement.column_descriptions[0]["entity"]
        return MagicMock(scalar_one_or_none=MagicMock(return_value=rows[entity]))

    async def get(model: type, ident: object) -> object:
        if model is User and user is not None and user.id == ident:
            return user
        return None

    db = AsyncMock()
    db.added = []
    db.execute = AsyncMock(side_effect=execute)
    db.get = AsyncMock(side_effect=get)
    db.add = MagicMock(side_effect=db.added.append)
    db.flush = AsyncMock()
    return db


def _request(ip: str, data: dict[str, str] | None = None, path: str = "/authorize") -> Request:
    body = urlencode(data or {}).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", b"application/x-www-form-urlencoded")] if data else []
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "query_string": b"",
            "client": (ip, 51234),
        },
        receive,
    )


def _issued_codes(db: AsyncMock) -> list[OAuthAuthorizationCode]:
    return [obj for obj in db.added if isinstance(obj, OAuthAuthorizationCode)]


class _ConsentCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # A fresh limiter per test: the module singleton would carry bans across tests.
        self.limiter = _fresh_login_limiter()
        patches = [
            patch.object(auth, "login_limiter", self.limiter),
            patch.object(mfa.settings, "require_mfa", False),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def consent(
        self,
        db: AsyncMock,
        *,
        email: str = VICTIM_EMAIL,
        password: str = PASSWORD,
        ip: str = ATTACKER_IP,
        extra: dict[str, str] | None = None,
    ) -> Response:
        data = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": "mcp",
            "state": "s",
            "csrf_token": _generate_csrf_token(CLIENT_ID),
            "email": email,
            "password": password,
            **(extra or {}),
        }
        return await authorize_post(request=_request(ip, data), db=db)

    async def api_login(self, db: AsyncMock, *, password: str, ip: str = ATTACKER_IP) -> None:
        await auth.login(
            user_data=UserLogin(email=VICTIM_EMAIL, password=password),
            request=_request(ip, path="/api/auth/login"),
            response=Response(),
            db=db,
        )

    def assert_consent_page(self, response: Response, status_code: int, message: str) -> None:
        self.assertIsInstance(response, HTMLResponse)
        self.assertEqual(response.status_code, status_code)
        body = response.body.decode()
        self.assertIn(message, body)
        self.assertIn('<form method="POST" action="/authorize">', body)
        self.assertNotIn("location", response.headers)


class ConsentSharesTheLoginBudgetTests(_ConsentCase):
    async def test_a_correct_password_under_the_limit_still_issues_a_code(self) -> None:
        db = _db(_victim())

        response = await self.consent(db)

        self.assertEqual(response.status_code, 302)
        (code,) = _issued_codes(db)
        location = urlparse(response.headers["location"])
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}", REDIRECT_URI)
        self.assertEqual(parse_qs(location.query)["code"], [code.code])

    async def test_after_the_limit_the_correct_password_gets_no_code(self) -> None:
        db = _db(_victim())
        for _ in range(LOGIN_MAX_ATTEMPTS):
            wrong = await self.consent(db, password=WRONG_PASSWORD)
            self.assert_consent_page(wrong, 400, "Invalid email or password")

        response = await self.consent(db)

        self.assert_consent_page(response, 429, "Too many login attempts. Try again later.")
        self.assertEqual(response.headers["retry-after"], "900")
        self.assertIn('name="password"', response.body.decode())
        self.assertEqual(_issued_codes(db), [])

    async def test_a_ban_earned_on_api_auth_login_blocks_the_consent_page(self) -> None:
        db = _db(_victim())
        for _ in range(LOGIN_MAX_ATTEMPTS):
            with self.assertRaises(HTTPException) as wrong:
                await self.api_login(db, password=WRONG_PASSWORD)
            self.assertEqual(wrong.exception.status_code, 401)
        with self.assertRaises(HTTPException) as banned:
            await self.api_login(db, password=WRONG_PASSWORD)
        self.assertEqual(banned.exception.status_code, 429)

        response = await self.consent(db)

        self.assert_consent_page(response, 429, "Too many login attempts. Try again later.")
        self.assertEqual(_issued_codes(db), [])

    async def test_a_ban_earned_on_the_consent_page_blocks_api_auth_login(self) -> None:
        db = _db(_victim())
        for _ in range(LOGIN_MAX_ATTEMPTS + 1):
            await self.consent(db, password=WRONG_PASSWORD)

        with self.assertRaises(HTTPException) as ctx:
            await self.api_login(db, password=PASSWORD)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)

    async def test_the_budget_is_kept_per_client_ip(self) -> None:
        db = _db(_victim())
        for _ in range(LOGIN_MAX_ATTEMPTS + 1):
            await self.consent(db, password=WRONG_PASSWORD, ip=ATTACKER_IP)

        response = await self.consent(db, ip=OTHER_IP)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(_issued_codes(db)), 1)


class ConsentMfaBranchTests(_ConsentCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(mfa.settings, "require_mfa", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mfa_limiter = SharedRateLimiter(namespace="mfa_test")
        mfa_patcher = patch.object(mfa, "mfa_limiter", self.mfa_limiter)
        mfa_patcher.start()
        self.addCleanup(mfa_patcher.stop)

    async def test_the_password_step_spends_one_attempt_and_asks_for_the_code(self) -> None:
        db = _db(_victim(mfa_on=True))

        with patch.object(self.limiter, "is_allowed", wraps=self.limiter.is_allowed) as spy:
            response = await self.consent(db)

        self.assert_consent_page(response, 400, "Enter the code from your authenticator app.")
        self.assertIn('name="mfa_challenge"', response.body.decode())
        spy.assert_called_once_with(ATTACKER_IP)
        self.assertEqual(_issued_codes(db), [])

    async def test_the_code_step_does_not_touch_the_login_limiter(self) -> None:
        user = _victim(mfa_on=True)
        db = _db(user)
        challenge = mfa.create_challenge_token(
            user.id, mfa.PURPOSE_VERIFY, client=f"oauth:{CLIENT_ID}"
        )
        code_step = {"mfa_challenge": challenge, "email": "", "password": ""}

        verify = AsyncMock(side_effect=[None, "totp"])
        with (
            patch.object(mfa, "verify_second_factor", verify),
            patch.object(self.limiter, "is_allowed", wraps=self.limiter.is_allowed) as spy,
        ):
            wrong = await self.consent(db, extra={**code_step, "code": "000000"})
            right = await self.consent(db, extra={**code_step, "code": "123456"})

        self.assert_consent_page(wrong, 400, "That code is not valid, or the attempt expired.")
        self.assertEqual(right.status_code, 302)
        self.assertEqual(len(_issued_codes(db)), 1)
        spy.assert_not_called()


class ConsentInputAndAuditTests(_ConsentCase):
    async def test_a_malformed_email_returns_the_consent_page_not_a_500(self) -> None:
        db = _db(_victim())

        response = await self.consent(db, email="not-an-email")

        self.assert_consent_page(response, 400, "Invalid email or password")
        self.assertIn('name="email"', response.body.decode())
        self.assertEqual(_issued_codes(db), [])

    async def test_a_failed_attempt_writes_an_auth_login_failure_line(self) -> None:
        db = _db(_victim())

        with self.assertLogs("winston.audit", level="INFO") as captured:
            await self.consent(db, password=WRONG_PASSWORD)

        (line,) = [record.getMessage() for record in captured.records]
        self.assertIn("action=auth.login", line)
        self.assertIn("outcome=failure", line)
        self.assertIn(f"actor_email={VICTIM_EMAIL}", line)
        self.assertIn("reason=bad_password", line)
        self.assertIn(f"client=oauth:{CLIENT_ID}", line)

    async def test_an_unknown_email_is_logged_and_refused_like_a_wrong_password(self) -> None:
        db = _db(None)

        with self.assertLogs("winston.audit", level="INFO") as captured:
            response = await self.consent(db, email="nobody@example.com")

        self.assert_consent_page(response, 400, "Invalid email or password")
        (line,) = [record.getMessage() for record in captured.records]
        self.assertIn("outcome=failure", line)
        self.assertIn("reason=unknown_email", line)

    async def test_an_sso_only_instance_refuses_the_password_with_the_login_message(
        self,
    ) -> None:
        db = _db(_victim(), sso_row=_sso_only_row())

        with self.assertLogs("winston.audit", level="INFO") as captured:
            response = await self.consent(db)

        self.assert_consent_page(
            response, 400, "Password sign-in is disabled on this instance. Use SSO."
        )
        self.assertEqual(_issued_codes(db), [])
        (line,) = [record.getMessage() for record in captured.records]
        self.assertIn("outcome=denied", line)
        self.assertIn("reason=password_login_disabled", line)
        self.assertIn(f"client=oauth:{CLIENT_ID}", line)

    async def test_a_deactivated_account_is_refused_after_a_correct_password(self) -> None:
        db = _db(_victim(is_active=False))

        response = await self.consent(db)

        self.assert_consent_page(response, 400, DEACTIVATED_DETAIL)
        self.assertEqual(_issued_codes(db), [])


if __name__ == "__main__":
    unittest.main()
