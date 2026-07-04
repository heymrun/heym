"""Authorization tests for single-item template get/use paths.

Regression coverage for GHSA-5748-x76g-v68m (horizontal IDOR): get-by-id and
/use must enforce the same visibility rules as the list endpoint, and must not
disclose or mutate templates the caller cannot see.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException, status

from app.api.templates import (
    get_node_template,
    get_workflow_template,
    use_node_template,
    use_workflow_template,
)
from app.db.models import TemplateVisibility


def _user(email: str = "caller@example.com") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), email=email)


def _wf_template(
    author_id: uuid.UUID,
    visibility: TemplateVisibility,
    shared_with: list[str] | None = None,
    shared_with_teams: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        author_id=author_id,
        author=SimpleNamespace(name="Owner"),
        name="Secret WF",
        description=None,
        tags=[],
        nodes=[{"id": "secret"}],
        edges=[],
        canvas_snapshot=None,
        visibility=visibility,
        shared_with=shared_with or [],
        shared_with_teams=shared_with_teams or [],
        use_count=0,
        created_at=datetime.now(timezone.utc),
    )


def _nd_template(
    author_id: uuid.UUID,
    visibility: TemplateVisibility,
    shared_with: list[str] | None = None,
    shared_with_teams: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        author_id=author_id,
        author=SimpleNamespace(name="Owner"),
        name="Secret Node",
        description=None,
        tags=[],
        node_type="httpRequest",
        node_data={"secret": "node"},
        visibility=visibility,
        shared_with=shared_with or [],
        shared_with_teams=shared_with_teams or [],
        use_count=0,
        created_at=datetime.now(timezone.utc),
    )


def _db(template: object, team_rows: tuple = ()) -> AsyncMock:
    """db.execute: 1st call = get-by-id (scalar_one_or_none), 2nd = team ids (.all())."""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=template)),
            MagicMock(all=MagicMock(return_value=list(team_rows))),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class WorkflowTemplateGetAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_template_of_other_user_returns_404(self) -> None:
        caller = _user()
        template = _wf_template(uuid.uuid4(), TemplateVisibility.specific_users)
        db = _db(template)

        with self.assertRaises(HTTPException) as ctx:
            await get_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_author_can_read_own_private_template(self) -> None:
        caller = _user()
        template = _wf_template(caller.id, TemplateVisibility.specific_users)
        db = _db(template)

        result = await get_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(result.nodes, [{"id": "secret"}])

    async def test_everyone_template_is_readable(self) -> None:
        caller = _user()
        template = _wf_template(uuid.uuid4(), TemplateVisibility.everyone)
        db = _db(template)

        result = await get_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(result.id, template.id)

    async def test_shared_by_email_is_readable(self) -> None:
        caller = _user("shared@example.com")
        template = _wf_template(
            uuid.uuid4(), TemplateVisibility.specific_users, shared_with=["shared@example.com"]
        )
        db = _db(template)

        result = await get_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(result.id, template.id)

    async def test_shared_by_team_is_readable(self) -> None:
        caller = _user()
        team_id = str(uuid.uuid4())
        template = _wf_template(
            uuid.uuid4(), TemplateVisibility.specific_users, shared_with_teams=[team_id]
        )
        db = _db(template, team_rows=[(team_id,)])

        result = await get_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(result.id, template.id)


class NodeTemplateGetAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_node_template_of_other_user_returns_404(self) -> None:
        caller = _user()
        template = _nd_template(uuid.uuid4(), TemplateVisibility.specific_users)
        db = _db(template)

        with self.assertRaises(HTTPException) as ctx:
            await get_node_template(template.id, db=db, current_user=caller)
        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_shared_node_template_is_readable(self) -> None:
        caller = _user("shared@example.com")
        template = _nd_template(
            uuid.uuid4(), TemplateVisibility.specific_users, shared_with=["shared@example.com"]
        )
        db = _db(template)

        result = await get_node_template(template.id, db=db, current_user=caller)
        self.assertEqual(result.node_data, {"secret": "node"})


class UsePathAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_use_private_workflow_of_other_user_404_and_no_mutation(self) -> None:
        caller = _user()
        template = _wf_template(uuid.uuid4(), TemplateVisibility.specific_users)
        db = _db(template)

        with self.assertRaises(HTTPException) as ctx:
            await use_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
        # use_count must not be incremented for an invisible template
        self.assertEqual(template.use_count, 0)
        db.commit.assert_not_awaited()

    async def test_use_everyone_workflow_increments(self) -> None:
        caller = _user()
        template = _wf_template(uuid.uuid4(), TemplateVisibility.everyone)
        db = _db(template)

        result = await use_workflow_template(template.id, db=db, current_user=caller)
        self.assertEqual(template.use_count, 1)
        self.assertEqual(result.use_count, 1)

    async def test_use_private_node_of_other_user_404_and_no_mutation(self) -> None:
        caller = _user()
        template = _nd_template(uuid.uuid4(), TemplateVisibility.specific_users)
        db = _db(template)

        with self.assertRaises(HTTPException) as ctx:
            await use_node_template(template.id, db=db, current_user=caller)
        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(template.use_count, 0)
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
