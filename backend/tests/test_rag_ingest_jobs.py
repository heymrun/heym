"""Background vector store uploads: one job's run, with sessions and backends mocked."""

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.db.models import Credential, CredentialType, VectorStore, VectorStoreIngestJob
from app.services import rag_ingest_jobs
from app.services.file_processor import TextChunk
from app.services.rag_ingest import RagFileKind, RagIngestError


class _Sessions:
    """Stands in for async_session_maker: every `async with` yields the same mock session."""

    def __init__(self, db: AsyncMock) -> None:
        self.db = db

    def __call__(self) -> "_Sessions":
        return self

    async def __aenter__(self) -> AsyncMock:
        return self.db

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class RunJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Calls",
            collection_name="calls",
            owner_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
        )
        self.credential = Credential(
            id=self.store.credential_id,
            owner_id=self.store.owner_id,
            name="RAG",
            type=CredentialType.rag,
            encrypted_config="x",
        )
        self.job = VectorStoreIngestJob(
            id=uuid.uuid4(),
            vector_store_id=self.store.id,
            filename="call.mp3",
            file_size=3,
            kind=RagFileKind.AUDIO.value,
            status="queued",
            override_duplicates=True,
        )
        rows = {
            VectorStoreIngestJob: self.job,
            VectorStore: self.store,
            Credential: self.credential,
        }
        self.db = AsyncMock()
        self.db.get = AsyncMock(side_effect=lambda model, _key: rows[model])
        self.db.add = Mock()
        self.service = Mock()
        work_dir = Path(self.tmp.name)
        for target, value in (
            ("app.services.rag_ingest_jobs.async_session_maker", _Sessions(self.db)),
            ("app.services.rag_ingest_jobs._work_dir", Mock(return_value=work_dir)),
            ("app.services.rag_ingest_jobs.decrypt_config", Mock(return_value={})),
            (
                "app.services.rag_ingest_jobs.create_vector_store_service_for_credential",
                Mock(return_value=self.service),
            ),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        rag_ingest_jobs.job_file_path(self.job.id).write_bytes(b"mp3")

    async def test_success_replaces_the_old_source_inserts_and_deletes_the_row(self) -> None:
        chunks = [TextChunk(text="Hello", metadata={"source": "call.mp3"})]
        with patch("app.services.rag_ingest.extract_chunks", return_value=chunks) as extract:
            await rag_ingest_jobs.run_job(self.job.id)

        extract.assert_called_once_with(RagFileKind.AUDIO, b"mp3", "call.mp3", 3)
        self.service.delete_by_source.assert_called_once_with("calls", "call.mp3")
        self.service.insert_batch.assert_called_once_with(
            "calls", ["Hello"], [{"source": "call.mp3"}]
        )
        self.assertEqual(self.job.status, "processing")
        deleted = self.db.execute.await_args_list[-1].args[0]
        self.assertEqual(deleted.table.name, "vector_store_ingest_jobs")
        self.assertEqual(deleted.__visit_name__, "delete")
        self.assertFalse(rag_ingest_jobs.job_file_path(self.job.id).exists())

    async def test_a_read_error_keeps_the_old_source_and_records_the_message(self) -> None:
        with (
            patch(
                "app.services.rag_ingest.extract_chunks",
                side_effect=RagIngestError("No speech was found in call.mp3."),
            ),
            patch.object(rag_ingest_jobs, "_mark_failed", new=AsyncMock()) as failed,
        ):
            await rag_ingest_jobs.run_job(self.job.id)

        failed.assert_awaited_once_with(self.job.id, "No speech was found in call.mp3.")
        self.service.delete_by_source.assert_not_called()
        self.service.insert_batch.assert_not_called()
        self.assertFalse(rag_ingest_jobs.job_file_path(self.job.id).exists())

    async def test_an_unexpected_error_records_a_generic_message(self) -> None:
        with (
            patch("app.services.rag_ingest.extract_chunks", side_effect=RuntimeError("boom")),
            patch.object(rag_ingest_jobs, "_mark_failed", new=AsyncMock()) as failed,
            self.assertLogs("app.services.rag_ingest_jobs", level="ERROR"),
        ):
            await rag_ingest_jobs.run_job(self.job.id)

        failed.assert_awaited_once_with(self.job.id, rag_ingest_jobs.GENERIC_FAILURE)

    async def test_a_job_that_is_no_longer_queued_is_left_alone(self) -> None:
        self.job.status = "failed"
        with patch("app.services.rag_ingest.extract_chunks") as extract:
            await rag_ingest_jobs.run_job(self.job.id)

        extract.assert_not_called()

    async def test_a_store_without_its_credential_fails_the_job(self) -> None:
        rows = {VectorStoreIngestJob: self.job, VectorStore: self.store, Credential: None}
        self.db.get = AsyncMock(side_effect=lambda model, _key: rows[model])
        with patch("app.services.rag_ingest.extract_chunks") as extract:
            await rag_ingest_jobs.run_job(self.job.id)

        extract.assert_not_called()
        self.assertEqual(self.job.status, "failed")
        self.assertEqual(self.job.error, rag_ingest_jobs.MISSING_STORE_MESSAGE)


class EnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_writes_the_file_commits_and_starts_the_job(self) -> None:
        db = AsyncMock()
        db.add = Mock()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("app.services.rag_ingest_jobs._work_dir", return_value=Path(tmp)),
            patch("app.services.rag_ingest_jobs.start") as start,
        ):
            job_id = await rag_ingest_jobs.enqueue(
                db,
                store_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                filename="../../etc/passwd.mp3",
                data=b"audio",
                kind=RagFileKind.AUDIO,
                override_duplicates=False,
            )
            written = Path(tmp) / str(job_id)
            self.assertEqual(written.read_bytes(), b"audio")

        job = db.add.call_args.args[0]
        self.assertEqual(job.id, job_id)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.kind, "audio")
        db.commit.assert_awaited_once()
        start.assert_called_once_with(job_id)
