"""The vector store upload route and its background job routes."""

import io
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile

from app.db.models import Credential, CredentialType, VectorStore, VectorStoreIngestJob
from app.services.ocr_service import OcrResult


def _result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class UploadRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Docs",
            collection_name="docs",
            owner_id=self.user.id,
            credential_id=uuid.uuid4(),
        )
        credential = Credential(
            id=self.store.credential_id,
            owner_id=self.user.id,
            name="RAG",
            type=CredentialType.rag,
            encrypted_config="x",
        )
        self.db = AsyncMock()
        self.db.execute = AsyncMock(return_value=_result(credential))
        self.service = Mock()
        self.service.insert_batch.return_value = ["p1"]
        self.has_active = AsyncMock(return_value=False)
        self.enqueue = AsyncMock(return_value=uuid.uuid4())
        self.audit = Mock()
        for target, value in (
            ("app.api.vector_stores._get_accessible_store", AsyncMock(return_value=self.store)),
            ("app.api.vector_stores.decrypt_config", Mock(return_value={})),
            (
                "app.api.vector_stores.get_vector_store_service_from_config",
                Mock(return_value=self.service),
            ),
            ("app.api.vector_stores.rag_ingest_jobs.has_active_job", self.has_active),
            ("app.api.vector_stores.rag_ingest_jobs.enqueue", self.enqueue),
            ("app.api.vector_stores.audit", self.audit),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _upload(self, name: str, data: bytes, override: bool = False):
        from app.api.vector_stores import upload_file_to_vector_store

        return await upload_file_to_vector_store(
            self.store.id,
            file=UploadFile(file=io.BytesIO(data), filename=name),
            override_duplicates=override,
            current_user=self.user,
            db=self.db,
        )

    async def test_utf8_file_of_any_name_is_added_now(self) -> None:
        response = await self._upload("burak.akgun", "açık issue listesi".encode())

        self.assertEqual(response.status, "done")
        self.assertEqual(response.points_inserted, 1)
        _, texts, metadata = self.service.insert_batch.call_args.args
        self.assertIn("açık issue listesi", texts[0])
        self.assertEqual(metadata[0]["file_type"], "text")
        self.assertEqual(metadata[0]["source"], "burak.akgun")

    async def test_unknown_binary_file_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await self._upload("report.docx", b"PK\x03\x04\x00\x00")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Heym cannot read report.docx", raised.exception.detail)
        self.service.insert_batch.assert_not_called()

    async def test_image_is_read_by_ocr_now(self) -> None:
        ocr = OcrResult(text="Total 40 EUR", language="eng", encoding="utf-8")
        with patch("app.services.ocr_service.image_to_text", return_value=ocr):
            response = await self._upload("receipt.jpg", b"\xff\xd8\xff\x00")

        self.assertEqual(response.status, "done")
        self.assertEqual(self.service.insert_batch.call_args.args[2][0]["file_type"], "image")

    async def test_image_without_text_is_unprocessable(self) -> None:
        ocr = OcrResult(text="", language="eng", encoding="utf-8")
        with patch("app.services.ocr_service.image_to_text", return_value=ocr):
            with self.assertRaises(HTTPException) as raised:
                await self._upload("blank.png", b"\x89PNG\x00")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "No text was found in blank.png.")

    async def test_audio_is_queued_and_audited(self) -> None:
        response = await self._upload("call.mp3", b"ID3\x00", override=True)

        self.assertEqual(response.status, "queued")
        self.assertEqual(response.job_id, self.enqueue.return_value)
        self.assertEqual((response.chunks_processed, response.points_inserted), (0, 0))
        kwargs = self.enqueue.await_args.kwargs
        self.assertEqual(kwargs["filename"], "call.mp3")
        self.assertTrue(kwargs["override_duplicates"])
        self.service.delete_by_source.assert_not_called()
        self.assertTrue(self.audit.call_args.kwargs["queued"])

    async def test_same_name_in_flight_conflicts(self) -> None:
        self.has_active.return_value = True

        with self.assertRaises(HTTPException) as raised:
            await self._upload("call.mp3", b"ID3\x00")

        self.assertEqual(raised.exception.status_code, 409)
        self.enqueue.assert_not_awaited()

    async def test_override_deletes_the_old_source_after_reading_the_new_one(self) -> None:
        order: list[str] = []
        self.service.delete_by_source.side_effect = lambda *_: order.append("delete")
        self.service.insert_batch.side_effect = lambda *_: order.append("insert") or ["p"]

        await self._upload("faq.md", b"# FAQ", override=True)

        self.assertEqual(order, ["delete", "insert"])
        self.service.delete_by_source.assert_called_once_with("docs", "faq.md")

    async def test_a_read_error_keeps_the_old_source(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await self._upload("broken.json", b"{oops", override=True)

        self.assertEqual(raised.exception.status_code, 422)
        self.service.delete_by_source.assert_not_called()


class IngestJobRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Docs",
            collection_name="docs",
            owner_id=self.user.id,
            credential_id=uuid.uuid4(),
        )
        patcher = patch(
            "app.api.vector_stores._get_accessible_store", AsyncMock(return_value=self.store)
        )
        self.accessible = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_listing_fails_stale_jobs_first(self) -> None:
        from app.api.vector_stores import list_ingest_jobs

        now = datetime.now(timezone.utc)
        job = VectorStoreIngestJob(
            id=uuid.uuid4(),
            vector_store_id=self.store.id,
            filename="call.mp3",
            file_size=10,
            kind="audio",
            status="processing",
            error=None,
            created_at=now,
            updated_at=now,
        )
        db = AsyncMock()
        with (
            patch(
                "app.api.vector_stores.rag_ingest_jobs.fail_stale_jobs", new=AsyncMock()
            ) as stale,
            patch(
                "app.api.vector_stores.rag_ingest_jobs.list_jobs",
                new=AsyncMock(return_value=([job], 1)),
            ),
        ):
            response = await list_ingest_jobs(
                self.store.id, limit=100, offset=0, current_user=self.user, db=db
            )

        stale.assert_awaited_once_with(db, self.store.id)
        self.assertEqual(response.total, 1)
        self.assertEqual(response.jobs[0].status, "processing")
        self.assertEqual(response.jobs[0].filename, "call.mp3")

    async def test_listing_needs_store_access(self) -> None:
        from app.api.vector_stores import list_ingest_jobs

        self.accessible.side_effect = HTTPException(
            status_code=404, detail="Vector store not found"
        )
        with patch("app.api.vector_stores.rag_ingest_jobs.list_jobs", new=AsyncMock()) as listed:
            with self.assertRaises(HTTPException) as raised:
                await list_ingest_jobs(
                    self.store.id, limit=100, offset=0, current_user=self.user, db=AsyncMock()
                )

        self.assertEqual(raised.exception.status_code, 404)
        listed.assert_not_awaited()

    async def test_dismiss_maps_outcomes(self) -> None:
        from app.api.vector_stores import dismiss_ingest_job

        for outcome, code in (("missing", 404), ("running", 409)):
            with patch(
                "app.api.vector_stores.rag_ingest_jobs.dismiss",
                new=AsyncMock(return_value=outcome),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await dismiss_ingest_job(
                        self.store.id, uuid.uuid4(), current_user=self.user, db=AsyncMock()
                    )
            self.assertEqual(raised.exception.status_code, code)

        with patch(
            "app.api.vector_stores.rag_ingest_jobs.dismiss", new=AsyncMock(return_value="deleted")
        ):
            self.assertIsNone(
                await dismiss_ingest_job(
                    self.store.id, uuid.uuid4(), current_user=self.user, db=AsyncMock()
                )
            )
