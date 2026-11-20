"""A skill's tool runs any of the skill's own Python scripts, with arguments, in the sandbox.

Skills written for a shell (`python scripts/x.py in.docx out/`) run in Heym through the
skill tool's `script` and `args`: no shell, only the skill's own .py files, arguments as
argv, and `{output_dir}` naming the folder whose files the user receives.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.services.skill_python_executor as executor
from app.services.skill_python_executor import (
    OUTPUT_DIR_PLACEHOLDER,
    execute_skill_python,
    plan_invocation,
)

_ECHO = (
    "import json, os, sys\n"
    "print(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read(),"
    " 'out': os.environ.get('_OUTPUT_DIR')}))\n"
)
_FILES = [
    {"path": "main.py", "content": "print('{\"entry\": true}')"},
    {"path": "scripts/office/unpack.py", "content": _ECHO},
    {
        "path": "scripts/write.py",
        "content": (
            "import os, sys\n"
            "open(os.path.join(sys.argv[1], 'report.docx'), 'w').write('doc')\n"
            "print('{\"written\": true}')\n"
        ),
    },
    {"path": "SKILL.md", "content": "# Skill"},
]


class PlanTests(unittest.TestCase):
    def test_without_a_script_the_entry_point_runs_with_the_old_stdin(self) -> None:
        plan = plan_invocation(_FILES, {"input": "hello"})
        self.assertEqual((plan.script, plan.argv, plan.stdin), ("main.py", (), "hello"))
        legacy = plan_invocation(_FILES, {"a": 1})
        self.assertEqual(json.loads(legacy.stdin), {"a": 1})

    def test_a_named_script_with_arguments(self) -> None:
        plan = plan_invocation(
            _FILES,
            {"script": "./scripts/office/unpack.py", "args": ["in.docx", 3], "input": "x"},
        )
        self.assertEqual(plan.script, "scripts/office/unpack.py")
        self.assertEqual(plan.argv, ("in.docx", "3"))
        self.assertEqual(plan.stdin, "x")

    def test_only_the_skills_own_python_files_can_run(self) -> None:
        for script in (
            "../escape.py",
            "/usr/bin/python3",
            "scripts/../../x.py",
            "SKILL.md",
            "scripts/missing.py",
            "scripts/office",
        ):
            with self.subTest(script=script), self.assertRaises(ValueError):
                plan_invocation(_FILES, {"script": script})

    def test_arguments_are_checked(self) -> None:
        for args in (
            "in.docx",
            [{"x": 1}],
            ["a\x00b"],
            ["x" * 4001],
            ["a"] * 65,
        ):
            with self.subTest(args=str(args)[:40]), self.assertRaises(ValueError):
                plan_invocation(_FILES, {"script": "scripts/write.py", "args": args})


class SubprocessRunTests(unittest.TestCase):
    """The local subprocess path runs the plan for real (dev only, no shell)."""

    def _run(self, arguments: dict) -> executor.SkillExecutionResult:
        with mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "subprocess"}):
            return execute_skill_python(_FILES, arguments, 30)

    def test_arguments_reach_the_script_as_argv_without_a_shell(self) -> None:
        result = self._run(
            {
                "script": "scripts/office/unpack.py",
                "args": ["in.docx; rm -rf ~", "$(whoami)", OUTPUT_DIR_PLACEHOLDER],
                "input": "payload",
            }
        )
        output = result.output
        self.assertEqual(output["argv"][:2], ["in.docx; rm -rf ~", "$(whoami)"])
        self.assertEqual(output["argv"][2], output["out"])
        self.assertEqual(output["stdin"], "payload")

    def test_files_written_to_output_dir_reach_the_user(self) -> None:
        result = self._run({"script": "scripts/write.py", "args": [OUTPUT_DIR_PLACEHOLDER]})
        self.assertEqual(result.output, {"written": True})
        names = [item.get("filename") for item in result.generated_files or []]
        self.assertEqual(names, ["report.docx"])

    def test_an_unknown_script_fails_before_anything_runs(self) -> None:
        with self.assertRaises(ValueError):
            self._run({"script": "scripts/../../../tmp/evil.py"})


class SandboxArgvTests(unittest.TestCase):
    def test_the_sandbox_runs_the_script_with_resolved_arguments(self) -> None:
        manager = mock.Mock()
        manager.run.return_value = mock.Mock(
            stdout="{}", stderr="", start_failed=False, returncode=0
        )
        with (
            mock.patch.object(executor, "_shared_workspace", return_value=False),
            mock.patch.object(executor, "get_sandbox_manager", return_value=manager),
        ):
            executor._execute_skill_docker(
                _FILES,
                {"input": "x"},
                30.0,
                None,
                "scripts/office/unpack.py",
                "img",
                argv=("in.docx", OUTPUT_DIR_PLACEHOLDER),
            )
        spec, stdin, _timeout = manager.run.call_args.args
        run_dir = Path(spec.workdir)
        self.assertEqual(
            spec.args,
            ("scripts/office/unpack.py", "in.docx", str(run_dir / "_output_files")),
        )
        self.assertEqual(stdin, "x")
        self.assertTrue(run_dir.is_relative_to(Path(tempfile.gettempdir())))


class SkillLibrariesTests(unittest.TestCase):
    """Office skills parse document XML with defusedxml, in either Python a skill runs in."""

    def test_defusedxml_is_in_the_backend_and_the_sandbox_image(self) -> None:
        backend = Path(__file__).resolve().parents[1]
        pyproject = (backend / "pyproject.toml").read_text(encoding="utf-8")
        sandbox = (backend.parent / "docker" / "sandbox-requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('"defusedxml>=', pyproject)
        self.assertIn("defusedxml==", sandbox)


if __name__ == "__main__":
    unittest.main()
