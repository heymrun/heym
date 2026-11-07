"""A throwaway PostgreSQL database for tests that read table-wide state.

The key check and the re-encryption job look at every credential, the one canary row
and every rotation, so the shared test database (and suites running beside them) would
change their answers. This creates a database on the same server, builds the schema
from the models, and drops it afterwards. Skips when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Base


@dataclass
class IsolatedDatabase:
    name: str
    engine: AsyncEngine
    sessions: async_sessionmaker
    _admin_url: str

    async def drop(self) -> None:
        await self.engine.dispose()
        admin = create_async_engine(
            self._admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        try:
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        finally:
            await admin.dispose()


async def create_isolated_database(test) -> IsolatedDatabase:  # noqa: ANN001 - a TestCase
    url = make_url(settings.database_url)
    admin_url = url.set(database="postgres").render_as_string(hide_password=False)
    name = f"heym_test_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - any connection failure means "no PostgreSQL"
        await admin.dispose()
        test.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
    await admin.dispose()

    engine = create_async_engine(
        url.set(database=name).render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return IsolatedDatabase(
        name=name,
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
        _admin_url=admin_url,
    )
