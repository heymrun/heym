"""The wrapper scripts are shims: find the backend venv and hand over to wrapper_cli."""

import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):  # noqa: ANN202
    loader = SourceFileLoader(name.replace("-", "_"), str(REPO / "docker" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ShimTest(unittest.TestCase):
    def _exec_for(self, script: str, present: str) -> tuple:
        module = _load(script)
        with (
            patch.object(module.os.path, "isfile", side_effect=lambda p: p == present),
            patch.object(module.os, "execve") as execve,
            patch.object(module.sys, "argv", [script, "exec", "--json"]),
        ):
            module.main()
        return execve.call_args.args

    def test_compose_image_layout(self) -> None:
        python, argv, env = self._exec_for("heym-codex-docker", "/app/.venv/bin/python")
        self.assertEqual(python, "/app/.venv/bin/python")
        self.assertEqual(
            argv,
            [
                "/app/.venv/bin/python",
                "-m",
                "app.services.sandbox.wrapper_cli",
                "codex",
                "exec",
                "--json",
            ],
        )
        self.assertEqual(env["PYTHONPATH"], "/app")

    def test_release_image_layout(self) -> None:
        python, argv, env = self._exec_for("heym-opencode-docker", "/app/backend/.venv/bin/python")
        self.assertEqual(argv[3], "opencode")
        self.assertEqual(env["PYTHONPATH"], "/app/backend")

    def test_missing_venv_fails_without_running_anything(self) -> None:
        module = _load("heym-codex-docker")
        with (
            patch.object(module.os.path, "isfile", return_value=False),
            patch.object(module.os, "execve") as execve,
        ):
            self.assertEqual(module.main(), 127)
        execve.assert_not_called()
