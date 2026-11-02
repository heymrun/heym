import json
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox.errors import SandboxConfigError, SandboxTimeoutError
from app.services.sandbox.kubernetes import backend as kube_backend
from app.services.sandbox.kubernetes.backend import KubernetesBackend
from app.services.sandbox.kubernetes.config import KubeConfig
from app.services.sandbox.kubernetes.lifecycle import PodExit, PodStart
from app.services.sandbox.spec import SandboxSpec

CONFIG = KubeConfig(
    server="https://k:443", namespace="sb", own_namespace="sb", in_cluster=True, token="t"
)


def _backend(client: MagicMock | None = None) -> KubernetesBackend:
    client = client or MagicMock()
    client.namespace = "sb"
    client.has_api_group.return_value = False
    backend = KubernetesBackend(CONFIG, client=client, instance="heym-0")
    backend._offline = MagicMock()
    return backend


def _spec(network: str = "bridge") -> SandboxSpec:
    return SandboxSpec(
        site="pytool", name="heym-pytool-1", image="img", entrypoint="python", network=network
    )


class RunTest(unittest.TestCase):
    def test_happy_path_attaches_and_always_deletes(self) -> None:
        backend = _backend()
        with (
            patch.object(kube_backend, "wait_started", return_value=PodStart("running")),
            patch.object(kube_backend, "open_attach") as attach,
            patch.object(kube_backend, "exchange", return_value=(b"out", b"err", 0)) as exchange,
            patch.object(kube_backend, "wait_terminated", return_value=PodExit(0)),
        ):
            result = backend.run(_spec(), "payload", 5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "out", "err"))
        manifest = backend._client.create_pod.call_args.args[0]
        self.assertEqual(manifest["spec"]["activeDeadlineSeconds"], 35)
        self.assertEqual(exchange.call_args.args[1], b"payload")
        attach.return_value.close.assert_called_once()
        backend._client.delete_pod.assert_called_once_with("heym-pytool-1")

    def test_start_failure_never_attaches(self) -> None:
        backend = _backend()
        with (
            patch.object(
                kube_backend, "wait_started", return_value=PodStart("failed", "ImagePullBackOff: x")
            ),
            patch.object(kube_backend, "open_attach") as attach,
        ):
            result = backend.run(_spec(), None, 5)
        self.assertTrue(result.start_failed)
        self.assertIn("ImagePullBackOff", result.stderr)
        attach.assert_not_called()
        backend._client.delete_pod.assert_called_once()

    def test_container_gone_before_attach_falls_back_to_the_log(self) -> None:
        from websockets.exceptions import InvalidHandshake

        backend = _backend()
        backend._client.pod_log.return_value = "early output"
        with (
            patch.object(kube_backend, "wait_started", return_value=PodStart("running")),
            patch.object(kube_backend, "open_attach", side_effect=InvalidHandshake("500")),
            patch.object(kube_backend, "wait_terminated", return_value=PodExit(0)),
        ):
            result = backend.run(_spec(), None, 5)
        self.assertEqual((result.returncode, result.stdout), (0, "early output"))
        backend._client.delete_pod.assert_called_once()

    def test_timeout_deletes_and_raises(self) -> None:
        backend = _backend()
        with (
            patch.object(kube_backend, "wait_started", return_value=PodStart("running")),
            patch.object(kube_backend, "open_attach"),
            patch.object(kube_backend, "exchange", side_effect=TimeoutError),
        ):
            with self.assertRaises(SandboxTimeoutError):
                backend.run(_spec(), None, 5)
        backend._client.delete_pod.assert_called_once()

    def test_offline_specs_run_the_canary_first(self) -> None:
        backend = _backend()
        backend._offline.ensure.side_effect = SandboxConfigError("NetworkPolicy missing")
        with self.assertRaises(SandboxConfigError):
            backend.run(_spec(network="none"), None, 5)
        backend._client.create_pod.assert_not_called()

    def test_workspace_mounts_fail_closed_until_milestone_4(self) -> None:
        from pathlib import Path

        from app.services.sandbox.spec import DockerVolumeSource, WorkspaceMount

        mount = WorkspaceMount(Path("/w/x"), "/w/x", False, DockerVolumeSource(Path("/w"), (), "m"))
        spec = SandboxSpec(
            site="skill", name="n", image="i", entrypoint="p", workspace_mounts=(mount,)
        )
        with self.assertRaises(SandboxConfigError):
            _backend().run(spec, None, 5)


class AvailabilityTest(unittest.TestCase):
    def test_old_server_or_missing_rbac_is_unavailable(self) -> None:
        client = MagicMock()
        client.server_version.return_value = (1, 29)
        self.assertFalse(_backend(client).available())
        client = MagicMock()
        client.server_version.return_value = (1, 31)
        client.can_i.side_effect = lambda verb, resource, sub="": sub != "attach"
        self.assertFalse(_backend(client).available())

    def test_available_when_everything_checks_out(self) -> None:
        client = MagicMock()
        client.server_version.return_value = (1, 36)
        client.can_i.return_value = True
        self.assertTrue(_backend(client).available())


class ProcessAndImageTest(unittest.TestCase):
    def test_process_command_hands_the_manifest_to_the_bridge(self) -> None:
        command = _backend().process_command(_spec())
        self.assertEqual(command.argv[1:], ["-m", "app.services.sandbox.kubernetes.process"])
        payload = json.loads(command.env["HEYM_SANDBOX_PROCESS_SPEC"])
        self.assertEqual(payload["manifest"]["metadata"]["name"], "heym-pytool-1")
        self.assertEqual(payload["kube"]["server"], "https://k:443")
        self.assertTrue(command.env["PYTHONPATH"].endswith("backend"))

    def test_image_is_the_single_container_of_the_backend_pod(self) -> None:
        client = MagicMock()
        client.get_pod.return_value = {
            "spec": {"containers": [{"image": "ghcr.io/heymrun/heym:1"}]}
        }
        self.assertEqual(_backend(client).resolve_image(), "ghcr.io/heymrun/heym:1")
        client.get_pod.return_value = {"spec": {"containers": [{"image": "a"}, {"image": "b"}]}}
        self.assertIsNone(_backend(client).resolve_image())
