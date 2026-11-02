import unittest
from unittest.mock import MagicMock

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.network import OfflineCheck
from app.services.sandbox.spec import SandboxResult


class OfflineCheckTest(unittest.TestCase):
    def test_enforced_policy_is_checked_once(self) -> None:
        run = MagicMock(return_value=SandboxResult(0, "", ""))
        check = OfflineCheck(run)
        check.ensure("img")
        check.ensure("img")
        run.assert_called_once()
        spec = run.call_args.args[0]
        self.assertTrue(spec.offline)
        self.assertEqual(spec.image, "img")

    def test_open_network_fails_closed_every_time(self) -> None:
        run = MagicMock(return_value=SandboxResult(1, "", ""))
        check = OfflineCheck(run)
        for _ in range(2):
            with self.assertRaisesRegex(SandboxConfigError, "NetworkPolicy"):
                check.ensure("img")
        self.assertEqual(run.call_count, 2)

    def test_a_canary_that_did_not_run_fails_closed(self) -> None:
        check = OfflineCheck(MagicMock(return_value=SandboxResult(125, "", "ImagePullBackOff")))
        with self.assertRaisesRegex(SandboxConfigError, "did not run"):
            check.ensure("img")
