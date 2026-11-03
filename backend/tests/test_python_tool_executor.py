import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

import app.services.python_tool_executor as executor
from app.services import python_tool_runner
from app.services.python_tool_executor import execute_tool


class PythonToolRunnerValidationTest(unittest.TestCase):
    """Direct, fast tests of the in-process validation in the runner module."""

    def test_run_executes_basic_tool_code(self) -> None:
        code = "def add(left, right):\n    return left + right\n"
        result = python_tool_runner.run(
            {"code": code, "function_name": "add", "arguments": {"left": 2, "right": 3}}
        )
        self.assertEqual(result, 5)

    def test_run_allows_safe_stdlib_imports(self) -> None:
        code = (
            "def f():\n"
            "    import math, json, datetime\n"
            "    return json.dumps({'sqrt': math.sqrt(16)})\n"
        )
        result = python_tool_runner.run({"code": code, "function_name": "f", "arguments": {}})
        self.assertIn("4.0", result)

    def test_run_blocks_disallowed_import(self) -> None:
        # sqlite3 is not allowlisted -> rejected by the import allowlist.
        code = "def f():\n    import sqlite3\n    return 1\n"
        with self.assertRaisesRegex(ValueError, "not allowed"):
            python_tool_runner.run({"code": code, "function_name": "f", "arguments": {}})

    def test_run_blocks_attribute_os_reexport(self) -> None:
        # uuid is allowlisted, but reaching uuid.os via attribute access is blocked.
        code = "def f():\n    import uuid\n    return uuid.os.getpid()\n"
        with self.assertRaisesRegex(ValueError, "restricted attribute 'os'"):
            python_tool_runner.run({"code": code, "function_name": "f", "arguments": {}})

    def test_run_blocks_from_import_reexport(self) -> None:
        # `from uuid import os` reaches the os module without an attribute node.
        code = "def f():\n    from uuid import os as o\n    return o.getpid()\n"
        with self.assertRaisesRegex(ValueError, "not allowed"):
            python_tool_runner.run({"code": code, "function_name": "f", "arguments": {}})

    def test_run_blocks_private_attribute_access(self) -> None:
        code = "def probe(value):\n    return value._private\n"
        with self.assertRaisesRegex(ValueError, "private Python attributes"):
            python_tool_runner.run(
                {"code": code, "function_name": "probe", "arguments": {"value": {"_private": "x"}}}
            )

    def test_run_blocks_object_graph_escape(self) -> None:
        code = (
            "def leak():\n"
            "    cw = [\n"
            "        c for c in ().__class__.__base__.__subclasses__()\n"
            '        if c.__name__ == "catch_warnings"\n'
            "    ][0]\n"
            "    return cw\n"
        )
        with self.assertRaisesRegex(ValueError, "restricted Python introspection primitive"):
            python_tool_runner.run({"code": code, "function_name": "leak", "arguments": {}})

    def test_run_rejects_missing_function(self) -> None:
        code = "def present():\n    return 1\n"
        with self.assertRaises(NameError):
            python_tool_runner.run({"code": code, "function_name": "absent", "arguments": {}})


class PythonToolSubprocessBackendTest(unittest.TestCase):
    """End-to-end tests through execute_tool() forced into subprocess mode."""

    def setUp(self) -> None:
        self._prev = os.environ.get("HEYM_PYTHON_TOOL_SANDBOX")
        os.environ["HEYM_PYTHON_TOOL_SANDBOX"] = "subprocess"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("HEYM_PYTHON_TOOL_SANDBOX", None)
        else:
            os.environ["HEYM_PYTHON_TOOL_SANDBOX"] = self._prev

    def test_executes_basic_tool_code(self) -> None:
        code = "def add(left: int, right: int) -> int:\n    return left + right\n"
        self.assertEqual(execute_tool(code, "add", {"left": 2, "right": 3}, 5), 5)

    def test_rejects_object_graph_import_bypass(self) -> None:
        code = (
            "def leak() -> dict:\n"
            "    cw = [\n"
            "        c for c in ().__class__.__base__.__subclasses__()\n"
            '        if c.__name__ == "catch_warnings"\n'
            "    ][0]\n"
            "    imp = cw()._module.__builtins__['__import__']\n"
            "    os_mod = imp('os')\n"
            "    return {'secret': os_mod.environ.get('HEYM_PYTHON_TOOL_SECRET')}\n"
        )
        os.environ["HEYM_PYTHON_TOOL_SECRET"] = "should-not-leak"
        try:
            with self.assertRaisesRegex(ValueError, "restricted Python introspection primitive"):
                execute_tool(code, "leak", {}, 5)
        finally:
            os.environ.pop("HEYM_PYTHON_TOOL_SECRET", None)

    def test_rejects_private_attribute_access(self) -> None:
        code = "def probe(value):\n    return value._private\n"
        with self.assertRaisesRegex(ValueError, "private Python attributes"):
            execute_tool(code, "probe", {"value": {"_private": "x"}}, 5)

    def _assert_blocked_without_side_effect(self, code_template: str) -> None:
        marker = os.path.join(tempfile.gettempdir(), f"heym_test_marker_{uuid.uuid4().hex}")
        code = code_template.replace("MARKER", marker)
        try:
            with self.assertRaises(ValueError):
                execute_tool(code, "run", {}, 5)
            self.assertFalse(os.path.exists(marker))
        finally:
            if os.path.exists(marker):
                os.remove(marker)

    def test_blocks_glob_os_system_escape(self) -> None:
        self._assert_blocked_without_side_effect(
            "def run():\n    import glob\n    return glob.os.system('touch MARKER')\n"
        )

    def test_blocks_from_import_os_escape(self) -> None:
        self._assert_blocked_without_side_effect(
            "def run():\n    from uuid import os as o\n    return o.system('touch MARKER')\n"
        )

    def test_blocks_operator_attrgetter_escape(self) -> None:
        # operator is no longer allowlisted, so attrgetter is unreachable.
        self._assert_blocked_without_side_effect(
            "def run():\n"
            "    import operator, uuid\n"
            "    return operator.attrgetter('o'+'s')(uuid).system('touch MARKER')\n"
        )

    def test_blocks_pathlib_file_read(self) -> None:
        code = (
            "def run():\n"
            "    from pathlib import Path\n"
            "    return Path('/etc/hostname').read_text()\n"
        )
        with self.assertRaisesRegex(ValueError, "not allowed"):
            execute_tool(code, "run", {}, 5)

    def test_does_not_inherit_backend_environment(self) -> None:
        code = 'def read_env() -> str:\n    import json\n    return "ok"\n'
        os.environ["HEYM_PYTHON_TOOL_SECRET"] = "should-not-leak"
        try:
            result = execute_tool(code, "read_env", {}, 5)
        finally:
            os.environ.pop("HEYM_PYTHON_TOOL_SECRET", None)
        self.assertEqual(result, "ok")


class PythonToolSandboxModeTest(unittest.TestCase):
    """Backend selection logic (fail-closed) and Docker command hardening."""

    def test_auto_fails_closed_when_docker_unavailable(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "auto"}),
            mock.patch.object(executor, "_docker_available", return_value=False),
            mock.patch.object(executor, "_execute_subprocess", side_effect=AssertionError) as sub,
        ):
            with self.assertRaises(RuntimeError):
                execute_tool("def f():\n return 1\n", "f", {}, 5)
            sub.assert_not_called()

    def test_auto_uses_docker_when_available(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "auto"}),
            mock.patch.object(executor, "_docker_available", return_value=True),
            mock.patch.object(executor, "_resolve_image", return_value="heym-backend"),
            mock.patch.object(
                executor, "_execute_docker", return_value='{"success": true, "result": 9}'
            ) as dock,
            mock.patch.object(executor, "_execute_subprocess", side_effect=AssertionError) as sub,
        ):
            self.assertEqual(execute_tool("def f():\n return 9\n", "f", {}, 5), 9)
            dock.assert_called_once()
            sub.assert_not_called()

    def test_docker_mode_requires_docker(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "docker"}),
            mock.patch.object(executor, "_docker_available", return_value=False),
        ):
            with self.assertRaises(RuntimeError):
                execute_tool("def f():\n return 1\n", "f", {}, 5)

    def test_subprocess_mode_does_not_use_docker(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "subprocess"}),
            mock.patch.object(
                executor, "_execute_subprocess", return_value='{"success": true, "result": 3}'
            ) as sub,
            mock.patch.object(executor, "_execute_docker", side_effect=AssertionError) as dock,
            mock.patch.object(executor, "_docker_available", side_effect=AssertionError),
        ):
            self.assertEqual(execute_tool("def f():\n return 3\n", "f", {}, 5), 3)
            sub.assert_called_once()
            dock.assert_not_called()

    def test_docker_command_is_hardened_and_has_no_socket(self) -> None:
        cmd = executor._build_docker_command("heym-backend", "heym-pytool-test")
        # Real isolation flags must be present.
        for flag in (
            "--rm",
            "--read-only",
            "--cap-drop",
            "--security-opt",
            "--pids-limit",
            "--memory",
            "--user",
        ):
            self.assertIn(flag, cmd)
        self.assertIn("ALL", cmd)
        self.assertIn("no-new-privileges", cmd)
        # Network disabled by default.
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        # The image ENTRYPOINT (uvicorn startup) must be overridden to run python.
        self.assertEqual(cmd[cmd.index("--entrypoint") + 1], "python")
        # The Docker socket must never be exposed to the sandbox container.
        self.assertNotIn("docker.sock", " ".join(cmd))
        self.assertNotIn("-v", cmd)
        self.assertNotIn("--volume", cmd)
        # The image runs the bootstrap, not a file path that depends on the image layout.
        self.assertEqual(cmd[-3:], ["heym-backend", "-c", executor._BOOTSTRAP])
        self.assertNotIn("/app/", " ".join(cmd[-2:]))

    def test_bootstrap_runs_the_shipped_runner_from_stdin(self) -> None:
        payload = json.dumps(
            {
                "code": "def add(a, b):\n    return a + b\n",
                "function_name": "add",
                "arguments": {"a": 2, "b": 5},
            }
        )
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", executor._BOOTSTRAP],
                input=executor._sandbox_payload(payload),
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(executor._parse_runner_output(proc.stdout), 7)

    def test_bootstrap_keeps_the_runner_restrictions(self) -> None:
        payload = json.dumps(
            {
                "code": "def f():\n    return open('/etc/hostname').read()\n",
                "function_name": "f",
                "arguments": {},
            }
        )
        proc = subprocess.run(
            [sys.executable, "-I", "-c", executor._BOOTSTRAP],
            input=executor._sandbox_payload(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        with self.assertRaises(ValueError):
            executor._parse_runner_output(proc.stdout)


if __name__ == "__main__":
    unittest.main()
