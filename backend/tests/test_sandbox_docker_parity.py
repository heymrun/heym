"""Docker argv parity for every sandbox call site.

``fixtures/sandbox_docker_argv.json`` was recorded from the call sites as they were
before the SandboxManager refactor. Re-record only on purpose:
``HEYM_RECORD_SANDBOX_ARGV=1 uv run pytest tests/test_sandbox_docker_parity.py``.

Docker ignores flag order, so flags compare as a sorted list of (flag, value) pairs.
Values, the order of ``--env`` items, the entrypoint, the image and its arguments
compare exactly.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import unittest
import uuid
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

GOLDEN = Path(__file__).parent / "fixtures" / "sandbox_docker_argv.json"
RECORD = os.environ.get("HEYM_RECORD_SANDBOX_ARGV") == "1"
REPO = Path(__file__).resolve().parents[2]
TMP = tempfile.gettempdir()
TMP_REAL = os.path.realpath(TMP)
ROOT = Path(TMP) / "heym-sandbox-parity"
RUN_ID = "0123456789abcdef0123456789abcdef"
_ENVELOPE = '{"success": true, "result": 1, "logs": ""}'
_FLAGS_WITHOUT_VALUE = {"--rm", "-i", "--read-only"}
_HEX32 = re.compile(r"[0-9a-f]{32}")
_MCP_NAME = re.compile(r"heym-mcp-stdio-[0-9a-f]{12}")
_IMAGE = "heym-backend:parity"
_BASE_ENV = {
    "PATH": os.environ.get("PATH", ""),
    "LANG": "C.UTF-8",
    "HTTP_PROXY": "http://proxy.internal:3128",
    "NO_PROXY": "localhost",
    "NODE_EXTRA_CA_CERTS": "/etc/ssl/extra.pem",
    "SECRET_KEY": "parity-secret-must-not-leak",
    "HEYM_PYTHON_TOOL_IMAGE": _IMAGE,
    "HEYM_SKILL_IMAGE": _IMAGE,
    "HEYM_PLAYWRIGHT_SANDBOX_IMAGE": _IMAGE,
    "HEYM_PLAYWRIGHT_SANDBOX_PYTHON": "/app/.venv/bin/python",
    "HEYM_MCP_STDIO_IMAGE": _IMAGE,
    "HEYM_CODEX_DOCKER_IMAGE": _IMAGE,
    "HEYM_OPENCODE_DOCKER_IMAGE": _IMAGE,
    "HEYM_SKILL_PYTHON": "/app/.venv/bin/python",
    # A local .env may set mcp_stdio_sandbox=subprocess; the parity cases need the sandbox.
    "HEYM_MCP_STDIO_SANDBOX": "docker",
}


def _scrub(token: str) -> str:
    token = token.replace(TMP_REAL, "<tmp>").replace(TMP, "<tmp>")
    token = _MCP_NAME.sub("heym-mcp-stdio-<id>", token)
    return _HEX32.sub("<hex>", token)


def normalize(argv: list[str]) -> dict:
    """Reduce a ``docker run`` argv to what Docker actually acts on."""
    argv = [_scrub(token) for token in argv]
    if argv[:2] != ["docker", "run"]:
        raise AssertionError(f"not a docker run argv: {argv[:3]}")
    flags: list[list[str]] = []
    env: list[str] = []
    entrypoint = None
    index = 2
    while index < len(argv) and argv[index].startswith("-"):
        flag = argv[index]
        if flag in _FLAGS_WITHOUT_VALUE:
            flags.append([flag])
            index += 1
            continue
        value = argv[index + 1]
        if flag == "--env":
            env.append(value)
        elif flag == "--entrypoint":
            entrypoint = value
        else:
            flags.append([flag, value])
        index += 2
    return {
        "flags": sorted(flags),
        "env": env,
        "entrypoint": entrypoint,
        "image": argv[index],
        "args": argv[index + 1 :],
    }


class FakeDocker:
    """Stands in for the docker CLI and records every ``docker run`` argv."""

    def __init__(self) -> None:
        self.runs: list[list[str]] = []

    def run(self, cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN201
        cmd = list(cmd)
        if cmd[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(cmd, 0, "27.0.0\n", "")
        if cmd[:2] == ["docker", "run"]:
            self.runs.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "")

    def popen(self, cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN201
        cmd = list(cmd)
        if cmd[:2] == ["docker", "run"]:
            self.runs.append(cmd)
        proc = MagicMock()
        proc.communicate.return_value = (_ENVELOPE, "")
        proc.returncode = 0
        proc.wait.return_value = 0
        return proc

    def capture(self, call: Callable[[], object]) -> list[list[str]]:
        start = len(self.runs)
        call()
        return self.runs[start:]


def _reset_caches() -> None:
    for name in (
        "app.services.python_tool_executor",
        "app.services.code_python_executor",
        "app.services.skill_python_executor",
        "app.services.playwright_sandbox",
        "app.services.mcp_stdio_sandbox",
    ):
        module = importlib.import_module(name)
        if hasattr(module, "_docker_available_cache"):
            module._docker_available_cache = None
    if importlib.util.find_spec("app.services.sandbox") is not None:
        from app.services.sandbox import reset_sandbox_manager

        reset_sandbox_manager()


def _code() -> str:
    return "def main(params):\n    return 1\n"


def _site_cases(docker: FakeDocker) -> dict[str, list[str]]:
    from app.services import (
        code_formatter,
        code_python_executor,
        mcp_stdio_sandbox,
        playwright_sandbox,
        python_tool_executor,
        skill_python_executor,
    )
    from app.services.file_sandbox import code_node
    from app.services.file_sandbox import executor as file_executor
    from app.services.file_sandbox.scope import RunFileScope
    from app.services.file_sandbox.workspace import FileWorkspace

    out: dict[str, list[str]] = {}
    (out["pytool"],) = docker.capture(
        lambda: python_tool_executor.execute_tool("def f():\n return 1\n", "f", {}, 5)
    )
    with patch.dict(
        os.environ, {"HEYM_PYTHON_TOOL_NETWORK": "bridge", "HEYM_PYTHON_TOOL_USER": "1000:1000"}
    ):
        (out["pytool_custom"],) = docker.capture(
            lambda: python_tool_executor.execute_tool("def f():\n return 1\n", "f", {}, 5)
        )
    (out["formatter"],) = docker.capture(lambda: code_formatter.format_python("x=1\n"))
    (out["code_offline"],) = docker.capture(
        lambda: code_python_executor.execute_code(_code(), "", {"a": 1}, False)
    )
    (out["code_online"],) = docker.capture(
        lambda: code_python_executor.execute_code(_code(), "", {}, True)
    )
    out["code_install_native"], out["code_run_native"] = docker.capture(
        lambda: code_python_executor.execute_code(_code(), "requests==2.32.3", {}, False)
    )
    volume_env = {
        "HEYM_CODEX_WORKSPACE_DIR": str(ROOT / "codex-workspaces"),
        "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces",
    }
    with (
        patch.dict(os.environ, volume_env),
        patch.object(code_python_executor, "_is_containerized", return_value=True),
    ):
        out["code_install_volume"], out["code_run_volume"] = docker.capture(
            lambda: code_python_executor.execute_code(_code(), "requests==2.32.3", {}, False)
        )

    workspace = FileWorkspace(ROOT / "files", owner_id=uuid.UUID(int=1))
    workspace.ensure()
    (out["files"],) = docker.capture(
        lambda: file_executor.run_in_sandbox(
            workspace, file_executor.build_payload("python", code="print(1)")
        )
    )
    with (
        patch.object(code_node, "resolve_files", return_value=[]),
        patch("app.db.session.SessionLocal"),
        patch.object(code_node, "store_outputs", return_value=([], [])),
    ):
        (out["code_files"],) = docker.capture(
            lambda: code_node.execute_code_with_files(
                code=_code(),
                requirements="",
                params={},
                allow_network=False,
                file_refs=[],
                actor_id=uuid.UUID(int=1),
                scope=RunFileScope(),
                workflow_id=None,
                source_label="Code",
            )
        )

    (out["playwright"],) = docker.capture(
        lambda: playwright_sandbox.run_script("print(1)", 10, image=_IMAGE)
    )

    skill_root = ROOT / "skills"
    (skill_root / "_skill-workspaces").mkdir(parents=True, exist_ok=True)
    skill_env = {
        "HEYM_PYTHON_TOOL_SANDBOX": "docker",
        "HEYM_SKILL_WORKSPACE_MOUNT": str(skill_root),
        "HEYM_SKILL_WORKSPACE_DIR": str(skill_root / "_skill-workspaces"),
    }
    skill_files = [{"path": "main.py", "content": "print(1)"}]
    with patch.dict(
        os.environ, {**skill_env, "HEYM_SKILL_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces"}
    ):
        (out["skill_volume"],) = docker.capture(
            lambda: skill_python_executor.execute_skill_python(skill_files, {"input": "x"}, 10)
        )
    with patch.dict(os.environ, {**skill_env, "HEYM_SKILL_HOST_WORKSPACE_DIR": "/srv/heym"}):
        (out["skill_bind"],) = docker.capture(
            lambda: skill_python_executor.execute_skill_python(skill_files, {"input": "x"}, 10)
        )

    out["mcp_backend_image"] = mcp_stdio_sandbox.build_sandboxed_command(
        "npx", ["-y", "@modelcontextprotocol/server-everything"], {"API_KEY": "user-value"}
    ).argv
    out["mcp_docker_form"] = mcp_stdio_sandbox.build_sandboxed_command(
        "docker",
        [
            "run",
            "-i",
            "--rm",
            "-e",
            "TOKEN=abc",
            "-w",
            "/srv",
            "--entrypoint",
            "node",
            "ghcr.io/acme/mcp:1",
            "server.js",
        ],
        {"EXTRA": "1"},
    ).argv
    with patch.dict(
        os.environ,
        {"HEYM_MCP_STDIO_FILES_VOLUME": "mcp-files", "HEYM_MCP_STDIO_FILES_SUBPATH": "team-a"},
    ):
        out["mcp_files_volume"] = mcp_stdio_sandbox.build_sandboxed_command("npx", [], None).argv
    with patch.dict(
        os.environ,
        {"HEYM_MCP_STDIO_FILES_HOST_DIR": "/srv/mcp", "HEYM_MCP_STDIO_FILES_WRITABLE": "true"},
    ):
        out["mcp_files_host_dir"] = mcp_stdio_sandbox.build_sandboxed_command("npx", [], None).argv
    return out


def agent_dirs(agent: str) -> tuple[Path, Path, Path]:
    """``(root, run workspace, run home)`` for a parity run of one coding agent."""
    root = ROOT / f"{agent}-workspaces"
    workspace = root / RUN_ID
    home = Path(f"{workspace}{'.codex-home' if agent == 'codex' else '.oc-home'}")
    workspace.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    return root, workspace, home


def agent_env(agent: str) -> dict[str, str]:
    root, _workspace, home = agent_dirs(agent)
    if agent == "codex":
        return {
            "HEYM_CODEX_WORKSPACE_DIR": str(root),
            "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces",
            "CODEX_HOME": str(home),
            "CODEX_ACCESS_TOKEN": "tok",
        }
    return {
        "HEYM_OPENCODE_WORKSPACE_DIR": str(root),
        "HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME": "heym-opencode-workspaces",
        "HOME": str(home),
        "XDG_CONFIG_HOME": f"{home}/.config",
        "XDG_DATA_HOME": f"{home}/.local/share",
        "HEYM_OPENCODE_RUN_ID": "feedfacefeedfacefeedfacefeedface",
    }


AGENT_ARGS = {"codex": ["exec", "--json", "hello"], "opencode": ["run", "--format", "json", "hi"]}


def keep_signal_handlers(test: unittest.TestCase) -> None:
    """Wrappers install SIGTERM/SIGINT/SIGHUP handlers; restore pytest's afterwards."""
    for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        test.addCleanup(signal.signal, caught, signal.getsignal(caught))


def without_mounts(normalized: dict) -> dict:
    """The normalized argv minus ``--mount`` flags (Milestone 2 changes only those)."""
    return {**normalized, "flags": [f for f in normalized["flags"] if f[0] != "--mount"]}


class DockerArgvParityTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        ROOT.mkdir(parents=True)
        self.docker = FakeDocker()
        for target, fake in (
            ("subprocess.run", self.docker.run),
            ("subprocess.Popen", self.docker.popen),
        ):
            patcher = patch(target, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, _BASE_ENV, clear=True)
        env.start()
        self.addCleanup(env.stop)
        for target in (
            "app.services.code_python_executor._is_containerized",
            "app.services.file_sandbox.workspace._is_containerized",
        ):
            patcher = patch(target, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)
        _reset_caches()
        self.addCleanup(_reset_caches)
        self.addCleanup(shutil.rmtree, ROOT, True)
        keep_signal_handlers(self)

    def _actual(self) -> dict[str, dict]:
        cases = _site_cases(self.docker)
        for agent in ("codex", "opencode"):
            cases[agent] = self.agent_argv(agent)
        return {name: normalize(argv) for name, argv in cases.items()}

    def agent_argv(self, agent: str) -> list[str]:
        from app.services.sandbox.coding_agents import PROFILES, agent_spec, run_scope
        from app.services.sandbox.docker_backend import render_docker_argv

        profile = PROFILES[agent]
        _root, workspace, _home = agent_dirs(agent)
        env = {**os.environ, **agent_env(agent)}
        with patch.dict(os.environ, agent_env(agent)):
            scope = run_scope(profile, workspace, env)
            run_id = env.get(profile.run_id_env or "", "") or "<hex>"
            spec = agent_spec(
                profile,
                scope,
                AGENT_ARGS[agent],
                env,
                image=_IMAGE,
                name=f"heym-{agent}-{run_id}",
                kubernetes=False,
                cwd=workspace,
            )
            return render_docker_argv(spec)

    def test_every_site_renders_the_recorded_argv(self) -> None:
        actual = self._actual()
        if RECORD:
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.skipTest(f"recorded {len(actual)} cases into {GOLDEN}")
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(sorted(actual), sorted(golden))
        for name in sorted(golden):
            with self.subTest(case=name):
                if name in ("codex", "opencode"):
                    # Milestone 2 replaced the whole-volume mount with two scoped ones.
                    self.assertEqual(without_mounts(actual[name]), without_mounts(golden[name]))
                else:
                    self.assertEqual(actual[name], golden[name])

    def test_no_backend_secret_reaches_any_argv(self) -> None:
        for name, normalized in self._actual().items():
            with self.subTest(case=name):
                self.assertNotIn("parity-secret-must-not-leak", json.dumps(normalized))


if __name__ == "__main__":
    unittest.main()
