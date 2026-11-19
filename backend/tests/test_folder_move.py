"""Moving a folder with PUT /folders/{id}: `parent_id: null` means root, as the docs say."""

import unittest
import uuid
from unittest.mock import AsyncMock

from app.api.folders import update_folder
from app.models.schemas import FolderUpdate
from tests.test_folder_icon import make_folder, make_result, make_user


class FolderMoveTests(unittest.IsolatedAsyncioTestCase):
    async def _update(self, body: str) -> tuple[object, uuid.UUID]:
        current_user = make_user()
        parent_id = uuid.uuid4()
        folder = make_folder(owner_id=current_user.id, parent_id=parent_id)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await update_folder(folder.id, FolderUpdate.model_validate_json(body), db, current_user)
        db.commit.assert_awaited_once()
        return folder, parent_id

    async def test_parent_id_null_moves_the_folder_to_the_root(self) -> None:
        folder, _parent_id = await self._update('{"parent_id": null}')

        self.assertIsNone(folder.parent_id)

    async def test_a_rename_without_parent_id_keeps_the_parent(self) -> None:
        folder, parent_id = await self._update('{"name": "Renamed"}')

        self.assertEqual(folder.parent_id, parent_id)
        self.assertEqual(folder.name, "Renamed")


if __name__ == "__main__":
    unittest.main()
