import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api import plugins
from app.config import settings
from app.models.plugin_schemas import PluginManifest


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


class PluginIconResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "ikv").mkdir()
        (self.root / "ikv" / "icon.svg").write_text("<svg/>")
        (self.root / "ikv" / "trigger.svg").write_text("<svg id='t'/>")
        self._patch = patch.object(plugins.plugin_store, "plugins_root", return_value=self.root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.manifest = PluginManifest.model_validate(
            {
                "id": "ikv",
                "name": "IKV",
                "version": "1.0.0",
                "description": "x",
                "nodes": [
                    {"key": "t", "name": "t", "kind": "trigger", "icon": "trigger.svg"},
                    {"key": "p", "name": "p", "kind": "action"},
                ],
            }
        )

    def test_node_with_icon_uses_its_own(self) -> None:
        path = plugins._resolve_icon("ikv", self.manifest, "t")
        self.assertEqual(path, (self.root / "ikv" / "trigger.svg").resolve())

    def test_node_without_icon_falls_back_to_package(self) -> None:
        path = plugins._resolve_icon("ikv", self.manifest, "p")
        self.assertEqual(path, (self.root / "ikv" / "icon.svg").resolve())

    def test_rejects_path_traversal(self) -> None:
        (self.root / "secret.svg").write_text("<svg/>")
        self.assertIsNone(plugins._safe_icon_path("ikv", "../secret.svg"))

    def test_missing_icon_returns_none(self) -> None:
        self.assertIsNone(plugins._safe_icon_path("ikv", "nope.svg"))
