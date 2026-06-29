import unittest

from pydantic import ValidationError

from app.models.plugin_schemas import PluginManifest


class PluginManifestTests(unittest.TestCase):
    def _valid_legacy(self) -> dict:
        return {
            "id": "acme-crm",
            "name": "Acme CRM",
            "version": "1.0.0",
            "kind": "action",
            "description": "Send records to Acme",
            "fields": [
                {
                    "key": "apiKey",
                    "label": "API Key",
                    "type": "string",
                    "secret": True,
                    "required": True,
                },
            ],
        }

    def _valid_multinode(self) -> dict:
        return {
            "id": "ikv",
            "name": "IKV",
            "version": "1.0.0",
            "description": "Test package",
            "dependencies": ["coolname"],
            "nodes": [
                {"key": "ikvTrigger", "name": "ikvTrigger", "kind": "trigger"},
                {
                    "key": "ikvPublisher",
                    "name": "ikvPublisher",
                    "kind": "action",
                    "fields": [{"key": "text", "label": "Text", "type": "string"}],
                },
            ],
        }

    def test_legacy_single_kind_synthesizes_one_node(self) -> None:
        manifest = PluginManifest.model_validate(self._valid_legacy())
        nodes = manifest.resolved_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].key, "acme-crm")
        self.assertEqual(nodes[0].kind, "action")
        self.assertEqual(nodes[0].function, "run")
        self.assertEqual(nodes[0].fields[0].key, "apiKey")

    def test_multinode_manifest(self) -> None:
        manifest = PluginManifest.model_validate(self._valid_multinode())
        nodes = manifest.resolved_nodes()
        self.assertEqual([n.key for n in nodes], ["ikvTrigger", "ikvPublisher"])
        self.assertEqual(nodes[0].function, "trigger")
        self.assertEqual(nodes[1].function, "run")
        self.assertEqual(manifest.package_kind(), "mixed")
        self.assertEqual(manifest.dependencies, ["coolname"])

    def test_explicit_function_name(self) -> None:
        data = self._valid_multinode()
        data["nodes"][0]["function"] = "tick"
        manifest = PluginManifest.model_validate(data)
        self.assertEqual(manifest.resolved_nodes()[0].function, "tick")

    def test_rejects_bad_id(self) -> None:
        bad = self._valid_legacy()
        bad["id"] = "Acme CRM!"
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(bad)

    def test_rejects_no_nodes_and_no_kind(self) -> None:
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(
                {"id": "x", "name": "X", "version": "1.0.0", "description": "no nodes"}
            )

    def test_rejects_duplicate_node_keys(self) -> None:
        data = self._valid_multinode()
        data["nodes"][1]["key"] = "ikvTrigger"
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(data)

    def test_get_node_by_key(self) -> None:
        manifest = PluginManifest.model_validate(self._valid_multinode())
        self.assertEqual(manifest.get_node("ikvPublisher").kind, "action")
        self.assertIsNone(manifest.get_node("missing"))
