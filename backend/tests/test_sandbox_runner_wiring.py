import unittest
from unittest.mock import MagicMock, patch

from app.services.codex_runner_service import CodexRunnerService
from app.services.opencode_runner_service import OpenCodeRunnerService


def _manager(name: str) -> MagicMock:
    manager = MagicMock()
    manager.backend_name = name
    return manager


class CodexWiringTest(unittest.TestCase):
    def test_danger_full_access_only_for_the_shim_on_kubernetes(self) -> None:
        cases = (
            ("/usr/local/bin/heym-codex-docker", "kubernetes", "danger-full-access"),
            ("/usr/local/bin/heym-codex-docker", "docker", "workspace-write"),
            ("codex", "kubernetes", "workspace-write"),
        )
        for cli, backend, expected in cases:
            with (
                self.subTest(cli=cli, backend=backend),
                patch(
                    "app.services.codex_runner_service.get_sandbox_manager",
                    return_value=_manager(backend),
                ),
            ):
                service = CodexRunnerService(cli_command=cli, workspace_root="/tmp/x")
                self.assertEqual(service._codex_sandbox_mode(), expected)

    def test_child_env_names_the_backend(self) -> None:
        with patch(
            "app.services.codex_runner_service.get_sandbox_manager",
            return_value=_manager("kubernetes"),
        ):
            env = CodexRunnerService(cli_command="codex", workspace_root="/tmp/x")._safe_env()
        self.assertEqual(env["HEYM_SANDBOX_BACKEND"], "kubernetes")


class OpenCodeWiringTest(unittest.TestCase):
    def test_kubernetes_cleanup_deletes_the_pod_by_name(self) -> None:
        manager = _manager("kubernetes")
        with patch(
            "app.services.opencode_runner_service.get_sandbox_manager", return_value=manager
        ):
            OpenCodeRunnerService._remove_runner_container("abc123")
        manager.force_remove.assert_called_once_with("heym-opencode-abc123")
