import os
import unittest
from unittest.mock import patch

from app.services.sandbox.env import CODE_FORWARD_PREFIXES, SKILL_FORWARD_PREFIXES, forwarded_env
from app.services.sandbox.spec import SandboxResult, SandboxSpec, Tmpfs


class TmpfsTest(unittest.TestCase):
    def test_parse_round_trips_every_docker_value_in_use(self) -> None:
        for value in (
            "/tmp:rw,nosuid,size=512m",
            "/tmp:rw,noexec,nosuid,size=64m",
            "/tmp:rw,exec,nosuid,size=1g",
        ):
            self.assertEqual(Tmpfs.parse(value).docker_value(), value)

    def test_parse_requires_a_size(self) -> None:
        with self.assertRaises(ValueError):
            Tmpfs.parse("/tmp:rw,nosuid")


class SandboxResultTest(unittest.TestCase):
    def test_start_failure_codes(self) -> None:
        for code in (125, 126, 127):
            self.assertTrue(SandboxResult(code, "", "").start_failed)
        self.assertFalse(SandboxResult(1, "", "").start_failed)

    def test_oom(self) -> None:
        self.assertTrue(SandboxResult(137, "", "").oom_killed)
        self.assertFalse(SandboxResult(0, "", "").oom_killed)


class SpecTest(unittest.TestCase):
    def test_offline_means_network_none(self) -> None:
        spec = SandboxSpec(site="t", name="n", image="i", entrypoint="python")
        self.assertTrue(spec.offline)
        self.assertFalse(
            SandboxSpec(site="t", name="n", image="i", entrypoint=None, network="bridge").offline
        )


class ForwardedEnvTest(unittest.TestCase):
    def test_allowlist_keeps_proxies_and_drops_secrets_and_home(self) -> None:
        env = {
            "LANG": "C",
            "HTTP_PROXY": "http://p:3128",
            "SECRET_KEY": "s",
            "DATABASE_URL": "postgresql://x",
            "HOME": "/root",
            "NODE_EXTRA_CA_CERTS": "/x.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                forwarded_env(CODE_FORWARD_PREFIXES), ("LANG=C", "HTTP_PROXY=http://p:3128")
            )
            self.assertIn("NODE_EXTRA_CA_CERTS=/x.pem", forwarded_env(SKILL_FORWARD_PREFIXES))
