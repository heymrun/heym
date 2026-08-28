from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _application_name() -> str:
    """Tag every connection with this instance, so the admin view can tell a
    stopped container from one that merely missed a heartbeat."""
    from app.services.cluster.identity import instance_id

    return f"heym-{instance_id()}"


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    connect_args={"server_settings": {"application_name": _application_name()}},
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def libpq_dsn() -> str:
    """Plain libpq URL for consumers that bypass SQLAlchemy's async driver prefix.

    Used by the sync engine and by the raw asyncpg connections that hold
    LISTEN/NOTIFY channels open.
    """
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


sync_database_url = libpq_dsn()
sync_engine = create_engine(
    sync_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.db_sync_pool_size,
    max_overflow=settings.db_sync_max_overflow,
    connect_args={"application_name": _application_name()},
)

SessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
