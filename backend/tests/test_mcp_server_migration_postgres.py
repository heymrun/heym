"""PostgreSQL integration test for migration 155_mcp_server_endpoint_path.

Verifies against a live PostgreSQL database:
1. Starts with the pre-migration mcp_servers schema.
2. Inserts an existing server record.
3. Applies migration 155_mcp_server_endpoint_path.
4. Verifies that the existing record has endpoint_path = 'sse'.
5. Inserts a new record without explicitly specifying the field.
6. Verifies that its database default is 'mcp'.
7. Verifies downgrade behavior.
"""

from __future__ import annotations

import importlib.util
import unittest
import uuid
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "155_mcp_server_endpoint_path.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_155_mcp_server_endpoint_path", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPServerMigrationPostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
        except Exception as exc:
            await self.engine.dispose()
            self.skipTest(f"PostgreSQL database is not reachable ({type(exc).__name__})")
        self.migration = _load_migration()
        self.schema_name = f"test_mig_155_{uuid.uuid4().hex[:12]}"

    async def asyncTearDown(self) -> None:
        if hasattr(self, "engine"):
            if hasattr(self, "schema_name"):
                try:
                    async with self.engine.connect() as conn:
                        await conn.execute(
                            sa.text(f'DROP SCHEMA IF EXISTS "{self.schema_name}" CASCADE')
                        )
                        await conn.commit()
                except Exception:
                    pass
            await self.engine.dispose()

    async def test_migration_155_lifecycle_on_postgres(self) -> None:
        def run_lifecycle(conn: Connection) -> None:
            # Set search path to our isolated schema
            conn.execute(sa.text(f'CREATE SCHEMA "{self.schema_name}"'))
            conn.execute(sa.text(f'SET search_path TO "{self.schema_name}", public'))

            # 1. Starts with the pre-migration mcp_servers schema (no endpoint_path column)
            conn.execute(
                sa.text(
                    """
                    CREATE TABLE mcp_servers (
                        id UUID PRIMARY KEY,
                        user_id UUID NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        api_key VARCHAR(64) NOT NULL UNIQUE,
                        chat_enabled BOOLEAN DEFAULT FALSE NOT NULL,
                        chat_credential_id UUID,
                        chat_model VARCHAR(128),
                        a2a_enabled BOOLEAN DEFAULT FALSE NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                    )
                    """
                )
            )

            # 2. Inserts an existing server record
            legacy_id = uuid.uuid4()
            user_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    """
                    INSERT INTO mcp_servers (id, user_id, name, api_key, chat_enabled, a2a_enabled)
                    VALUES (:id, :user_id, 'Legacy Server', 'key-legacy-123', false, false)
                    """
                ),
                {"id": legacy_id, "user_id": user_id},
            )

            # 3. Applies migration 155_mcp_server_endpoint_path
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                self.migration.upgrade()

            # 4. Verifies that the existing record has endpoint_path = 'sse'
            legacy_row = conn.execute(
                sa.text("SELECT endpoint_path FROM mcp_servers WHERE id = :id"),
                {"id": legacy_id},
            ).scalar_one()
            self.assertEqual(legacy_row, "sse")

            # 5. Inserts a new record without explicitly specifying the field
            new_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    """
                    INSERT INTO mcp_servers (id, user_id, name, api_key, chat_enabled, a2a_enabled)
                    VALUES (:id, :user_id, 'New Server', 'key-new-456', false, false)
                    """
                ),
                {"id": new_id, "user_id": user_id},
            )

            # 6. Verifies that its database default is 'mcp'
            new_row = conn.execute(
                sa.text("SELECT endpoint_path FROM mcp_servers WHERE id = :id"),
                {"id": new_id},
            ).scalar_one()
            self.assertEqual(new_row, "mcp")

            # 7. Verifies downgrade behavior
            with Operations.context(ctx):
                self.migration.downgrade()

            # Verify endpoint_path is dropped
            col_check = conn.execute(
                sa.text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = 'mcp_servers' AND column_name = 'endpoint_path'
                    """
                ),
                {"schema": self.schema_name},
            ).scalar_one_or_none()
            self.assertIsNone(col_check)

            # And querying endpoint_path raises an error
            with self.assertRaises(sa.exc.ProgrammingError):
                conn.execute(sa.text("SELECT endpoint_path FROM mcp_servers"))

        async with self.engine.connect() as conn:
            await conn.run_sync(run_lifecycle)


if __name__ == "__main__":
    unittest.main()
