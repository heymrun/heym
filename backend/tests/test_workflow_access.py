"""Unit tests for app.services.workflow_access helpers."""

import unittest
import uuid
from unittest.mock import AsyncMock, Mock

from app.services.workflow_access import (
    accessible_workflow_filter,
    get_accessible_workflow_ids,
    list_accessible_workflows,
)


class AccessibleWorkflowFilterTests(unittest.TestCase):
    def test_full_access_includes_team_share_branch(self) -> None:
        compiled = str(
            accessible_workflow_filter(uuid.uuid4(), include_team_shares=True).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("workflow_team_shares", compiled)

    def test_direct_share_only_omits_team_share_branch(self) -> None:
        compiled = str(
            accessible_workflow_filter(uuid.uuid4(), include_team_shares=False).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertNotIn("workflow_team_shares", compiled)
        self.assertIn("workflow_shares", compiled)


class AccessibleWorkflowQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_accessible_workflow_ids_returns_rows(self) -> None:
        workflow_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=Mock(all=Mock(return_value=[(workflow_id,)])))

        result = await get_accessible_workflow_ids(db, uuid.uuid4())

        self.assertEqual(result, [workflow_id])
        db.execute.assert_awaited_once()

    async def test_list_accessible_workflows_returns_scalars(self) -> None:
        workflow = Mock()
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[workflow]))))
        )

        result = await list_accessible_workflows(db, uuid.uuid4())

        self.assertEqual(result, [workflow])
        db.execute.assert_awaited_once()
