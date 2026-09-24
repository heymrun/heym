"""Multiple dashboards and dashboard sharing.

Covers who can reach a dashboard and how far, that widgets always run as the
dashboard owner whoever is viewing, that read-only viewers get the chart but not
the raw node outputs behind it, and owner-only share management.
"""

import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api import dashboards as dash_api
from app.models.dashboard_schemas import (
    DashboardCreateRequest,
    DashboardShareRequest,
    DashboardTeamShareRequest,
    DashboardUpdateRequest,
    MarkdownTaskToggleRequest,
    WidgetCreateRequest,
    WidgetDataResponse,
)
from app.services import dashboard_access


class _User:
    def __init__(self, name: str = "Owner") -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.email = f"{name.lower()}@example.com"


def _dashboard(owner_id: uuid.UUID, name: str = "Sales") -> MagicMock:
    dashboard = MagicMock(id=uuid.uuid4(), owner_id=owner_id, updated_at=datetime.datetime.now())
    # ``name`` is a MagicMock constructor argument, so it has to be set afterwards.
    dashboard.name = name
    return dashboard


def _scalar(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _grants(*permissions: str) -> MagicMock:
    """The grant lookup ``dashboard_permission`` runs for anyone but the owner."""
    return _scalars(list(permissions))


def _widget_row(widget: object, dashboard: object) -> MagicMock:
    return MagicMock(one_or_none=MagicMock(return_value=(widget, dashboard)))


def _db(*results: object) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()

    async def fake_flush() -> None:
        for call in db.add.call_args_list:
            if getattr(call.args[0], "id", None) is None:
                call.args[0].id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=fake_flush)

    async def fake_refresh(obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "position", None) is None:
            obj.position = 0
        obj.updated_at = datetime.datetime.now()
        obj.created_at = datetime.datetime.now()

    db.refresh = AsyncMock(side_effect=fake_refresh)
    return db


def _widget(**attrs: object) -> MagicMock:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "dashboard_id": uuid.uuid4(),
        "title": "Revenue",
        "description": None,
        "chart_type": "bar",
        "layout": {"x": 0, "y": 0, "w": 4, "h": 4},
        "cache_ttl_seconds": 300,
        "position": 0,
    }
    defaults.update(attrs)
    return MagicMock(**defaults)


class TestStrongestPermission(unittest.TestCase):
    def test_write_wins_over_read(self) -> None:
        self.assertEqual(dashboard_access.strongest_permission(["read", "write", "read"]), "write")

    def test_read_only_grants_stay_read(self) -> None:
        self.assertEqual(dashboard_access.strongest_permission(["read", "read"]), "read")

    def test_no_grant_is_no_access(self) -> None:
        self.assertIsNone(dashboard_access.strongest_permission([]))


class TestDashboardPermission(unittest.IsolatedAsyncioTestCase):
    async def test_owner_short_circuits_without_a_query(self) -> None:
        owner = _User()
        db = _db()

        permission = await dashboard_access.dashboard_permission(db, _dashboard(owner.id), owner.id)

        self.assertEqual(permission, "owner")
        db.execute.assert_not_awaited()

    async def test_team_write_beats_direct_read(self) -> None:
        db = _db(_grants("read", "write"))

        permission = await dashboard_access.dashboard_permission(
            db, _dashboard(uuid.uuid4()), uuid.uuid4()
        )

        self.assertEqual(permission, "write")

    async def test_unshared_dashboard_is_unreachable(self) -> None:
        db = _db(_grants())

        permission = await dashboard_access.dashboard_permission(
            db, _dashboard(uuid.uuid4()), uuid.uuid4()
        )

        self.assertIsNone(permission)

    async def test_grant_lookup_covers_direct_and_team_shares(self) -> None:
        db = _db(_grants())

        await dashboard_access.dashboard_permission(db, _dashboard(uuid.uuid4()), uuid.uuid4())

        sql = str(
            db.execute.await_args.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("dashboard_shares", sql)
        self.assertIn("dashboard_team_shares", sql)
        self.assertIn("team_members", sql)

    async def test_shared_permissions_collapse_per_dashboard(self) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        rows = MagicMock()
        rows.all.return_value = [(first, "read"), (first, "write"), (second, "read")]
        db = _db(rows)

        permissions = await dashboard_access.shared_dashboard_permissions(db, uuid.uuid4())

        self.assertEqual(permissions, {first: "write", second: "read"})


class TestWidgetAccess(unittest.IsolatedAsyncioTestCase):
    async def test_read_viewer_cannot_write(self) -> None:
        widget = _widget()
        db = _db(_widget_row(widget, _dashboard(uuid.uuid4())), _grants("read"))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api._load_widget_for_user(db, widget.id, _User("Viewer"), write=True)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_read_viewer_can_read(self) -> None:
        widget = _widget()
        dashboard = _dashboard(uuid.uuid4())
        db = _db(_widget_row(widget, dashboard), _grants("read"))

        loaded = await dash_api._load_widget_for_user(db, widget.id, _User("Viewer"), write=False)

        self.assertEqual(loaded, (widget, dashboard, "read"))

    async def test_unshared_widget_is_not_found(self) -> None:
        widget = _widget()
        db = _db(_widget_row(widget, _dashboard(uuid.uuid4())), _grants())

        with self.assertRaises(HTTPException) as ctx:
            await dash_api._load_widget_for_user(db, widget.id, _User("Stranger"), write=False)

        self.assertEqual(ctx.exception.status_code, 404)


class TestWidgetDataRunsAsOwner(unittest.IsolatedAsyncioTestCase):
    def _data(self, widget_id: uuid.UUID) -> WidgetDataResponse:
        return WidgetDataResponse(
            widget_id=widget_id,
            payload={"type": "numeric", "value": 42},
            cached=False,
            computed_at=None,
            highlight={
                "records": [
                    {
                        "node_id": "http",
                        "node_label": "fetch",
                        "node_type": "http",
                        "kind": "output",
                        "runs": ['{"raw": "upstream response"}'],
                    }
                ]
            },
        )

    async def test_read_viewer_gets_the_chart_computed_as_owner_without_highlights(self) -> None:
        owner_id = uuid.uuid4()
        widget = _widget()
        dashboard = _dashboard(owner_id)
        db = _db(_widget_row(widget, dashboard), _grants("read"))
        compute = AsyncMock(return_value=self._data(widget.id))

        with patch.object(dash_api, "compute_widget_data", compute):
            response = await dash_api.get_widget_data(
                widget_id=widget.id, force=True, current_user=_User("Viewer"), db=db
            )

        compute.assert_awaited_once_with(db, widget, owner_id, force=True)
        self.assertEqual(response.payload, {"type": "numeric", "value": 42})
        self.assertIsNone(response.highlight)

    async def test_editor_keeps_highlights(self) -> None:
        widget = _widget()
        dashboard = _dashboard(uuid.uuid4())
        db = _db(_widget_row(widget, dashboard), _grants("write"))
        compute = AsyncMock(return_value=self._data(widget.id))

        with patch.object(dash_api, "compute_widget_data", compute):
            response = await dash_api.get_widget_data(
                widget_id=widget.id, force=False, current_user=_User("Editor"), db=db
            )

        compute.assert_awaited_once_with(db, widget, dashboard.owner_id, force=False)
        self.assertIsNotNone(response.highlight)


class TestCollaboratorWidgetWrites(unittest.IsolatedAsyncioTestCase):
    async def test_editor_created_widget_workflow_belongs_to_the_dashboard_owner(self) -> None:
        owner_id = uuid.uuid4()
        dashboard = _dashboard(owner_id)
        db = _db(_scalar(dashboard), _grants("write"))

        with patch.object(dash_api, "audit") as audit:
            await dash_api.create_widget(
                dashboard_id=dashboard.id,
                body=WidgetCreateRequest(title="Signups", chart_type="line"),
                current_user=_User("Editor"),
                db=db,
            )

        workflow = db.add.call_args_list[0].args[0]
        widget = db.add.call_args_list[1].args[0]
        self.assertEqual(workflow.kind, "dashboard_widget")
        self.assertEqual(workflow.owner_id, owner_id)
        self.assertEqual(widget.dashboard_id, dashboard.id)
        self.assertEqual(audit.call_args.kwargs["action"], "dashboard.widget_create")

    async def test_read_viewer_cannot_add_widgets(self) -> None:
        dashboard = _dashboard(uuid.uuid4())
        db = _db(_scalar(dashboard), _grants("read"))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.create_widget(
                dashboard_id=dashboard.id,
                body=WidgetCreateRequest(title="Signups"),
                current_user=_User("Viewer"),
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 403)
        db.add.assert_not_called()

    async def test_editor_clone_keeps_the_dashboard_owner(self) -> None:
        owner_id = uuid.uuid4()
        widget = _widget()
        workflow = MagicMock(
            description=None,
            nodes=[{"id": "chart", "type": "chartOutput", "data": {}}],
            edges=[],
        )
        db = _db(
            _widget_row(widget, _dashboard(owner_id)),
            _grants("write"),
            _scalar(workflow),
        )

        await dash_api.clone_widget(widget.id, current_user=_User("Editor"), db=db)

        cloned_workflow = db.add.call_args_list[0].args[0]
        self.assertEqual(cloned_workflow.owner_id, owner_id)

    async def test_read_viewer_cannot_tick_task_items(self) -> None:
        widget = _widget()
        db = _db(_widget_row(widget, _dashboard(uuid.uuid4())), _grants("read"))
        compute = AsyncMock()

        with patch.object(dash_api, "compute_widget_data", compute):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.toggle_markdown_task(
                    widget_id=widget.id,
                    body=MarkdownTaskToggleRequest(line_index=0),
                    current_user=_User("Viewer"),
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 403)
        compute.assert_not_awaited()

    async def test_read_viewer_cannot_delete_widgets(self) -> None:
        widget = _widget()
        db = _db(_widget_row(widget, _dashboard(uuid.uuid4())), _grants("read"))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.delete_widget(widget.id, current_user=_User("Viewer"), db=db)

        self.assertEqual(ctx.exception.status_code, 403)
        db.delete.assert_not_awaited()


class TestDashboardLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_list_puts_own_dashboards_first_and_labels_shared_ones(self) -> None:
        user = _User("Alex")
        other = _User("Sam")
        owned = _dashboard(user.id, name="Mine")
        shared = _dashboard(other.id, name="Theirs")
        grants = MagicMock()
        grants.all.return_value = [(shared.id, "write")]
        rows = MagicMock()
        rows.all.return_value = [(shared, other), (owned, user)]
        db = _db(_scalar(owned.id), grants, rows)

        summaries = await dash_api.list_dashboards(current_user=user, db=db)

        self.assertEqual([s.name for s in summaries], ["Mine", "Theirs"])
        self.assertEqual(summaries[0].permission, "owner")
        self.assertIsNone(summaries[0].shared_by)
        self.assertEqual(summaries[1].permission, "write")
        self.assertEqual(summaries[1].owner_name, "Sam")
        self.assertEqual(summaries[1].shared_by, "sam@example.com")
        db.add.assert_not_called()

    async def test_list_creates_a_default_dashboard_for_a_user_without_one(self) -> None:
        user = _User()
        grants = MagicMock()
        grants.all.return_value = []
        rows = MagicMock()
        rows.all.return_value = []
        db = _db(_scalar(None), grants, rows)

        await dash_api.list_dashboards(current_user=user, db=db)

        created = db.add.call_args.args[0]
        self.assertEqual(created.owner_id, user.id)
        self.assertEqual(created.name, "Dashboard")

    async def test_create_dashboard_is_owned_by_the_caller(self) -> None:
        user = _User()
        db = _db()

        summary = await dash_api.create_dashboard(
            body=DashboardCreateRequest(name="  Ops  "), current_user=user, db=db
        )

        created = db.add.call_args.args[0]
        self.assertEqual(created.owner_id, user.id)
        self.assertEqual(created.name, "Ops")
        self.assertEqual(summary.permission, "owner")

    async def test_get_dashboard_tells_a_viewer_who_shared_it(self) -> None:
        owner = _User("Sam")
        dashboard = _dashboard(owner.id)
        widget = _widget(dashboard_id=dashboard.id, updated_at=datetime.datetime.now())
        db = _db(
            _scalar(dashboard),
            _grants("read"),
            MagicMock(scalar_one=MagicMock(return_value=owner)),
            _scalars([widget]),
        )

        response = await dash_api.get_dashboard(
            dashboard_id=dashboard.id, current_user=_User("Viewer"), db=db
        )

        self.assertEqual(response.permission, "read")
        self.assertEqual(response.shared_by, "sam@example.com")
        self.assertEqual([w.id for w in response.widgets], [widget.id])

    async def test_only_the_owner_renames(self) -> None:
        db = _db(_scalar(None))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.update_dashboard(
                dashboard_id=uuid.uuid4(),
                body=DashboardUpdateRequest(name="Renamed"),
                current_user=_User("Editor"),
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 404)
        db.commit.assert_not_awaited()

    async def test_last_owned_dashboard_cannot_be_deleted(self) -> None:
        user = _User()
        dashboard = _dashboard(user.id)
        db = _db(_scalar(dashboard), MagicMock(scalar=MagicMock(return_value=1)))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.delete_dashboard(dashboard_id=dashboard.id, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, 409)
        db.delete.assert_not_awaited()

    async def test_delete_removes_the_hidden_widget_workflows(self) -> None:
        user = _User()
        dashboard = _dashboard(user.id)
        first, second = MagicMock(), MagicMock()
        db = _db(
            _scalar(dashboard),
            MagicMock(scalar=MagicMock(return_value=2)),
            _scalars([first, second]),
        )

        await dash_api.delete_dashboard(dashboard_id=dashboard.id, current_user=user, db=db)

        deleted = [call.args[0] for call in db.delete.await_args_list]
        self.assertEqual(deleted, [first, second, dashboard])
        db.commit.assert_awaited_once()


class TestDashboardShares(unittest.IsolatedAsyncioTestCase):
    async def test_cannot_share_with_yourself(self) -> None:
        owner = _User()
        db = _db(_scalar(_dashboard(owner.id)), _scalar(owner))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.create_dashboard_share(
                dashboard_id=uuid.uuid4(),
                body=DashboardShareRequest(email=owner.email),
                current_user=owner,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_unknown_email_is_not_found(self) -> None:
        owner = _User()
        db = _db(_scalar(_dashboard(owner.id)), _scalar(None))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.create_dashboard_share(
                dashboard_id=uuid.uuid4(),
                body=DashboardShareRequest(email="nobody@example.com"),
                current_user=owner,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_new_share_records_permission_without_revoking(self) -> None:
        owner, target = _User(), _User("Sam")
        db = _db(_scalar(_dashboard(owner.id)), _scalar(target), _scalar(None))
        revoke = AsyncMock()

        with (
            patch.object(dash_api, "_revoke_widget_tokens_without_access", revoke),
            patch.object(dash_api, "audit") as audit,
        ):
            response = await dash_api.create_dashboard_share(
                dashboard_id=uuid.uuid4(),
                body=DashboardShareRequest(email=target.email, permission="write"),
                current_user=owner,
                db=db,
            )

        share = db.add.call_args.args[0]
        self.assertEqual(share.user_id, target.id)
        self.assertEqual(response.permission, "write")
        revoke.assert_not_awaited()
        self.assertEqual(audit.call_args.kwargs["action"], "dashboard.share_add")

    async def test_downgrading_write_to_read_revokes_widget_tokens(self) -> None:
        owner, target = _User(), _User("Sam")
        dashboard = _dashboard(owner.id)
        existing = MagicMock(
            id=uuid.uuid4(), permission="write", created_at=datetime.datetime.now()
        )
        db = _db(_scalar(dashboard), _scalar(target), _scalar(existing))
        revoke = AsyncMock()

        with patch.object(dash_api, "_revoke_widget_tokens_without_access", revoke):
            await dash_api.create_dashboard_share(
                dashboard_id=dashboard.id,
                body=DashboardShareRequest(email=target.email, permission="read"),
                current_user=owner,
                db=db,
            )

        self.assertEqual(existing.permission, "read")
        revoke.assert_awaited_once_with(db, dashboard.id)

    async def test_upgrading_read_to_write_revokes_nothing(self) -> None:
        owner, target = _User(), _User("Sam")
        existing = MagicMock(id=uuid.uuid4(), permission="read", created_at=datetime.datetime.now())
        db = _db(_scalar(_dashboard(owner.id)), _scalar(target), _scalar(existing))
        revoke = AsyncMock()

        with patch.object(dash_api, "_revoke_widget_tokens_without_access", revoke):
            await dash_api.create_dashboard_share(
                dashboard_id=uuid.uuid4(),
                body=DashboardShareRequest(email=target.email, permission="write"),
                current_user=owner,
                db=db,
            )

        self.assertEqual(existing.permission, "write")
        revoke.assert_not_awaited()

    async def test_removing_a_share_revokes_widget_tokens(self) -> None:
        owner = _User()
        dashboard = _dashboard(owner.id)
        share = MagicMock()
        db = _db(_scalar(dashboard), _scalar(share))
        revoke = AsyncMock()

        with patch.object(dash_api, "_revoke_widget_tokens_without_access", revoke):
            await dash_api.delete_dashboard_share(
                dashboard_id=dashboard.id, user_id=uuid.uuid4(), current_user=owner, db=db
            )

        db.delete.assert_awaited_once_with(share)
        revoke.assert_awaited_once_with(db, dashboard.id)

    async def test_non_owner_cannot_see_shares(self) -> None:
        db = _db(_scalar(None))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.list_dashboard_shares(
                dashboard_id=uuid.uuid4(), current_user=_User("Editor"), db=db
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_team_share_needs_team_membership(self) -> None:
        owner = _User()
        db = _db(_scalar(_dashboard(owner.id)), _scalar(None))

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.create_dashboard_team_share(
                dashboard_id=uuid.uuid4(),
                body=DashboardTeamShareRequest(team_id=uuid.uuid4()),
                current_user=owner,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 404)
        db.add.assert_not_called()

    async def test_team_share_downgrade_revokes_widget_tokens(self) -> None:
        owner = _User()
        dashboard = _dashboard(owner.id)
        team = MagicMock(id=uuid.uuid4())
        team.name = "Data"
        existing = MagicMock(
            id=uuid.uuid4(), permission="write", created_at=datetime.datetime.now()
        )
        db = _db(_scalar(dashboard), _scalar(team), _scalar(existing))
        revoke = AsyncMock()

        with patch.object(dash_api, "_revoke_widget_tokens_without_access", revoke):
            response = await dash_api.create_dashboard_team_share(
                dashboard_id=dashboard.id,
                body=DashboardTeamShareRequest(team_id=team.id, permission="read"),
                current_user=owner,
                db=db,
            )

        self.assertEqual(response.team_name, "Data")
        revoke.assert_awaited_once_with(db, dashboard.id)

    async def test_token_revocation_checks_every_widget_workflow(self) -> None:
        first, second = MagicMock(), MagicMock()
        db = _db(_scalars([first, second]))
        revoke = AsyncMock()

        with patch.object(dash_api, "revoke_execution_tokens_without_access", revoke):
            await dash_api._revoke_widget_tokens_without_access(db, uuid.uuid4())

        self.assertEqual([call.args[1] for call in revoke.await_args_list], [first, second])


class TestDashboardSchemas(unittest.TestCase):
    def test_blank_names_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            DashboardCreateRequest(name="   ")
        with self.assertRaises(ValidationError):
            DashboardUpdateRequest(name="")

    def test_names_are_trimmed(self) -> None:
        self.assertEqual(DashboardUpdateRequest(name="  Q3 KPIs ").name, "Q3 KPIs")

    def test_share_permission_is_read_or_write(self) -> None:
        with self.assertRaises(ValidationError):
            DashboardShareRequest(email="a@example.com", permission="owner")
        with self.assertRaises(ValidationError):
            DashboardTeamShareRequest(team_id=uuid.uuid4(), permission="admin")
        self.assertEqual(DashboardShareRequest(email="a@example.com").permission, "read")


if __name__ == "__main__":
    unittest.main()
