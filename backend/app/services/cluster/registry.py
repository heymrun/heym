"""The cluster_instances table: heartbeat writes and candidate-pool reads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.models import ClusterInstance
from app.db.session import async_session_maker
from app.services.cluster import identity

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


def is_compatible_with(instance: InstanceView, main: InstanceView) -> bool:
    """Whether this instance can safely execute work main would have executed.

    A version or schema difference means it may not know a node type. A key
    fingerprint difference means it cannot decrypt credentials at all, and the
    resulting failures name nothing useful - so it is excluded up front.
    """
    return (
        instance.version == main.version
        and instance.schema_revision == main.schema_revision
        and instance.keys_fingerprint == main.keys_fingerprint
    )


def find_main(instances: list[InstanceView]) -> InstanceView | None:
    for instance in instances:
        if instance.role == "main":
            return instance
    return None


def candidate_instances(instances: list[InstanceView], *, now: datetime) -> list[InstanceView]:
    """Instances eligible to receive an ANYWHERE run, in stable id order."""
    main = find_main(instances)
    if main is None:
        return []
    eligible = [
        i
        for i in instances
        if i.enabled and i.weight > 0 and is_live(i, now=now) and is_compatible_with(i, main)
    ]
    return sorted(eligible, key=lambda i: i.id)


def _docker_reachable() -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(_DOCKER_SOCKET)
        return True
    except OSError:
        return False


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
        docker_ok=_docker_reachable(),
        db_latency_ms=latency_ms,
        heartbeat_at=datetime.now(timezone.utc),
    )
    # name, enabled and weight are owned by the admin UI: set on insert, never
    # overwritten by a heartbeat, or a restart would undo the operator's changes.
    stmt = (
        pg_insert(ClusterInstance)
        .values(
            **values,
            name=identity.instance_name(),
            enabled=True,
            # Main's 100 is deliberate, so it is never a candidate for seeding.
            # A worker starts unweighted and unconfigured: automatic weighting
            # gives it a share on the leader's next pass, once.
            weight=100 if identity.is_main() else 0,
            weight_configured=identity.is_main(),
        )
        .on_conflict_do_update(index_elements=[ClusterInstance.id], set_=values)
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
