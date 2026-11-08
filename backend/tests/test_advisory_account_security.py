"""Two-factor sign-in, account deactivation, session revocation and data retention.

The negative cases are the point: a challenge is not a session, a used code does not work
twice, a stored recovery digest is not a code, and a deactivated or signed-out account is
refused by every credential it held.

The real-PostgreSQL tests require a reachable database with migrations applied, like every
other `RealPostgres*` test (see AGENTS.md, "PostgreSQL Integration Tests").
"""

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select

from app.api import admin_users
from app.api.auth import login, login_mfa, refresh_tokens
from app.api.deps import get_current_user
from app.api.mcp import get_mcp_user
from app.api.work_channel import channel_login, channel_login_mfa
from app.api.workflows import set_owner_triggers_paused
from app.config import settings
from app.db.models import (
    ExecutionHistory,
    HITLRequest,
    LLMTrace,
    RefreshToken,
    User,
    UserMfaRecoveryCode,
    Workflow,
)
from app.db.session import async_session_maker, engine
from app.models.schemas import MfaLoginRequest, TokenRefresh, UserLogin
from app.services import mfa
from app.services.account_status import meets_mfa_policy, token_still_valid
from app.services.auth import (
    SIGN_IN_MFA,
    SIGN_IN_PASSWORD,
    SIGN_IN_SSO,
    create_access_token,
    create_refresh_token,
    hash_password,
    read_access_claims,
    store_refresh_token,
)
from app.services.data_retention import apply_retention
from app.services.encryption import encrypt_text
from app.services.secret_tokens import hash_secret
from app.services.workflow_lifecycle import (
    ADMIN_PAUSE_MARKER,
    OWNER_DEACTIVATED_MARKER,
    set_automatic_triggers_paused,
)

PASSWORD = "Correct-horse-9"


def _request(ip: str = "198.51.100.10") -> SimpleNamespace:
    return SimpleNamespace(headers={}, cookies={}, query_params={}, client=SimpleNamespace(host=ip))


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _access_token_issued(user_id: uuid.UUID, seconds_ago: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "exp": now + timedelta(hours=1),
            "issued_at_ms": int((now.timestamp() - seconds_ago) * 1000),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


class TokenStillValidTests(unittest.TestCase):
    def test_an_inactive_account_refuses_every_token(self) -> None:
        self.assertFalse(token_still_valid(False, None, 10**10))

    def test_a_token_from_before_the_revocation_is_refused(self) -> None:
        revoked = datetime(2026, 11, 8, 12, 0, 0, 500000, tzinfo=timezone.utc)
        revoked_ms = int(revoked.timestamp() * 1000)
        # The same second, a moment earlier: whole seconds would have let it through.
        self.assertFalse(token_still_valid(True, revoked, revoked_ms - 200))
        self.assertTrue(token_still_valid(True, revoked, revoked_ms))
        self.assertTrue(token_still_valid(True, revoked, revoked_ms + 1))

    def test_a_token_without_issue_time_is_refused_once_sessions_were_revoked(self) -> None:
        self.assertTrue(token_still_valid(True, None, None))
        self.assertFalse(token_still_valid(True, datetime.now(timezone.utc), None))


class MfaSessionPolicyTests(unittest.TestCase):
    def _allowed(self, method: str | None, *, password: bool, sso: bool) -> bool:
        return meets_mfa_policy(method, has_password=password, has_sso_identity=sso)

    def test_every_session_continues_while_the_flag_is_off(self) -> None:
        with patch.object(settings, "require_mfa", False):
            self.assertTrue(self._allowed(SIGN_IN_PASSWORD, password=True, sso=False))
            self.assertTrue(self._allowed(None, password=True, sso=False))

    def test_turning_the_flag_on_ends_password_sessions_without_a_code(self) -> None:
        with patch.object(settings, "require_mfa", True):
            self.assertFalse(self._allowed(SIGN_IN_PASSWORD, password=True, sso=False))
            self.assertFalse(self._allowed(None, password=True, sso=False))
            self.assertTrue(self._allowed(SIGN_IN_MFA, password=True, sso=False))

    def test_sso_sessions_are_never_asked_for_a_code(self) -> None:
        with patch.object(settings, "require_mfa", True):
            self.assertTrue(self._allowed(SIGN_IN_SSO, password=True, sso=True))
            self.assertTrue(self._allowed(None, password=False, sso=True))
            self.assertTrue(self._allowed(None, password=True, sso=True))


class OwnerDeactivationMarkerTests(unittest.TestCase):
    def _nodes(self, *, active: bool, admin_paused: bool = False) -> list[dict]:
        data: dict = {"active": active}
        if admin_paused:
            data[ADMIN_PAUSE_MARKER] = True
        return [{"id": "cron", "type": "cron", "data": data}]

    def test_deactivation_pauses_and_reactivation_resumes(self) -> None:
        paused = set_automatic_triggers_paused(
            self._nodes(active=True), paused=True, marker=OWNER_DEACTIVATED_MARKER
        )
        self.assertFalse(paused[0]["data"]["active"])
        self.assertTrue(paused[0]["data"][OWNER_DEACTIVATED_MARKER])
        resumed = set_automatic_triggers_paused(
            paused, paused=False, marker=OWNER_DEACTIVATED_MARKER
        )
        self.assertTrue(resumed[0]["data"]["active"])
        self.assertNotIn(OWNER_DEACTIVATED_MARKER, resumed[0]["data"])

    def test_reactivation_leaves_an_administrator_pause_alone(self) -> None:
        nodes = self._nodes(active=False, admin_paused=True)
        paused = set_automatic_triggers_paused(nodes, paused=True, marker=OWNER_DEACTIVATED_MARKER)
        resumed = set_automatic_triggers_paused(
            paused, paused=False, marker=OWNER_DEACTIVATED_MARKER
        )
        self.assertFalse(resumed[0]["data"]["active"])
        self.assertTrue(resumed[0]["data"][ADMIN_PAUSE_MARKER])

    def test_an_owner_resume_never_turns_on_a_trigger_that_was_already_off(self) -> None:
        nodes = self._nodes(active=False)
        paused = set_automatic_triggers_paused(nodes, paused=True, marker=OWNER_DEACTIVATED_MARKER)
        resumed = set_automatic_triggers_paused(
            paused, paused=False, marker=OWNER_DEACTIVATED_MARKER
        )
        self.assertFalse(resumed[0]["data"]["active"])


class SetOwnerTriggersPausedTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_workflows_with_a_change_are_saved_through_update_workflow(self) -> None:
        owner_id = uuid.uuid4()
        with_trigger = SimpleNamespace(
            id=uuid.uuid4(),
            updated_at=datetime.now(timezone.utc),
            nodes=[{"id": "c", "type": "cron", "data": {"active": True}}],
        )
        without_trigger = SimpleNamespace(
            id=uuid.uuid4(), updated_at=None, nodes=[{"id": "l", "type": "llm", "data": {}}]
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [with_trigger, without_trigger])
            )
        )
        admin = SimpleNamespace(id=uuid.uuid4())
        with patch("app.api.workflows.update_workflow", AsyncMock()) as update:
            changed = await set_owner_triggers_paused(owner_id, True, admin, db)

        self.assertEqual(changed, 1)
        update.assert_awaited_once()
        saved = update.await_args.args[1].nodes
        self.assertFalse(saved[0]["data"]["active"])
        self.assertTrue(saved[0]["data"][OWNER_DEACTIVATED_MARKER])


class _RealUsers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.user_ids: list[uuid.UUID] = []

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.owner_id.in_(self.user_ids)))
            await session.execute(delete(User).where(User.id.in_(self.user_ids)))
            await session.commit()
        await engine.dispose()

    async def _user(self, *, enrolled: bool = False, mcp_key: str | None = None) -> User:
        user_id = uuid.uuid4()
        self.user_ids.append(user_id)
        async with async_session_maker() as session:
            user = User(
                id=user_id,
                email=f"acct_{user_id.hex[:10]}@example.com",
                name="Account",
                hashed_password=hash_password(PASSWORD),
                mcp_api_key=hash_secret(mcp_key) if mcp_key else None,
            )
            session.add(user)
            await session.flush()
            if enrolled:
                self.secret = mfa.generate_secret()
                user.mfa_secret = encrypt_text(self.secret)
                user.mfa_enabled_at = datetime.now(timezone.utc)
                self.recovery_codes = await mfa.regenerate_recovery_codes(session, user)
            await session.commit()
            await session.refresh(user)
            return user

    async def _login(self, user: User, ip: str) -> object:
        async with async_session_maker() as session:
            result = await login(
                UserLogin(email=user.email, password=PASSWORD), _request(ip), Response(), session
            )
            await session.commit()
            return result

    async def _answer(self, challenge: str, code: str, setup_token: str | None = None) -> object:
        async with async_session_maker() as session:
            result = await login_mfa(
                MfaLoginRequest(challenge_token=challenge, code=code, setup_token=setup_token),
                Response(),
                session,
            )
            await session.commit()
            return result


class RealPostgresMfaSignInTests(_RealUsers):
    async def test_flag_off_signs_in_with_the_password_alone(self) -> None:
        user = await self._user(enrolled=True)
        with patch.object(settings, "require_mfa", False):
            result = await self._login(user, "198.51.100.21")
        self.assertIsNotNone(result.access_token)
        self.assertIsNone(result.mfa)

    async def test_a_correct_password_yields_a_challenge_and_no_session(self) -> None:
        user = await self._user(enrolled=True)
        with patch.object(settings, "require_mfa", True):
            result = await self._login(user, "198.51.100.22")
        self.assertIsNone(result.access_token)
        self.assertIsNone(result.refresh_token)
        self.assertEqual(result.mfa.purpose, "verify")

        # The challenge is not a session anywhere a bearer token is accepted.
        async with async_session_maker() as session:
            with self.assertRaises(HTTPException) as raised:
                await get_current_user(_request(), _bearer(result.mfa.challenge_token), session)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_a_totp_code_finishes_the_sign_in_once(self) -> None:
        user = await self._user(enrolled=True)
        with patch.object(settings, "require_mfa", True):
            challenge = (await self._login(user, "198.51.100.23")).mfa.challenge_token
            code = mfa.code_at_step(self.secret, mfa.current_step())
            result = await self._answer(challenge, code)
            self.assertIsNotNone(result.access_token)
            with self.assertRaises(HTTPException) as raised:
                await self._answer(challenge, code)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_a_wrong_code_is_refused(self) -> None:
        user = await self._user(enrolled=True)
        with patch.object(settings, "require_mfa", True):
            challenge = (await self._login(user, "198.51.100.24")).mfa.challenge_token
            right = mfa.code_at_step(self.secret, mfa.current_step())
            wrong = str((int(right) + 1) % 10**6).zfill(6)
            with self.assertRaises(HTTPException) as raised:
                await self._answer(challenge, wrong)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_a_recovery_code_works_once_and_its_digest_never(self) -> None:
        user = await self._user(enrolled=True)
        code = self.recovery_codes[0]
        with patch.object(settings, "require_mfa", True):
            challenge = (await self._login(user, "198.51.100.25")).mfa.challenge_token
            stored_digest = hash_secret(mfa.normalize_recovery_code(code))
            with self.assertRaises(HTTPException):
                await self._answer(challenge, stored_digest[:32])
            self.assertIsNotNone((await self._answer(challenge, code.lower())).access_token)
            with self.assertRaises(HTTPException):
                await self._answer(challenge, code)
        async with async_session_maker() as session:
            remaining = await mfa.recovery_codes_remaining(session, user.id)
        self.assertEqual(remaining, mfa.RECOVERY_CODE_COUNT - 1)

    async def test_a_challenge_minted_for_heym_work_does_not_finish_a_web_sign_in(self) -> None:
        user = await self._user(enrolled=True)
        work_challenge = mfa.create_challenge_token(user.id, mfa.PURPOSE_VERIFY, client="work")
        with patch.object(settings, "require_mfa", True):
            with self.assertRaises(HTTPException) as raised:
                await self._answer(
                    work_challenge, mfa.code_at_step(self.secret, mfa.current_step())
                )
        self.assertEqual(raised.exception.status_code, 401)

    async def test_an_account_without_a_factor_enrols_before_any_session(self) -> None:
        user = await self._user()
        with patch.object(settings, "require_mfa", True):
            result = await self._login(user, "198.51.100.26")
            self.assertIsNone(result.access_token)
            self.assertEqual(result.mfa.purpose, "enroll")
            setup = result.mfa.setup
            secret = setup.secret
            # Without the setup token the enrolment cannot complete.
            with self.assertRaises(HTTPException):
                await self._answer(
                    result.mfa.challenge_token, mfa.code_at_step(secret, mfa.current_step())
                )
            done = await self._answer(
                result.mfa.challenge_token,
                mfa.code_at_step(secret, mfa.current_step()),
                setup.setup_token,
            )
        self.assertIsNotNone(done.access_token)
        self.assertEqual(len(done.recovery_codes), mfa.RECOVERY_CODE_COUNT)
        async with async_session_maker() as session:
            stored = await session.get(User, user.id)
            self.assertIsNotNone(stored.mfa_enabled_at)
            self.assertNotEqual(stored.mfa_secret, secret)
            hashes = (
                await session.execute(
                    select(UserMfaRecoveryCode.code_hash).where(
                        UserMfaRecoveryCode.user_id == user.id
                    )
                )
            ).scalars()
            self.assertNotIn(done.recovery_codes[0], set(hashes))


class RealPostgresWorkEnrolmentTests(_RealUsers):
    """Heym Work shows the QR code itself, so a Work-only user can enrol before any session."""

    async def test_work_enrols_an_account_without_an_authenticator(self) -> None:
        user = await self._user()
        row = SimpleNamespace(key_hash=hash_secret("work-key"))
        with patch.object(settings, "require_mfa", True):
            async with async_session_maker() as session:
                challenge = await channel_login(
                    UserLogin(email=user.email, password=PASSWORD),
                    _request("198.51.100.41"),
                    row,
                    session,
                )
            self.assertEqual(challenge.status_code, 401)
            body = json.loads(challenge.body)
            self.assertIn("qr_code", body["mfa_setup"])
            setup = body["mfa_setup"]
            async with async_session_maker() as session:
                result = await channel_login_mfa(
                    MfaLoginRequest(
                        challenge_token=body["mfa_challenge"],
                        code=mfa.code_at_step(setup["secret"], mfa.current_step()),
                        setup_token=setup["setup_token"],
                    ),
                    row,
                    session,
                )
                await session.commit()
        self.assertTrue(result.access_token)
        self.assertEqual(len(result.recovery_codes), mfa.RECOVERY_CODE_COUNT)
        claims = read_access_claims(result.access_token)
        self.assertEqual((claims.client, claims.method), ("work", SIGN_IN_MFA))

    async def test_a_work_challenge_cannot_enrol_through_the_web_endpoint(self) -> None:
        user = await self._user()
        challenge = mfa.create_challenge_token(user.id, mfa.PURPOSE_ENROLL, client="work")
        async with async_session_maker() as session:
            offer = mfa.create_setup_offer(await session.get(User, user.id))
        with patch.object(settings, "require_mfa", True):
            with self.assertRaises(HTTPException) as raised:
                await self._answer(
                    challenge, mfa.code_at_step(offer.secret, mfa.current_step()), offer.setup_token
                )
        self.assertEqual(raised.exception.status_code, 401)


class RealPostgresMfaSessionTests(_RealUsers):
    async def test_a_password_session_from_before_the_flag_must_sign_in_again(self) -> None:
        user = await self._user()
        access = create_access_token(user.id, method=SIGN_IN_PASSWORD)
        refresh = create_refresh_token(user.id, method=SIGN_IN_PASSWORD)
        async with async_session_maker() as session:
            await store_refresh_token(session, refresh, user.id)
            await session.commit()
        with patch.object(settings, "require_mfa", True):
            async with async_session_maker() as session:
                with self.assertRaises(HTTPException) as raised:
                    await get_current_user(_request(), _bearer(access), session)
                self.assertEqual(raised.exception.status_code, 401)
                with self.assertRaises(HTTPException) as raised:
                    await refresh_tokens(
                        TokenRefresh(refresh_token=refresh), _request(), Response(), session
                    )
                self.assertEqual(raised.exception.status_code, 401)

    async def test_mfa_and_sso_sessions_continue(self) -> None:
        user = await self._user()
        with patch.object(settings, "require_mfa", True):
            async with async_session_maker() as session:
                for method in (SIGN_IN_MFA, SIGN_IN_SSO):
                    token = create_access_token(user.id, method=method)
                    current = await get_current_user(_request(), _bearer(token), session)
                    self.assertEqual(current.id, user.id)

    async def test_a_refresh_keeps_the_method_it_began_with(self) -> None:
        user = await self._user()
        refresh = create_refresh_token(user.id, method=SIGN_IN_MFA)
        async with async_session_maker() as session:
            await store_refresh_token(session, refresh, user.id)
            await session.commit()
        with patch.object(settings, "require_mfa", True):
            async with async_session_maker() as session:
                rotated = await refresh_tokens(
                    TokenRefresh(refresh_token=refresh), _request(), Response(), session
                )
                await session.commit()
        claims = read_access_claims(rotated.access_token)
        self.assertEqual(claims.method, SIGN_IN_MFA)


class RealPostgresDeactivationTests(_RealUsers):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.admin = await self._user()

    async def _act(self, action, user_id: uuid.UUID):  # noqa: ANN001, ANN202
        with (
            patch.object(settings, "admin_emails", self.admin.email),
            patch.object(
                admin_users, "set_owner_triggers_paused", AsyncMock(return_value=3)
            ) as triggers,
        ):
            async with async_session_maker() as session:
                admin = await session.get(User, self.admin.id)
                result = await action(user_id, current_user=admin, db=session)
                await session.commit()
        return result, triggers

    async def test_deactivation_refuses_every_credential_the_account_held(self) -> None:
        raw_key = f"mcp-{uuid.uuid4().hex}"
        user = await self._user(mcp_key=raw_key)
        access = create_access_token(user.id)
        refresh = create_refresh_token(user.id)
        async with async_session_maker() as session:
            await store_refresh_token(session, refresh, user.id)
            await session.commit()

        result, triggers = await self._act(admin_users.deactivate_user, user.id)
        self.assertFalse(result.user.is_active)
        self.assertEqual(result.workflows_changed, 3)
        self.assertTrue(triggers.await_args.args[1])

        async with async_session_maker() as session:
            with self.assertRaises(HTTPException) as raised:
                await get_current_user(_request(), _bearer(access), session)
            self.assertEqual(raised.exception.status_code, 401)

            with self.assertRaises(HTTPException) as raised:
                await refresh_tokens(
                    TokenRefresh(refresh_token=refresh), _request(), Response(), session
                )
            self.assertEqual(raised.exception.status_code, 401)
            revoked = (
                await session.execute(
                    select(RefreshToken.revoked).where(RefreshToken.user_id == user.id)
                )
            ).scalars()
            self.assertTrue(all(revoked))

            with self.assertRaises(HTTPException) as raised:
                await get_mcp_user(request=_request(), x_mcp_key=raw_key, db=session)
            self.assertEqual(raised.exception.status_code, 401)

        with self.assertRaises(HTTPException) as raised:
            await self._login(user, "198.51.100.31")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_reactivation_restores_sign_in_and_resumes_triggers(self) -> None:
        user = await self._user()
        await self._act(admin_users.deactivate_user, user.id)
        result, triggers = await self._act(admin_users.reactivate_user, user.id)
        self.assertTrue(result.user.is_active)
        self.assertFalse(triggers.await_args.args[1])
        self.assertIsNotNone((await self._login(user, "198.51.100.32")).access_token)

    async def test_an_administrator_cannot_deactivate_themselves(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await self._act(admin_users.deactivate_user, self.admin.id)
        self.assertEqual(raised.exception.status_code, 400)

    async def test_a_non_administrator_cannot_deactivate_anyone(self) -> None:
        user = await self._user()
        async with async_session_maker() as session:
            outsider = await session.get(User, user.id)
            with self.assertRaises(HTTPException) as raised:
                await admin_users.deactivate_user(self.admin.id, current_user=outsider, db=session)
        self.assertEqual(raised.exception.status_code, 403)

    async def test_sign_out_refuses_older_tokens_and_accepts_newer_ones(self) -> None:
        user = await self._user()
        older = _access_token_issued(user.id, seconds_ago=5)
        await self._act(admin_users.sign_out_user, user.id)
        newer = create_access_token(user.id)
        async with async_session_maker() as session:
            with self.assertRaises(HTTPException):
                await get_current_user(_request(), _bearer(older), session)
            current = await get_current_user(_request(), _bearer(newer), session)
        self.assertEqual(current.id, user.id)

    async def test_an_mfa_reset_removes_the_factor_and_its_codes(self) -> None:
        user = await self._user(enrolled=True)
        result, _ = await self._act(admin_users.reset_user_mfa, user.id)
        self.assertFalse(result.user.mfa_enabled)
        async with async_session_maker() as session:
            self.assertEqual(await mfa.recovery_codes_remaining(session, user.id), 0)


class RealPostgresRetentionTests(_RealUsers):
    """Runs with a cutoff in the year 2000, so only this test's rows are old enough."""

    async def test_old_rows_go_and_recent_or_pending_ones_stay(self) -> None:
        owner = await self._user()
        old = datetime(1999, 6, 1, tzinfo=timezone.utc)
        recent = datetime(2000, 6, 1, tzinfo=timezone.utc)
        ids = {name: uuid.uuid4() for name in ("old", "recent", "pending")}
        trace_ids = {name: uuid.uuid4() for name in ("old", "recent")}
        async with async_session_maker() as session:
            workflow = Workflow(name="Retention", owner_id=owner.id, nodes=[], edges=[])
            session.add(workflow)
            await session.flush()
            for name, started in (("old", old), ("recent", recent), ("pending", old)):
                session.add(
                    ExecutionHistory(
                        id=ids[name], workflow_id=workflow.id, status="success", started_at=started
                    )
                )
            await session.flush()
            session.add(
                HITLRequest(
                    workflow_id=workflow.id,
                    execution_history_id=ids["pending"],
                    public_token=uuid.uuid4().hex,
                    workflow_name="Retention",
                    agent_node_id="agent",
                    agent_label="Agent",
                    status="pending",
                    expires_at=recent,
                )
            )
            for name, created in (("old", old), ("recent", recent)):
                session.add(
                    LLMTrace(
                        id=trace_ids[name],
                        user_id=owner.id,
                        source="test",
                        request_type="chat",
                        request={},
                        response={},
                        created_at=created,
                    )
                )
            await session.commit()

        with patch.object(settings, "data_retention_days", 90):
            await apply_retention(now=datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(90))

        async with async_session_maker() as session:
            kept = set(
                (
                    await session.execute(
                        select(ExecutionHistory.id).where(ExecutionHistory.id.in_(ids.values()))
                    )
                ).scalars()
            )
            traces = set(
                (
                    await session.execute(
                        select(LLMTrace.id).where(LLMTrace.id.in_(trace_ids.values()))
                    )
                ).scalars()
            )
            await session.execute(delete(LLMTrace).where(LLMTrace.user_id == owner.id))
            await session.execute(
                delete(ExecutionHistory).where(ExecutionHistory.id.in_(ids.values()))
            )
            await session.commit()
        self.assertEqual(kept, {ids["recent"], ids["pending"]})
        self.assertEqual(traces, {trace_ids["recent"]})

    async def test_zero_days_keeps_everything(self) -> None:
        with patch.object(settings, "data_retention_days", 0):
            result = await apply_retention()
        self.assertEqual((result.executions_deleted, result.traces_deleted), (0, 0))


if __name__ == "__main__":
    unittest.main()
