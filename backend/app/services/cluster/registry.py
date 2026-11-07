"""The cluster_instances table: heartbeat writes and candidate-pool reads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.models import ClusterInstance
from app.db.session import async_session_maker
from app.services.cluster import identity
from app.services.k8s_credentials.store import store as k8s_credential_store
from app.services.sandbox import get_sandbox_manager

logger = logging.getLogger("cluster")

# Properties of the mechanism, not deployment configuration.
HEARTBEAT_INTERVAL_SECONDS = 10
LIVENESS_WINDOW_SECONDS = 30
_DOCKER_SOCKET = "/var/run/docker.sock"


@dataclass(frozen=True)
class InstanceView:
    id: str
    name: str
    role: str
    enabled: bool
    weight: int
    weight_configured: bool
    version: str
    schema_revision: str
    keys_fingerprint: str
    docker_ok: bool
    db_latency_ms: float
    heartbeat_at: datetime
    # None until a process of this instance has synced its Kubernetes credentials.
    credentials_synced_at: datetime | None = None
    # Every key it decrypts with, primary first. Empty from an instance that predates
    # key rotation, which can decrypt with its primary only.
    decrypt_fingerprints: tuple[str, ...] = ()


def is_live(instance: InstanceView, *, now: datetime) -> bool:
    """Whether this instance beat recently enough to be given work."""
    return instance.heartbeat_at >= now - timedelta(seconds=LIVENESS_WINDOW_SECONDS)


def is_live_now(instance: InstanceView, *, now: datetime, connected_ids: set[str] | None) -> bool:
    """Liveness for the admin view, which must answer "right now".

    A stopped container drops its database connections within seconds, while its
    last heartbeat stays fresh for the rest of the window - so the heartbeat
    alone cannot report a stop quickly. Requiring both signals makes a stop
    visible on the next Refresh, and still catches an instance whose process is
    up but no longer beating.

    `connected_ids` of None means pg_stat_activity could not be read; fall back
    to the heartbeat rather than declaring a healthy instance dead.
    """
    if not is_live(instance, now=now):
        return False
    if connected_ids is None:
        return True
    return instance.id in connected_ids


def credentials_synced(instance: InstanceView, *, now: datetime) -> bool:
    """Whether a process of this instance with synced Kubernetes credentials beat recently.

    Read like liveness: the timestamp is refreshed on every heartbeat while synced, so
    it goes stale when no process of the instance can serve a Secret-backed credential.
    When the feature is off, every heartbeat counts as synced.
    """
    synced_at = instance.credentials_synced_at
    return synced_at is not None and synced_at >= now - timedelta(seconds=LIVENESS_WINDOW_SECONDS)


def primary_fingerprint(instance: InstanceView) -> str:
    """The ENCRYPTION_KEY half of keys_fingerprint: the key the instance encrypts with."""
    return instance.keys_fingerprint[: len(instance.keys_fingerprint) // 2]


def secret_fingerprint(instance: InstanceView) -> str:
    """The SECRET_KEY half of keys_fingerprint."""
    return instance.keys_fingerprint[len(instance.keys_fingerprint) // 2 :]


def can_decrypt(instance: InstanceView, fingerprint: str) -> bool:
    """Whether the instance holds the key with this fingerprint."""
    return fingerprint in (instance.decrypt_fingerprints or (primary_fingerprint(instance),))


def is_compatible_with(instance: InstanceView, main: InstanceView) -> bool:
    """Whether this instance can safely execute work main would have executed.

    A version or schema difference means it may not know a node type. SECRET_KEY must
    match exactly. ENCRYPTION_KEY need not, during a rotation: each must be able to
    decrypt what the other writes, so main holds this instance's primary and this
    instance holds main's. Outside a rotation that is the same as an exact match.
    """
    return (
        instance.version == main.version
        and instance.schema_revision == main.schema_revision
        and secret_fingerprint(instance) == secret_fingerprint(main)
        and can_decrypt(instance, primary_fingerprint(main))
        and can_decrypt(main, primary_fingerprint(instance))
    )


def compatible_ids(instances: list[InstanceView], *, now: datetime) -> set[str]:
    """Instances that can read what every other one writes, anchored on main.

    First, each instance is compared with main (`is_compatible_with`). Then, among those,
    an instance stays only if it can decrypt the primary of every other live one: during
    a rotation, a worker that skipped phase 1 still matches a main that hasn't rolled
    yet, but can't read rows another worker already wrote under the new key.

    Anchoring on main means a bad instance only excludes itself: a worker that joins with
    a typo in its key fails the first step, so it never pushes main or anyone else out.
    The second step can drop two instances that each fail on the other (three primaries
    at once), which only costs capacity; main can't drop out, and the rollout order
    never produces that state.
    """
    main = find_main(instances)
    if main is None:
        return set()
    first = [i for i in instances if is_compatible_with(i, main)]
    writers = [i for i in first if i.id == main.id or is_live(i, now=now)]
    return {
        i.id
        for i in first
        if all(can_decrypt(i, primary_fingerprint(w)) for w in writers if w.id != i.id)
    }


def find_main(instances: list[InstanceView]) -> InstanceView | None:
    for instance in instances:
        if instance.role == "main":
            return instance
    return None


def candidate_instances(instances: list[InstanceView], *, now: datetime) -> list[InstanceView]:
    """Instances eligible to receive an ANYWHERE run, in stable id order."""
    compatible = compatible_ids(instances, now=now)
    eligible = [
        i
        for i in instances
        if i.enabled
        and i.weight > 0
        and is_live(i, now=now)
        and credentials_synced(i, now=now)
        and i.id in compatible
    ]
    return sorted(eligible, key=lambda i: i.id)


async def may_lead() -> bool:
    """Whether a process of this instance may take the leader lock.

    The leader runs cron, the pollers and the RabbitMQ consumers, which read credentials
    and write them back on an OAuth refresh, so in cluster mode it must pass the same
    compatibility rule as dispatch. Only that rule: not `enabled` or the weight, or a
    main kept at weight 0 for the UI could never lead. Main's last published row counts
    even while main is down, so cron keeps running on a worker then. An instance with no
    heartbeat row yet can't lead, which makes the startup order irrelevant.
    """
    if not settings.cluster_enabled:
        return True
    instances = await list_instances()
    own_id = identity.instance_id()
    if not any(i.id == own_id for i in instances):
        return False
    return own_id in compatible_ids(instances, now=datetime.now(timezone.utc))


def _docker_reachable() -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(_DOCKER_SOCKET)
        return True
    except OSError:
        return False


def _sandbox_reachable() -> bool:
    """``docker_ok`` now means "a sandbox backend is reachable" (column name kept)."""
    manager = get_sandbox_manager()
    if manager.backend_name == "kubernetes":
        return manager.available()
    return _docker_reachable()


APPLICATION_NAME_PREFIX = "heym-"


async def connected_instance_ids() -> set[str] | None:
    """Instance ids holding a database connection, or None if unreadable.

    Every pooled connection is tagged with the instance's id, so this is the
    fastest honest signal that a container is gone.
    """
    try:
        async with async_session_maker() as db:
            rows = await db.execute(
                text(
                    "SELECT DISTINCT application_name FROM pg_stat_activity "
                    "WHERE application_name LIKE :prefix"
                ),
                {"prefix": f"{APPLICATION_NAME_PREFIX}%"},
            )
        return {str(name)[len(APPLICATION_NAME_PREFIX) :] for (name,) in rows.all()}
    except Exception:
        logger.warning("Could not read pg_stat_activity; falling back to heartbeats")
        return None


async def _schema_revision() -> str:
    async with async_session_maker() as db:
        result = await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.first()
        return str(row[0]) if row else ""


async def write_heartbeat() -> None:
    """Upsert this instance's row. Safe to call from all 8 processes."""
    started = time.perf_counter()
    revision = await _schema_revision()
    latency_ms = (time.perf_counter() - started) * 1000

    values = dict(
        id=identity.instance_id(),
        role="main" if identity.is_main() else "worker",
        version=settings.resolved_version,
        schema_revision=revision,
        keys_fingerprint=identity.keys_fingerprint(),
        decrypt_fingerprints=identity.decrypt_fingerprints(),
        docker_ok=await asyncio.to_thread(_sandbox_reachable),
        db_latency_ms=latency_ms,
        heartbeat_at=datetime.now(timezone.utc),
    )
    # Every process of the instance upserts this one row, but sync state is per process.
    # GREATEST keeps the newest synced beat, so an unsynced sibling (None) can't clear it.
    synced_at = values["heartbeat_at"] if k8s_credential_store.ready() else None
    insert = pg_insert(ClusterInstance)
    # name, enabled and weight are owned by the admin UI: set on insert, never
    # overwritten by a heartbeat, or a restart would undo the operator's changes.
    stmt = insert.values(
        **values,
        credentials_synced_at=synced_at,
        name=identity.instance_name(),
        enabled=True,
        # Main's 100 is deliberate, so it is never a candidate for seeding.
        # A worker starts unweighted and unconfigured: automatic weighting
        # gives it a share on the leader's next pass, once.
        weight=100 if identity.is_main() else 0,
        weight_configured=identity.is_main(),
    ).on_conflict_do_update(
        index_elements=[ClusterInstance.id],
        set_={
            **values,
            "credentials_synced_at": func.greatest(
                ClusterInstance.credentials_synced_at, insert.excluded.credentials_synced_at
            ),
        },
    )
    async with async_session_maker() as db:
        await db.execute(stmt)
        await db.commit()


_INSTANCE_CACHE: tuple[float, list[InstanceView]] | None = None
_INSTANCE_CACHE_TTL_SECONDS = 1.0


async def list_instances(*, use_cache: bool = False) -> list[InstanceView]:
    global _INSTANCE_CACHE
    now = time.monotonic()
    if use_cache and _INSTANCE_CACHE and now - _INSTANCE_CACHE[0] < _INSTANCE_CACHE_TTL_SECONDS:
        return _INSTANCE_CACHE[1]

    async with async_session_maker() as db:
        result = await db.execute(select(ClusterInstance))
        views = [
            InstanceView(
                id=row.id,
                name=row.name,
                role=row.role,
                enabled=row.enabled,
                weight=row.weight,
                weight_configured=row.weight_configured,
                version=row.version,
                schema_revision=row.schema_revision,
                keys_fingerprint=row.keys_fingerprint,
                docker_ok=row.docker_ok,
                db_latency_ms=row.db_latency_ms,
                heartbeat_at=row.heartbeat_at,
                credentials_synced_at=row.credentials_synced_at,
                decrypt_fingerprints=tuple(row.decrypt_fingerprints or ()),
            )
            for row in result.scalars().all()
        ]
    _INSTANCE_CACHE = (now, views)
    return views


class ClusterHeartbeatService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Cluster heartbeat started (instance=%s)", identity.instance_id())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await write_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cluster heartbeat failed")
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


heartbeat_service = ClusterHeartbeatService()
