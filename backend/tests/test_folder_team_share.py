import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

from app.api.folders import move_workflow_to_folder
from app.db.models import Folder, User, Workflow, WorkflowShare


def make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class FolderTeamShareTests(unittest.IsolatedAsyncioTestCase):
    async def test_move_team_shared_workflow_creates_folder_placement_share(self) -> None:
        user_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        folder_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        current_user = User(
            id=user_id,
            email="member@example.com",
            hashed_password="hashed",
        )
        folder = Folder(
            id=folder_id,
            name="Team Folder",
            owner_id=user_id,
            parent_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        workflow = Workflow(
            id=workflow_id,
            name="Shared Workflow",
            description=None,
            owner_id=owner_id,
            nodes=[],
            edges=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                make_result(folder),
                make_result(workflow),
                make_result(None),
            ]
        )

        async def refresh_side_effect(share: WorkflowShare) -> None:
            share.id = uuid.uuid4()

        db.refresh = AsyncMock(side_effect=refresh_side_effect)

        response = await move_workflow_to_folder(folder_id, workflow_id, db, current_user)

        self.assertEqual(response.id, workflow_id)
        self.assertEqual(response.folder_id, folder_id)
        db.add.assert_called_once()
        added_share = db.add.call_args.args[0]
        self.assertIsInstance(added_share, WorkflowShare)
        self.assertEqual(added_share.workflow_id, workflow_id)
        self.assertEqual(added_share.user_id, user_id)
        self.assertEqual(added_share.folder_id, folder_id)
        db.commit.assert_awaited_once()

    async def test_move_team_shared_workflow_updates_existing_share(self) -> None:
        user_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        folder_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        current_user = User(
            id=user_id,
            email="member@example.com",
            hashed_password="hashed",
        )
        folder = Folder(
            id=folder_id,
            name="Team Folder",
            owner_id=user_id,
            parent_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        workflow = Workflow(
            id=workflow_id,
            name="Shared Workflow",
            description=None,
            owner_id=owner_id,
            nodes=[],
            edges=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        existing_share = WorkflowShare(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            user_id=user_id,
            folder_id=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                make_result(folder),
                make_result(workflow),
                make_result(existing_share),
            ]
        )

        response = await move_workflow_to_folder(folder_id, workflow_id, db, current_user)

        self.assertEqual(response.folder_id, folder_id)
        self.assertEqual(existing_share.folder_id, folder_id)
        db.add.assert_not_called()
        db.commit.assert_awaited_once()
