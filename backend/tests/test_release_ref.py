"""Exercise the release source gate against real Git histories."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

VERIFY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify-release-ref.sh"


class TestReleaseRef(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Release Test",
            "GIT_AUTHOR_EMAIL": "release@example.com",
            "GIT_COMMITTER_NAME": "Release Test",
            "GIT_COMMITTER_EMAIL": "release@example.com",
        }
        self.git("init", "-b", "main")
        (self.repo / "VERSION").write_text("1.2.3\n")
        self.git("add", "VERSION")
        self.git("commit", "-m", "Initial version")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def git(self, *args: str) -> str:
        """Run Git in the isolated repository without inheriting signing policy."""
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
            cwd=self.repo,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def verify(self, tag: str = "v1.2.3") -> subprocess.CompletedProcess[str]:
        """Invoke the same gate used by the publish workflow."""
        return subprocess.run(
            ["sh", str(VERIFY_SCRIPT), tag],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_accepts_lightweight_tag_on_main(self) -> None:
        self.git("tag", "v1.2.3")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_annotated_tag_on_detached_main_ancestor(self) -> None:
        self.git("tag", "-a", "v1.2.3", "-m", "Release")
        self.git("commit", "--allow-empty", "-m", "Later change")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "--detach", "v1.2.3")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_unmerged_commit(self) -> None:
        self.git("checkout", "-b", "unmerged")
        self.git("commit", "--allow-empty", "-m", "Unmerged change")
        self.git("tag", "v1.2.3")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be present on origin/main", result.stderr)

    def test_rejects_version_mismatch(self) -> None:
        self.git("tag", "v1.2.4")
        result = self.verify("v1.2.4")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must match v<VERSION>", result.stderr)

    def test_rejects_tag_pointing_to_another_commit(self) -> None:
        self.git("tag", "v1.2.3")
        self.git("commit", "--allow-empty", "-m", "Later change")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not point to the checked-out commit", result.stderr)

    def test_rejects_missing_tag(self) -> None:
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_missing_version_file(self) -> None:
        self.git("tag", "v")
        (self.repo / "VERSION").unlink()
        result = self.verify("v")
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_empty_version(self) -> None:
        self.git("tag", "v")
        (self.repo / "VERSION").write_text("")
        result = self.verify("v")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must match v<VERSION>", result.stderr)

    def test_rejects_missing_main_history(self) -> None:
        self.git("tag", "v1.2.3")
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be present on origin/main", result.stderr)
