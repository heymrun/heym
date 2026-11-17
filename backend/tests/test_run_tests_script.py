"""run_tests.sh must fail closed when a worker leaves no usable status."""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "run_tests.sh"

# Fake uv: behaviour is picked by the suite file name.
FAKE_UV = """#!/bin/sh
case "$3" in
    *test_fail.py) echo "1 failed"; exit 1 ;;
    *test_die.py) kill -9 "$PPID"; sleep 5 ;;
    *) echo "1 passed"; exit 0 ;;
esac
"""

FAKE_XARGS = """#!/bin/sh
{real} "$@"
exit 123
"""


class TestRunTestsScript(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copy(SCRIPT, self.root / "run_tests.sh")
        (self.root / "backend" / "tests").mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.fake("uv", FAKE_UV)

    def fake(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def run_script(self, *suites: str) -> subprocess.CompletedProcess[str]:
        for suite in suites:
            (self.root / "backend" / "tests" / suite).write_text("")
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        return subprocess.run(
            ["sh", str(self.root / "run_tests.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_all_pass(self) -> None:
        result = self.run_script("test_a.py", "test_b.py")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_failing_suite(self) -> None:
        result = self.run_script("test_a.py", "test_fail.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] test_fail.py", result.stdout)

    def test_worker_dies_before_status_file(self) -> None:
        result = self.run_script("test_a.py", "test_die.py")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("[FAIL] test_die.py", result.stdout)
        self.assertIn("no exit status", result.stdout)

    def test_xargs_nonzero_with_passing_suites(self) -> None:
        real = shutil.which("xargs")
        self.fake("xargs", FAKE_XARGS.format(real=real))
        result = self.run_script("test_a.py")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("xargs exited with status 123", result.stdout)


if __name__ == "__main__":
    unittest.main()
