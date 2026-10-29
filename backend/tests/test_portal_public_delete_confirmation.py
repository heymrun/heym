"""Deleting the last user of an enabled portal needs an explicit acknowledgement.

A portal with zero users is a supported, public configuration, so the delete is
not blocked: without `confirm_public=true` it returns 409 instead of publishing
the portal as a side effect. The mock cases pin the branch; the PostgreSQL class
drives the real router and database, where the 409, the untouched row and the
public state after a confirmed delete are all observable.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete, func, select

from app.api import portal
from app.api.portal import delete_portal_user
from app.db.models import PortalSession, User, Workflow, WorkflowPortalUser
from app.db.session import async_session_maker, engine


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value


class PortalPublicDeleteConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def _delete(
        self, *, portal_enabled: bool, user_count: int, confirm_public: bool
    ) -> tuple[AsyncMock, HTTPException | None]:
        """Run the endpoint over one portal user and a workflow holding `user_count` users."""
        workflow_id = uuid.uuid4()
        user_id = uuid.uuid4()
        owner = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(owner_id=owner.id, portal_enabled=portal_enabled)
        portal_user = SimpleNamespace(id=user_id, username="alice", workflow_id=workflow_id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarResult(portal_user),
                _ScalarResult(user_count),
                _ScalarResult(None),
            ]
        )
        db.delete = AsyncMock()

        error: HTTPException | None = None
        with patch("app.api.portal.get_workflow_for_user", AsyncMock(return_value=workflow)):
            try:
                await delete_portal_user(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    confirm_public=confirm_public,
                    current_user=owner,
                    db=db,
                )
            except HTTPException as exc:
                error = exc
        return db, error

    async def test_the_last_user_of_an_enabled_portal_needs_confirmation(self) -> None:
        db, error = await self._delete(portal_enabled=True, user_count=1, confirm_public=False)

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error.status_code, 409)
        self.assertIn("confirm_public=true", error.detail)
        db.delete.assert_not_awaited()

    async def test_confirmation_deletes_the_last_user_and_makes_the_portal_public(self) -> None:
        db, error = await self._delete(portal_enabled=True, user_count=1, confirm_public=True)

        self.assertIsNone(error)
        db.delete.assert_awaited_once()
        # Looking up the user and purging their sessions; the count is skipped.
        self.assertEqual(db.execute.await_count, 2)

    async def test_other_users_do_not_need_confirmation(self) -> None:
        db, error = await self._delete(portal_enabled=True, user_count=2, confirm_public=False)

        self.assertIsNone(error)
        db.delete.assert_awaited_once()
        # Lookup, the count that answers "is this the last one", and the session purge.
        self.assertEqual(db.execute.await_count, 3)


class RealPostgresPortalDeleteConfirmationTests(unittest.IsolatedAsyncioTestCase):
    """The same three outcomes through the real router and a live database."""

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.portal_user_id = uuid.uuid4()
        self.slug = f"confirm-public-{self.workflow_id.hex[:10]}"

        async with async_session_maker() as session:
            session.add(
                User(
                    id=self.owner_id,
                    email=f"portal-confirm_{self.owner_id.hex[:8]}@example.com",
                    hashed_password="x",
                    name="Owner",
                )
            )
            await session.flush()
            session.add(
                Workflow(
                    id=self.workflow_id,
                    name="Confirm public",
                    owner_id=self.owner_id,
                    nodes=[],
                    edges=[],
                    portal_enabled=True,
                    portal_slug=self.slug,
                )
            )
            await session.flush()
            session.add(
                WorkflowPortalUser(
                    id=self.portal_user_id,
                    workflow_id=self.workflow_id,
                    username="alice",
                    hashed_password="x",
                )
            )
            await session.commit()
            self.owner = await session.get(User, self.owner_id)

        app = FastAPI()
        app.include_router(portal.router, prefix="/api/portal")
        app.dependency_overrides[portal.get_current_user] = lambda: self.owner

        async def request_session():
            async with async_session_maker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[portal.get_db] = request_session
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://portal.test"
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        async with async_session_maker() as session:
            await session.execute(
                delete(PortalSession).where(PortalSession.workflow_id == self.workflow_id)
            )
            await session.execute(
                delete(WorkflowPortalUser).where(WorkflowPortalUser.workflow_id == self.workflow_id)
            )
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(delete(User).where(User.id == self.owner_id))
            await session.commit()
        await engine.dispose()

    async def _state(self) -> tuple[bool, int]:
        async with async_session_maker() as session:
            workflow = await session.get(Workflow, self.workflow_id)
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(WorkflowPortalUser)
                    .where(WorkflowPortalUser.workflow_id == self.workflow_id)
                )
            ).scalar_one()
            return workflow.portal_enabled, count

    async def _requires_auth(self) -> bool:
        response = await self.client.get(f"/api/portal/{self.slug}/info")
        self.assertEqual(response.status_code, 200)
        return response.json()["requires_auth"]

    async def test_without_the_flag_the_last_user_survives_and_the_portal_stays_guarded(
        self,
    ) -> None:
        response = await self.client.delete(
            f"/api/portal/{self.workflow_id}/portal/users/{self.portal_user_id}"
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("confirm_public=true", response.json()["detail"])
        self.assertEqual(await self._state(), (True, 1))
        self.assertTrue(await self._requires_auth())

    async def test_the_flag_deletes_through_and_the_portal_is_deliberately_public(self) -> None:
        response = await self.client.delete(
            f"/api/portal/{self.workflow_id}/portal/users/{self.portal_user_id}",
            params={"confirm_public": "true"},
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(await self._state(), (True, 0))
        self.assertFalse(await self._requires_auth())

    async def test_a_second_user_deletes_without_the_flag(self) -> None:
        async with async_session_maker() as session:
            session.add(
                WorkflowPortalUser(
                    id=uuid.uuid4(),
                    workflow_id=self.workflow_id,
                    username="bob",
                    hashed_password="x",
                )
            )
            await session.commit()

        response = await self.client.delete(
            f"/api/portal/{self.workflow_id}/portal/users/{self.portal_user_id}"
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(await self._state(), (True, 1))
        self.assertTrue(await self._requires_auth())
