import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.sandbox import ca_bundle
from app.services.sandbox.docker_backend import DockerBackend, render_docker_argv
from app.services.sandbox.kubernetes.backend import KubernetesBackend
from app.services.sandbox.kubernetes.config import KubeConfig
from app.services.sandbox.spec import SandboxSpec

PEM = b"-----BEGIN CERTIFICATE-----\nCORP\n-----END CERTIFICATE-----\n"
DIGEST = hashlib.sha256(PEM).hexdigest()[:16]


def _spec(*env: str) -> SandboxSpec:
    return SandboxSpec(
        site="code-run", name="heym-code-1", image="img", entrypoint="python", env=env
    )


class CaBundleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self.ca = self.tmp / "secrets" / "corp-ca.pem"
        self.ca.parent.mkdir()
        self.ca.write_bytes(PEM)
        self.root = self.tmp / "ws"
        self.root.mkdir()
        env = patch.dict(os.environ, {"HEYM_CODEX_WORKSPACE_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)


class CaFilesTest(CaBundleTestCase):
    def test_only_existing_absolute_files_of_ca_variables(self) -> None:
        env = (
            f"SSL_CERT_FILE={self.ca}",
            f"REQUESTS_CA_BUNDLE={self.ca}",
            f"SSL_CERT_DIR={self.ca.parent}",
            "NODE_EXTRA_CA_CERTS=relative.pem",
            "CURL_CA_BUNDLE=/does/not/exist.pem",
            f"OTHER={self.ca}",
        )
        self.assertEqual(ca_bundle.ca_files(env), [str(self.ca)])

    def test_copy_is_content_addressed_and_readable_by_the_sandbox_user(self) -> None:
        (mount,) = ca_bundle.ca_mounts(_spec(f"SSL_CERT_FILE={self.ca}"), shared_workspace=True)
        copy = self.root / "_ca" / DIGEST / "corp-ca.pem"
        self.assertEqual(
            (mount.host_path, mount.target, mount.readonly), (copy, str(self.ca), True)
        )
        self.assertEqual(copy.read_bytes(), PEM)
        self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(copy.parent.stat().st_mode), 0o755)
        ca_bundle.ca_mounts(_spec(f"SSL_CERT_FILE={self.ca}"), shared_workspace=True)
        self.assertEqual(os.listdir(copy.parent), ["corp-ca.pem"])

    def test_unwritable_workspace_leaves_the_file_out(self) -> None:
        with patch.dict(os.environ, {"HEYM_CODEX_WORKSPACE_DIR": "/proc/heym-no-such-dir"}):
            mounts = ca_bundle.ca_mounts(_spec(f"SSL_CERT_FILE={self.ca}"), shared_workspace=True)
        self.assertEqual(mounts, [])


class DockerCaTest(CaBundleTestCase):
    def _argv(self, spec: SandboxSpec, *, containerized: bool) -> list[str]:
        backend = DockerBackend()
        with patch.object(DockerBackend, "uses_shared_workspace", return_value=containerized):
            return render_docker_argv(backend.with_ca_files(spec))

    def test_host_backend_binds_the_file_itself(self) -> None:
        argv = self._argv(_spec(f"SSL_CERT_FILE={self.ca}"), containerized=False)
        self.assertIn(f"type=bind,src={self.ca},dst={self.ca},readonly", argv)

    def test_containerized_backend_mounts_the_copy_from_the_volume(self) -> None:
        with patch.dict(os.environ, {"HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-ws"}):
            argv = self._argv(_spec(f"REQUESTS_CA_BUNDLE={self.ca}"), containerized=True)
        self.assertIn(
            f"type=volume,src=heym-ws,dst={self.ca},volume-subpath=_ca/{DIGEST}/corp-ca.pem,"
            "readonly",
            argv,
        )

    def test_unresolvable_volume_runs_without_the_mount(self) -> None:
        with patch("app.services.sandbox.docker_backend.current_container_mounts", return_value=[]):
            argv = self._argv(_spec(f"SSL_CERT_FILE={self.ca}"), containerized=True)
        self.assertNotIn("--mount", argv)

    def test_no_ca_variable_changes_nothing(self) -> None:
        spec = _spec("LANG=C.UTF-8")
        self.assertIs(DockerBackend().with_ca_files(spec), spec)


class KubernetesCaTest(CaBundleTestCase):
    def _backend(self, mount_path: str) -> KubernetesBackend:
        client = MagicMock()
        client.namespace = "sb"
        client.has_api_group.return_value = False
        client.get_pod.return_value = {
            "spec": {
                "containers": [
                    {"image": "img", "volumeMounts": [{"name": "d", "mountPath": mount_path}]}
                ],
                "volumes": [{"name": "d", "persistentVolumeClaim": {"claimName": "heym-data"}}],
            }
        }
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteMany"]}}
        config = KubeConfig(
            server="https://k:443", namespace="sb", own_namespace="sb", in_cluster=True, token="t"
        )
        return KubernetesBackend(config, client=client, instance="heym-0")

    def test_copy_is_mounted_read_only_at_the_original_path(self) -> None:
        backend = self._backend(str(self.tmp))
        manifest = backend.manifest(_spec(f"NODE_EXTRA_CA_CERTS={self.ca}"), 5)
        self.assertIn(
            {
                "name": "ws-0",
                "mountPath": str(self.ca),
                "subPath": f"ws/_ca/{DIGEST}/corp-ca.pem",
                "readOnly": True,
            },
            manifest["spec"]["containers"][0]["volumeMounts"],
        )

    def test_workspace_off_every_claim_runs_without_the_mount(self) -> None:
        backend = self._backend("/somewhere/else")
        manifest = backend.manifest(_spec(f"SSL_CERT_FILE={self.ca}"), 5)
        self.assertEqual(manifest["spec"]["containers"][0].get("volumeMounts", []), [])


if __name__ == "__main__":
    unittest.main()
