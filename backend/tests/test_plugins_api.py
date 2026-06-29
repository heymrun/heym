import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException, status

from app.api import plugins
from app.config import settings


class PluginGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._enabled = settings.plugins_enabled
        self._admins = settings.plugin_admin_emails
        settings.plugins_enabled = True
        settings.plugin_admin_emails = "admin@example.com"

    def tearDown(self) -> None:
        settings.plugins_enabled = self._enabled
        settings.plugin_admin_emails = self._admins

    def test_require_enabled_raises_when_off(self) -> None:
        settings.plugins_enabled = False
        with self.assertRaises(HTTPException) as ctx:
            plugins.require_plugins_enabled()
        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    def test_require_admin_rejects_unlisted(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="viewer@example.com")
        with self.assertRaises(HTTPException) as ctx:
            plugins.require_plugin_admin(user)
        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_require_admin_allows_listed(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="Admin@Example.com")
        plugins.require_plugin_admin(user)  # no raise

    async def test_uninstall_rejects_non_admin(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="viewer@example.com")
        with self.assertRaises(HTTPException) as ctx:
            await plugins.uninstall_plugin("acme-crm", current_user=user, db=AsyncMock())
        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
