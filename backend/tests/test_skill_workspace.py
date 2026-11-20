"""A skill keeps one workspace for one agent run, and a failing script is an error.

The first call writes the skill's files; later calls of the same skill in the same run see
what earlier calls wrote, so a skill can make a document and then check or convert it. Only
files that are new or changed since the last call reach Drive. The agent node closes the
workspace when it ends.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.services.skill_python_executor as executor
from app.services.skill_python_executor import (
    OUTPUT_DIR_PLACEHOLDER,
    SkillWorkspace,
    execute_skill_python,
)

_FILES = [
    {
        "path": "make.py",
        "content": (
            "import os, sys\n"
            "open(os.path.join(os.environ['_OUTPUT_DIR'], 'report.docx'), 'w')"
            ".write(sys.stdin.read() or 'v1')\n"
            "print('{\"made\": true}')\n"
        ),
    },
    {
        "path": "check.py",
        "content": (
            "import os, sys\n"
            "text = open(sys.argv[1]).read()\n"
            "open(os.path.join(os.environ['_OUTPUT_DIR'], 'checked.txt'), 'w').write(text)\n"
            "print('{\"checked\": \"' + text + '\"}')\n"
        ),
    },
    {"path": "fail.py", "content": "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n"},
    {
        "path": "review.py",
        "content": (
            "import json, os\n"
            "p = os.path.join(os.environ['_OUTPUT_DIR'], '_hitl_request.json')\n"
            "json.dump({'draft_text': 'ok?'}, open(p, 'w'))\n"
            "print('{}')\n"
        ),
    },
]


def _names(result: executor.SkillExecutionResult) -> list[str]:
    return sorted(item["filename"] for item in result.generated_files or [])


class LocalWorkspaceTests(unittest.TestCase):
    """The subprocess path (dev only) runs the calls for real."""

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "subprocess"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.workspace = SkillWorkspace()
        self.addCleanup(self.workspace.close)

    def _call(self, arguments: dict) -> executor.SkillExecutionResult:
        return execute_skill_python(_FILES, arguments, 30, workspace=self.workspace)

    def test_a_later_call_reads_what_an_earlier_call_wrote(self) -> None:
        first = self._call({"script": "make.py"})
        second = self._call(
            {"script": "check.py", "args": [f"{OUTPUT_DIR_PLACEHOLDER}/report.docx"]}
        )
        self.assertEqual(_names(first), ["report.docx"])
        self.assertEqual(second.output, {"checked": "v1"})
        # The document made earlier is not saved to Drive a second time.
        self.assertEqual(_names(second), ["checked.txt"])

    def test_a_changed_file_is_saved_again(self) -> None:
        self._call({"script": "make.py"})
        again = self._call({"script": "make.py", "input": "version two"})
        self.assertEqual(_names(again), ["report.docx"])

    def test_a_review_request_is_read_once(self) -> None:
        self.assertIsNotNone(self._call({"script": "review.py"}).hitl_request)
        self.assertIsNone(self._call({"script": "make.py"}).hitl_request)

    def test_the_workspace_is_private_and_removed_on_close(self) -> None:
        self._call({"script": "make.py"})
        run_dir = self.workspace.run_dir
        assert run_dir is not None
        self.assertEqual(stat.S_IMODE(os.lstat(run_dir.parent).st_mode) & 0o077, 0)
        self.workspace.close()
        self.assertFalse(run_dir.parent.exists())
        with self.assertRaises(RuntimeError):
            self._call({"script": "make.py"})

    def test_a_script_that_fails_reports_its_exit_code(self) -> None:
        result = self._call({"script": "fail.py"})
        self.assertEqual(result.exit_code, 3)
        self.assertIn("boom", result.stderr)

    def test_without_a_workspace_every_call_starts_empty(self) -> None:
        execute_skill_python(_FILES, {"script": "make.py"}, 30)
        alone = execute_skill_python(
            _FILES, {"script": "check.py", "args": [f"{OUTPUT_DIR_PLACEHOLDER}/report.docx"]}, 30
        )
        self.assertNotEqual(alone.exit_code, 0)


class SandboxWorkspaceTests(unittest.TestCase):
    def test_sandbox_calls_share_one_private_run_dir(self) -> None:
        manager = mock.Mock()
        manager.run.return_value = mock.Mock(
            stdout="{}", stderr="", start_failed=False, returncode=0
        )
        workspace = SkillWorkspace()
        with (
            mock.patch.object(executor, "_shared_workspace", return_value=False),
            mock.patch.object(executor, "get_sandbox_manager", return_value=manager),
        ):
            for _ in range(2):
                executor._execute_skill_docker(
                    _FILES, {}, 30.0, None, "make.py", "img", workspace=workspace
                )
        first, second = (call.args[0] for call in manager.run.call_args_list)
        self.assertEqual(first.workdir, second.workdir)
        run_dir = Path(first.workdir)
        self.assertTrue(run_dir.is_relative_to(Path(tempfile.gettempdir())))
        self.assertTrue(run_dir.exists())
        workspace.close()
        self.assertFalse(run_dir.exists())


class ToolResultTests(unittest.TestCase):
    def test_a_failing_script_is_an_error_for_the_agent(self) -> None:
        from app.services.llm_service import _skill_tool_output

        failed = executor.SkillExecutionResult(
            output={"output": ""}, exit_code=3, stderr="Traceback: boom"
        )
        output = _skill_tool_output(failed)
        self.assertEqual(output["status"], "error")
        self.assertIn("exited with code 3", output["error"])
        self.assertIn("boom", output["stderr"])
        ok = executor.SkillExecutionResult(output={"made": True}, exit_code=0)
        self.assertEqual(_skill_tool_output(ok), {"made": True})


if __name__ == "__main__":
    unittest.main()
