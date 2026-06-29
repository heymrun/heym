import unittest

from pydantic import ValidationError

from app.models.plugin_schemas import PluginManifest


class PluginManifestTests(unittest.TestCase):
    def _valid(self) -> dict:
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
                {
                    "key": "recordId",
                    "label": "Record ID",
                    "type": "string",
                    "dynamic": True,
                    "expression": True,
                },
            ],
        }

    def test_parses_valid_manifest(self) -> None:
        manifest = PluginManifest.model_validate(self._valid())
        self.assertEqual(manifest.id, "acme-crm")
        self.assertEqual(manifest.kind, "action")
        self.assertEqual(manifest.entry, "handler.py")
        self.assertEqual(manifest.fields[0].key, "apiKey")
        self.assertTrue(manifest.fields[0].secret)

    def test_rejects_bad_id(self) -> None:
        bad = self._valid()
        bad["id"] = "Acme CRM!"
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(bad)

    def test_rejects_unknown_kind(self) -> None:
        bad = self._valid()
        bad["kind"] = "webhook"
        with self.assertRaises(ValidationError):
            PluginManifest.model_validate(bad)

    def test_defaults_optional_fields(self) -> None:
        minimal = {"id": "p1", "name": "P1", "version": "0.1.0", "kind": "trigger"}
        manifest = PluginManifest.model_validate(minimal)
        self.assertEqual(manifest.fields, [])
        self.assertEqual(manifest.dependencies, [])
        self.assertEqual(manifest.doc_slug, "p1")
