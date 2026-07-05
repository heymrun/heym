import importlib.util
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


def _load_wrapper() -> object:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "docker" / "heym-codex-docker"
    loader = SourceFileLoader("heym_codex_docker", str(script_path))
    spec = importlib.util.spec_from_loader("heym_codex_docker", loader)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load heym-codex-docker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCodexDockerWrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = _load_wrapper()

    def test_runner_image_prefers_env(self) -> None:
        with patch.dict(os.environ, {"HEYM_CODEX_DOCKER_IMAGE": "custom:tag"}, clear=True):
            self.assertEqual(self.wrapper._runner_image(), "custom:tag")

    def test_runner_image_falls_back_to_current_container_image(self) -> None:
        inspected = {"Config": {"Image": "ghcr.io/heymrun/heym:1.2.3"}}
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.wrapper, "_inspect_current_container", return_value=inspected),
        ):
            self.assertEqual(self.wrapper._runner_image(), "ghcr.io/heymrun/heym:1.2.3")

    def test_workspace_mount_prefers_configured_volume(self) -> None:
        with patch.dict(
            os.environ,
            {"HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces"},
            clear=True,
        ):
            self.assertEqual(
                self.wrapper._workspace_mount(Path("/app/data/codex-workspaces")),
                [
                    "--mount",
                    "type=volume,src=heym-codex-workspaces,dst=/app/data/codex-workspaces",
                ],
            )

    def test_workspace_mount_detects_bind_mount_from_current_container(self) -> None:
        inspected = {
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/srv/heym/codex-workspaces",
                    "Destination": "/app/data/codex-workspaces",
                }
            ]
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.wrapper, "_inspect_current_container", return_value=inspected),
        ):
            self.assertEqual(
                self.wrapper._workspace_mount(Path("/app/data/codex-workspaces")),
                [
                    "--mount",
                    "type=bind,src=/srv/heym/codex-workspaces,dst=/app/data/codex-workspaces",
                ],
            )

    def test_workspace_mount_fails_closed_without_shared_mount(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.wrapper, "_inspect_current_container", return_value={}),
            self.assertRaises(SystemExit),
        ):
            self.wrapper._workspace_mount(Path("/app/data/codex-workspaces"))

    def test_inspect_current_container_parses_docker_output(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps([{"Config": {"Image": "heym-backend:local"}}]),
            },
        )()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("container-id\n")
            handle.flush()
            with (
                patch("pathlib.Path.read_text", return_value="container-id"),
                patch("subprocess.run", return_value=completed),
            ):
                self.assertEqual(
                    self.wrapper._inspect_current_container(),
                    {"Config": {"Image": "heym-backend:local"}},
                )


if __name__ == "__main__":
    unittest.main()
