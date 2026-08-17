import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

from app.api.folders import create_folder, get_folder_tree, update_folder
from app.db.models import Folder, User, Workflow
from app.models.schemas import FolderCreate, FolderUpdate


def make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="owner@example.com",
        hashed_password="hashed",
    )


def make_folder(**overrides: object) -> Folder:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Folder",
        "owner_id": uuid.uuid4(),
        "parent_id": None,
        "icon": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return Folder(**values)


class FolderIconCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_folder_persists_icon(self) -> None:
        current_user = make_user()
        db = AsyncMock()
        db.add = Mock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_folder(FolderCreate(name="Team", icon="Briefcase"), db, current_user)

        added_folder = db.add.call_args.args[0]
        self.assertIsInstance(added_folder, Folder)
        self.assertEqual(added_folder.icon, "Briefcase")
        db.commit.assert_awaited_once()

    async def test_create_folder_empty_icon_becomes_none(self) -> None:
        current_user = make_user()
        db = AsyncMock()
        db.add = Mock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_folder(FolderCreate(name="Team", icon=""), db, current_user)

        added_folder = db.add.call_args.args[0]
        self.assertIsNone(added_folder.icon)


class FolderIconUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_folder_sets_icon(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_folder(folder.id, FolderUpdate(icon="Briefcase"), db, current_user)

        self.assertEqual(folder.icon, "Briefcase")
        db.commit.assert_awaited_once()

    async def test_update_folder_clears_icon(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id, icon="Briefcase")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_folder(folder.id, FolderUpdate(icon=None), db, current_user)

        self.assertIsNone(folder.icon)

    async def test_update_folder_rename_keeps_icon(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id, icon="Briefcase")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_folder(folder.id, FolderUpdate(name="Renamed"), db, current_user)

        self.assertEqual(folder.name, "Renamed")
        self.assertEqual(folder.icon, "Briefcase")


class FolderIconTreeTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_folder_tree_includes_icon(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id, icon="Briefcase")
        workflow = Workflow(
            id=uuid.uuid4(),
            name="Workflow",
            owner_id=current_user.id,
            nodes=[],
            edges=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db = AsyncMock()
        folders_result = Mock()
        folders_result.scalars.return_value.unique.return_value.all.return_value = [folder]
        shares_result = Mock()
        shares_result.scalars.return_value.all.return_value = []

        # First call returns the folder list, second the (empty) share list.
        db.execute = AsyncMock(side_effect=[folders_result, shares_result])

        # Attach the workflow relationship so selectinload has something to iterate.
        folder.workflows = [workflow]

        tree = await get_folder_tree(db, current_user)

        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].icon, "Briefcase")


if __name__ == "__main__":
    unittest.main()
