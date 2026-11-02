import tempfile
import unittest
from pathlib import Path

from app.services.sandbox.coding_agents import CODEX, OPENCODE, RunScopeError, run_scope

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
        scope = run_scope(CODEX, self.root / RUN / "src", self._codex_env(f"{self.root}/{RUN}.codex-home"))
        self.assertEqual(scope.run_id, RUN)
        self.assertEqual(scope.workspace, self.root / RUN)
        self.assertEqual(scope.home, self.root / f"{RUN}.codex-home")

    def test_opencode_scope_uses_home(self) -> None:
        env = {"HEYM_OPENCODE_WORKSPACE_DIR": str(self.root), "HOME": f"{self.root}/{RUN}.oc-home"}
        self.assertEqual(run_scope(OPENCODE, self.root / RUN, env).home, self.root / f"{RUN}.oc-home")

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
