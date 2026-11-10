"""Vector store uploads read in the background (audio, PDFs with scanned pages).

A job runs as an asyncio task in the process that accepted the upload, so the file only has to
exist on that host: it waits in `<tempdir>/heym-rag-ingest/<job id>`. Each process reads one
such file at a time, which keeps concurrent uploads from saturating the instance.

The job's row moves `heartbeat_at` every 30 seconds. A process that dies (restart, crash,
worker recycle) stops the heartbeat; the next listing of the store's jobs marks the row
failed. This needs no startup hook and no leader, and holds with several uvicorn workers per
instance and several instances.

Audit lines are written by the router when a job is queued, never from here (AGENTS.md).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, VectorStore, VectorStoreIngestJob
from app.db.session import async_session_maker
from app.services import rag_ingest
from app.services.encryption import decrypt_config
from app.services.file_processor import TextChunk
from app.services.rag_ingest import RagFileKind
from app.services.vector_store import create_vector_store_service_for_credential

logger = logging.getLogger(__name__)

QUEUED = "queued"
PROCESSING = "processing"
FAILED = "failed"
ACTIVE_STATUSES = (QUEUED, PROCESSING)

HEARTBEAT_SECONDS = 30
STALE_AFTER = timedelta(minutes=3)
MAX_CONCURRENT_JOBS = 1
MAX_ERROR_CHARS = 2000

RESTARTED_MESSAGE = "Processing stopped because Heym restarted. Upload the file again."
GENERIC_FAILURE = "Heym could not read this file."
MISSING_STORE_MESSAGE = "The vector store or its credential no longer exists."

_tasks: set[asyncio.Task[None]] = set()
_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


@dataclass(frozen=True)
class _Target:
    collection: str
    credential_type: object
    config: dict


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _work_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "heym-rag-ingest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_file_path(job_id: uuid.UUID) -> Path:
    """Where a job's upload waits; named by the job id, never by the uploaded name."""
    return _work_dir() / str(job_id)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        _semaphores[loop] = semaphore
    return semaphore


async def enqueue(
    db: AsyncSession,
    *,
    store_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    kind: RagFileKind,
    override_duplicates: bool,
) -> uuid.UUID:
    """Record a background job for an upload, keep its bytes, and start it."""
    job = VectorStoreIngestJob(
        id=uuid.uuid4(),
        vector_store_id=store_id,
        created_by_id=user_id,
        filename=filename,
        file_size=len(data),
        kind=kind.value,
        status=QUEUED,
        override_duplicates=override_duplicates,
        heartbeat_at=_now(),
    )
    db.add(job)
    await db.flush()
    await asyncio.to_thread(job_file_path(job.id).write_bytes, data)
    # get_db commits after the response is sent; the job's task must see the row now.
    await db.commit()
    start(job.id)
    return job.id


def start(job_id: uuid.UUID) -> None:
    """Run a job in this process; the task is kept referenced until it ends."""
    task = asyncio.create_task(run_job(job_id), name=f"rag-ingest-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_job(job_id: uuid.UUID) -> None:
    """Read a queued job's file into its store and delete the row, or record why not."""
    beat = asyncio.create_task(_heartbeat(job_id))
    try:
        async with _semaphore():
            await _process(job_id)
    except Exception:  # noqa: BLE001 - a background job must never die without a trace
        logger.exception("RAG ingest job %s failed", job_id)
        await _mark_failed(job_id, GENERIC_FAILURE)
    finally:
        beat.cancel()
        job_file_path(job_id).unlink(missing_ok=True)


async def _process(job_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        job = await db.get(VectorStoreIngestJob, job_id)
        if job is None or job.status != QUEUED:
            return
        store = await db.get(VectorStore, job.vector_store_id)
        credential = await db.get(Credential, store.credential_id) if store else None
        if store is None or credential is None:
            job.status = FAILED
            job.error = MISSING_STORE_MESSAGE
            await db.commit()
            return
        job.status = PROCESSING
        await db.commit()
        target = _Target(
            collection=store.collection_name,
            credential_type=credential.type,
            config=decrypt_config(credential.encrypted_config),
        )
        filename = job.filename
        file_size = job.file_size
        kind = RagFileKind(job.kind)
        override = job.override_duplicates

    try:
        data = await asyncio.to_thread(job_file_path(job_id).read_bytes)
        chunks = await asyncio.to_thread(rag_ingest.extract_chunks, kind, data, filename, file_size)
        await asyncio.to_thread(_write_chunks, target, filename, chunks, override)
    except ValueError as exc:  # OCR, STT, "no text", backend unavailable: shown as they are
        await _mark_failed(job_id, str(exc))
        return

    async with async_session_maker() as db:
        await db.execute(delete(VectorStoreIngestJob).where(VectorStoreIngestJob.id == job_id))
        await db.commit()


def _write_chunks(target: _Target, filename: str, chunks: list[TextChunk], override: bool) -> None:
    """Replace a same-named source only now, so the old one stayed searchable meanwhile."""
    service = create_vector_store_service_for_credential(target.credential_type, target.config)
    if override:
        service.delete_by_source(target.collection, filename)
    if chunks:
        service.insert_batch(
            target.collection,
            [chunk.text for chunk in chunks],
            [chunk.metadata for chunk in chunks],
        )


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    async with async_session_maker() as db:
        await db.execute(
            update(VectorStoreIngestJob)
            .where(VectorStoreIngestJob.id == job_id)
            .values(status=FAILED, error=message[:MAX_ERROR_CHARS], updated_at=_now())
        )
        await db.commit()


async def _heartbeat(job_id: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            async with async_session_maker() as db:
                await db.execute(
                    update(VectorStoreIngestJob)
                    .where(
                        VectorStoreIngestJob.id == job_id,
                        VectorStoreIngestJob.status.in_(ACTIVE_STATUSES),
                    )
                    .values(heartbeat_at=_now())
                )
                await db.commit()
        except Exception:  # noqa: BLE001 - a missed beat must not end the job
            logger.warning("RAG ingest heartbeat for %s failed", job_id, exc_info=True)


async def has_active_job(db: AsyncSession, store_id: uuid.UUID, filename: str) -> bool:
    """Whether a live job is reading a file of this name into the store."""
    result = await db.execute(
        select(VectorStoreIngestJob.id)
        .where(
            VectorStoreIngestJob.vector_store_id == store_id,
            VectorStoreIngestJob.filename == filename,
            VectorStoreIngestJob.status.in_(ACTIVE_STATUSES),
            VectorStoreIngestJob.heartbeat_at >= _now() - STALE_AFTER,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def fail_stale_jobs(db: AsyncSession, store_id: uuid.UUID) -> None:
    """Mark the store's jobs whose process stopped beating as failed."""
    result = await db.execute(
        update(VectorStoreIngestJob)
        .where(
            VectorStoreIngestJob.vector_store_id == store_id,
            VectorStoreIngestJob.status.in_(ACTIVE_STATUSES),
            VectorStoreIngestJob.heartbeat_at < _now() - STALE_AFTER,
        )
        .values(status=FAILED, error=RESTARTED_MESSAGE, updated_at=_now())
        .returning(VectorStoreIngestJob.id)
        .execution_options(synchronize_session=False)
    )
    stale = list(result.scalars())
    if not stale:
        return
    await db.commit()
    for job_id in stale:
        job_file_path(job_id).unlink(missing_ok=True)


async def list_jobs(
    db: AsyncSession, store_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[VectorStoreIngestJob], int]:
    """The store's jobs, newest first, and how many there are."""
    total = await db.scalar(
        select(func.count())
        .select_from(VectorStoreIngestJob)
        .where(VectorStoreIngestJob.vector_store_id == store_id)
    )
    rows = await db.scalars(
        select(VectorStoreIngestJob)
        .where(VectorStoreIngestJob.vector_store_id == store_id)
        .order_by(VectorStoreIngestJob.created_at.desc(), VectorStoreIngestJob.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), int(total or 0)


async def dismiss(
    db: AsyncSession, store_id: uuid.UUID, job_id: uuid.UUID
) -> Literal["deleted", "missing", "running"]:
    """Remove a failed job; a running one stays."""
    job = await db.get(VectorStoreIngestJob, job_id)
    if job is None or job.vector_store_id != store_id:
        return "missing"
    if job.status != FAILED:
        return "running"
    await db.delete(job)
    await db.commit()
    return "deleted"
