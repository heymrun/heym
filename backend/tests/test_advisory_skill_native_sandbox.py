"""A skill on a backend started with run.sh stays inside its sandbox.

Such a backend is not in a container, so a skill's run directory lives on the host and
is bind-mounted into the sandbox. That directory must be private to the backend user,
mounted alone, removed after the run, and impossible to escape: no skill file path, link
the sandbox leaves behind or Drive copy may reach anything outside it. On Kubernetes the
run directory stays on the shared PersistentVolumeClaim and is never a host path.
"""

import os
import stat
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

import app.services.skill_python_executor as executor
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.errors import SandboxConfigError, SandboxTimeoutError

_SKILL = [{"path": "main.py", "content": "print('{}')"}]


class _FakeSandbox:
    """Stands in for the container: runs `act` on the run dir, then exits."""

    def __init__(self, act: Callable[[Path], None] | None = None) -> None:
        self.act = act
        self.spec: Any = None
        self.seen: dict[str, Any] = {}

    def run(self, spec: Any, _stdin: str, _timeout: float) -> Any:
        self.spec = spec
        run_dir = Path(spec.workdir)
        parent = run_dir.parent
        self.seen = {
            "parent_mode": stat.S_IMODE(os.lstat(parent).st_mode),
            "parent_is_link": parent.is_symlink(),
            "parent_owner": os.lstat(parent).st_uid,
        }
        if self.act is not None:
            self.act(run_dir)
        return mock.Mock(stdout='{"ok": true}', stderr="", start_failed=False, returncode=0)


def _run_native(
    sandbox: _FakeSandbox,
    files: list[dict[str, str]] | None = None,
    drive_files: list[dict[str, Any]] | None = None,
) -> executor.SkillExecutionResult:
    with (
        mock.patch.object(executor, "_shared_workspace", return_value=False),
        mock.patch.object(executor, "get_sandbox_manager", return_value=sandbox),
    ):
        return executor._execute_skill_docker(
            files or _SKILL, {}, 30.0, drive_files, "main.py", "img"
        )


def _leftover_parents() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("heym-skill-*")}


class PrivateRunDirTests(unittest.TestCase):
    def test_the_run_dir_sits_in_a_private_parent_that_is_removed(self) -> None:
        before = _leftover_parents()
        sandbox = _FakeSandbox()
        _run_native(sandbox)

        run_dir = Path(sandbox.spec.workdir)
        self.assertEqual(sandbox.seen["parent_mode"] & 0o077, 0, "no group or other access")
        self.assertFalse(sandbox.seen["parent_is_link"])
        self.assertEqual(sandbox.seen["parent_owner"], os.getuid())
        self.assertTrue(run_dir.parent.name.startswith("heym-skill-"))
        self.assertEqual(run_dir.parent.parent, Path(tempfile.gettempdir()))
        self.assertFalse(run_dir.parent.exists())
        self.assertEqual(_leftover_parents(), before)

    def test_every_run_gets_its_own_unpredictable_parent(self) -> None:
        first, second = _FakeSandbox(), _FakeSandbox()
        _run_native(first)
        _run_native(second)
        self.assertNotEqual(Path(first.spec.workdir).parent, Path(second.spec.workdir).parent)

    def test_a_failed_run_leaves_nothing_behind(self) -> None:
        before = _leftover_parents()
        sandbox = mock.Mock()
        sandbox.run.side_effect = SandboxTimeoutError("slow")
        with (
            mock.patch.object(executor, "_shared_workspace", return_value=False),
            mock.patch.object(executor, "get_sandbox_manager", return_value=sandbox),
            self.assertRaises(TimeoutError),
        ):
            executor._execute_skill_docker(_SKILL, {}, 1.0, None, "main.py", "img")
        self.assertEqual(_leftover_parents(), before)


class MountTests(unittest.TestCase):
    def test_only_the_run_dir_is_mounted_into_a_hardened_sandbox(self) -> None:
        run_dir = Path(tempfile.gettempdir()) / "heym-skill-abc" / "run"
        argv = render_docker_argv(
            executor._skill_spec(
                "img",
                "n",
                Path("/app/data/codex-workspaces"),
                run_dir,
                "main.py",
                native_bind=True,
            )
        )
        mounts = [argv[i + 1] for i, item in enumerate(argv) if item == "--mount"]
        self.assertEqual(mounts, [f"type=bind,src={run_dir},dst={run_dir}"])
        for flag in ("--rm", "--read-only", "--cap-drop", "--security-opt", "--pids-limit"):
            self.assertIn(flag, argv)
        self.assertIn("no-new-privileges", argv)
        self.assertEqual(argv[argv.index("--user") + 1], "65534:65534")
        joined = " ".join(argv)
        self.assertNotIn("docker.sock", joined)
        self.assertNotIn(f"src={tempfile.gettempdir()},", joined)
        self.assertNotIn(f"src={Path.home()},", joined)
        self.assertNotIn("-v", argv)


class EscapeTests(unittest.TestCase):
    def test_skill_file_paths_cannot_leave_the_run_dir(self) -> None:
        before = _leftover_parents()
        for path in ("../escape.py", "/tmp/escape.py", "a/../../escape.py", "s/../../../e.py"):
            with self.subTest(path=path):
                sandbox = _FakeSandbox()
                files = [*_SKILL, {"path": path, "content": "x = 1"}]
                with self.assertRaises(ValueError):
                    _run_native(sandbox, files=files)
                self.assertIsNone(sandbox.spec, "the sandbox never starts")
                self.assertFalse((Path(tempfile.gettempdir()) / "escape.py").exists())
        self.assertEqual(_leftover_parents(), before)

    def test_a_backslash_is_part_of_a_name_and_stays_inside(self) -> None:
        seen: list[Path] = []

        def look(run_dir: Path) -> None:
            seen.extend(p for p in run_dir.parent.rglob("*escape.py"))

        files = [*_SKILL, {"path": "..\\escape.py", "content": "x = 1"}]
        sandbox = _FakeSandbox(look)
        _run_native(sandbox, files=files)
        run_dir = Path(sandbox.spec.workdir)
        self.assertEqual([p.parent for p in seen], [run_dir])
        self.assertFalse((Path(tempfile.gettempdir()) / "escape.py").exists())

    def test_links_the_sandbox_leaves_are_neither_collected_nor_followed(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "secret.txt"
            secret.write_text("host secret")
            keep_dir = Path(outside) / "keep"
            keep_dir.mkdir()
            (keep_dir / "file.txt").write_text("keep me")

            def plant(run_dir: Path) -> None:
                output = run_dir / "_output_files"
                output.mkdir(exist_ok=True)
                (output / "stolen.txt").symlink_to(secret)
                (output / "report.txt").write_text("real output")
                (run_dir / "escape").symlink_to(keep_dir, target_is_directory=True)

            result = _run_native(_FakeSandbox(plant))

            names = {item.get("filename") for item in result.generated_files or []}
            self.assertEqual(names, {"report.txt"})
            self.assertNotIn("host secret", repr(result.generated_files))
            self.assertEqual(secret.read_text(), "host secret")
            self.assertEqual((keep_dir / "file.txt").read_text(), "keep me")

    def test_a_drive_file_reaches_the_sandbox_as_a_copy(self) -> None:
        with tempfile.TemporaryDirectory() as storage:
            original = Path(storage) / "contract.txt"
            original.write_text("signed")

            def overwrite(run_dir: Path) -> None:
                for copy in (run_dir / "_drive_files").rglob("contract.txt"):
                    copy.write_text("tampered")

            drive = [{"id": "f1", "filename": "contract.txt", "source_path": str(original)}]
            _run_native(_FakeSandbox(overwrite), drive_files=drive)
            self.assertEqual(original.read_text(), "signed")


class KubernetesTests(unittest.TestCase):
    def _backend(self) -> Any:
        from app.services.sandbox.kubernetes.backend import KubernetesBackend
        from app.services.sandbox.kubernetes.config import KubeConfig

        client = mock.MagicMock()
        client.namespace = "heym"
        client.has_api_group.return_value = False
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteMany"]}}
        client.get_pod.return_value = {
            "spec": {
                "containers": [
                    {"image": "i", "volumeMounts": [{"name": "d", "mountPath": "/app/data"}]}
                ],
                "volumes": [{"name": "d", "persistentVolumeClaim": {"claimName": "heym-data"}}],
            }
        }
        config = KubeConfig(
            server="https://k", namespace="heym", own_namespace="heym", in_cluster=True
        )
        return KubernetesBackend(config, client=client, instance="heym-0")

    def test_kubernetes_keeps_skills_on_the_shared_claim(self) -> None:
        backend = self._backend()
        self.assertTrue(backend.uses_shared_workspace())
        with mock.patch.object(executor, "get_sandbox_manager") as manager:
            manager.return_value.uses_shared_workspace = backend.uses_shared_workspace
            self.assertTrue(executor._shared_workspace())

    def test_a_pod_never_gets_a_host_path_even_for_a_native_spec(self) -> None:
        backend = self._backend()
        run_dir = Path("/app/data/codex-workspaces/_skill-workspaces/_skills/abc")
        for native in (False, True):
            with self.subTest(native_bind=native):
                spec = executor._skill_spec(
                    "img",
                    "n",
                    Path("/app/data/codex-workspaces"),
                    run_dir,
                    "main.py",
                    native_bind=native,
                )
                manifest = backend.manifest(spec, 5)
                volumes = manifest["spec"].get("volumes", [])
                self.assertFalse([v for v in volumes if "hostPath" in v], volumes)
                claims = [
                    m
                    for m in manifest["spec"]["containers"][0]["volumeMounts"]
                    if m["name"].startswith("ws-")
                ]
                self.assertEqual(
                    [m["subPath"] for m in claims],
                    ["codex-workspaces/_skill-workspaces/_skills/abc"],
                )

    def test_a_host_temp_dir_is_refused_on_kubernetes(self) -> None:
        backend = self._backend()
        run_dir = Path(tempfile.gettempdir()) / "heym-skill-abc" / "run"
        spec = executor._skill_spec(
            "img", "n", Path("/app/data/codex-workspaces"), run_dir, "main.py", native_bind=True
        )
        with self.assertRaises(SandboxConfigError):
            backend.manifest(spec, 5)


if __name__ == "__main__":
    unittest.main()
