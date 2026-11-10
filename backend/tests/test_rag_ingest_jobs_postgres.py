"""rag_ingest_jobs queries against real PostgreSQL: stale jobs, the in-flight check, listing."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Credential, CredentialType, User, VectorStore, VectorStoreIngestJob
from app.services import rag_ingest_jobs


class RagIngestJobsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1 FROM vector_store_ingest_jobs LIMIT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL with migration 154 is not reachable")
        now = datetime.now(timezone.utc)
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            self.user = User(
                email=f"jobs-{uuid.uuid4()}@example.com", hashed_password="x", name="J"
            )
            db.add(self.user)
            await db.flush()
            credential = Credential(
                owner_id=self.user.id, name="RAG", type=CredentialType.rag, encrypted_config="x"
            )
            db.add(credential)
            await db.flush()
            self.store = VectorStore(
                name="Calls",
                collection_name=f"calls-{uuid.uuid4()}",
                owner_id=self.user.id,
                credential_id=credential.id,
            )
            self.other = VectorStore(
                name="Other",
                collection_name=f"other-{uuid.uuid4()}",
                owner_id=self.user.id,
                credential_id=credential.id,
            )
            db.add_all([self.store, self.other])
            await db.flush()

            def job(
                store: VectorStore, name: str, status: str, age: timedelta
            ) -> VectorStoreIngestJob:
                return VectorStoreIngestJob(
                    vector_store_id=store.id,
                    filename=name,
                    file_size=1,
                    kind="audio",
                    status=status,
                    heartbeat_at=now - age,
                    created_at=now - age,
                )

            self.jobs = {
                "live": job(self.store, "live.mp3", "processing", timedelta(seconds=10)),
                "stale": job(self.store, "stale.mp3", "processing", timedelta(minutes=10)),
                "stale_queued": job(self.store, "q.mp3", "queued", timedelta(minutes=5)),
                "failed": job(self.store, "failed.mp3", "failed", timedelta(minutes=11)),
                "elsewhere": job(self.other, "stale.mp3", "processing", timedelta(minutes=10)),
            }
            db.add_all(self.jobs.values())
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(User).where(User.id == self.user.id))
            await db.commit()
        await self.engine.dispose()

    async def _status(self, key: str) -> tuple[str, str | None]:
        async with AsyncSession(self.engine) as db:
            row = await db.get(VectorStoreIngestJob, self.jobs[key].id)
            return row.status, row.error

    async def test_stale_active_jobs_of_the_store_fail(self) -> None:
        async with AsyncSession(self.engine) as db:
            await rag_ingest_jobs.fail_stale_jobs(db, self.store.id)

        restarted = ("failed", rag_ingest_jobs.RESTARTED_MESSAGE)
        self.assertEqual(await self._status("live"), ("processing", None))
        self.assertEqual(await self._status("stale"), restarted)
        self.assertEqual(await self._status("stale_queued"), restarted)
        self.assertEqual(await self._status("failed"), ("failed", None))
        self.assertEqual((await self._status("elsewhere"))[0], "processing")

    async def test_only_a_live_job_blocks_the_same_name(self) -> None:
        async with AsyncSession(self.engine) as db:
            self.assertTrue(await rag_ingest_jobs.has_active_job(db, self.store.id, "live.mp3"))
            self.assertFalse(await rag_ingest_jobs.has_active_job(db, self.store.id, "stale.mp3"))
            self.assertFalse(await rag_ingest_jobs.has_active_job(db, self.store.id, "failed.mp3"))
            self.assertFalse(await rag_ingest_jobs.has_active_job(db, self.other.id, "live.mp3"))

    async def test_listing_is_newest_first_and_counts_the_store_only(self) -> None:
        async with AsyncSession(self.engine) as db:
            jobs, total = await rag_ingest_jobs.list_jobs(db, self.store.id, limit=2, offset=0)

        self.assertEqual(total, 4)
        self.assertEqual([j.filename for j in jobs], ["live.mp3", "q.mp3"])

    async def test_dismiss_removes_failed_jobs_only(self) -> None:
        async with AsyncSession(self.engine) as db:
            running = await rag_ingest_jobs.dismiss(db, self.store.id, self.jobs["live"].id)
            wrong_store = await rag_ingest_jobs.dismiss(db, self.other.id, self.jobs["failed"].id)
            done = await rag_ingest_jobs.dismiss(db, self.store.id, self.jobs["failed"].id)

        self.assertEqual((running, wrong_store, done), ("running", "missing", "deleted"))
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.get(VectorStoreIngestJob, self.jobs["failed"].id))

    async def test_deleting_the_store_deletes_its_jobs(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(VectorStore).where(VectorStore.id == self.store.id))
            await db.commit()
            left = await db.scalars(
                select(VectorStoreIngestJob.id).where(
                    VectorStoreIngestJob.vector_store_id == self.store.id
                )
            )
            self.assertEqual(list(left), [])
