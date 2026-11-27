"""Real PostgreSQL concurrency and constraint tests for file share downloads.

Tests that concurrent downloads respect max_downloads limits without races,
using asyncio.Barrier to synchronize concurrent requests after validation reads
and file/disk checks, but before claiming the atomic increment.

Covers both:
- GET /api/files/dl/{token} (bearer token)
- GET /api/files/ba/{file_id} (Basic auth)

Also covers negative cases:
- Exhausted links stay rejected without increments
- Missing files (database or disk) leave download_count unchanged
- Expired links stay rejected
- Unlimited links count every download
"""

from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bcrypt
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

import app.api.files as files_api
from app.config import settings
from app.db.models import FileAccessToken, GeneratedFile, User


def _make_basic_auth_request(username: str, password: str) -> Request:
    creds = f"{username}:{password}"
    encoded = base64.b64encode(creds.encode("utf-8")).decode("utf-8")
    return Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [(b"authorization", f"Basic {encoded}".encode("utf-8"))],
        }
    )


class RealPostgresFileShareDownloadConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")

        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.storage_patcher = patch(
            "app.services.file_storage._storage_root", return_value=self.storage_dir
        )
        self.storage_patcher.start()

        self.owner_id = uuid.uuid4()
        async with self.session_factory() as session:
            user = User(
                id=self.owner_id,
                email=f"shares_{self.owner_id.hex[:8]}@example.com",
                hashed_password="x",
                name="Share Owner",
            )
            session.add(user)
            await session.commit()

    async def asyncTearDown(self) -> None:
        self.storage_patcher.stop()
        self.temp_dir.cleanup()
        try:
            async with self.session_factory() as session:
                await session.execute(
                    delete(FileAccessToken).where(FileAccessToken.created_by_id == self.owner_id)
                )
                await session.execute(
                    delete(GeneratedFile).where(GeneratedFile.owner_id == self.owner_id)
                )
                await session.execute(delete(User).where(User.id == self.owner_id))
                await session.commit()
        finally:
            await self.engine.dispose()

    async def _create_file_fixture(
        self,
        *,
        write_disk: bool = True,
        filename: str = "document.txt",
        content: bytes = b"test payload content",
    ) -> GeneratedFile:
        file_id = uuid.uuid4()
        rel_path = f"{self.owner_id}/{file_id}/{filename}"
        if write_disk:
            disk_path = self.storage_dir / rel_path
            disk_path.parent.mkdir(parents=True, exist_ok=True)
            disk_path.write_bytes(content)

        async with self.session_factory() as session:
            file_row = GeneratedFile(
                id=file_id,
                owner_id=self.owner_id,
                filename=filename,
                storage_path=rel_path,
                mime_type="text/plain",
                size_bytes=len(content),
            )
            session.add(file_row)
            await session.commit()
            return file_row

    async def _create_share_token(
        self,
        file_id: uuid.UUID,
        *,
        token_str: str | None = None,
        max_downloads: int | None = 1,
        download_count: int = 0,
        expires_at: datetime | None = None,
        basic_auth_password: str | None = None,
    ) -> FileAccessToken:
        pw_hash = (
            bcrypt.hashpw(basic_auth_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            if basic_auth_password
            else None
        )
        token_id = uuid.uuid4()
        token = token_str or f"token_{uuid.uuid4().hex}"

        async with self.session_factory() as session:
            tok_row = FileAccessToken(
                id=token_id,
                file_id=file_id,
                token=token,
                basic_auth_username="file" if basic_auth_password else None,
                basic_auth_password_hash=pw_hash,
                max_downloads=max_downloads,
                download_count=download_count,
                expires_at=expires_at,
                created_by_id=self.owner_id,
            )
            session.add(tok_row)
            await session.commit()
            return tok_row

    async def _get_token_row(self, token_id: uuid.UUID) -> FileAccessToken:
        async with self.session_factory() as session:
            stmt = select(FileAccessToken).where(FileAccessToken.id == token_id)
            return (await session.execute(stmt)).scalar_one()

    # ---- Concurrency tests with Barrier ----

    async def test_concurrent_bearer_downloads_single_winner_and_loser_404(self) -> None:
        file_row = await self._create_file_fixture(content=b"bearer race content")
        token_row = await self._create_share_token(file_row.id, max_downloads=1, download_count=0)

        barrier = asyncio.Barrier(2)
        real_increment = files_api.increment_download_count

        async def synchronized_increment(db: AsyncSession, access_token: FileAccessToken) -> bool:
            await barrier.wait()
            return await real_increment(db, access_token)

        async def run_download(client_id: int) -> dict:
            async with self.session_factory() as session:
                try:
                    response = await files_api.download_via_token(token_row.token, db=session)
                    return {"client_id": client_id, "success": True, "response": response}
                except HTTPException as exc:
                    return {"client_id": client_id, "success": False, "error": exc}

        with patch("app.api.files.increment_download_count", side_effect=synchronized_increment):
            res1, res2 = await asyncio.gather(run_download(1), run_download(2))

        results = [res1, res2]
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]

        self.assertEqual(len(successes), 1, f"Expected 1 winner, got {len(successes)}")
        self.assertEqual(len(failures), 1, f"Expected 1 loser, got {len(failures)}")

        winner_resp = successes[0]["response"]
        self.assertIsInstance(winner_resp, FileResponse)
        self.assertEqual(Path(winner_resp.path).read_bytes(), b"bearer race content")

        loser_err = failures[0]["error"]
        self.assertEqual(loser_err.status_code, 404)
        self.assertEqual(loser_err.detail, "Invalid or expired link")

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 1)

    async def test_concurrent_basic_auth_downloads_single_winner_and_loser_401(self) -> None:
        file_row = await self._create_file_fixture(content=b"basic auth race content")
        token_row = await self._create_share_token(
            file_row.id,
            max_downloads=1,
            download_count=0,
            basic_auth_password="secretpassword",
        )

        barrier = asyncio.Barrier(2)
        real_increment = files_api.increment_download_count

        async def synchronized_increment(db: AsyncSession, access_token: FileAccessToken) -> bool:
            await barrier.wait()
            return await real_increment(db, access_token)

        req = _make_basic_auth_request("file", "secretpassword")

        async def run_download(client_id: int) -> dict:
            async with self.session_factory() as session:
                try:
                    response = await files_api.download_via_basic_auth(file_row.id, req, db=session)
                    return {"client_id": client_id, "success": True, "response": response}
                except HTTPException as exc:
                    return {"client_id": client_id, "success": False, "error": exc}

        with patch("app.api.files.increment_download_count", side_effect=synchronized_increment):
            res1, res2 = await asyncio.gather(run_download(1), run_download(2))

        results = [res1, res2]
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]

        self.assertEqual(len(successes), 1, f"Expected 1 winner, got {len(successes)}")
        self.assertEqual(len(failures), 1, f"Expected 1 loser, got {len(failures)}")

        winner_resp = successes[0]["response"]
        self.assertIsInstance(winner_resp, FileResponse)
        self.assertEqual(Path(winner_resp.path).read_bytes(), b"basic auth race content")

        loser_err = failures[0]["error"]
        self.assertEqual(loser_err.status_code, 401)
        self.assertEqual(loser_err.detail, "Invalid credentials")
        self.assertEqual(loser_err.headers, {"WWW-Authenticate": 'Basic realm="file"'})

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 1)

    # ---- Negative cases: exhausted links ----

    async def test_exhausted_bearer_link_stays_rejected(self) -> None:
        file_row = await self._create_file_fixture()
        token_row = await self._create_share_token(file_row.id, max_downloads=1, download_count=1)

        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as ctx:
                await files_api.download_via_token(token_row.token, db=session)

            self.assertEqual(ctx.exception.status_code, 404)
            self.assertEqual(ctx.exception.detail, "Invalid or expired link")

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 1)

    async def test_exhausted_basic_auth_link_stays_rejected(self) -> None:
        file_row = await self._create_file_fixture()
        token_row = await self._create_share_token(
            file_row.id,
            max_downloads=1,
            download_count=1,
            basic_auth_password="secretpassword",
        )

        req = _make_basic_auth_request("file", "secretpassword")
        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as ctx:
                await files_api.download_via_basic_auth(file_row.id, req, db=session)

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertEqual(ctx.exception.detail, "Invalid credentials")
            self.assertEqual(ctx.exception.headers, {"WWW-Authenticate": 'Basic realm="file"'})

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 1)

    # ---- Negative cases: missing files leave count unchanged ----

    async def test_missing_disk_file_leaves_bearer_count_unchanged(self) -> None:
        file_row = await self._create_file_fixture(write_disk=False)
        token_row = await self._create_share_token(file_row.id, max_downloads=1, download_count=0)

        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as ctx:
                await files_api.download_via_token(token_row.token, db=session)

            self.assertEqual(ctx.exception.status_code, 404)
            self.assertEqual(ctx.exception.detail, "File missing from storage")

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 0)

    async def test_missing_disk_file_leaves_basic_auth_count_unchanged(self) -> None:
        file_row = await self._create_file_fixture(write_disk=False)
        token_row = await self._create_share_token(
            file_row.id,
            max_downloads=1,
            download_count=0,
            basic_auth_password="secretpassword",
        )

        req = _make_basic_auth_request("file", "secretpassword")
        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as ctx:
                await files_api.download_via_basic_auth(file_row.id, req, db=session)

            self.assertEqual(ctx.exception.status_code, 404)
            self.assertEqual(ctx.exception.detail, "File missing from storage")

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 0)

    # ---- Negative cases: expired links ----

    async def test_expired_bearer_link_stays_rejected(self) -> None:
        file_row = await self._create_file_fixture()
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        token_row = await self._create_share_token(
            file_row.id, max_downloads=5, download_count=0, expires_at=past
        )

        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as ctx:
                await files_api.download_via_token(token_row.token, db=session)

            self.assertEqual(ctx.exception.status_code, 404)
            self.assertEqual(ctx.exception.detail, "Invalid or expired link")

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 0)

    async def test_expired_basic_auth_link_stays_rejected(self) -> None:
        file_row = await self._create_file_fixture()
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        token_row = await self._create_share_token(
            file_row.id,
            max_downloads=5,
            download_count=0,
            expires_at=past,
            basic_auth_password="secretpassword",
        )

        req = _make_basic_auth_request("file", "secretpassword")
        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as ctx:
                await files_api.download_via_basic_auth(file_row.id, req, db=session)

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertEqual(ctx.exception.detail, "Invalid credentials")
            self.assertEqual(ctx.exception.headers, {"WWW-Authenticate": 'Basic realm="file"'})

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 0)

    # ---- Positive cases: unlimited links ----

    async def test_unlimited_bearer_link_counts_every_download(self) -> None:
        file_row = await self._create_file_fixture(content=b"unlimited payload")
        token_row = await self._create_share_token(
            file_row.id, max_downloads=None, download_count=0
        )

        for _ in range(3):
            async with self.session_factory() as session:
                response = await files_api.download_via_token(token_row.token, db=session)
                self.assertIsInstance(response, FileResponse)

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 3)

    async def test_unlimited_basic_auth_link_counts_every_download(self) -> None:
        file_row = await self._create_file_fixture(content=b"unlimited basic auth payload")
        token_row = await self._create_share_token(
            file_row.id,
            max_downloads=None,
            download_count=0,
            basic_auth_password="secretpassword",
        )

        req = _make_basic_auth_request("file", "secretpassword")
        for _ in range(3):
            async with self.session_factory() as session:
                response = await files_api.download_via_basic_auth(file_row.id, req, db=session)
                self.assertIsInstance(response, FileResponse)

        persisted = await self._get_token_row(token_row.id)
        self.assertEqual(persisted.download_count, 3)


if __name__ == "__main__":
    unittest.main()
