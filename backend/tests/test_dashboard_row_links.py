"""Row links: a table widget opens another dashboard with ?record=, for viewers who can open it."""

import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import dashboards as dash_api
from app.config import settings
from app.db.models import Dashboard, DashboardShare, User
from app.models.dashboard_schemas import WidgetUpdateRequest
from app.services.dashboard_access import reachable_dashboard_ids


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "Editor"
        self.email = "editor@example.com"


def _widget() -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        dashboard_id=uuid.uuid4(),
        title="Customers",
        description=None,
        chart_type="table",
        layout={"x": 0, "y": 0, "w": 6, "h": 4},
        cache_ttl_seconds=300,
        position=0,
        link_dashboard_id=None,
        link_record_field=None,
        link_label_field=None,
        updated_at=datetime.datetime.now(),
    )


def _scalar(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


class UpdateRowLinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = _User()
        self.widget = _widget()
        self.dashboard = MagicMock(id=self.widget.dashboard_id, owner_id=self.user.id)
        self.target = MagicMock(id=uuid.uuid4(), owner_id=uuid.uuid4())
        self.db = MagicMock()
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()

    async def _update(self, body: WidgetUpdateRequest, target_permission: str | None) -> object:
        lookups = [
            MagicMock(one_or_none=MagicMock(return_value=(self.widget, self.dashboard))),
            _scalar(self.target),
        ]
        self.db.execute = AsyncMock(side_effect=lookups)
        reachable = AsyncMock(return_value={self.target.id} if target_permission else set())

        async def permission(_db: object, dashboard: object, _user_id: uuid.UUID) -> str | None:
            # The editor owns the widget's dashboard; the target is the one under test.
            return "owner" if dashboard is self.dashboard else target_permission

        with (
            patch.object(dash_api, "dashboard_permission", permission),
            patch.object(dash_api, "reachable_dashboard_ids", reachable),
        ):
            return await dash_api.update_widget(
                widget_id=self.widget.id, body=body, current_user=self.user, db=self.db
            )

    async def test_an_editor_links_rows_to_a_dashboard_they_can_open(self) -> None:
        response = await self._update(
            WidgetUpdateRequest(
                link_dashboard_id=self.target.id,
                link_record_field=" customer_id ",
                link_label_field="name",
            ),
            target_permission="read",
        )

        self.assertEqual(self.widget.link_dashboard_id, self.target.id)
        self.assertEqual(self.widget.link_record_field, "customer_id")
        self.assertEqual(self.widget.link_label_field, "name")
        self.assertTrue(response.link_accessible)

    async def test_a_dashboard_the_editor_cannot_open_is_not_a_target(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._update(
                WidgetUpdateRequest(link_dashboard_id=self.target.id, link_record_field="id"),
                target_permission=None,
            )

        self.assertEqual(caught.exception.status_code, 404)
        self.db.commit.assert_not_awaited()

    async def test_a_link_needs_the_record_column(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._update(
                WidgetUpdateRequest(link_dashboard_id=self.target.id, link_record_field="  "),
                target_permission="owner",
            )

        self.assertEqual(caught.exception.status_code, 422)

    async def test_null_removes_the_link_and_omitting_it_keeps_it(self) -> None:
        self.widget.link_dashboard_id = self.target.id
        self.widget.link_record_field = "id"

        await self._update(WidgetUpdateRequest(title="Accounts"), target_permission="read")
        self.assertEqual(self.widget.link_dashboard_id, self.target.id)

        await self._update(WidgetUpdateRequest(link_dashboard_id=None), target_permission="read")
        self.assertIsNone(self.widget.link_dashboard_id)
        self.assertIsNone(self.widget.link_record_field)
        self.assertIsNone(self.widget.link_label_field)


class GetDashboardRowLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_rows_are_clickable_only_for_viewers_who_can_open_the_target(self) -> None:
        user = _User()
        dashboard = MagicMock(
            id=uuid.uuid4(),
            owner_id=user.id,
            record_format="id",
            updated_at=datetime.datetime.now(),
        )
        dashboard.name = "Customers"
        reachable_target, hidden_target = uuid.uuid4(), uuid.uuid4()
        linked, hidden = _widget(), _widget()
        linked.link_dashboard_id, linked.link_record_field = reachable_target, "id"
        hidden.link_dashboard_id, hidden.link_record_field = hidden_target, "id"
        widgets = MagicMock()
        widgets.scalars.return_value.all.return_value = [linked, hidden]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_scalar(dashboard), widgets])
        reachable = AsyncMock(return_value={reachable_target})

        with patch.object(dash_api, "reachable_dashboard_ids", reachable):
            response = await dash_api.get_dashboard(
                dashboard_id=dashboard.id, current_user=user, db=db
            )

        reachable.assert_awaited_once_with(db, {reachable_target, hidden_target}, user.id)
        self.assertEqual([w.link_accessible for w in response.widgets], [True, False])
        self.assertEqual(response.widgets[1].link_dashboard_id, hidden_target)


class ReachableDashboardsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.owner = User(email=f"o-{uuid.uuid4()}@example.com", hashed_password="x", name="O")
        self.viewer = User(email=f"v-{uuid.uuid4()}@example.com", hashed_password="x", name="V")
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all([self.owner, self.viewer])
            await db.flush()
            self.own = Dashboard(owner_id=self.viewer.id, name="Mine")
            self.shared = Dashboard(owner_id=self.owner.id, name="Shared")
            self.private = Dashboard(owner_id=self.owner.id, name="Private")
            db.add_all([self.own, self.shared, self.private])
            await db.flush()
            db.add(DashboardShare(dashboard_id=self.shared.id, user_id=self.viewer.id))
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            ids = [self.own.id, self.shared.id, self.private.id]
            await db.execute(delete(Dashboard).where(Dashboard.id.in_(ids)))
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.viewer.id])))
            await db.commit()
        await self.engine.dispose()

    async def test_owned_and_shared_dashboards_are_reachable(self) -> None:
        async with AsyncSession(self.engine) as db:
            reachable = await reachable_dashboard_ids(
                db, {self.own.id, self.shared.id, self.private.id}, self.viewer.id
            )

        self.assertEqual(reachable, {self.own.id, self.shared.id})


if __name__ == "__main__":
    unittest.main()
