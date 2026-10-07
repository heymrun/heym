"""Heym Work imports Heym's models and access helpers without Heym's settings."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
_MODULES = (
    "app.db.models",
    "app.services.workflow_access",
    "app.services.credential_access",
    "app.services.dashboard_access",
    "app.services.alert_access",
    "app.services.data_table_access",
)
_PROBE = (
    "import importlib, sys\n"
    "for name in sys.argv[1:]:\n"
    "    importlib.import_module(name)\n"
    "print('config_loaded', 'app.config' in sys.modules)\n"
)


class ModelsImportableWithoutSettingsTests(unittest.TestCase):
    def test_models_and_access_helpers_import_without_secrets(self) -> None:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"SECRET_KEY", "ENCRYPTION_KEY", "DATABASE_URL"}
        }
        result = subprocess.run(
            [sys.executable, "-c", _PROBE, *_MODULES],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("config_loaded False", result.stdout)
