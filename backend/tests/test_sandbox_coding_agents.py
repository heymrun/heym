import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.sandbox.coding_agents import CODEX, OPENCODE, RunScopeError, agent_spec, run_scope
from app.services.sandbox.docker_backend import render_docker_argv

RUN = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"


class RunScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        for name in (RUN, f"{RUN}.codex-home", f"{RUN}.oc-home", OTHER, f"{OTHER}.codex-home"):
            (self.root / name).mkdir()
        (self.root / RUN / "src").mkdir()

    def _codex_env(self, home: str) -> dict[str, str]:
        return {"HEYM_CODEX_WORKSPACE_DIR": str(self.root), "CODEX_HOME": home}

    def test_codex_scope_is_the_run_and_its_home(self) -> None:
        scope = run_scope(
            CODEX, self.root / RUN / "src", self._codex_env(f"{self.root}/{RUN}.codex-home")
        )
        self.assertEqual(scope.run_id, RUN)
        self.assertEqual(scope.workspace, self.root / RUN)
        self.assertEqual(scope.home, self.root / f"{RUN}.codex-home")

    def test_opencode_scope_uses_home(self) -> None:
        env = {"HEYM_OPENCODE_WORKSPACE_DIR": str(self.root), "HOME": f"{self.root}/{RUN}.oc-home"}
        self.assertEqual(
            run_scope(OPENCODE, self.root / RUN, env).home, self.root / f"{RUN}.oc-home"
        )

    def test_refusals(self) -> None:
        good_home = f"{self.root}/{RUN}.codex-home"
        cases = {
            "cwd is the root": (self.root, good_home),
            "cwd outside the root": (Path(tempfile.gettempdir()), good_home),
            "cwd is a home dir": (self.root / f"{OTHER}.codex-home", good_home),
            "home of another run": (self.root / RUN, f"{self.root}/{OTHER}.codex-home"),
            "legacy shared home": (self.root / RUN, f"{self.root}/.codex-home"),
            "home unset": (self.root / RUN, ""),
        }
        for label, (cwd, home) in cases.items():
            with self.subTest(label), self.assertRaises(RunScopeError):
                run_scope(CODEX, cwd, self._codex_env(home))

    def test_missing_home_directory_is_refused(self) -> None:
        (self.root / f"{RUN}.codex-home").rmdir()
        with self.assertRaises(RunScopeError):
            run_scope(CODEX, self.root / RUN, self._codex_env(f"{self.root}/{RUN}.codex-home"))


class AgentSpecTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        for name in (RUN, f"{RUN}.codex-home", f"{RUN}.oc-home"):
            (self.root / name).mkdir()
        self.env = {
            "HEYM_CODEX_WORKSPACE_DIR": str(self.root),
            "CODEX_HOME": f"{self.root}/{RUN}.codex-home",
            "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces",
        }

    def _argv(self, kubernetes: bool = False) -> list[str]:
        scope = run_scope(CODEX, self.root / RUN, self.env)
        with patch.dict(os.environ, self.env, clear=True):
            spec = agent_spec(
                CODEX,
                scope,
                ["exec", "hi"],
                self.env,
                image="img",
                name="heym-codex-x",
                kubernetes=kubernetes,
                cwd=self.root / RUN,
            )
            return render_docker_argv(spec)

    def test_docker_mounts_exactly_the_run_and_its_home(self) -> None:
        argv = self._argv()
        mounts = [argv[i + 1] for i, token in enumerate(argv) if token == "--mount"]
        self.assertEqual(
            mounts,
            [
                f"type=volume,src=heym-codex-workspaces,dst={self.root}/{RUN},volume-subpath={RUN}",
                f"type=volume,src=heym-codex-workspaces,dst={self.root}/{RUN}.codex-home,"
                f"volume-subpath={RUN}.codex-home",
            ],
        )

    def test_bind_source_is_scoped_too(self) -> None:
        self.env.pop("HEYM_CODEX_DOCKER_WORKSPACE_VOLUME")
        self.env["HEYM_CODEX_HOST_WORKSPACE_DIR"] = "/srv/codex"
        argv = self._argv()
        mounts = [argv[i + 1] for i, token in enumerate(argv) if token == "--mount"]
        self.assertEqual(
            mounts,
            [
                f"type=bind,src=/srv/codex/{RUN},dst={self.root}/{RUN}",
                f"type=bind,src=/srv/codex/{RUN}.codex-home,dst={self.root}/{RUN}.codex-home",
            ],
        )

    def test_kubernetes_spec_gates_start_and_trusts_the_repo(self) -> None:
        scope = run_scope(CODEX, self.root / RUN, self.env)
        spec = agent_spec(
            CODEX,
            scope,
            ["exec"],
            self.env,
            image="img",
            name="n",
            kubernetes=True,
            cwd=self.root / RUN,
        )
        self.assertTrue(spec.start_gate)
        self.assertIn("GIT_CONFIG_VALUE_0=*", spec.env)
        docker_spec = agent_spec(
            CODEX,
            scope,
            ["exec"],
            self.env,
            image="img",
            name="n",
            kubernetes=False,
            cwd=self.root / RUN,
        )
        self.assertFalse(docker_spec.start_gate)
        self.assertNotIn("GIT_CONFIG_VALUE_0=*", docker_spec.env)
