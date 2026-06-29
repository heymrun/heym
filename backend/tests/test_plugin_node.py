import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.services import plugin_loader
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import plugin_node, plugin_trigger_node


def _write_plugin(root: Path, plugin_id: str, kind: str, body: str) -> None:
    pdir = root / plugin_id
    pdir.mkdir(parents=True)
    (pdir / "plugin.json").write_text(
        json.dumps(
            {"id": plugin_id, "name": plugin_id, "version": "1.0.0", "kind": kind, "fields": []}
        )
    )
    (pdir / "handler.py").write_text(body)


def _ctx(node_data: dict, inputs: dict) -> NodeExecutionContext:
    executor = SimpleNamespace(
        resolve_expression=lambda value, *_a, **_k: value,
        _first_visible_input=lambda i: next(iter(i.values()), None),
    )
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs=inputs,
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1"},
        node_type=node_data.get("_type", "plugin"),
        node_data=node_data,
        node_label="plugin1",
    )


class PluginNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        plugin_loader.clear_cache()

    def test_action_node_runs_handler(self) -> None:
        _write_plugin(
            self.root,
            "acme",
            "action",
            "def run(inputs, config, ctx):\n    return {'result': config['x']}\n",
        )
        ctx = _ctx({"pluginId": "acme", "config": {"x": "hi"}}, {"in": {"v": 1}})
        with patch.object(plugin_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_node.execute(ctx)
        self.assertEqual(output, {"result": "hi"})

    def test_trigger_node_runs_handler(self) -> None:
        _write_plugin(
            self.root,
            "tick",
            "trigger",
            "def trigger(config, ctx):\n    return {'fired': config['name']}\n",
        )
        ctx = _ctx({"pluginId": "tick", "config": {"name": "ping"}}, {})
        with patch.object(plugin_trigger_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_trigger_node.execute(ctx)
        self.assertEqual(output, {"fired": "ping"})
