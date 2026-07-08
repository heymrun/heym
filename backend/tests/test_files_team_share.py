"""Tests for Drive file team sharing API behavior."""

from __future__ import annotations

import io
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, UploadFile, status

from app.api.files import (
    create_share,
    download_authenticated_file,
    get_file_metadata,
    list_files,
    update_file_team_sharing,
    upload_file,
)
from app.api.teams import get_team_shared_entities
from app.db.models import FileTeamShare
from app.models.schemas import CreateFileShareRequest, FileTeamSharingRequest


def _result(
    *,
    scalar_one: object | None = None,
    scalars: list[object] | None = None,
    all_rows: list[object] | None = None,
    scalar: object | None = None,
    first: object | None = None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one
    result.scalar.return_value = scalar
    result.first.return_value = first
    result.all.return_value = all_rows or []
    result.scalars.return_value.all.return_value = scalars or []
    return result


def _db(execute_results: list[MagicMock]) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _user(user_id: uuid.UUID | None = None, email: str = "user@example.com") -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), email=email, name="User")


def _file_row(
    *,
    file_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    filename: str = "report.txt",
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id or uuid.uuid4(),
        owner_id=owner_id or uuid.uuid4(),
        filename=filename,
        storage_path="owner/file/report.txt",
        mime_type="text/plain",
        size_bytes=12,
        workflow_id=None,
        source_node_label="manual upload",
        access_tokens=[],
        team_shares=[],
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class FileTeamSharingApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_enable_team_sharing_adds_missing_current_team_shares(self) -> None:
        owner = _user()
        file_id = uuid.uuid4()
        team_a = uuid.uuid4()
        team_b = uuid.uuid4()
        row = _file_row(file_id=file_id, owner_id=owner.id)
        db = _db(
            [
                _result(scalar_one=row),
                _result(scalars=[team_a, team_b]),
                _result(scalars=[team_a]),
                _result(scalar=2),
            ]
        )

        response = await update_file_team_sharing(
            file_id,
            FileTeamSharingRequest(enabled=True),
            user=owner,
            db=db,
        )

        self.assertTrue(response.enabled)
        self.assertEqual(response.shared_team_count, 2)
        db.add.assert_called_once()
        added_share = db.add.call_args.args[0]
        self.assertIsInstance(added_share, FileTeamShare)
        self.assertEqual(added_share.file_id, file_id)
        self.assertEqual(added_share.team_id, team_b)
        db.commit.assert_awaited_once()

    async def test_disable_team_sharing_removes_file_team_shares(self) -> None:
        owner = _user()
        file_id = uuid.uuid4()
        row = _file_row(file_id=file_id, owner_id=owner.id)
        db = _db([_result(scalar_one=row), _result()])

        response = await update_file_team_sharing(
            file_id,
            FileTeamSharingRequest(enabled=False),
            user=owner,
            db=db,
        )

        self.assertFalse(response.enabled)
        self.assertEqual(response.shared_team_count, 0)
        db.commit.assert_awaited_once()

    async def test_upload_file_can_share_with_current_teams(self) -> None:
        owner = _user()
        row = _file_row(owner_id=owner.id)
        db = _db([])
        upload = UploadFile(filename="report.txt", file=io.BytesIO(b"hello"))

        with (
            patch("app.api.files.build_public_base_url", return_value="https://heym.run"),
            patch("app.api.files.read_upload_file_limited", new=AsyncMock(return_value=b"hello")),
            patch("app.api.files.store_file", new=AsyncMock(return_value=row)),
            patch("app.api.files.create_access_token", new=AsyncMock()),
            patch("app.api.files._set_file_team_sharing", new=AsyncMock(return_value=1)) as share,
        ):
            response = await upload_file(
                request=MagicMock(),
                file=upload,
                share_with_my_teams=True,
                user=owner,
                db=db,
            )

        self.assertEqual(response.id, row.id)
        share.assert_awaited_once_with(db, file_id=row.id, owner_id=owner.id, enabled=True)
        db.commit.assert_awaited_once()

    async def test_list_files_includes_team_shared_files_as_read_only(self) -> None:
        user = _user()
        owned = _file_row(owner_id=user.id, filename="owned.txt")
        shared = _file_row(owner_id=uuid.uuid4(), filename="shared.txt")
        shared.team_shares = [SimpleNamespace(team_id=uuid.uuid4())]
        db = _db(
            [
                _result(scalars=[owned]),
                _result(all_rows=[(shared, "owner@example.com", "Product")]),
            ]
        )

        with patch("app.api.files.build_public_base_url", return_value="https://heym.run"):
            response = await list_files(request=MagicMock(), user=user, db=db)

        self.assertEqual(response.total, 2)
        by_name = {item.filename: item for item in response.files}
        self.assertFalse(by_name["owned.txt"].is_shared)
        self.assertTrue(by_name["shared.txt"].is_shared)
        self.assertEqual(by_name["shared.txt"].shared_by, "owner@example.com")
        self.assertEqual(by_name["shared.txt"].shared_by_team, "Product")
        self.assertTrue(by_name["shared.txt"].shared_with_my_teams)

    async def test_team_member_can_get_shared_file_metadata(self) -> None:
        member = _user()
        shared = _file_row(owner_id=uuid.uuid4(), filename="team.txt")
        db = _db(
            [
                _result(scalar_one=None),
                _result(first=(shared, "owner@example.com", "Ops")),
            ]
        )

        with patch("app.api.files.build_public_base_url", return_value="https://heym.run"):
            response = await get_file_metadata(shared.id, request=MagicMock(), user=member, db=db)

        self.assertTrue(response.is_shared)
        self.assertEqual(response.shared_by_team, "Ops")
        self.assertEqual(
            response.authenticated_download_url,
            f"https://heym.run/api/files/{shared.id}/download",
        )

    async def test_team_member_can_download_shared_file(self) -> None:
        member = _user()
        shared = _file_row(owner_id=uuid.uuid4(), filename="team.txt")
        db = _db(
            [
                _result(scalar_one=None),
                _result(first=(shared, "owner@example.com", "Ops")),
            ]
        )
        fake_path = MagicMock()
        fake_path.exists.return_value = True

        with patch("app.api.files.get_file_path", return_value=fake_path):
            response = await download_authenticated_file(shared.id, user=member, db=db)

        self.assertEqual(response.filename, "team.txt")

    async def test_team_member_cannot_create_public_share_for_shared_file(self) -> None:
        member = _user()
        file_id = uuid.uuid4()
        db = _db([_result(scalar_one=None)])

        with self.assertRaises(HTTPException) as ctx:
            await create_share(
                file_id,
                CreateFileShareRequest(),
                request=MagicMock(),
                user=member,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
        db.commit.assert_not_called()

    async def test_team_shared_entities_include_files(self) -> None:
        member = _user()
        team_id = uuid.uuid4()
        file_id = uuid.uuid4()
        team = SimpleNamespace(id=team_id)
        db = _db(
            [
                _result(scalar_one=team),
                _result(all_rows=[]),
                _result(all_rows=[]),
                _result(all_rows=[]),
                _result(all_rows=[]),
                _result(all_rows=[]),
                _result(all_rows=[]),
                _result(all_rows=[]),
                _result(all_rows=[(file_id, "shared-report.pdf")]),
            ]
        )

        response = await get_team_shared_entities(team_id, db=db, current_user=member)

        self.assertEqual(len(response.files), 1)
        self.assertEqual(response.files[0].id, file_id)
        self.assertEqual(response.files[0].name, "shared-report.pdf")


if __name__ == "__main__":
    unittest.main()
