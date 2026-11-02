import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.sandbox import reset_sandbox_manager, wrapper_cli

RUN = "0123456789abcdef0123456789abcdef"


class WrapperCliTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)
        for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.addCleanup(signal.signal, caught, signal.getsignal(caught))
        self.root = Path(tempfile.mkdtemp()).resolve()
        for name in (RUN, f"{RUN}.oc-home"):
            (self.root / name).mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "HEYM_OPENCODE_WORKSPACE_DIR": str(self.root),
            "HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME": "heym-opencode-workspaces",
            "HEYM_OPENCODE_DOCKER_IMAGE": "img:1",
            "HOME": f"{self.root}/{RUN}.oc-home",
            "HEYM_OPENCODE_RUN_ID": "abc123",
        }

    def test_runs_docker_with_the_scoped_spec_and_removes_the_container(self) -> None:
        process = MagicMock()
        process.wait.return_value = 0
        with (
            patch.dict(os.environ, self.env, clear=True),
            patch.object(wrapper_cli.Path, "cwd", return_value=self.root / RUN),
            patch("subprocess.Popen", return_value=process) as popen,
            patch("app.services.sandbox.docker_backend._docker_rm") as rm,
        ):
            code = wrapper_cli.main(["opencode", "run", "hi"])
        self.assertEqual(code, 0)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:2], ["docker", "run"])
        self.assertEqual(argv[argv.index("--name") + 1], "heym-opencode-abc123")
        self.assertEqual(argv[-3:], ["img:1", "run", "hi"])
        rm.assert_called_with("heym-opencode-abc123")

    def test_refuses_a_cwd_outside_a_run(self) -> None:
        with (
            patch.dict(os.environ, self.env, clear=True),
            patch.object(wrapper_cli.Path, "cwd", return_value=self.root),
            patch("subprocess.Popen") as popen,
        ):
            self.assertEqual(wrapper_cli.main(["opencode", "run"]), 2)
        popen.assert_not_called()

    def test_unknown_agent(self) -> None:
        self.assertEqual(wrapper_cli.main(["vim"]), 2)
