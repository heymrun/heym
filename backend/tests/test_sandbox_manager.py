import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox import get_sandbox_manager, reset_sandbox_manager
from app.services.sandbox import manager as manager_module
from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.manager import SandboxManager, UnavailableBackend


class ManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)

    def test_singleton_until_reset(self) -> None:
        first = get_sandbox_manager()
        self.assertIs(first, get_sandbox_manager())
        reset_sandbox_manager()
        self.assertIsNot(first, get_sandbox_manager())

    def test_docker_is_the_default_backend(self) -> None:
        self.assertEqual(get_sandbox_manager().backend_name, "docker")

    def test_image_overrides_win_in_order_then_the_backend(self) -> None:
        backend = MagicMock()
        backend.resolve_image.return_value = "self:1"
        manager = SandboxManager(backend)
        with patch.dict(os.environ, {"B": "b:1", "A": " "}, clear=True):
            self.assertEqual(manager.resolve_image(("A", "B")), "b:1")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(manager.resolve_image(("A", "B")), "self:1")

    def test_calls_delegate_to_the_backend(self) -> None:
        backend = MagicMock()
        manager = SandboxManager(backend)
        manager.run("spec", "in", 3)  # type: ignore[arg-type]
        backend.run.assert_called_once_with("spec", "in", 3)
        manager.force_remove("n")
        backend.force_remove.assert_called_once_with("n")


class SelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)

    def _select(self, env: dict, docker_up: bool, in_cluster: bool, k8s_up: bool):  # noqa: ANN202
        k8s = MagicMock()
        k8s.name = "kubernetes"
        k8s.available.return_value = k8s_up
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(manager_module.DockerBackend, "available", return_value=docker_up),
            patch(
                "app.services.sandbox.kubernetes.config.in_cluster_available",
                return_value=in_cluster,
            ),
            patch("app.services.sandbox.kubernetes.config.load_in_cluster"),
            patch("app.services.sandbox.kubernetes.backend.KubernetesBackend", return_value=k8s),
        ):
            return manager_module._build_manager()

    def test_auto_prefers_a_reachable_docker(self) -> None:
        self.assertEqual(self._select({}, True, True, True).backend_name, "docker")

    def test_auto_uses_kubernetes_in_a_pod_without_docker(self) -> None:
        self.assertEqual(self._select({}, False, True, True).backend_name, "kubernetes")

    def test_auto_without_either_stays_docker_and_fails_closed(self) -> None:
        # available() is asked again after selection, so keep Docker down for it too.
        with patch.object(manager_module.DockerBackend, "available", return_value=False):
            manager = self._select({}, False, False, False)
            self.assertEqual(manager.backend_name, "docker")
            self.assertFalse(manager.available())

    def test_forced_docker_never_tries_kubernetes(self) -> None:
        self.assertEqual(
            self._select({"HEYM_SANDBOX_BACKEND": "docker"}, False, True, True).backend_name,
            "docker",
        )

    def test_forced_kubernetes_without_config_fails_closed(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"HEYM_SANDBOX_BACKEND": "kubernetes", "KUBECONFIG": "/nonexistent"},
                clear=True,
            ),
            patch(
                "app.services.sandbox.kubernetes.config.in_cluster_available", return_value=False
            ),
        ):
            manager = manager_module._build_manager()
        self.assertEqual(manager.backend_name, "kubernetes")
        self.assertFalse(manager.available())
        with self.assertRaises(SandboxConfigError):
            manager.run(MagicMock(), None, 1)

    def test_unavailable_backend(self) -> None:
        backend = UnavailableBackend("kubernetes", "why")
        self.assertIsNone(backend.resolve_image())
        backend.force_remove("x")
