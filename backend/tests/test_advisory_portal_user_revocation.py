"""Portal revocation: a deleted portal user's bearer session must stop working.

Deleting a portal user removes only the WorkflowPortalUser row.
PortalSession.username is a bare string with no foreign key, so no cascade
reaches the session rows, and _validate_session checked only token digest +
workflow_id + expiry. The deleted user's bearer token therefore kept full
portal execute/stream access for the rest of the 168-hour session lifetime.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select

from app.api.portal import _create_session, _validate_session, delete_portal_user
from app.db.models import PortalSession, User, Workflow, WorkflowPortalUser
from app.db.session import async_session_maker, engine
from app.services.secret_tokens import hash_secret


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class PortalUserRevocationMockTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_session_rejects_a_session_whose_portal_user_was_deleted(self) -> None:
        """Validation must consult the portal user, not just the session row."""
        workflow_id = uuid.uuid4()
        session = SimpleNamespace(
            username="alice",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        captured: list[object] = []

        async def fake_execute(statement):
            captured.append(statement)
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            if "workflow_portal_users" in compiled:
                # The user row is gone: any query that consults it matches nothing,
                # so a join/exists-backed validation sees no session row either.
                return _ScalarResult(None)
            return _ScalarResult(session)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        self.assertFalse(await _validate_session(db, "plain-token", workflow_id))

        compiled = [str(s.compile(compile_kwargs={"literal_binds": True})) for s in captured]
        self.assertTrue(
            any("workflow_portal_users" in sql for sql in compiled),
            "session validation never consulted workflow_portal_users",
        )

    async def test_delete_portal_user_issues_a_session_purge_for_that_username(self) -> None:
        workflow_id = uuid.uuid4()
        user_id = uuid.uuid4()
        owner = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(owner_id=owner.id)
        portal_user = SimpleNamespace(id=user_id, username="alice", workflow_id=workflow_id)
        captured: list[object] = []

        async def fake_execute(statement):
            captured.append(statement)
            return _ScalarResult(portal_user)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.delete = AsyncMock()

        with patch("app.api.portal.get_workflow_for_user", AsyncMock(return_value=workflow)):
            await delete_portal_user(
                workflow_id=workflow_id,
                user_id=user_id,
                current_user=owner,
                db=db,
            )

        compiled = [str(s.compile(compile_kwargs={"literal_binds": True})) for s in captured]
        self.assertTrue(
            any(
                sql.startswith("DELETE FROM portal_sessions") and "'alice'" in sql
                for sql in compiled
            ),
            "deleting a portal user issued no portal_sessions purge for its username",
        )


class RealPostgresPortalUserRevocationTests(unittest.IsolatedAsyncioTestCase):
    """Run the actual code against a live database (see AGENTS.md,
    "PostgreSQL Integration Tests"), so nothing a mock could hide survives."""

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.other_workflow_id = uuid.uuid4()
        self.portal_user_id = uuid.uuid4()
        self.plain_token = "portal-revocation-proof-token"
        self.bob_token = "portal-bob-untouched-token"
        self.other_alice_token = "portal-alice-other-workflow-token"
        expires = datetime.now(timezone.utc) + timedelta(hours=1)

        async with async_session_maker() as session:
            session.add(
                User(
                    id=self.owner_id,
                    email=f"owner_{self.owner_id.hex[:8]}@example.com",
                    hashed_password="x",
                    name="Owner",
                )
            )
            await session.flush()
            session.add_all(
                [
                    Workflow(
                        id=self.workflow_id,
                        name="Portal",
                        owner_id=self.owner_id,
                        nodes=[],
                        edges=[],
                    ),
                    Workflow(
                        id=self.other_workflow_id,
                        name="Other portal",
                        owner_id=self.owner_id,
                        nodes=[],
                        edges=[],
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WorkflowPortalUser(
                        id=self.portal_user_id,
                        workflow_id=self.workflow_id,
                        username="alice",
                        hashed_password="x",
                    ),
                    WorkflowPortalUser(
                        workflow_id=self.workflow_id,
                        username="bob",
                        hashed_password="x",
                    ),
                    # The same username, scoped to a different workflow.
                    WorkflowPortalUser(
                        workflow_id=self.other_workflow_id,
                        username="alice",
                        hashed_password="x",
                    ),
                ]
            )
            session.add_all(
                [
                    PortalSession(
                        token=hash_secret(self.plain_token),
                        workflow_id=self.workflow_id,
                        username="alice",
                        expires_at=expires,
                    ),
                    PortalSession(
                        token=hash_secret(self.bob_token),
                        workflow_id=self.workflow_id,
                        username="bob",
                        expires_at=expires,
                    ),
                    PortalSession(
                        token=hash_secret(self.other_alice_token),
                        workflow_id=self.other_workflow_id,
                        username="alice",
                        expires_at=expires,
                    ),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as session:
            await session.execute(
                delete(PortalSession).where(
                    PortalSession.workflow_id.in_([self.workflow_id, self.other_workflow_id])
                )
            )
            await session.execute(
                delete(WorkflowPortalUser).where(
                    WorkflowPortalUser.workflow_id.in_([self.workflow_id, self.other_workflow_id])
                )
            )
            await session.execute(
                delete(Workflow).where(Workflow.id.in_([self.workflow_id, self.other_workflow_id]))
            )
            await session.execute(delete(User).where(User.id == self.owner_id))
            await session.commit()
        await engine.dispose()

    async def _delete_portal_user(self) -> None:
        async with async_session_maker() as session:
            owner = await session.get(User, self.owner_id)
            await delete_portal_user(
                workflow_id=self.workflow_id,
                user_id=self.portal_user_id,
                current_user=owner,
                db=session,
            )
            await session.commit()

    async def test_deleting_a_portal_user_makes_their_live_session_stop_validating(
        self,
    ) -> None:
        async with async_session_maker() as session:
            # Baseline: the bearer token works while its owner still exists.
            self.assertTrue(await _validate_session(session, self.plain_token, self.workflow_id))

        await self._delete_portal_user()

        async with async_session_maker() as session:
            remaining = (
                await session.execute(
                    select(WorkflowPortalUser).where(WorkflowPortalUser.id == self.portal_user_id)
                )
            ).scalar_one_or_none()
            self.assertIsNone(remaining)
            self.assertFalse(
                await _validate_session(session, self.plain_token, self.workflow_id),
                "a deleted portal user's bearer token still validated",
            )

    async def test_deleting_a_portal_user_purges_their_session_rows(self) -> None:
        await self._delete_portal_user()

        async with async_session_maker() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(PortalSession)
                    .where(
                        PortalSession.workflow_id == self.workflow_id,
                        PortalSession.username == "alice",
                    )
                )
            ).scalar_one()
            self.assertEqual(count, 0)

    async def test_a_live_portal_users_session_keeps_validating(self) -> None:
        """Control: revocation machinery must never break a legitimate session."""
        async with async_session_maker() as session:
            self.assertTrue(await _validate_session(session, self.plain_token, self.workflow_id))

    async def test_deleting_alice_does_not_invalidate_bobs_session(self) -> None:
        await self._delete_portal_user()

        async with async_session_maker() as session:
            self.assertTrue(
                await _validate_session(session, self.bob_token, self.workflow_id),
                "an unrelated portal user's session died with alice",
            )
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(PortalSession)
                    .where(
                        PortalSession.workflow_id == self.workflow_id,
                        PortalSession.username == "bob",
                    )
                )
            ).scalar_one()
            self.assertEqual(count, 1)

    async def test_the_same_username_in_another_workflow_is_unaffected(self) -> None:
        await self._delete_portal_user()

        async with async_session_maker() as session:
            self.assertTrue(
                await _validate_session(session, self.other_alice_token, self.other_workflow_id),
                "deleting alice in one workflow killed the same username elsewhere",
            )

    async def test_a_recreated_username_does_not_resurrect_the_old_token(self) -> None:
        """Delete alice, then create a fresh portal user with the same username:
        the deleted user's old token must stay dead, while the new user's own
        sessions work normally. This pins down the difference between username
        identity and session ownership."""
        async with async_session_maker() as session:
            self.assertTrue(await _validate_session(session, self.plain_token, self.workflow_id))

        await self._delete_portal_user()

        async with async_session_maker() as session:
            session.add(
                WorkflowPortalUser(
                    workflow_id=self.workflow_id,
                    username="alice",
                    hashed_password="y",
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            self.assertFalse(
                await _validate_session(session, self.plain_token, self.workflow_id),
                "a recreated username resurrected the deleted user's old token",
            )
            new_token, _ = await _create_session(session, self.workflow_id, "alice")
            await session.commit()

        async with async_session_maker() as session:
            self.assertTrue(
                await _validate_session(session, new_token, self.workflow_id),
                "the recreated portal user's fresh session does not work",
            )

    async def test_an_orphaned_session_row_fails_closed_when_the_user_row_is_missing(
        self,
    ) -> None:
        """Even with the session row still present, validation must fail once the
        portal user is gone (e.g. deleted out-of-band, directly in the database)."""
        async with async_session_maker() as session:
            self.assertTrue(await _validate_session(session, self.plain_token, self.workflow_id))
            # Simulate an out-of-band user deletion that bypasses the endpoint purge.
            await session.execute(
                delete(WorkflowPortalUser).where(WorkflowPortalUser.id == self.portal_user_id)
            )
            await session.commit()

        async with async_session_maker() as session:
            rows = (
                await session.execute(
                    select(func.count())
                    .select_from(PortalSession)
                    .where(
                        PortalSession.workflow_id == self.workflow_id,
                        PortalSession.username == "alice",
                    )
                )
            ).scalar_one()
            self.assertEqual(rows, 1, "expected the orphaned session row to still exist")
            self.assertFalse(
                await _validate_session(session, self.plain_token, self.workflow_id),
                "an orphaned session row still validated without its portal user",
            )

    async def test_portal_user_deletion_and_session_purge_are_atomic(self) -> None:
        """Both operations share the request transaction: a failure between them
        rolls back both, never leaving a half-revoked state."""
        async with async_session_maker() as session:
            owner = await session.get(User, self.owner_id)

            with patch.object(
                session, "delete", AsyncMock(side_effect=RuntimeError("injected failure"))
            ):
                with self.assertRaises(RuntimeError):
                    await delete_portal_user(
                        workflow_id=self.workflow_id,
                        user_id=self.portal_user_id,
                        current_user=owner,
                        db=session,
                    )
            await session.rollback()

        async with async_session_maker() as session:
            user = (
                await session.execute(
                    select(WorkflowPortalUser).where(WorkflowPortalUser.id == self.portal_user_id)
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(user, "the user row vanished despite a failed transaction")
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(PortalSession)
                    .where(
                        PortalSession.workflow_id == self.workflow_id,
                        PortalSession.username == "alice",
                    )
                )
            ).scalar_one()
            self.assertEqual(count, 1, "the session purge survived a failed transaction")


if __name__ == "__main__":
    unittest.main()
