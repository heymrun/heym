import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.plugin_schemas import PluginManifest
from app.services import plugin_loader
from app.services.plugin_loader import PluginRuntimeError


def _write_plugin(root: Path, plugin_id: str, kind: str, body: str) -> None:
    pdir = root / plugin_id
    pdir.mkdir(parents=True)
    manifest = {"id": plugin_id, "name": plugin_id, "version": "1.0.0", "kind": kind, "fields": []}
    (pdir / "plugin.json").write_text(json.dumps(manifest))
    (pdir / "handler.py").write_text(body)


class PluginLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        plugin_loader.clear_cache()

    def test_load_manifest_from_disk(self) -> None:
        _write_plugin(self.root, "p1", "action", "def run(inputs, config, ctx):\n    return {}\n")
        manifest = plugin_loader.load_manifest("p1", self.root)
        self.assertIsInstance(manifest, PluginManifest)
        self.assertEqual(manifest.kind, "action")

    def test_run_action_handler(self) -> None:
        _write_plugin(
            self.root,
            "p1",
            "action",
            "def run(inputs, config, ctx):\n    return {'sum': inputs['a'] + config['b']}\n",
        )
        result = plugin_loader.call_handler(
            "p1", self.root, "run", {"inputs": {"a": 1}, "config": {"b": 2}, "ctx": {}}
        )
        self.assertEqual(result, {"sum": 3})

    def test_run_trigger_handler(self) -> None:
        _write_plugin(
            self.root,
            "t1",
            "trigger",
            "def trigger(config, ctx):\n    return {'event': config['name']}\n",
        )
        result = plugin_loader.call_handler(
            "t1", self.root, "trigger", {"config": {"name": "ping"}, "ctx": {}}
        )
        self.assertEqual(result, {"event": "ping"})

    def test_missing_function_raises(self) -> None:
        _write_plugin(self.root, "p1", "action", "x = 1\n")
        with self.assertRaises(PluginRuntimeError):
            plugin_loader.call_handler(
                "p1", self.root, "run", {"inputs": {}, "config": {}, "ctx": {}}
            )

    def test_missing_plugin_raises(self) -> None:
        with self.assertRaises(PluginRuntimeError):
            plugin_loader.load_manifest("nope", self.root)
