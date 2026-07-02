import unittest

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT, build_assistant_prompt


class PluginDslPromptTests(unittest.TestCase):
    def test_injects_installed_plugins_section(self) -> None:
        plugins = [
            {
                "id": "acme-crm",
                "kind": "action",
                "description": "Create Acme records",
                "dsl_hint": "Use to create a CRM record",
                "fields": [{"key": "apiKey", "label": "API Key", "type": "string"}],
            }
        ]
        prompt = build_assistant_prompt(None, None, None, installed_plugins=plugins)
        self.assertIn("Installed Plugins", prompt)
        self.assertIn("acme-crm", prompt)
        self.assertIn("Use to create a CRM record", prompt)

    def test_no_section_without_plugins(self) -> None:
        prompt = build_assistant_prompt(None, None, None)
        self.assertNotIn("Installed Plugins", prompt)

    def test_static_prompt_constant_unchanged(self) -> None:
        # Guard: plugin injection must NOT leak into the synced static constant.
        self.assertNotIn("Installed Plugins", WORKFLOW_DSL_SYSTEM_PROMPT)
