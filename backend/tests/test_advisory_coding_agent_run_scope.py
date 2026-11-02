"""A Codex or OpenCode run must not see another run's repository or credentials.

Before this fix both Docker wrappers mounted the whole workspace volume, where every
persisted workspace and every ``<id>.codex-home/auth.json`` lives.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.sandbox.coding_agents import (
    CODEX,
    OPENCODE,
    AgentProfile,
    RunScopeError,
    agent_spec,
    run_scope,
)
from app.services.sandbox.docker_backend import render_docker_argv

RUN = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"


class RunScopeAdvisoryTest(unittest.TestCase):
    def _root(self, profile: AgentProfile) -> Path:
        root = Path(tempfile.mkdtemp()).resolve()
        for run in (RUN, OTHER):
            (root / run).mkdir()
            (root / f"{run}{profile.home_suffix}").mkdir()
        return root

    def _env(self, profile: AgentProfile, root: Path, home: Path) -> dict[str, str]:
        return {
            f"{profile.env_prefix}_WORKSPACE_DIR": str(root),
            f"{profile.env_prefix}_DOCKER_WORKSPACE_VOLUME": "vol",
            profile.home_env: str(home),
        }

    def test_docker_argv_never_mounts_the_volume_root_or_another_run(self) -> None:
        for profile in (CODEX, OPENCODE):
            with self.subTest(profile.agent):
                root = self._root(profile)
                env = self._env(profile, root, root / f"{RUN}{profile.home_suffix}")
                with patch.dict(os.environ, env, clear=True):
                    scope = run_scope(profile, root / RUN, env)
                    argv = render_docker_argv(
                        agent_spec(
                            profile,
                            scope,
                            [],
                            env,
                            image="i",
                            name="n",
                            kubernetes=False,
                            cwd=root / RUN,
                        )
                    )
                mounts = [argv[i + 1] for i, token in enumerate(argv) if token == "--mount"]
                self.assertEqual(len(mounts), 2)
                for mount in mounts:
                    self.assertIn("volume-subpath=", mount)
                    self.assertNotIn(f"dst={root},", mount + ",")
                    self.assertNotIn(OTHER, mount)

    def test_cwd_or_home_pointing_elsewhere_is_refused(self) -> None:
        for profile in (CODEX, OPENCODE):
            root = self._root(profile)
            own_home = root / f"{RUN}{profile.home_suffix}"
            other_home = root / f"{OTHER}{profile.home_suffix}"
            for label, cwd, home in (
                ("root as cwd", root, own_home),
                ("other home as cwd", other_home, own_home),
                ("other run's home", root / RUN, other_home),
            ):
                with self.subTest(f"{profile.agent}: {label}"), self.assertRaises(RunScopeError):
                    run_scope(profile, cwd, self._env(profile, root, home))
