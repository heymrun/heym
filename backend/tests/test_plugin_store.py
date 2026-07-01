import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import plugin_store
from app.services.plugin_store import PluginInstallError


def _make_zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


_VALID_MANIFEST = """{
  "id": "acme-crm", "name": "Acme CRM", "version": "1.0.0", "kind": "action",
  "description": "x", "fields": []
}"""
_HANDLER = "def run(inputs, config, ctx):\n    return {'ok': True}\n"


class PluginStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_extract_valid_plugin(self) -> None:
        data = _make_zip(
            {"plugin.json": _VALID_MANIFEST, "handler.py": _HANDLER, "README.md": "# Acme"}
        )
        with patch.object(plugin_store, "_install_dependencies") as deps:
            manifest = plugin_store.extract_and_validate(data, self.dir)
        self.assertEqual(manifest.id, "acme-crm")
        self.assertTrue((self.dir / "acme-crm" / "handler.py").exists())
        # No dependencies in this manifest -> installer not called.
        deps.assert_not_called()

    def test_extract_allows_nested_plugin_members(self) -> None:
        data = _make_zip(
            {
                "plugin.json": _VALID_MANIFEST,
                "handler.py": _HANDLER,
                "assets/icon.svg": "<svg/>",
            }
        )

        with patch.object(plugin_store, "_install_dependencies"):
            plugin_store.extract_and_validate(data, self.dir)

        self.assertEqual((self.dir / "acme-crm" / "assets" / "icon.svg").read_text(), "<svg/>")

    def test_rejects_zip_slip(self) -> None:
        data = _make_zip({"plugin.json": _VALID_MANIFEST, "../evil.py": "x"})
        with self.assertRaises(PluginInstallError):
            plugin_store.extract_and_validate(data, self.dir)
        self.assertFalse((self.dir.parent / "evil.py").exists())

    def test_rejects_missing_manifest(self) -> None:
        data = _make_zip({"handler.py": _HANDLER})
        with self.assertRaises(PluginInstallError):
            plugin_store.extract_and_validate(data, self.dir)

    def test_rejects_missing_handler(self) -> None:
        data = _make_zip({"plugin.json": _VALID_MANIFEST})
        with self.assertRaises(PluginInstallError):
            plugin_store.extract_and_validate(data, self.dir)

    def test_dependency_failure_rolls_back(self) -> None:
        manifest_with_deps = _VALID_MANIFEST.replace(
            '"fields": []', '"fields": [], "dependencies": ["nonexistent-xyz"]'
        )
        data = _make_zip({"plugin.json": manifest_with_deps, "handler.py": _HANDLER})
        with patch.object(
            plugin_store, "_install_dependencies", side_effect=PluginInstallError("pip failed")
        ):
            with self.assertRaises(PluginInstallError):
                plugin_store.extract_and_validate(data, self.dir)
        self.assertFalse((self.dir / "acme-crm").exists())

    def test_remove_plugin_dir(self) -> None:
        target = self.dir / "acme-crm"
        target.mkdir()
        (target / "handler.py").write_text("x")
        plugin_store.remove_plugin_dir("acme-crm", self.dir)
        self.assertFalse(target.exists())
