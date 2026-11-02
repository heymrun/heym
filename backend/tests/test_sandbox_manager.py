import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox import get_sandbox_manager, reset_sandbox_manager
from app.services.sandbox.manager import SandboxManager


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
