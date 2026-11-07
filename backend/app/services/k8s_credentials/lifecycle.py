"""Start and stop Kubernetes credentials with the app."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import httpx

from app.config import settings
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.k8s_credentials import rows
from app.services.k8s_credentials.store import store
from app.services.k8s_credentials.watcher import (
    SecretsForbiddenError,
    SecretWatcher,
    load_config,
    watched_namespace,
)

logger = logging.getLogger("k8s_credentials")

# How often the leader reconciles rows without a watch event. Events only reach a
# process's syncer while it is leader, so this is also how a process that wins the
# lock after its first sync, or takes over from a leader that died, writes its rows.
RECONCILE_SECONDS = 30
_LEADER_POLL_SECONDS = 5


class RowSyncer:
    """Runs `rows.reconcile` on the leader, one pass at a time, never dropping a change."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._dirty = False

    async def __call__(self) -> None:
        if not lock_service.is_leader:
            return
        self._dirty = True
        if self._lock.locked():
            return  # the running pass picks the change up
        async with self._lock:
            while self._dirty:
                self._dirty = False
                async with async_session_maker() as db:
                    await rows.reconcile(db, store.items())


class LeaderReconciler:
    """Reconcile as soon as this process becomes leader, then every RECONCILE_SECONDS."""

    def __init__(self, syncer: RowSyncer) -> None:
        self._syncer = syncer
        self._was_leader = False
        self._last = 0.0

    async def tick(self) -> None:
        leader = lock_service.is_leader
        due = time.monotonic() - self._last >= RECONCILE_SECONDS
        if store.synced and leader and (not self._was_leader or due):
            try:
                await self._syncer()
            except Exception:
                logger.exception("Kubernetes credential row sync failed")
            self._last = time.monotonic()
        self._was_leader = leader

    async def run(self) -> None:
        while True:
            await asyncio.sleep(_LEADER_POLL_SECONDS)
            await self.tick()


_watcher: SecretWatcher | None = None
_leader_task: asyncio.Task[None] | None = None


async def start() -> None:
    """Begin watching. Raises only for a configuration error the API server confirms."""
    global _watcher, _leader_task
    if not settings.k8s_credentials:
        return
    store.enabled = True
    config = load_config()
    syncer = RowSyncer()
    watcher = SecretWatcher(config, watched_namespace(config), on_change=syncer)
    try:
        await asyncio.wait_for(watcher.check_permissions(), timeout=10)
    except SecretsForbiddenError:
        await watcher.stop()
        raise
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        # Not a configuration error: the watch retries, and runs wait for the first sync.
        logger.warning("Kubernetes API unreachable at startup (%s); will keep retrying", exc)
    watcher.start()
    _watcher = watcher
    _leader_task = asyncio.create_task(LeaderReconciler(syncer).run())
    logger.info("Watching Kubernetes credential Secrets in namespace %s", watcher.namespace)


async def stop() -> None:
    global _watcher, _leader_task
    if _leader_task is not None:
        _leader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _leader_task
        _leader_task = None
    if _watcher is not None:
        await _watcher.stop()
        _watcher = None
