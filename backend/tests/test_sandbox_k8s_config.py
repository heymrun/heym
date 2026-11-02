import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.sandbox.kubernetes import config as kube_config
from app.services.sandbox.kubernetes.config import (
    KubeConfig,
    KubeConfigError,
    load_in_cluster,
    load_kubeconfig,
)


def _sa_dir() -> Path:
    path = Path(tempfile.mkdtemp())
    (path / "token").write_text("token-1")
    (path / "namespace").write_text("heym")
    (path / "ca.crt").write_text("unused-in-these-tests")
    return path


class InClusterTest(unittest.TestCase):
    def test_reads_service_env_and_serviceaccount_files(self) -> None:
        sa = _sa_dir()
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "KUBERNETES_SERVICE_PORT": "443"}
        with patch.object(kube_config, "SA_DIR", sa), patch.dict(os.environ, env, clear=True):
            config = load_in_cluster()
        self.assertEqual(config.server, "https://10.0.0.1:443")
        self.assertEqual((config.namespace, config.own_namespace), ("heym", "heym"))
        self.assertTrue(config.in_cluster)
        self.assertEqual(config.bearer_token(), "token-1")
        (sa / "token").write_text("token-2")
        self.assertEqual(config.bearer_token(), "token-2")

    def test_sandbox_namespace_override_and_ipv6(self) -> None:
        env = {
            "KUBERNETES_SERVICE_HOST": "fd00::1",
            "KUBERNETES_SERVICE_PORT": "6443",
            "HEYM_SANDBOX_K8S_NAMESPACE": "heym-sandbox",
        }
        with (
            patch.object(kube_config, "SA_DIR", _sa_dir()),
            patch.dict(os.environ, env, clear=True),
        ):
            config = load_in_cluster()
        self.assertEqual(config.server, "https://[fd00::1]:6443")
        self.assertEqual((config.namespace, config.own_namespace), ("heym-sandbox", "heym"))

    def test_round_trips_through_a_dict(self) -> None:
        config = KubeConfig(
            server="https://x", namespace="a", own_namespace="b", in_cluster=False, token="t"
        )
        self.assertEqual(KubeConfig.from_dict(config.to_dict()), config)


class KubeconfigTest(unittest.TestCase):
    def _write(self, user: dict, cluster_extra: dict | None = None) -> str:
        import yaml

        data = {
            "current-context": "dev",
            "contexts": [
                {"name": "dev", "context": {"cluster": "c", "user": "u", "namespace": "ns"}}
            ],
            "clusters": [
                {
                    "name": "c",
                    "cluster": {"server": "https://127.0.0.1:26443/", **(cluster_extra or {})},
                }
            ],
            "users": [{"name": "u", "user": user}],
        }
        path = Path(tempfile.mkdtemp()) / "config"
        path.write_text(yaml.safe_dump(data))
        return str(path)

    def test_client_certificate_data(self) -> None:
        cert = base64.b64encode(b"CERT").decode()
        key = base64.b64encode(b"KEY").decode()
        path = self._write({"client-certificate-data": cert, "client-key-data": key})
        with patch.dict(os.environ, {}, clear=True):
            config = load_kubeconfig(path)
        self.assertEqual(config.server, "https://127.0.0.1:26443")
        self.assertEqual((config.client_cert_data, config.client_key_data), ("CERT", "KEY"))
        self.assertEqual(config.namespace, "ns")
        self.assertFalse(config.in_cluster)

    def test_plugins_and_insecure_tls_are_refused(self) -> None:
        with self.assertRaisesRegex(KubeConfigError, "plugins"):
            load_kubeconfig(self._write({"exec": {"command": "aws"}}))
        with self.assertRaisesRegex(KubeConfigError, "TLS"):
            load_kubeconfig(self._write({"token": "t"}, {"insecure-skip-tls-verify": True}))
