import asyncio
import hashlib
import logging
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker

logger = logging.getLogger("distributed_lock")


def _string_to_lock_id(key: str) -> int:
    hash_bytes = hashlib.md5(key.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big", signed=True)


class DistributedLockService:
    def __init__(self) -> None:
        self._worker_id: str = f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._is_leader = False
        self._leader_task: asyncio.Task | None = None
        self._running = False
        self._leader_lock_id = _string_to_lock_id("heym:leader:lock")
        self._leader_session: AsyncSession | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    async def start(self) -> None:
        self._running = True
        self._leader_task = asyncio.create_task(self._leader_election_loop())
        logger.info("Distributed lock service started (worker_id=%s)", self._worker_id)

    async def stop(self) -> None:
        self._running = False
        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass
        await self._release_leader_session()
        logger.info("Distributed lock service stopped")

    async def _release_leader_session(self) -> None:
        if self._leader_session:
            try:
                await self._leader_session.close()
            except Exception:
                pass
            self._leader_session = None
            self._is_leader = False

    async def _leader_election_loop(self) -> None:
        check_count = 0
        while self._running:
            try:
                if self._is_leader:
                    still_valid = await self._check_leader_lock_valid()
                    if not still_valid:
                        logger.info("Worker %s lost leader status", self._worker_id)
                        await self._release_leader_session()
                    else:
                        check_count += 1
                        if check_count % 12 == 0:
                            logger.info(
                                "Worker %s still leader (check #%d)", self._worker_id, check_count
                            )
                else:
                    acquired = await self._try_acquire_leader_lock()
                    if acquired:
                        self._is_leader = True
                        check_count = 0
                        logger.info("Worker %s became the leader", self._worker_id)
            except Exception as e:
                logger.exception("Error in leader election loop: %s", e)
                await self._release_leader_session()

            await asyncio.sleep(5)

    async def _try_acquire_leader_lock(self) -> bool:
        try:
            self._leader_session = async_session_maker()
            result = await self._leader_session.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": self._leader_lock_id},
            )
            row = result.fetchone()
            acquired = row[0] if row else False
            if not acquired:
                await self._release_leader_session()
            return acquired
        except Exception as e:
            logger.warning("Failed to acquire leader lock: %s", e)
            await self._release_leader_session()
            return False

    async def _check_leader_lock_valid(self) -> bool:
        if not self._leader_session:
            return False
        try:
            await self._leader_session.execute(
                text("SELECT pg_advisory_lock_shared(:lock_id)"),
                {"lock_id": self._leader_lock_id},
            )
            await self._leader_session.execute(
                text("SELECT pg_advisory_unlock_shared(:lock_id)"),
                {"lock_id": self._leader_lock_id},
            )
            return True
        except Exception:
            return False

    async def check_cron_execution(
        self,
        workflow_id: str,
        node_id: str,
        minute_key: str,
    ) -> bool:
        lock_key = f"cron:{workflow_id}:{node_id}:{minute_key}"
        lock_id = _string_to_lock_id(lock_key)

        try:
            async with async_session_maker() as db:
                result = await db.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
                row = result.fetchone()
                return row[0] if row else False
        except Exception as e:
            logger.warning("Failed to check cron execution lock: %s", e)
            return False


lock_service = DistributedLockService()
