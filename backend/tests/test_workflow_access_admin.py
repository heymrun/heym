"""Instance administration is a parameter of the workflow access helpers.

Heym leaves ``is_admin`` unset and reads ``HEYM_ADMIN_EMAILS``. Heym Work imports the
helpers without Heym's settings, so it passes its own answer, and calling them must
never load ``app.config``.
"""

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import User, Workflow
from app.services import workflow_access
from app.services.workflow_access import (
    PERMISSION_WRITE,
    get_workflow_permission,
    workflow_access_clause,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

_CALL_PROBE = """
import sys, uuid, asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from app.db.models import Workflow
from app.services.workflow_access import get_workflow_permission, workflow_access_clause
from app.services.run_history_list import run_history_rows

user_id = uuid.uuid4()
for is_admin in (True, False):
    query = select(Workflow.id).where(workflow_access_clause(user_id, is_admin=is_admin))
    str(query.compile(dialect=postgresql.dialect()))
str(select(run_history_rows(user_id, is_admin=False)).compile(dialect=postgresql.dialect()))
workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), kind="workflow")
print("admin_permission", asyncio.run(get_workflow_permission(AsyncMock(), workflow, user_id, is_admin=True)))
print("config_loaded", "app.config" in sys.modules)
"""


class ConfigFreeCallTests(unittest.TestCase):
    def test_the_helpers_run_without_heym_settings_when_told_who_is_admin(self) -> None:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"SECRET_KEY", "ENCRYPTION_KEY", "DATABASE_URL"}
        }
        result = subprocess.run(
            [sys.executable, "-c", _CALL_PROBE],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("admin_permission write", result.stdout)
        self.assertIn("config_loaded False", result.stdout)


class PermissionAdminTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), kind="workflow")

    async def test_an_admin_writes_without_a_share_lookup(self) -> None:
        db = AsyncMock()

        permission = await get_workflow_permission(db, self.workflow, self.user_id, is_admin=True)

        self.assertEqual(permission, PERMISSION_WRITE)
        db.execute.assert_not_awaited()

    async def test_unset_asks_heym_settings(self) -> None:
        with patch(
            "app.services.instance_admin.is_instance_admin_id", AsyncMock(return_value=True)
        ) as lookup:
            permission = await get_workflow_permission(AsyncMock(), self.workflow, self.user_id)

        self.assertEqual(permission, PERMISSION_WRITE)
        lookup.assert_awaited_once()

    async def test_false_skips_heym_settings(self) -> None:
        no_shares = MagicMock()
        no_shares.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=no_shares)
        with patch("app.services.instance_admin.is_instance_admin_id", AsyncMock()) as lookup:
            permission = await get_workflow_permission(
                db, self.workflow, self.user_id, is_admin=False
            )

        self.assertIsNone(permission)
        lookup.assert_not_awaited()

    async def test_write_access_passes_the_answer_on(self) -> None:
        with patch.object(
            workflow_access, "get_workflow_permission", AsyncMock(return_value=PERMISSION_WRITE)
        ) as permission:
            allowed = await workflow_access.user_can_write_workflow(
                AsyncMock(), self.workflow, self.user_id, is_admin=False
            )

        self.assertTrue(allowed)
        self.assertFalse(permission.await_args.kwargs["is_admin"])


class AccessClauseAdminPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.owner = User(email=f"o-{uuid.uuid4()}@example.com", hashed_password="x", name="O")
        self.admin = User(email=f"a-{uuid.uuid4()}@example.com", hashed_password="x", name="A")
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all([self.owner, self.admin])
            await db.flush()
            self.workflow = Workflow(name="Payroll", owner_id=self.owner.id, nodes=[], edges=[])
            db.add(self.workflow)
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow.id))
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.admin.id])))
            await db.commit()
        await self.engine.dispose()

    async def _reaches(self, **kwargs: bool) -> bool:
        async with AsyncSession(self.engine) as db:
            result = await db.execute(
                select(Workflow.id).where(
                    Workflow.id == self.workflow.id,
                    workflow_access_clause(self.admin.id, **kwargs),
                )
            )
            return result.scalar_one_or_none() is not None

    async def test_the_answer_decides_what_an_unshared_user_reaches(self) -> None:
        self.assertTrue(await self._reaches(is_admin=True))
        self.assertFalse(await self._reaches(is_admin=False))

    async def test_unset_follows_heym_admin_emails(self) -> None:
        with patch.object(settings, "admin_emails", self.admin.email.upper()):
            self.assertTrue(await self._reaches())
        with patch.object(settings, "admin_emails", ""):
            self.assertFalse(await self._reaches())


if __name__ == "__main__":
    unittest.main()
