import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.services import plugin_loader
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import plugin_node, plugin_trigger_node

_MULTINODE_MANIFEST = {
    "id": "ikv",
    "name": "IKV",
    "version": "1.0.0",
    "description": "test",
    "nodes": [
        {"key": "ikvTrigger", "name": "ikvTrigger", "kind": "trigger", "function": "trigger"},
        {"key": "ikvPublisher", "name": "ikvPublisher", "kind": "action", "function": "run"},
    ],
}

_HANDLER = (
    "def trigger(config, ctx):\n"
    "    return {'value': config.get('seed', 0)}\n"
    "\n"
    "def run(inputs, config, ctx):\n"
    "    return {'text': str(config['text']).upper()}\n"
)


def _write_package(root: Path) -> None:
    pdir = root / "ikv"
    pdir.mkdir(parents=True)
    (pdir / "plugin.json").write_text(json.dumps(_MULTINODE_MANIFEST))
    (pdir / "handler.py").write_text(_HANDLER)


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
        _write_package(self.root)

    def test_action_node_runs_named_function(self) -> None:
        ctx = _ctx(
            {"pluginId": "ikv", "pluginNodeKey": "ikvPublisher", "config": {"text": "hi"}},
            {"in": {"v": 1}},
        )
        with patch.object(plugin_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_node.execute(ctx)
        self.assertEqual(output, {"text": "HI"})

    def test_trigger_node_runs_named_function(self) -> None:
        ctx = _ctx({"pluginId": "ikv", "pluginNodeKey": "ikvTrigger", "config": {"seed": 1}}, {})
        with patch.object(plugin_trigger_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_trigger_node.execute(ctx)
        self.assertEqual(output, {"value": 1})

    def test_falls_back_to_first_node_of_kind_without_key(self) -> None:
        ctx = _ctx({"pluginId": "ikv", "config": {"text": "yo"}}, {})
        with patch.object(plugin_node.plugin_store, "plugins_root", return_value=self.root):
            output = plugin_node.execute(ctx)
        self.assertEqual(output, {"text": "YO"})
