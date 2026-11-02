import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.sandbox import docker_backend
from app.services.sandbox.docker_backend import (
    DockerBackend,
    docker_mount_args,
    operator_mount_args,
    render_docker_argv,
)
from app.services.sandbox.errors import SandboxTimeoutError
from app.services.sandbox.spec import (
    DockerVolumeSource,
    OperatorMount,
    SandboxSpec,
    Tmpfs,
    WorkspaceMount,
)

_SOURCE = DockerVolumeSource(
    mount_point=Path("/app/data/codex-workspaces"),
    volume_env=("HEYM_TEST_VOLUME",),
    host_root_env="HEYM_TEST_HOST_ROOT",
    missing_message="no shared volume",
)


def _mount(
    host: str, readonly: bool = False, source: DockerVolumeSource = _SOURCE
) -> WorkspaceMount:
    return WorkspaceMount(host_path=Path(host), target=host, readonly=readonly, docker=source)


class RenderTest(unittest.TestCase):
    def test_full_spec_renders_in_canonical_order(self) -> None:
        spec = SandboxSpec(
            site="t",
            name="heym-t-1",
            image="img:1",
            entrypoint="python",
            args=("-c", "pass"),
            tmpfs=(Tmpfs("/tmp", "rw,nosuid", "64m"),),
            workdir="/tmp",
            pids="128",
            memory="256m",
            memory_swap="256m",
            cpus="1",
            env=("A=1", "B=2"),
        )
        self.assertEqual(
            render_docker_argv(spec),
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--name",
                "heym-t-1",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,nosuid,size=64m",
                "--workdir",
                "/tmp",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "128",
                "--memory",
                "256m",
                "--memory-swap",
                "256m",
                "--cpus",
                "1",
                "--env",
                "A=1",
                "--env",
                "B=2",
                "--entrypoint",
                "python",
                "img:1",
                "-c",
                "pass",
            ],
        )

    def test_image_default_entrypoint_and_no_user(self) -> None:
        spec = SandboxSpec(site="t", name="n", image="img", entrypoint=None, user=None, args=("x",))
        argv = render_docker_argv(spec)
        self.assertNotIn("--entrypoint", argv)
        self.assertNotIn("--user", argv)
        self.assertEqual(argv[-2:], ["img", "x"])


class MountTest(unittest.TestCase):
    def test_native_backend_binds_the_path_itself(self) -> None:
        source = DockerVolumeSource(Path("/unused"), (), "x", native_bind=True)
        self.assertEqual(
            docker_mount_args(_mount("/tmp/r", readonly=True, source=source)),
            ["--mount", "type=bind,src=/tmp/r,dst=/tmp/r,readonly"],
        )

    def test_named_volume_mounts_only_the_subpath(self) -> None:
        with patch.dict(os.environ, {"HEYM_TEST_VOLUME": "vol"}, clear=True):
            args = docker_mount_args(_mount("/app/data/codex-workspaces/_code-runs/abc", True))
        self.assertEqual(
            args,
            [
                "--mount",
                "type=volume,src=vol,dst=/app/data/codex-workspaces/_code-runs/abc,"
                "volume-subpath=_code-runs/abc,readonly",
            ],
        )

    def test_host_root_env_binds_the_subdirectory(self) -> None:
        with patch.dict(os.environ, {"HEYM_TEST_HOST_ROOT": "/srv/ws"}, clear=True):
            args = docker_mount_args(_mount("/app/data/codex-workspaces/x"))
        self.assertEqual(
            args, ["--mount", "type=bind,src=/srv/ws/x,dst=/app/data/codex-workspaces/x"]
        )

    def test_inspected_volume_and_bind(self) -> None:
        volume = [{"Destination": "/app/data/codex-workspaces", "Type": "volume", "Name": "v"}]
        bind = [{"Destination": "/app/data/codex-workspaces", "Type": "bind", "Source": "/h"}]
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(docker_backend, "current_container_mounts", return_value=volume):
                self.assertIn(
                    "volume-subpath=x", docker_mount_args(_mount("/app/data/codex-workspaces/x"))[1]
                )
            with patch.object(docker_backend, "current_container_mounts", return_value=bind):
                self.assertEqual(
                    docker_mount_args(_mount("/app/data/codex-workspaces/x"))[1],
                    "type=bind,src=/h/x,dst=/app/data/codex-workspaces/x",
                )

    def test_missing_volume_and_outside_path_fail_closed(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(docker_backend, "current_container_mounts", return_value=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "no shared volume"):
                docker_mount_args(_mount("/app/data/codex-workspaces/x"))
        with self.assertRaisesRegex(RuntimeError, "is not under the workspace volume mount"):
            docker_mount_args(_mount("/elsewhere/x"))

    def test_operator_mounts(self) -> None:
        self.assertEqual(
            operator_mount_args(OperatorMount(target="/mnt/f", volume="v", subpath="a")),
            ["--mount", "type=volume,src=v,dst=/mnt/f,volume-subpath=a,readonly"],
        )
        self.assertEqual(
            operator_mount_args(OperatorMount(target="/mnt/f", host_dir="/srv", writable=True)),
            ["--volume", "/srv:/mnt/f"],
        )


class BackendTest(unittest.TestCase):
    def _spec(self) -> SandboxSpec:
        return SandboxSpec(site="t", name="heym-t-1", image="img", entrypoint="python")

    def test_run_returns_the_result(self) -> None:
        proc = MagicMock()
        proc.communicate.return_value = ("out", "err")
        proc.returncode = 3
        with patch("subprocess.Popen", return_value=proc) as popen:
            result = DockerBackend().run(self._spec(), "payload", 5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, "out", "err"))
        self.assertEqual(popen.call_args.args[0][:2], ["docker", "run"])
        proc.communicate.assert_called_once_with(input="payload", timeout=5)

    def test_timeout_kills_removes_and_raises(self) -> None:
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        with (
            patch("subprocess.Popen", return_value=proc),
            patch.object(docker_backend, "_docker_rm") as rm,
        ):
            with self.assertRaises(SandboxTimeoutError):
                DockerBackend().run(self._spec(), None, 5)
        proc.kill.assert_called_once()
        rm.assert_called_once_with("heym-t-1")

    def test_availability_is_probed_once(self) -> None:
        ok = subprocess.CompletedProcess([], 0, "27.0\n", "")
        with patch("subprocess.run", return_value=ok) as run:
            backend = DockerBackend()
            self.assertTrue(backend.available())
            self.assertTrue(backend.available())
        run.assert_called_once()

    def test_missing_cli_is_unavailable(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(DockerBackend().available())

    def test_process_command_is_the_docker_argv(self) -> None:
        command = DockerBackend().process_command(self._spec())
        self.assertEqual(command.argv[:2], ["docker", "run"])
        self.assertEqual(command.env, {})
        self.assertEqual(command.name, "heym-t-1")
