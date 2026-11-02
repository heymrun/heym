"""The sandbox package must import without app.config (the wrapper and bridge run without settings)."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULES = (
    "app.services.sandbox",
    "app.services.sandbox.wrapper_cli",
    "app.services.sandbox.coding_agents",
    "app.services.sandbox.kubernetes.backend",
    "app.services.sandbox.kubernetes.process",
    "app.services.sandbox.kubernetes.janitor",
)


class ImportRuleTest(unittest.TestCase):
    def test_no_settings_import(self) -> None:
        code = (
            "import importlib, sys\n"
            f"for name in {MODULES!r}:\n"
            "    importlib.import_module(name)\n"
            "assert 'app.config' not in sys.modules, sorted(m for m in sys.modules if m.startswith('app.'))\n"
        )
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(BACKEND)}
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
