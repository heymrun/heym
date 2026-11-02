# Sandbox Manager and Kubernetes Sandbox Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every Heym sandbox through one `SandboxManager` that runs Docker sibling containers as today or Kubernetes pods through the API, and scope Codex/OpenCode runs to their own workspace on both backends.

**Architecture:** A new package `backend/app/services/sandbox/` holds a backend-neutral `SandboxSpec`, a `DockerBackend` that renders exactly today's `docker run` argv, and a `KubernetesBackend` (httpx + websockets, `v5.channel.k8s.io` attach) that renders the same spec as a restricted Pod. Call sites keep their module-level seams (`docker_available`, `_resolve_image`, `_build_*_command`, ...), so existing tests keep guarding parity, and build a `SandboxSpec` underneath.

**Tech Stack:** Python 3.11, FastAPI backend, `httpx` (sync client), `websockets.sync.client`, `unittest` + pytest, Docker CLI, Kubernetes 1.30+ (OrbStack locally), kustomize via `kubectl apply -k`.

**Spec:** `docs/superpowers/specs/2026-11-02-kubernetes-sandbox-backend-design.md`

---

## Ground rules

- **One branch, one PR:** `impl/native-k8s-api-and-pod-management` off `main`. Four milestones, committed in order. `./check.sh` is green at the end of every milestone.
- **No new security hole.** Every fail-closed path stays fail-closed; nothing falls back to `subprocess` or to the other backend. Security invariants have advisory tests (`test_advisory_*`).
- **Minimal env.** Three new variables, all optional with zero-config defaults: `HEYM_SANDBOX_BACKEND` (`auto`), `HEYM_SANDBOX_K8S_NAMESPACE` (backend's namespace), `HEYM_SANDBOX_K8S_POD_OVERRIDES` (none). One internal variable the runners set for their own child process: `HEYM_SANDBOX_DEADLINE_SECONDS`. No existing variable changes meaning or name.
- **Import rule.** Nothing under `backend/app/services/sandbox/` imports `app.config`.
- **Test command.** From `backend/`: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest <path> -q`. Below this is written as `PYTEST <path>`.
- **Lint per task.** `cd backend && uv run ruff check app tests && uv run ruff format --check app tests`.
- **No comments beyond one line for a non-obvious why.** Docstrings on public functions.

## File map

Create:

| Path | Responsibility |
|---|---|
| `backend/app/services/sandbox/__init__.py` | public exports |
| `backend/app/services/sandbox/spec.py` | `SandboxSpec`, `Tmpfs`, `WorkspaceMount`, `DockerVolumeSource`, `OperatorMount`, `SandboxResult`, `ProcessCommand`, exit-code constants |
| `backend/app/services/sandbox/errors.py` | `SandboxTimeout`, `SandboxConfigError` |
| `backend/app/services/sandbox/env.py` | env allowlists shared by sites |
| `backend/app/services/sandbox/docker_backend.py` | argv rendering, mount resolution, run, cleanup, self image |
| `backend/app/services/sandbox/manager.py` | backend selection, `get_sandbox_manager()` |
| `backend/app/services/sandbox/coding_agents.py` | `RunScope`, Codex/OpenCode `SandboxSpec` (stdlib only) |
| `backend/app/services/sandbox/wrapper_cli.py` | entry point behind the two wrapper shims |
| `backend/app/services/sandbox/kubernetes/__init__.py` | empty |
| `backend/app/services/sandbox/kubernetes/config.py` | in-cluster config, minimal kubeconfig |
| `backend/app/services/sandbox/kubernetes/client.py` | REST calls |
| `backend/app/services/sandbox/kubernetes/attach.py` | attach websocket framing |
| `backend/app/services/sandbox/kubernetes/lifecycle.py` | wait for start / termination |
| `backend/app/services/sandbox/kubernetes/pod.py` | `SandboxSpec` -> Pod manifest (pure) |
| `backend/app/services/sandbox/kubernetes/network.py` | offline canary |
| `backend/app/services/sandbox/kubernetes/backend.py` | `KubernetesBackend` |
| `backend/app/services/sandbox/kubernetes/process.py` | stdio bridge (`python -m ...process`) |
| `backend/app/services/sandbox/kubernetes/workspace.py` | backend path -> PVC + subPath |
| `backend/app/services/sandbox/kubernetes/janitor.py` | leaked pod sweep |
| `backend/tests/fixtures/sandbox_docker_argv.json` | golden argv, recorded before the refactor |
| `backend/tests/test_sandbox_docker_parity.py` | parity guard |
| `backend/tests/test_sandbox_spec.py`, `test_sandbox_docker_backend.py`, `test_sandbox_manager.py` | unit tests |
| `backend/tests/test_sandbox_coding_agents.py`, `test_advisory_coding_agent_run_scope.py` | Milestone 2 tests |
| `backend/tests/test_sandbox_k8s_*.py`, `test_advisory_k8s_sandbox.py`, `test_sandbox_import_rule.py` | Milestone 3 and 4 tests |
| `backend/tests/live/test_k8s_sandbox_live.py` | opt-in OrbStack tests |
| `deploy/kubernetes/**` | example manifests |
| `scripts/k8s-sandbox-smoke.sh`, `scripts/k8s_sandbox_smoke.py` | in-cluster smoke |

Modify: `python_tool_executor.py`, `code_python_executor.py`, `code_formatter.py`, `file_sandbox/executor.py`, `file_sandbox/code_node.py`, `playwright_sandbox.py`, `skill_python_executor.py`, `mcp_stdio_sandbox.py`, `cluster/registry.py`, `main.py`, `codex_runner_service.py`, `opencode_runner_service.py`, `docker/heym-codex-docker`, `docker/heym-opencode-docker`, `backend/Dockerfile`, `docker/release.Dockerfile`, tests listed per task, docs listed in Task 37.

---

## Task 0: Branch

- [ ] **Step 1: Create the branch from an up-to-date main**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git checkout main && git pull --ff-only
git checkout -b impl/native-k8s-api-and-pod-management
```

- [ ] **Step 2: Commit the spec and this plan**

```bash
git add docs/superpowers/specs/2026-11-02-kubernetes-sandbox-backend-design.md docs/superpowers/plans/2026-11-02-kubernetes-sandbox-backend.md
git commit -m "docs: kubernetes sandbox backend spec and plan"
```

---

# Milestone 1: SandboxManager and Docker parity (no behavior change)

## Task 1: Record the Docker argv snapshot before any site changes

The snapshot is taken at the public entry point of every site with `subprocess.run` and `subprocess.Popen` replaced by a fake Docker CLI, so it does not depend on builder signatures that later tasks change.

**Files:**
- Create: `backend/tests/test_sandbox_docker_parity.py`
- Create (recorded): `backend/tests/fixtures/sandbox_docker_argv.json`

- [ ] **Step 1: Write the parity test**

```python
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
from importlib.machinery import SourceFileLoader
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
        ["run", "-i", "--rm", "-e", "TOKEN=abc", "-w", "/srv", "--entrypoint", "node",
         "ghcr.io/acme/mcp:1", "server.js"],
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
        out["mcp_files_host_dir"] = mcp_stdio_sandbox.build_sandboxed_command(
            "npx", [], None
        ).argv
    return out


def _load_script(name: str):  # noqa: ANN202
    path = REPO / "docker" / name
    loader = SourceFileLoader(name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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


def _old_wrapper_case(docker: FakeDocker, agent: str) -> list[str]:
    _root, workspace, _home = agent_dirs(agent)
    module = _load_script(f"heym-{agent}-docker")
    with (
        patch.dict(os.environ, agent_env(agent)),
        patch.object(module.Path, "cwd", return_value=workspace),
        patch.object(module.sys, "argv", [f"heym-{agent}-docker", *AGENT_ARGS[agent]]),
    ):
        (argv,) = docker.capture(module.main)
    return argv


def without_mounts(normalized: dict) -> dict:
    """The normalized argv minus ``--mount`` flags (Milestone 2 changes only those)."""
    return {**normalized, "flags": [f for f in normalized["flags"] if f[0] != "--mount"]}


class DockerArgvParityTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        shutil.rmtree(ROOT, ignore_errors=True)
        ROOT.mkdir(parents=True)
        self.docker = FakeDocker()
        for target, fake in (("subprocess.run", self.docker.run), ("subprocess.Popen", self.docker.popen)):
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
        """Milestone 2 replaces this with the new builder."""
        return _old_wrapper_case(self.docker, agent)

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
                self.assertEqual(actual[name], golden[name])

    def test_no_backend_secret_reaches_any_argv(self) -> None:
        for name, normalized in self._actual().items():
            with self.subTest(case=name):
                self.assertNotIn("parity-secret-must-not-leak", json.dumps(normalized))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Record the golden file from today's code**

Run from `backend/`:
`HEYM_RECORD_SANDBOX_ARGV=1 SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_sandbox_docker_parity.py -q`
Expected: `1 passed, 1 skipped` (the skip message says `recorded 20 cases`).

- [ ] **Step 3: Read the golden file before trusting it**

Run: `python3 -c "import json;d=json.load(open('tests/fixtures/sandbox_docker_argv.json'));print(len(d));print(json.dumps(d['code_run_volume'],indent=1))"`
Expected: 20 cases; `code_run_volume` has a `--mount` flag with `volume-subpath=_code-runs/<hex>,readonly`, `--network none`, env starting `HOME=/tmp`, entrypoint `python`. If a case looks wrong, the harness is wrong: fix it, never the golden by hand.

- [ ] **Step 4: Run it against the recording**

Run: `PYTEST tests/test_sandbox_docker_parity.py`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_sandbox_docker_parity.py backend/tests/fixtures/sandbox_docker_argv.json
git commit -m "test(sandbox): record docker argv of every sandbox site"
```

## Task 2: `spec.py`, `errors.py`, `env.py`

**Files:**
- Create: `backend/app/services/sandbox/spec.py`, `errors.py`, `env.py`, `kubernetes/__init__.py` (empty)
- Test: `backend/tests/test_sandbox_spec.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import unittest
from unittest.mock import patch

from app.services.sandbox.env import CODE_FORWARD_PREFIXES, SKILL_FORWARD_PREFIXES, forwarded_env
from app.services.sandbox.spec import SandboxResult, SandboxSpec, Tmpfs


class TmpfsTest(unittest.TestCase):
    def test_parse_round_trips_every_docker_value_in_use(self) -> None:
        for value in (
            "/tmp:rw,nosuid,size=512m",
            "/tmp:rw,noexec,nosuid,size=64m",
            "/tmp:rw,exec,nosuid,size=1g",
        ):
            self.assertEqual(Tmpfs.parse(value).docker_value(), value)

    def test_parse_requires_a_size(self) -> None:
        with self.assertRaises(ValueError):
            Tmpfs.parse("/tmp:rw,nosuid")


class SandboxResultTest(unittest.TestCase):
    def test_start_failure_codes(self) -> None:
        for code in (125, 126, 127):
            self.assertTrue(SandboxResult(code, "", "").start_failed)
        self.assertFalse(SandboxResult(1, "", "").start_failed)

    def test_oom(self) -> None:
        self.assertTrue(SandboxResult(137, "", "").oom_killed)
        self.assertFalse(SandboxResult(0, "", "").oom_killed)


class SpecTest(unittest.TestCase):
    def test_offline_means_network_none(self) -> None:
        spec = SandboxSpec(site="t", name="n", image="i", entrypoint="python")
        self.assertTrue(spec.offline)
        self.assertFalse(SandboxSpec(site="t", name="n", image="i", entrypoint=None, network="bridge").offline)


class ForwardedEnvTest(unittest.TestCase):
    def test_allowlist_keeps_proxies_and_drops_secrets_and_home(self) -> None:
        env = {
            "LANG": "C",
            "HTTP_PROXY": "http://p:3128",
            "SECRET_KEY": "s",
            "DATABASE_URL": "postgresql://x",
            "HOME": "/root",
            "NODE_EXTRA_CA_CERTS": "/x.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(forwarded_env(CODE_FORWARD_PREFIXES), ("LANG=C", "HTTP_PROXY=http://p:3128"))
            self.assertIn("NODE_EXTRA_CA_CERTS=/x.pem", forwarded_env(SKILL_FORWARD_PREFIXES))
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_spec.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.sandbox'`.

- [ ] **Step 3: Write `spec.py`**

```python
"""Backend-neutral description of one sandbox container run.

Every sandbox call site builds a ``SandboxSpec`` and hands it to the
``SandboxManager``. The Docker backend renders it as ``docker run`` argv and the
Kubernetes backend as a Pod. Standard library only: the wrapper shims import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Exit codes that mean the sandbox never started. Kubernetes reports such a pod as
# START_FAILURE_RETURNCODE, so callers keep one check for both backends.
START_FAILURE_CODES: frozenset[int] = frozenset({125, 126, 127})
START_FAILURE_RETURNCODE = 125
OOM_RETURNCODE = 137


@dataclass(frozen=True)
class Tmpfs:
    """Memory-backed scratch space: ``--tmpfs`` on Docker, a Memory emptyDir on Kubernetes."""

    path: str
    options: str
    size: str

    @classmethod
    def parse(cls, value: str) -> Tmpfs:
        """Parse a Docker ``--tmpfs`` value such as ``/tmp:rw,nosuid,size=64m``."""
        path, _, raw_options = value.partition(":")
        options: list[str] = []
        size = ""
        for option in raw_options.split(","):
            if option.startswith("size="):
                size = option.removeprefix("size=")
            elif option:
                options.append(option)
        if not size:
            raise ValueError(f"tmpfs value {value!r} has no size")
        return cls(path=path, options=",".join(options), size=size)

    def docker_value(self) -> str:
        """The ``--tmpfs`` value."""
        return f"{self.path}:{self.options},size={self.size}"


@dataclass(frozen=True)
class DockerVolumeSource:
    """How the Docker backend finds the shared volume behind a backend path.

    Order: a native backend binds the path itself; else the first set variable in
    ``volume_env`` names a volume, mounted with ``volume-subpath``; else
    ``host_root_env`` names the host directory behind ``mount_point``; else the
    backend container's own mount at ``mount_point`` is inspected.
    """

    mount_point: Path
    volume_env: tuple[str, ...]
    missing_message: str
    host_root_env: str | None = None
    native_bind: bool = False
    label: str = "Sandbox dir"


@dataclass(frozen=True)
class WorkspaceMount:
    """Expose one backend directory inside the sandbox, and nothing above it."""

    host_path: Path
    target: str
    readonly: bool
    docker: DockerVolumeSource


@dataclass(frozen=True)
class OperatorMount:
    """The MCP stdio files mount. Only an operator configures it, never a caller."""

    target: str
    writable: bool = False
    volume: str | None = None
    subpath: str | None = None
    host_dir: str | None = None


@dataclass(frozen=True)
class SandboxSpec:
    """One sandbox run, independent of the backend that executes it."""

    site: str
    name: str
    image: str
    entrypoint: str | None
    args: tuple[str, ...] = ()
    network: str = "none"
    user: str | None = "65534:65534"
    read_only_root: bool = True
    tmpfs: tuple[Tmpfs, ...] = ()
    shm_size: str | None = None
    memory: str | None = None
    memory_swap: str | None = None
    cpus: str | None = None
    pids: str | None = None
    cap_drop_all: bool = True
    no_new_privileges: bool = True
    env: tuple[str, ...] = ()
    workdir: str | None = None
    workspace_mounts: tuple[WorkspaceMount, ...] = ()
    operator_mount: OperatorMount | None = None
    docker_extra_args: tuple[str, ...] = ()
    deadline_seconds: float | None = None
    start_gate: bool = False

    @property
    def offline(self) -> bool:
        """True when the sandbox must have no network at all."""
        return self.network == "none"


@dataclass(frozen=True)
class SandboxResult:
    """Exit code and output of one finished sandbox."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def start_failed(self) -> bool:
        """The sandbox never started (image, mount, entrypoint or scheduling)."""
        return self.returncode in START_FAILURE_CODES

    @property
    def oom_killed(self) -> bool:
        """The sandbox was killed for exceeding its memory limit."""
        return self.returncode == OOM_RETURNCODE


@dataclass(frozen=True)
class ProcessCommand:
    """A command for callers that spawn the sandbox as their own child process."""

    argv: list[str]
    env: dict[str, str]
    name: str
```

- [ ] **Step 4: Write `errors.py`**

```python
"""Errors shared by every sandbox backend."""


class SandboxTimeout(TimeoutError):
    """The sandbox ran past its limit. Its container or pod is already removed."""


class SandboxConfigError(RuntimeError):
    """The backend cannot run this spec safely. Callers fail closed with the message."""
```

- [ ] **Step 5: Write `env.py`**

```python
"""Environment that may cross into a sandbox.

Allowlists fail safe: a new backend secret stays out until someone adds it here.
"""

from __future__ import annotations

import os

CODE_FORWARD_PREFIXES: tuple[str, ...] = (
    "LANG",
    "LANGUAGE",
    "TZ",
    "LC_",
    "SSL_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
SKILL_FORWARD_PREFIXES: tuple[str, ...] = (*CODE_FORWARD_PREFIXES, "NODE_EXTRA_CA_CERTS")


def forwarded_env(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    """``KEY=value`` items for allowlisted variables. HOME never crosses; sandboxes set their own."""
    return tuple(
        f"{key}={value}"
        for key, value in os.environ.items()
        if key != "HOME" and key.startswith(prefixes)
    )
```

- [ ] **Step 6: Create the empty package files**

`backend/app/services/sandbox/kubernetes/__init__.py` is empty. `backend/app/services/sandbox/__init__.py` stays empty until Task 4.

- [ ] **Step 7: Run the test**

Run: `PYTEST tests/test_sandbox_spec.py`
Expected: `6 passed`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/sandbox backend/tests/test_sandbox_spec.py
git commit -m "feat(sandbox): backend-neutral sandbox spec and env allowlists"
```

## Task 3: `docker_backend.py`

**Files:**
- Create: `backend/app/services/sandbox/docker_backend.py`
- Test: `backend/tests/test_sandbox_docker_backend.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.sandbox import docker_backend
from app.services.sandbox.docker_backend import (
    DockerBackend,
    docker_mount_args,
    operator_mount_args,
    render_docker_argv,
)
from app.services.sandbox.errors import SandboxTimeout
from app.services.sandbox.spec import (
    DockerVolumeSource,
    OperatorMount,
    SandboxSpec,
    Tmpfs,
    WorkspaceMount,
)

_SOURCE = DockerVolumeSource(
    mount_point=Path("/app/data/codex-workspaces"),
    volume_env=("HEYM_TEST_VOLUME",),
    host_root_env="HEYM_TEST_HOST_ROOT",
    missing_message="no shared volume",
)


def _mount(host: str, readonly: bool = False, source: DockerVolumeSource = _SOURCE) -> WorkspaceMount:
    return WorkspaceMount(host_path=Path(host), target=host, readonly=readonly, docker=source)


class RenderTest(unittest.TestCase):
    def test_full_spec_renders_in_canonical_order(self) -> None:
        spec = SandboxSpec(
            site="t",
            name="heym-t-1",
            image="img:1",
            entrypoint="python",
            args=("-c", "pass"),
            tmpfs=(Tmpfs("/tmp", "rw,nosuid", "64m"),),
            workdir="/tmp",
            pids="128",
            memory="256m",
            memory_swap="256m",
            cpus="1",
            env=("A=1", "B=2"),
        )
        self.assertEqual(
            render_docker_argv(spec),
            [
                "docker", "run", "--rm", "-i", "--name", "heym-t-1", "--network", "none",
                "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=64m", "--workdir", "/tmp",
                "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt",
                "no-new-privileges", "--pids-limit", "128", "--memory", "256m",
                "--memory-swap", "256m", "--cpus", "1", "--env", "A=1", "--env", "B=2",
                "--entrypoint", "python", "img:1", "-c", "pass",
            ],
        )

    def test_image_default_entrypoint_and_no_user(self) -> None:
        spec = SandboxSpec(site="t", name="n", image="img", entrypoint=None, user=None, args=("x",))
        argv = render_docker_argv(spec)
        self.assertNotIn("--entrypoint", argv)
        self.assertNotIn("--user", argv)
        self.assertEqual(argv[-2:], ["img", "x"])


class MountTest(unittest.TestCase):
    def test_native_backend_binds_the_path_itself(self) -> None:
        source = DockerVolumeSource(Path("/unused"), (), "x", native_bind=True)
        self.assertEqual(
            docker_mount_args(_mount("/tmp/r", readonly=True, source=source)),
            ["--mount", "type=bind,src=/tmp/r,dst=/tmp/r,readonly"],
        )

    def test_named_volume_mounts_only_the_subpath(self) -> None:
        with patch.dict(os.environ, {"HEYM_TEST_VOLUME": "vol"}, clear=True):
            args = docker_mount_args(_mount("/app/data/codex-workspaces/_code-runs/abc", True))
        self.assertEqual(
            args,
            ["--mount", "type=volume,src=vol,dst=/app/data/codex-workspaces/_code-runs/abc,"
             "volume-subpath=_code-runs/abc,readonly"],
        )

    def test_host_root_env_binds_the_subdirectory(self) -> None:
        with patch.dict(os.environ, {"HEYM_TEST_HOST_ROOT": "/srv/ws"}, clear=True):
            args = docker_mount_args(_mount("/app/data/codex-workspaces/x"))
        self.assertEqual(
            args, ["--mount", "type=bind,src=/srv/ws/x,dst=/app/data/codex-workspaces/x"]
        )

    def test_inspected_volume_and_bind(self) -> None:
        volume = [{"Destination": "/app/data/codex-workspaces", "Type": "volume", "Name": "v"}]
        bind = [{"Destination": "/app/data/codex-workspaces", "Type": "bind", "Source": "/h"}]
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(docker_backend, "current_container_mounts", return_value=volume):
                self.assertIn("volume-subpath=x", docker_mount_args(_mount("/app/data/codex-workspaces/x"))[1])
            with patch.object(docker_backend, "current_container_mounts", return_value=bind):
                self.assertEqual(
                    docker_mount_args(_mount("/app/data/codex-workspaces/x"))[1],
                    "type=bind,src=/h/x,dst=/app/data/codex-workspaces/x",
                )

    def test_missing_volume_and_outside_path_fail_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            docker_backend, "current_container_mounts", return_value=[]
        ):
            with self.assertRaisesRegex(RuntimeError, "no shared volume"):
                docker_mount_args(_mount("/app/data/codex-workspaces/x"))
        with self.assertRaisesRegex(RuntimeError, "is not under the workspace volume mount"):
            docker_mount_args(_mount("/elsewhere/x"))

    def test_operator_mounts(self) -> None:
        self.assertEqual(
            operator_mount_args(OperatorMount(target="/mnt/f", volume="v", subpath="a")),
            ["--mount", "type=volume,src=v,dst=/mnt/f,volume-subpath=a,readonly"],
        )
        self.assertEqual(
            operator_mount_args(OperatorMount(target="/mnt/f", host_dir="/srv", writable=True)),
            ["--volume", "/srv:/mnt/f"],
        )


class BackendTest(unittest.TestCase):
    def _spec(self) -> SandboxSpec:
        return SandboxSpec(site="t", name="heym-t-1", image="img", entrypoint="python")

    def test_run_returns_the_result(self) -> None:
        proc = MagicMock()
        proc.communicate.return_value = ("out", "err")
        proc.returncode = 3
        with patch("subprocess.Popen", return_value=proc) as popen:
            result = DockerBackend().run(self._spec(), "payload", 5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, "out", "err"))
        self.assertEqual(popen.call_args.args[0][:2], ["docker", "run"])
        proc.communicate.assert_called_once_with(input="payload", timeout=5)

    def test_timeout_kills_removes_and_raises(self) -> None:
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        with (
            patch("subprocess.Popen", return_value=proc),
            patch.object(docker_backend, "_docker_rm") as rm,
        ):
            with self.assertRaises(SandboxTimeout):
                DockerBackend().run(self._spec(), None, 5)
        proc.kill.assert_called_once()
        rm.assert_called_once_with("heym-t-1")

    def test_availability_is_probed_once(self) -> None:
        ok = subprocess.CompletedProcess([], 0, "27.0\n", "")
        with patch("subprocess.run", return_value=ok) as run:
            backend = DockerBackend()
            self.assertTrue(backend.available())
            self.assertTrue(backend.available())
        run.assert_called_once()

    def test_missing_cli_is_unavailable(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(DockerBackend().available())

    def test_process_command_is_the_docker_argv(self) -> None:
        command = DockerBackend().process_command(self._spec())
        self.assertEqual(command.argv[:2], ["docker", "run"])
        self.assertEqual(command.env, {})
        self.assertEqual(command.name, "heym-t-1")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_docker_backend.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.sandbox.docker_backend'`.

- [ ] **Step 3: Write `docker_backend.py`**

```python
"""Docker backend: hardened sibling containers through the ``docker`` CLI."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

from app.services.sandbox.errors import SandboxTimeout
from app.services.sandbox.spec import (
    OperatorMount,
    ProcessCommand,
    SandboxResult,
    SandboxSpec,
    WorkspaceMount,
)

logger = logging.getLogger(__name__)


def render_docker_argv(spec: SandboxSpec) -> list[str]:
    """The ``docker run`` argv for ``spec``. No Docker socket is ever mounted."""
    argv = ["docker", "run", "--rm", "-i", "--name", spec.name, "--network", spec.network]
    if spec.read_only_root:
        argv.append("--read-only")
    for tmpfs in spec.tmpfs:
        argv.extend(["--tmpfs", tmpfs.docker_value()])
    if spec.shm_size:
        argv.extend(["--shm-size", spec.shm_size])
    if spec.workdir:
        argv.extend(["--workdir", spec.workdir])
    if spec.user:
        argv.extend(["--user", spec.user])
    if spec.cap_drop_all:
        argv.extend(["--cap-drop", "ALL"])
    if spec.no_new_privileges:
        argv.extend(["--security-opt", "no-new-privileges"])
    if spec.pids:
        argv.extend(["--pids-limit", spec.pids])
    if spec.memory:
        argv.extend(["--memory", spec.memory])
    if spec.memory_swap:
        argv.extend(["--memory-swap", spec.memory_swap])
    if spec.cpus:
        argv.extend(["--cpus", spec.cpus])
    for mount in spec.workspace_mounts:
        argv.extend(docker_mount_args(mount))
    if spec.operator_mount is not None:
        argv.extend(operator_mount_args(spec.operator_mount))
    argv.extend(spec.docker_extra_args)
    for item in spec.env:
        argv.extend(["--env", item])
    if spec.entrypoint is not None:
        argv.extend(["--entrypoint", spec.entrypoint])
    argv.append(spec.image)
    argv.extend(spec.args)
    return argv


def _first_set(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def docker_mount_args(mount: WorkspaceMount) -> list[str]:
    """``--mount`` args exposing only ``mount.host_path`` at ``mount.target``."""
    source = mount.docker
    suffix = ",readonly" if mount.readonly else ""
    if source.native_bind:
        return ["--mount", f"type=bind,src={mount.host_path},dst={mount.target}{suffix}"]
    try:
        rel = mount.host_path.relative_to(source.mount_point)
    except ValueError as exc:
        raise RuntimeError(
            f"{source.label} {mount.host_path} is not under the workspace volume mount "
            f"{source.mount_point}"
        ) from exc
    rel_str = rel.as_posix()
    volume = _first_set(source.volume_env)
    if volume:
        return [
            "--mount",
            f"type=volume,src={volume},dst={mount.target},volume-subpath={rel_str}{suffix}",
        ]
    host_root = os.environ.get(source.host_root_env, "").strip() if source.host_root_env else ""
    if not host_root:
        for entry in current_container_mounts():
            if str(entry.get("Destination") or "") != str(source.mount_point):
                continue
            if entry.get("Type") == "volume" and entry.get("Name"):
                return [
                    "--mount",
                    f"type=volume,src={entry['Name']},dst={mount.target},"
                    f"volume-subpath={rel_str}{suffix}",
                ]
            if entry.get("Type") == "bind" and entry.get("Source"):
                host_root = str(entry["Source"])
                break
    if host_root:
        return ["--mount", f"type=bind,src={Path(host_root) / rel},dst={mount.target}{suffix}"]
    raise RuntimeError(source.missing_message)


def operator_mount_args(mount: OperatorMount) -> list[str]:
    """Args for the operator-configured MCP files mount; read-only unless writable."""
    if mount.volume:
        value = f"type=volume,src={mount.volume},dst={mount.target}"
        if mount.subpath:
            value += f",volume-subpath={mount.subpath}"
        if not mount.writable:
            value += ",readonly"
        return ["--mount", value]
    if mount.host_dir:
        return ["--volume", f"{mount.host_dir}:{mount.target}{'' if mount.writable else ':ro'}"]
    return []


def current_container_mounts() -> list[dict[str, Any]]:
    """Best-effort inspection of the backend container's own Docker mounts."""
    try:
        hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not hostname:
        return []
    try:
        result = subprocess.run(
            ["docker", "inspect", hostname], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0:
        return []
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        mounts = parsed[0].get("Mounts")
        if isinstance(mounts, list):
            return [m for m in mounts if isinstance(m, dict)]
    return []


def _docker_rm(name: str) -> None:
    try:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass


def _probe_docker() -> bool:
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


class DockerBackend:
    """Sibling containers on the Docker daemon behind ``/var/run/docker.sock``."""

    name = "docker"

    def __init__(self) -> None:
        self._available: bool | None = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        """True when a working Docker daemon answers (probed once per process)."""
        with self._lock:
            if self._available is None:
                self._available = _probe_docker()
            return self._available

    def resolve_image(self) -> str | None:
        """The image this backend container runs, from ``docker inspect``."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Config.Image}}", socket.gethostname()],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return None
        image = result.stdout.strip()
        return image if result.returncode == 0 and image else None

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        """Run one container to completion; remove it and raise on timeout."""
        proc = subprocess.Popen(
            render_docker_argv(spec),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input=stdin, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            _docker_rm(spec.name)
            raise SandboxTimeout(
                f"sandbox {spec.name} ran past {timeout_seconds:.0f} seconds"
            ) from None
        return SandboxResult(proc.returncode, stdout or "", stderr or "")

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        """``docker run`` argv for callers that spawn and supervise the process."""
        return ProcessCommand(argv=render_docker_argv(spec), env={}, name=spec.name)

    def force_remove(self, name: str | None) -> None:
        """Remove a container that may have outlived its client."""
        if name:
            _docker_rm(name)

    def uses_shared_workspace(self) -> bool:
        """Inside a container, workspaces must live on the volume shared with siblings."""
        return Path("/.dockerenv").exists()
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_docker_backend.py`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/docker_backend.py backend/tests/test_sandbox_docker_backend.py
git commit -m "feat(sandbox): docker backend renders specs as hardened docker run"
```

## Task 4: `manager.py` and package exports

**Files:**
- Create: `backend/app/services/sandbox/manager.py`
- Modify: `backend/app/services/sandbox/__init__.py`
- Test: `backend/tests/test_sandbox_manager.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox import get_sandbox_manager, reset_sandbox_manager
from app.services.sandbox.manager import SandboxManager


class ManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)

    def test_singleton_until_reset(self) -> None:
        first = get_sandbox_manager()
        self.assertIs(first, get_sandbox_manager())
        reset_sandbox_manager()
        self.assertIsNot(first, get_sandbox_manager())

    def test_docker_is_the_default_backend(self) -> None:
        self.assertEqual(get_sandbox_manager().backend_name, "docker")

    def test_image_overrides_win_in_order_then_the_backend(self) -> None:
        backend = MagicMock()
        backend.resolve_image.return_value = "self:1"
        manager = SandboxManager(backend)
        with patch.dict(os.environ, {"B": "b:1", "A": " "}, clear=True):
            self.assertEqual(manager.resolve_image(("A", "B")), "b:1")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(manager.resolve_image(("A", "B")), "self:1")

    def test_calls_delegate_to_the_backend(self) -> None:
        backend = MagicMock()
        manager = SandboxManager(backend)
        manager.run("spec", "in", 3)  # type: ignore[arg-type]
        backend.run.assert_called_once_with("spec", "in", 3)
        manager.force_remove("n")
        backend.force_remove.assert_called_once_with("n")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_manager.py`
Expected: FAIL, `ImportError: cannot import name 'get_sandbox_manager'`.

- [ ] **Step 3: Write `manager.py`**

```python
"""The single entry point every sandbox call site goes through."""

from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

from app.services.sandbox.docker_backend import DockerBackend
from app.services.sandbox.spec import ProcessCommand, SandboxResult, SandboxSpec

logger = logging.getLogger(__name__)


class SandboxBackend(Protocol):
    """What a backend provides. Docker and Kubernetes implement it."""

    name: str

    def available(self) -> bool: ...

    def resolve_image(self) -> str | None: ...

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult: ...

    def process_command(self, spec: SandboxSpec) -> ProcessCommand: ...

    def force_remove(self, name: str | None) -> None: ...

    def uses_shared_workspace(self) -> bool: ...


class SandboxManager:
    """Delegates to the backend chosen once per process."""

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    @property
    def backend(self) -> SandboxBackend:
        """The backend in use."""
        return self._backend

    @property
    def backend_name(self) -> str:
        """``docker`` or ``kubernetes``."""
        return self._backend.name

    def available(self) -> bool:
        """True when the backend can start sandboxes right now."""
        return self._backend.available()

    def resolve_image(self, overrides: tuple[str, ...]) -> str | None:
        """First non-empty variable in ``overrides``, else the image the backend runs."""
        for name in overrides:
            value = (os.environ.get(name) or "").strip()
            if value:
                return value
        return self._backend.resolve_image()

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        """Run one sandbox to completion."""
        return self._backend.run(spec, stdin, timeout_seconds)

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        """Command for a caller that spawns and supervises the sandbox process."""
        return self._backend.process_command(spec)

    def force_remove(self, name: str | None) -> None:
        """Remove a sandbox that may have outlived its caller."""
        self._backend.force_remove(name)

    def uses_shared_workspace(self) -> bool:
        """True when sandbox workspaces must live on the shared workspace volume."""
        return self._backend.uses_shared_workspace()


def _build_manager() -> SandboxManager:
    return SandboxManager(DockerBackend())


_manager: SandboxManager | None = None
_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """The process-wide manager, built on first use."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = _build_manager()
        return _manager


def reset_sandbox_manager() -> None:
    """Forget the manager so the next call selects again (tests, config reloads)."""
    global _manager
    with _manager_lock:
        _manager = None
```

- [ ] **Step 4: Write `__init__.py`**

```python
"""One sandbox layer for Docker and Kubernetes. See the spec in docs/superpowers/specs."""

from app.services.sandbox.manager import (
    SandboxManager,
    get_sandbox_manager,
    reset_sandbox_manager,
)
from app.services.sandbox.spec import (
    DockerVolumeSource,
    OperatorMount,
    ProcessCommand,
    SandboxResult,
    SandboxSpec,
    Tmpfs,
    WorkspaceMount,
)

__all__ = [
    "DockerVolumeSource",
    "OperatorMount",
    "ProcessCommand",
    "SandboxManager",
    "SandboxResult",
    "SandboxSpec",
    "Tmpfs",
    "WorkspaceMount",
    "get_sandbox_manager",
    "reset_sandbox_manager",
]
```

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_sandbox_manager.py tests/test_sandbox_spec.py tests/test_sandbox_docker_backend.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/sandbox backend/tests/test_sandbox_manager.py
git commit -m "feat(sandbox): sandbox manager with docker as the only backend"
```

## Task 5: Python tool site

**Files:**
- Modify: `backend/app/services/python_tool_executor.py`
- Test: existing `backend/tests/test_python_tool_executor.py`, parity test

- [ ] **Step 1: Replace the Docker plumbing**

Delete `import socket`, `_docker_available_cache`, the bodies of `_docker_available`, `_resolve_image`, `_build_docker_command`, `_execute_docker`, and the whole `_force_remove_container`. Add the imports and the functions below; `_sandbox_mode`, `_runner_local_path`, `_parse_runner_output`, `_execute_subprocess` and `execute_tool` stay as they are.

```python
from app.services.sandbox import SandboxSpec, Tmpfs, get_sandbox_manager
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.errors import SandboxTimeout


def _docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def _resolve_image() -> str | None:
    """``HEYM_PYTHON_TOOL_IMAGE``, else the image the backend itself runs."""
    return get_sandbox_manager().resolve_image(("HEYM_PYTHON_TOOL_IMAGE",))


def _tool_spec(image: str, name: str) -> SandboxSpec:
    """Hardened, offline sandbox for one tool call. The runner reads its payload on stdin."""
    memory = os.environ.get("HEYM_PYTHON_TOOL_MEMORY", "256m")
    return SandboxSpec(
        site="pytool",
        name=name,
        image=image,
        entrypoint="python",
        args=(os.environ.get("HEYM_PYTHON_TOOL_RUNNER_PATH", _DEFAULT_CONTAINER_RUNNER_PATH),),
        network=os.environ.get("HEYM_PYTHON_TOOL_NETWORK", "none"),
        user=os.environ.get("HEYM_PYTHON_TOOL_USER", "65534:65534"),
        tmpfs=(Tmpfs("/tmp", "rw,noexec,nosuid", "64m"),),
        workdir="/tmp",
        pids=os.environ.get("HEYM_PYTHON_TOOL_PIDS", "128"),
        memory=memory,
        memory_swap=memory,
        cpus=os.environ.get("HEYM_PYTHON_TOOL_CPUS", "1"),
        env=("PYTHONDONTWRITEBYTECODE=1", "PYTHONIOENCODING=utf-8"),
    )


def _build_docker_command(image: str, name: str) -> list[str]:
    """The ``docker run`` argv of one tool call."""
    return render_docker_argv(_tool_spec(image, name))


def _execute_docker(payload_json: str, timeout_seconds: float, image: str) -> str:
    """Run the tool runner in a hardened, throwaway sandbox and return its stdout."""
    name = f"heym-pytool-{uuid.uuid4().hex}"
    try:
        result = get_sandbox_manager().run(_tool_spec(image, name), payload_json, timeout_seconds)
    except SandboxTimeout:
        raise TimeoutError(f"Tool execution timed out after {timeout_seconds} seconds") from None
    if result.stderr:
        logger.warning("Docker tool stderr: %s", result.stderr)
    return result.stdout
```

- [ ] **Step 2: Run the site tests and the parity test**

Run: `PYTEST tests/test_python_tool_executor.py tests/test_sandbox_docker_parity.py`
Expected: all pass. A parity failure on `pytool` or `pytool_custom` prints the differing flags; fix the spec, not the golden.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/python_tool_executor.py
git commit -m "refactor(sandbox): python tool runs through the sandbox manager"
```

## Task 6: Code node, formatter, file sandbox, Code node with files

**Files:**
- Modify: `backend/app/services/code_python_executor.py` (rewrite below)
- Modify: `backend/app/services/code_formatter.py`, `backend/app/services/file_sandbox/executor.py`, `backend/app/services/file_sandbox/code_node.py`
- Modify tests: `backend/tests/test_code_python_executor.py`

- [ ] **Step 1: Replace `code_python_executor.py` from the module docstring through `_install_dependencies`**

Keep `_BOOTSTRAP`, `CodeExecutionResult`, `_truncate`, `_runner_source`, `_workspace_mount_point`, `_code_run_root`, `_chmod_best_effort` and `_parse_envelope` exactly as they are. Everything else up to `execute_code` becomes:

```python
"""Execute Code node Python in a disposable, hardened sandbox.

Unlike the Agent tool sandbox (``python_tool_executor``) and the skill sandbox
(``skill_python_executor``), this path has **no subprocess fallback and reads
no sandbox-mode environment variable**. When no sandbox backend is reachable the
Code node fails closed, because the code it runs is arbitrary user Python with
arbitrary third-party dependencies.

Execution is one or two throwaway sandboxes (Docker containers or Kubernetes
pods, see ``app.services.sandbox``):

* With no dependencies, a single offline sandbox runs the code. The runner
  source travels in the stdin payload, so nothing is mounted.
* With dependencies, a network-enabled sandbox installs them into a per-run
  ``.deps`` directory on the shared workspace volume (``uv`` first, ``pip`` as
  a compatibility retry), then a second sandbox mounts that subtree
  ``readonly`` and runs the code with ``PYTHONPATH`` pointing at it.

Neither sandbox receives the Docker socket, a ServiceAccount token or any backend
secret, and the run directory is deleted on every exit path.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.sandbox import (
    DockerVolumeSource,
    SandboxSpec,
    Tmpfs,
    WorkspaceMount,
    get_sandbox_manager,
)
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.env import CODE_FORWARD_PREFIXES, forwarded_env
from app.services.sandbox.errors import SandboxTimeout
from app.services.sandbox.spec import START_FAILURE_CODES

logger = logging.getLogger(__name__)

# Limits are constants rather than environment variables: they are platform
# properties of the sandbox, not deployment configuration.
_MEMORY_LIMIT = "512m"
_CPU_LIMIT = "1"
_PIDS_LIMIT = "256"
_SANDBOX_USER = "65534:65534"
_INSTALL_TIMEOUT_SECONDS = 120.0
_RUN_TIMEOUT_SECONDS = 60.0
_INSTALL_TMPFS = "/tmp:rw,nosuid,size=512m"
_RUN_TMPFS = "/tmp:rw,nosuid,size=256m"
_MAX_INSTALL_LOG_CHARS = 8000

_DEFAULT_WORKSPACE_MOUNT = "/app/data/codex-workspaces"
_CODE_RUN_SUBDIR = "_code-runs"
_DEPS_DIRNAME = ".deps"
_REQUIREMENTS_FILENAME = "requirements.txt"

# Old name kept: the file sandbox imports it.
_DOCKER_START_FAILURE_CODES: frozenset[int] = START_FAILURE_CODES

# (keep _BOOTSTRAP, CodeExecutionResult and _truncate here unchanged)


def docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def resolve_sandbox_image() -> str | None:
    """``HEYM_PYTHON_TOOL_IMAGE``, ``HEYM_CODEX_DOCKER_IMAGE``, else the backend's own image."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_PYTHON_TOOL_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


# (keep _runner_source and _workspace_mount_point here unchanged)


def _is_containerized() -> bool:
    """True when sandbox workspaces must live on the volume shared with the sandbox."""
    return get_sandbox_manager().uses_shared_workspace()


# (keep _code_run_root here unchanged)


def workspace_mount(
    host_path: Path,
    container_path: str,
    readonly: bool,
    *,
    missing_volume_hint: str = "The sandbox needs a shared workspace volume.",
    fallback_hint: str = "",
) -> WorkspaceMount:
    """Expose only ``host_path`` at ``container_path``.

    ``host_path`` must live under the workspace mount when the backend runs in a
    container; a native backend binds it straight through.
    """
    mount_point = _workspace_mount_point()
    return WorkspaceMount(
        host_path=host_path,
        target=container_path,
        readonly=readonly,
        docker=DockerVolumeSource(
            mount_point=mount_point,
            volume_env=("HEYM_CODEX_DOCKER_WORKSPACE_VOLUME",),
            missing_message=(
                f"{missing_volume_hint} Set HEYM_CODEX_DOCKER_WORKSPACE_VOLUME to the named "
                f"volume mounted at {mount_point}.{fallback_hint}"
            ),
            native_bind=not _is_containerized(),
        ),
    )


def _code_workspace_mount(run_dir: Path, readonly: bool) -> WorkspaceMount:
    return workspace_mount(
        run_dir,
        str(run_dir),
        readonly,
        missing_volume_hint="The Code node needs a shared workspace volume to install "
        "dependencies.",
        fallback_hint=" Or leave requirements.txt empty to run without dependencies.",
    )


def code_spec(
    *,
    site: str,
    name: str,
    image: str,
    network: str,
    tmpfs: str,
    entrypoint: str,
    args: tuple[str, ...],
    workdir: str,
    mounts: tuple[WorkspaceMount, ...] = (),
    extra_env: tuple[str, ...] = (),
    memory: str = _MEMORY_LIMIT,
    cpus: str = _CPU_LIMIT,
) -> SandboxSpec:
    """The Code node sandbox: non-root, no capabilities, read-only root, allowlisted env."""
    return SandboxSpec(
        site=site,
        name=name,
        image=image,
        entrypoint=entrypoint,
        args=args,
        network=network,
        user=_SANDBOX_USER,
        tmpfs=(Tmpfs.parse(tmpfs),),
        workdir=workdir,
        pids=_PIDS_LIMIT,
        memory=memory,
        memory_swap=memory,
        cpus=cpus,
        env=(
            "HOME=/tmp",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONIOENCODING=utf-8",
            *forwarded_env(CODE_FORWARD_PREFIXES),
            *extra_env,
        ),
        workspace_mounts=mounts,
    )


def _install_spec(
    image: str, name: str, mounts: tuple[WorkspaceMount, ...], run_dir: Path, tool: str
) -> SandboxSpec:
    target = str(run_dir / _DEPS_DIRNAME)
    requirements = str(run_dir / _REQUIREMENTS_FILENAME)
    if tool == "uv":
        args = ("pip", "install", "--no-cache", "--target", target, "-r", requirements)
    else:
        args = ("install", "--no-cache-dir", "--target", target, "-r", requirements)
    return code_spec(
        site="code-install",
        name=name,
        image=image,
        network="bridge",
        tmpfs=_INSTALL_TMPFS,
        entrypoint=tool,
        args=args,
        workdir="/tmp",
        mounts=mounts,
    )


def _run_spec(
    image: str,
    name: str,
    allow_network: bool,
    mounts: tuple[WorkspaceMount, ...],
    deps_path: Path | None,
) -> SandboxSpec:
    return code_spec(
        site="code-run",
        name=name,
        image=image,
        network="bridge" if allow_network else "none",
        tmpfs=_RUN_TMPFS,
        entrypoint="python",
        args=("-c", _BOOTSTRAP),
        workdir="/tmp",
        mounts=mounts,
        extra_env=(f"PYTHONPATH={deps_path}",) if deps_path is not None else (),
    )


def _build_install_command(
    image: str, name: str, mounts: tuple[WorkspaceMount, ...], run_dir: Path, tool: str
) -> list[str]:
    """The install sandbox as ``docker run`` argv (``uv`` or ``pip``)."""
    return render_docker_argv(_install_spec(image, name, mounts, run_dir, tool))


def _build_run_command(
    image: str,
    name: str,
    allow_network: bool,
    mounts: tuple[WorkspaceMount, ...],
    deps_path: Path | None,
) -> list[str]:
    """The execution sandbox as ``docker run`` argv."""
    return render_docker_argv(_run_spec(image, name, allow_network, mounts, deps_path))


def run_sandbox_container(
    spec: SandboxSpec,
    stdin_text: str | None,
    timeout_seconds: float,
    phase: str,
) -> tuple[int, str, str]:
    """Run one sandbox and return ``(returncode, stdout, stderr)``."""
    try:
        result = get_sandbox_manager().run(spec, stdin_text, timeout_seconds)
    except SandboxTimeout:
        raise TimeoutError(
            f"Code node {phase} timed out after {timeout_seconds:.0f} seconds"
        ) from None
    return result.returncode, result.stdout, result.stderr


# (keep _chmod_best_effort here unchanged)


def _install_dependencies(image: str, run_dir: Path, requirements: str) -> tuple[str, str]:
    """Install requirements into ``run_dir/.deps``; return ``(tool, log)``."""
    (run_dir / _REQUIREMENTS_FILENAME).write_text(requirements, encoding="utf-8")
    deps_dir = run_dir / _DEPS_DIRNAME
    deps_dir.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(deps_dir, 0o777)

    mounts = (_code_workspace_mount(run_dir, readonly=False),)
    attempts: list[str] = []
    for tool in ("uv", "pip"):
        name = f"heym-code-install-{uuid.uuid4().hex}"
        returncode, stdout, stderr = run_sandbox_container(
            _install_spec(image, name, mounts, run_dir, tool),
            None,
            _INSTALL_TIMEOUT_SECONDS,
            "dependency install",
        )
        attempts.append(f"[{tool}] exit {returncode}\n{stdout}{stderr}".strip())
        if returncode == 0:
            return tool, _truncate("\n\n".join(attempts))
        logger.warning("Code node %s install failed (exit %s)", tool, returncode)

    raise RuntimeError(
        "Code node dependency install failed with both uv and pip.\n\n"
        + _truncate("\n\n".join(attempts))
    )
```

Delete `socket`, `subprocess`, `typing.Any`, `_docker_available_cache`, `_current_container_mounts`, `_resolve_workspace_mount`, `resolve_mount`, `_ENV_FORWARD_PREFIXES`, `_forwarded_env`, `hardening_args` and `_force_remove_container`.

- [ ] **Step 2: Update the body of `execute_code` after the image check**

```python
    payload = json.dumps({"runner": _runner_source(), "code": code, "params": params}, default=str)
    needs_install = bool((requirements or "").strip())
    run_dir: Path | None = None
    install_tool = "none"
    install_log = ""

    try:
        mounts: tuple[WorkspaceMount, ...] = ()
        deps_path: Path | None = None
        if needs_install:
            run_dir = _code_run_root() / uuid.uuid4().hex
            run_dir.mkdir(parents=True, exist_ok=True)
            _chmod_best_effort(run_dir, 0o777)
            install_tool, install_log = _install_dependencies(image, run_dir, requirements)
            mounts = (_code_workspace_mount(run_dir, readonly=True),)
            deps_path = run_dir / _DEPS_DIRNAME

        name = f"heym-code-{uuid.uuid4().hex}"
        returncode, stdout, stderr = run_sandbox_container(
            _run_spec(image, name, allow_network, mounts, deps_path),
            payload,
            _RUN_TIMEOUT_SECONDS,
            "execution",
        )
        if returncode in _DOCKER_START_FAILURE_CODES:
            raise RuntimeError(
                f"Code node sandbox failed to start (docker exit {returncode}): "
                f"{stderr.strip()[:500]}"
            )
        if stderr.strip():
            logger.warning("Code node sandbox stderr: %s", stderr.strip()[:2000])

        result, logs = _parse_envelope(stdout)
        return CodeExecutionResult(
            result=result,
            logs=logs,
            install_ok=True,
            install_tool=install_tool,
            install_log=install_log,
        )
    finally:
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
```

- [ ] **Step 3: Update `code_formatter.py`**

Replace the import block from `app.services.code_python_executor` and the two functions:

```python
from app.services.code_python_executor import (
    code_spec,
    docker_available,
    resolve_sandbox_image,
    run_sandbox_container,
)
from app.services.sandbox import SandboxSpec
from app.services.sandbox.docker_backend import render_docker_argv


def _format_spec(image: str, name: str) -> SandboxSpec:
    """Hardened, offline sandbox for Ruff."""
    return code_spec(
        site="code-format",
        name=name,
        image=image,
        network="none",
        tmpfs=_FORMAT_TMPFS,
        entrypoint="sh",
        args=("-c", _PROBE_SCRIPT),
        workdir="/tmp",
    )


def _build_format_command(image: str, name: str) -> list[str]:
    """Build the hardened, offline ``docker run`` invocation for Ruff."""
    return render_docker_argv(_format_spec(image, name))


def _run_ruff(image: str, source: str) -> tuple[int, str, str]:
    """Run one throwaway Ruff sandbox over ``source``."""
    name = f"heym-code-format-{uuid.uuid4().hex}"
    try:
        return run_sandbox_container(_format_spec(image, name), source, _TIMEOUT_SECONDS, "formatting")
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc
```

- [ ] **Step 4: Update `file_sandbox/executor.py`**

Replace the import from `code_python_executor` with:

```python
from app.services.code_python_executor import (
    _DOCKER_START_FAILURE_CODES,
    code_spec,
    docker_available,
    resolve_sandbox_image,
    run_sandbox_container,
    workspace_mount,
)
from app.services.sandbox import SandboxSpec
```

Replace `build_command` with `build_spec`, and the call inside `run_in_sandbox`:

```python
def build_spec(image: str, name: str, workspace: FileWorkspace) -> SandboxSpec:
    """The sandbox for one call: offline, ``/input`` read-only, ``/work`` writable."""
    return code_spec(
        site="files",
        name=name,
        image=image,
        network="none",
        tmpfs=TMPFS,
        entrypoint="python",
        args=("-c", _BOOTSTRAP),
        workdir=WORK_MOUNT,
        mounts=(
            workspace_mount(workspace.in_dir, INPUT_MOUNT, readonly=True),
            workspace_mount(workspace.work_dir, WORK_MOUNT, readonly=False),
        ),
        memory=MEMORY_LIMIT,
        cpus=CPU_LIMIT,
    )
```

```python
    name = f"heym-files-{uuid.uuid4().hex}"
    with _containers:
        try:
            returncode, stdout, stderr = run_sandbox_container(
                build_spec(image, name, workspace),
                json.dumps(payload, default=str),
                CALL_TIMEOUT_SECONDS,
                "file call",
            )
        except TimeoutError:
            raise TimeoutError(
                f"The sandbox call ran past {CALL_TIMEOUT_SECONDS:.0f} seconds. Read less at "
                "once (nrows, a page range, chunks) and save intermediate results under /work."
            ) from None
```

- [ ] **Step 5: Update `file_sandbox/code_node.py`**

Import list from `code_python_executor` becomes `_DOCKER_START_FAILURE_CODES, _install_dependencies, _parse_envelope, _runner_source, code_spec, docker_available, resolve_sandbox_image, run_sandbox_container, workspace_mount`. Replace the block from `name = f"heym-code-{uuid.uuid4().hex}"` through the `run_sandbox_container` call with:

```python
        name = f"heym-code-{uuid.uuid4().hex}"
        spec = code_spec(
            site="code-files",
            name=name,
            image=image,
            network="bridge" if allow_network else "none",
            tmpfs=TMPFS,
            entrypoint="python",
            args=("-c", sandbox._BOOTSTRAP),
            workdir=WORK_MOUNT,
            mounts=(
                workspace_mount(workspace.in_dir, INPUT_MOUNT, readonly=True),
                workspace_mount(workspace.work_dir, WORK_MOUNT, readonly=False),
            ),
            extra_env=(f"PYTHONPATH={_DEPS_PATH}",) if requirements.strip() else (),
            memory=MEMORY_LIMIT,
            cpus=CPU_LIMIT,
        )
        payload = sandbox.build_payload(
            "code_node", code_runner=_runner_source(), code=code, params=run_params
        )
        with sandbox._containers:
            returncode, stdout, stderr = run_sandbox_container(
                spec, json.dumps(payload, default=str), CALL_TIMEOUT_SECONDS, "execution"
            )
```

- [ ] **Step 6: Move the Code node tests to the new seams**

```bash
cd backend
sed -i '' 's/mount_args=\[\]/mounts=()/g' tests/test_code_python_executor.py
sed -i '' 's/mount_args=\["--mount", "type=bind,src=\/h\/r,dst=\/r"\]/mounts=()/' tests/test_code_python_executor.py
sed -i '' 's/patch.object(executor, "_resolve_workspace_mount", return_value=\["--mount", "m"\])/patch("app.services.sandbox.docker_backend.docker_mount_args", return_value=["--mount", "m"])/' tests/test_code_python_executor.py
sed -i '' 's/patch.object(executor, "_force_remove_container")/patch("app.services.sandbox.docker_backend._docker_rm")/' tests/test_code_python_executor.py
sed -i '' 's/executor\._resolve_workspace_mount(run_dir, readonly=True)/docker_mount_args(executor._code_workspace_mount(run_dir, readonly=True))/' tests/test_code_python_executor.py
sed -i '' 's/executor\._resolve_workspace_mount(run_dir, readonly=False)/docker_mount_args(executor._code_workspace_mount(run_dir, readonly=False))/' tests/test_code_python_executor.py
grep -n "_resolve_workspace_mount\|mount_args=" tests/test_code_python_executor.py
```

Expected from the `grep`: only the `test_deps_path_is_exported_as_pythonpath` line, which is replaced below. Add `from app.services.sandbox.docker_backend import docker_mount_args` to the test's imports.

Replace `test_deps_path_is_exported_as_pythonpath` with:

```python
    def test_deps_path_is_exported_as_pythonpath(self) -> None:
        with patch.object(executor, "_is_containerized", return_value=False):
            cmd = executor._build_run_command(
                image="heym-backend:local",
                name="heym-code-abc",
                allow_network=False,
                mounts=(executor._code_workspace_mount(Path("/d"), readonly=True),),
                deps_path=Path("/d/.deps"),
            )
        self.assertIn("PYTHONPATH=/d/.deps", cmd)
        self.assertIn("type=bind,src=/d,dst=/d,readonly", cmd)
```

- [ ] **Step 7: Run every affected suite and the parity test**

Run: `PYTEST tests/test_code_python_executor.py tests/test_code_format_api.py tests/test_file_sandbox_tools.py tests/test_file_sandbox_workspace.py tests/test_file_sandbox_chat_lifecycle.py tests/test_file_sandbox_docker.py tests/test_advisory_file_sandbox_access.py tests/test_sandbox_docker_parity.py`
Expected: all pass (`test_file_sandbox_docker.py` skips without a local sandbox image). Parity cases `formatter`, `code_*`, `files`, `code_files` must match.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/code_python_executor.py backend/app/services/code_formatter.py backend/app/services/file_sandbox backend/tests/test_code_python_executor.py
git commit -m "refactor(sandbox): code node, formatter and file sandbox use sandbox specs"
```

## Task 7: Playwright site

**Files:**
- Modify: `backend/app/services/playwright_sandbox.py`
- Test: existing `backend/tests/test_playwright_security.py`, parity test

- [ ] **Step 1: Replace the Docker plumbing**

Delete `import socket`, `import subprocess`, `_docker_available_cache`, `_force_remove_container`, and the bodies below. Keep `PlaywrightSandboxUnavailableError`, `sandbox_mode`, `_sandbox_python` and `require_image`.

```python
from app.services.sandbox import SandboxSpec, Tmpfs, get_sandbox_manager
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.errors import SandboxTimeout


def _docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def _resolve_image() -> str | None:
    """``HEYM_PLAYWRIGHT_SANDBOX_IMAGE``, ``HEYM_CODEX_DOCKER_IMAGE``, else the backend's own image."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_PLAYWRIGHT_SANDBOX_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


def _playwright_spec(image: str, name: str) -> SandboxSpec:
    """Throwaway sandbox that reads the script on stdin. Network stays on for browsing."""
    memory = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_MEMORY", "1g")
    user = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_USER", "").strip()
    return SandboxSpec(
        site="playwright",
        name=name,
        image=image,
        entrypoint=_sandbox_python(),
        args=("-",),
        network=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_NETWORK", "bridge"),
        user=user or None,
        read_only_root=False,
        tmpfs=(Tmpfs("/tmp", "rw,nosuid", "256m"),),
        shm_size=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_SHM_SIZE", "1g"),
        pids=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_PIDS", "512"),
        memory=memory,
        memory_swap=memory,
        cpus=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_CPUS", "2"),
        env=("PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1"),
    )


def build_docker_command(image: str, name: str) -> list[str]:
    """Build a hardened, throwaway ``docker run`` invocation that reads the script on stdin."""
    return render_docker_argv(_playwright_spec(image, name))


def run_script(
    script_content: str,
    timeout_seconds: float,
    image: str | None = None,
) -> tuple[int, str, str]:
    """Run ``script_content`` in a hardened throwaway sandbox; return ``(returncode, stdout, stderr)``.

    Raises :class:`TimeoutError` past ``timeout_seconds`` and
    :class:`PlaywrightSandboxUnavailableError` when the sandbox cannot be established.
    """
    image = image or require_image()
    name = f"heym-pw-{uuid.uuid4().hex}"
    try:
        result = get_sandbox_manager().run(
            _playwright_spec(image, name), script_content, timeout_seconds
        )
    except SandboxTimeout:
        raise TimeoutError(
            f"Playwright script timed out after {timeout_seconds:.1f} seconds"
        ) from None
    return result.returncode, result.stdout, result.stderr
```

- [ ] **Step 2: Run tests**

Run: `PYTEST tests/test_playwright_security.py tests/test_playwright_ai_step_errors.py tests/test_playwright_disabled_steps.py tests/test_sandbox_docker_parity.py`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/playwright_sandbox.py
git commit -m "refactor(sandbox): playwright runs through the sandbox manager"
```

## Task 8: Skill site

**Files:**
- Modify: `backend/app/services/skill_python_executor.py`
- Test: existing `backend/tests/test_skill_python_executor_sandbox.py`, `test_skill_python_executor_drive.py`, parity test

- [ ] **Step 1: Replace the Docker plumbing**

Delete `_DOCKER_START_FAILURE_CODES`, `_docker_available_cache`, `_DOCKER_ENV_FORWARD_PREFIXES`, `_docker_forward_env`, `_resolve_workspace_mount`, `_current_container_mounts` and `_force_remove_container`. Replace `_docker_available`, `_resolve_image`, `_build_skill_docker_command` and `_execute_skill_docker`:

```python
from app.services.sandbox import (
    DockerVolumeSource,
    SandboxSpec,
    Tmpfs,
    WorkspaceMount,
    get_sandbox_manager,
)
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.env import SKILL_FORWARD_PREFIXES, forwarded_env
from app.services.sandbox.errors import SandboxTimeout


def _docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def _resolve_image() -> str | None:
    """``HEYM_SKILL_IMAGE``, ``HEYM_PYTHON_TOOL_IMAGE``, ``HEYM_CODEX_DOCKER_IMAGE``, else the backend's own."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_SKILL_IMAGE", "HEYM_PYTHON_TOOL_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


def _skill_workspace_mount(mount_point: Path, run_dir: Path) -> WorkspaceMount:
    """Only this run's subtree, at the same path as on the backend."""
    return WorkspaceMount(
        host_path=run_dir,
        target=str(run_dir),
        readonly=False,
        docker=DockerVolumeSource(
            mount_point=mount_point,
            volume_env=("HEYM_SKILL_DOCKER_WORKSPACE_VOLUME", "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME"),
            host_root_env="HEYM_SKILL_HOST_WORKSPACE_DIR",
            label="Skill run dir",
            missing_message=(
                "Skill Docker sandbox needs a shared workspace: set "
                "HEYM_SKILL_DOCKER_WORKSPACE_VOLUME (or HEYM_CODEX_DOCKER_WORKSPACE_VOLUME) to "
                "the named volume mounted at the workspace volume mount point, or run with "
                "HEYM_PYTHON_TOOL_SANDBOX=subprocess for trusted/dev use only."
            ),
        ),
    )


def _skill_spec(
    image: str, name: str, mount_point: Path, run_dir: Path, entry_point: str
) -> SandboxSpec:
    """Hardened sandbox for a skill: network egress and a per-run writable workspace."""
    memory = os.environ.get("HEYM_SKILL_MEMORY", "512m")
    return SandboxSpec(
        site="skill",
        name=name,
        image=image,
        entrypoint=_skill_interpreter(),
        args=(entry_point,),
        network=os.environ.get("HEYM_SKILL_NETWORK", "bridge"),
        user=os.environ.get("HEYM_SKILL_USER", "65534:65534"),
        tmpfs=(Tmpfs("/tmp", "rw,nosuid", "64m"),),
        workdir=str(run_dir),
        pids=os.environ.get("HEYM_SKILL_PIDS", "256"),
        memory=memory,
        memory_swap=memory,
        cpus=os.environ.get("HEYM_SKILL_CPUS", "1"),
        env=(
            f"HOME={run_dir / '.home'}",
            f"_OUTPUT_DIR={run_dir / _OUTPUT_FILES_DIR}",
            *forwarded_env(SKILL_FORWARD_PREFIXES),
        ),
        workspace_mounts=(_skill_workspace_mount(mount_point, run_dir),),
    )


def _build_skill_docker_command(
    image: str,
    name: str,
    mount_point: Path,
    run_dir: Path,
    entry_point: str,
) -> list[str]:
    """The skill sandbox as ``docker run`` argv."""
    return render_docker_argv(_skill_spec(image, name, mount_point, run_dir, entry_point))


def _execute_skill_docker(
    skill_files: list[dict[str, Any]],
    arguments: dict[str, Any],
    timeout_seconds: float,
    drive_files: list[dict[str, Any]] | None,
    entry_point: str,
    image: str,
) -> SkillExecutionResult:
    """Run the skill inside a hardened, throwaway sandbox (no Docker socket, no SA token)."""
    mount_point = _skill_volume_mount_point()
    run_dir = _skill_workspace_root() / "_skills" / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        # The sandbox runs non-root against a root-owned volume, so the throwaway
        # run dir (and the dirs the sandbox user must write) are made writable.
        _chmod_best_effort(run_dir, 0o777)
        (run_dir / ".home").mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(run_dir / ".home", 0o777)

        output_dir = _populate_workspace(run_dir, skill_files, drive_files)
        _chmod_best_effort(output_dir, 0o777)

        args_json = _serialize_skill_stdin(arguments)
        name = f"heym-skill-{uuid.uuid4().hex}"
        spec = _skill_spec(image, name, mount_point, run_dir, entry_point)
        try:
            result = get_sandbox_manager().run(spec, args_json, timeout_seconds)
        except SandboxTimeout:
            raise TimeoutError(
                f"Skill execution timed out after {timeout_seconds} seconds"
            ) from None

        if result.stderr:
            logger.warning("Skill docker stderr: %s", result.stderr)
        # A sandbox that never started fails closed; any other exit code is the
        # skill's own process and stays a soft result like the subprocess path.
        if result.start_failed:
            raise RuntimeError(
                "Skill Docker sandbox failed to start "
                f"(docker exit {result.returncode}): {(result.stderr or '').strip()[:500]}"
            )
        return _build_result(result.stdout, result.stderr, output_dir)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
```

`json` stays imported (used elsewhere in the module); remove `subprocess` only if nothing else in the module uses it (`_execute_skill_subprocess` does, so it stays).

- [ ] **Step 2: Run tests**

Run: `PYTEST tests/test_skill_python_executor_sandbox.py tests/test_skill_python_executor_drive.py tests/test_sandbox_docker_parity.py`
Expected: all pass, including parity cases `skill_volume` and `skill_bind`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/skill_python_executor.py
git commit -m "refactor(sandbox): skills run through the sandbox manager"
```

## Task 9: MCP stdio site

**Files:**
- Modify: `backend/app/services/mcp_stdio_sandbox.py`
- Test: existing `backend/tests/test_mcp_stdio_sandbox.py`, parity test

- [ ] **Step 1: Replace the Docker plumbing**

Delete `import socket`, `import subprocess`, `_docker_available_cache`, `_hardening_flags`. Replace `_resolve_files_mount`, `docker_available`, `reset_docker_available_cache`, `_sandbox_image`, `_parse_docker_run`'s return value, `build_sandboxed_command` and `force_remove_container`. Keep `_DOCKER_VALUE_FLAGS`, `_DOCKER_REFUSED_FLAGS`, `MCPStdioSandboxError`, `SandboxedCommand`, `sandbox_mode`, `_NEVER_AUTO_MOUNTED_VOLUME_VARS`, `_tunable`, `_parse_nonroot_id`, `_sandbox_user`.

```python
from app.services.sandbox import (
    OperatorMount,
    SandboxSpec,
    Tmpfs,
    get_sandbox_manager,
    reset_sandbox_manager,
)


@dataclass
class _CarriedFlags:
    """What a caller's ``docker run`` may keep: env, workdir and entrypoint."""

    env: list[str] = field(default_factory=list)
    workdir: str | None = None
    entrypoint: str | None = None


def _files_mount() -> OperatorMount | None:
    """The operator-configured files mount, or None. See the module docstring."""
    for var in _NEVER_AUTO_MOUNTED_VOLUME_VARS:
        if os.environ.get(var, "").strip():
            logger.debug(
                "MCP stdio sandbox: ignoring %s; application volumes are never auto-mounted",
                var,
            )
    writable = os.environ.get("HEYM_MCP_STDIO_FILES_WRITABLE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    volume = os.environ.get("HEYM_MCP_STDIO_FILES_VOLUME", "").strip()
    if volume:
        subpath = os.environ.get("HEYM_MCP_STDIO_FILES_SUBPATH", "").strip() or None
        return OperatorMount(
            target=_FILES_MOUNT_PATH, volume=volume, subpath=subpath, writable=writable
        )
    host_dir = os.environ.get("HEYM_MCP_STDIO_FILES_HOST_DIR", "").strip()
    if host_dir:
        return OperatorMount(target=_FILES_MOUNT_PATH, host_dir=host_dir, writable=writable)
    logger.debug("MCP stdio sandbox: no file mount configured; the server sees no Heym files")
    return None


def docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def reset_docker_available_cache() -> None:
    """Forget the selected sandbox backend (used by tests)."""
    reset_sandbox_manager()


def _sandbox_image() -> str | None:
    """Image for non-``docker`` commands (it ships node and uv); None fails closed."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_MCP_STDIO_IMAGE", "HEYM_PYTHON_TOOL_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


def _mcp_spec(
    *,
    name: str,
    image: str,
    entrypoint: str | None,
    args: list[str],
    workdir: str | None,
    extra_env: list[str],
) -> SandboxSpec:
    """Flags shared by every sandboxed MCP server. ``-i`` carries the protocol.

    The tmpfs at ``/tmp`` is the only writable path. It is ``exec`` so npx/uvx can
    run what they install, and ``HOME`` plus the npm/uv/XDG caches point into it,
    because uid 65534's passwd home does not exist. See the git history of
    ``_hardening_flags`` for why each one was needed.
    """
    return SandboxSpec(
        site="mcp-stdio",
        name=name,
        image=image,
        entrypoint=entrypoint,
        args=tuple(args),
        network="bridge",
        user=_sandbox_user(),
        tmpfs=(
            Tmpfs(_SANDBOX_TMPFS_PATH, "rw,exec,nosuid", _tunable("HEYM_MCP_STDIO_TMPFS_SIZE", "512m")),
        ),
        workdir=workdir,
        pids=_tunable("HEYM_MCP_STDIO_PIDS", "256"),
        memory=_tunable("HEYM_MCP_STDIO_MEMORY", "512m"),
        cpus=_tunable("HEYM_MCP_STDIO_CPUS", "2"),
        env=(
            "HOME=/tmp",
            "NPM_CONFIG_CACHE=/tmp/.npm",
            "NPM_CONFIG_UPDATE_NOTIFIER=false",
            "XDG_CACHE_HOME=/tmp/.cache",
            "XDG_DATA_HOME=/tmp/.local/share",
            "UV_CACHE_DIR=/tmp/.uv",
            *extra_env,
        ),
        operator_mount=_files_mount(),
    )
```

In `_parse_docker_run`, change the return type to `tuple[_CarriedFlags, list[str], str, list[str]]`, start with `carried = _CarriedFlags()`, and replace the three `carried.extend(...)` lines:

```python
        elif flag in ("-e", "--env"):
            if value:
                carried.env.append(value)
```

```python
        elif flag in ("-w", "--workdir"):
            if value:
                carried.workdir = value
        elif flag == "--entrypoint":
            if value:
                carried.entrypoint = value
```

Replace the tail of `build_sandboxed_command` from `name = f"heym-mcp-stdio-..."` on:

```python
    name = f"heym-mcp-stdio-{uuid.uuid4().hex[:12]}"
    basename = os.path.basename((command or "").strip()).lower()
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    user_env = [f"{key}={value}" for key, value in (env or {}).items()]

    if stem == "docker":
        carried, notes, image, image_args = _parse_docker_run([command, *args])
        spec = _mcp_spec(
            name=name,
            image=image,
            entrypoint=carried.entrypoint,
            args=image_args,
            workdir=carried.workdir,
            extra_env=[*carried.env, *user_env],
        )
    else:
        notes = []
        image = _sandbox_image()
        if not image:
            raise MCPStdioSandboxError(
                f"Cannot isolate the MCP stdio command '{command}': the sandbox image could "
                "not be resolved. Set HEYM_MCP_STDIO_IMAGE (or HEYM_PYTHON_TOOL_IMAGE) to the "
                "backend image, or use the `docker run <image>` form, which names its own image."
            )
        spec = _mcp_spec(
            name=name,
            image=image,
            entrypoint=command,
            args=list(args),
            workdir=_SANDBOX_TMPFS_PATH,
            extra_env=user_env,
        )
    # Env travels inside the command; the spawning client inherits nothing of ours.
    process = get_sandbox_manager().process_command(spec)
    return SandboxedCommand(
        argv=process.argv, env=process.env, container_name=process.name, notes=notes
    )


def force_remove_container(name: str | None) -> None:
    """Best-effort cleanup for a sandbox that outlived its session."""
    get_sandbox_manager().force_remove(name)
```

Add `field` to the `dataclasses` import.

- [ ] **Step 2: Run tests**

Run: `PYTEST tests/test_mcp_stdio_sandbox.py tests/test_sandbox_docker_parity.py`
Expected: all pass, including parity cases `mcp_*`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/mcp_stdio_sandbox.py
git commit -m "refactor(sandbox): mcp stdio runs through the sandbox manager"
```

## Task 10: Milestone 1 gate

- [ ] **Step 1: Confirm no duplicated Docker helper is left**

Run: `cd backend && grep -rn '"docker", "version"\|"docker", "rm"\|"docker", "inspect"\|_docker_available_cache' app | grep -v app/services/sandbox/`
Expected: no output. (The Codex and OpenCode scripts under `docker/` change in Milestone 2.)

- [ ] **Step 2: Lint and the full check**

Run from the repo root: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`
Expected: green. Known local-only failures are the egress tests that read `.env` and two Postgres flakes; confirm any failure also fails on `main` before treating it as unrelated.

- [ ] **Step 3: Commit any formatting from check.sh**

```bash
git add -A backend && git commit -m "style: ruff format" || true
```

---

# Milestone 2: Codex and OpenCode run scope (both backends)

## Task 11: `RunScope`

**Files:**
- Create: `backend/app/services/sandbox/coding_agents.py`
- Test: `backend/tests/test_sandbox_coding_agents.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_coding_agents.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.sandbox.coding_agents'`.

- [ ] **Step 3: Write the scope half of `coding_agents.py`**

```python
"""Run scope and sandbox spec for the Codex and OpenCode runners.

A run sees exactly two directories of its workspace volume: its workspace
``<root>/<id>`` and its home ``<root>/<id><home_suffix>``. Never the volume root,
never another run. Standard library only: the wrapper shims import this module.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.services.sandbox.spec import DockerVolumeSource, SandboxSpec, Tmpfs, WorkspaceMount

_PROXY_AND_CA: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)
# The pod runs as 65534 against a tree the backend cloned as root.
_GIT_SAFE_DIRECTORY: tuple[str, ...] = (
    "GIT_CONFIG_COUNT=1",
    "GIT_CONFIG_KEY_0=safe.directory",
    "GIT_CONFIG_VALUE_0=*",
)
# Bubblewrap inside the Codex container needs these on Docker (see the wrapper's history).
_CODEX_DOCKER_PRIVILEGES: tuple[str, ...] = (
    "--cap-add",
    "SYS_ADMIN",
    "--security-opt",
    "seccomp=unconfined",
    "--security-opt",
    "apparmor=unconfined",
    "--security-opt",
    "systempaths=unconfined",
)
DEADLINE_ENV = "HEYM_SANDBOX_DEADLINE_SECONDS"


class RunScopeError(ValueError):
    """The runner was asked to start outside a single run's own directories."""


@dataclass(frozen=True)
class AgentProfile:
    """Everything that differs between the Codex and OpenCode runners."""

    agent: str
    label: str
    env_prefix: str
    default_root: str
    home_suffix: str
    home_env: str
    entrypoint: str
    run_id_env: str | None
    forward_env: tuple[str, ...]


CODEX = AgentProfile(
    agent="codex",
    label="Codex",
    env_prefix="HEYM_CODEX",
    default_root="/app/data/codex-workspaces",
    home_suffix=".codex-home",
    home_env="CODEX_HOME",
    entrypoint="codex",
    run_id_env=None,
    forward_env=("CODEX_ACCESS_TOKEN", *_PROXY_AND_CA, "CODEX_CA_CERTIFICATE"),
)
OPENCODE = AgentProfile(
    agent="opencode",
    label="OpenCode",
    env_prefix="HEYM_OPENCODE",
    default_root="/app/data/opencode-workspaces",
    home_suffix=".oc-home",
    home_env="HOME",
    entrypoint="opencode",
    run_id_env="HEYM_OPENCODE_RUN_ID",
    forward_env=_PROXY_AND_CA,
)
PROFILES: dict[str, AgentProfile] = {"codex": CODEX, "opencode": OPENCODE}


@dataclass(frozen=True)
class RunScope:
    """The two directories one run may see."""

    root: Path
    run_id: str
    workspace: Path
    home: Path


def _value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def run_scope(profile: AgentProfile, cwd: Path, env: Mapping[str, str]) -> RunScope:
    """The run the runner was started for, or :class:`RunScopeError`."""
    root = Path(_value(env, f"{profile.env_prefix}_WORKSPACE_DIR") or profile.default_root).resolve()
    here = cwd.resolve()
    try:
        rel = here.relative_to(root)
    except ValueError:
        raise RunScopeError(
            f"{profile.label} runner cwd {here} is outside "
            f"{profile.env_prefix}_WORKSPACE_DIR {root}"
        ) from None
    if not rel.parts:
        raise RunScopeError(
            f"{profile.label} runner cwd is the workspace root {root}; a run starts in its own "
            "workspace"
        )
    run_id = rel.parts[0]
    if run_id.startswith(".") or run_id.endswith(profile.home_suffix):
        raise RunScopeError(f"{profile.label} runner cwd {here} is not a run workspace")
    workspace = root / run_id
    home = root / f"{run_id}{profile.home_suffix}"
    raw_home = _value(env, profile.home_env)
    if not raw_home:
        raise RunScopeError(
            f"{profile.home_env} is not set; the {profile.label} runner mounts only the run's "
            f"own home {home}"
        )
    if Path(raw_home).resolve() != home:
        raise RunScopeError(f"{profile.home_env}={raw_home} is not this run's home {home}")
    for directory in (workspace, home):
        if not directory.is_dir():
            raise RunScopeError(f"{directory} does not exist")
    return RunScope(root=root, run_id=run_id, workspace=workspace, home=home)
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_coding_agents.py`
Expected: `4 passed` (the refusal test has six subtests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/coding_agents.py backend/tests/test_sandbox_coding_agents.py
git commit -m "feat(sandbox): codex and opencode run scope"
```

## Task 12: Agent `SandboxSpec` with scoped mounts

**Files:**
- Modify: `backend/app/services/sandbox/coding_agents.py`
- Modify: `backend/tests/test_sandbox_coding_agents.py`, `backend/tests/test_sandbox_docker_parity.py`

- [ ] **Step 1: Add failing tests**

Append to `test_sandbox_coding_agents.py`:

```python
import os
from unittest.mock import patch

from app.services.sandbox.coding_agents import agent_spec
from app.services.sandbox.docker_backend import render_docker_argv


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
                CODEX, scope, ["exec", "hi"], self.env, image="img", name="heym-codex-x",
                kubernetes=kubernetes, cwd=self.root / RUN,
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
            CODEX, scope, ["exec"], self.env, image="img", name="n", kubernetes=True,
            cwd=self.root / RUN,
        )
        self.assertTrue(spec.start_gate)
        self.assertIn("GIT_CONFIG_VALUE_0=*", spec.env)
        docker_spec = agent_spec(
            CODEX, scope, ["exec"], self.env, image="img", name="n", kubernetes=False,
            cwd=self.root / RUN,
        )
        self.assertFalse(docker_spec.start_gate)
        self.assertNotIn("GIT_CONFIG_VALUE_0=*", docker_spec.env)
```

In `test_sandbox_docker_parity.py`, replace `agent_argv` and add a dedicated test:

```python
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
                profile, scope, AGENT_ARGS[agent], env, image=_IMAGE,
                name=f"heym-{agent}-{run_id}", kubernetes=False, cwd=workspace,
            )
            return render_docker_argv(spec)
```

and in `test_every_site_renders_the_recorded_argv`, compare the two agents without their mounts:

```python
        for name in sorted(golden):
            with self.subTest(case=name):
                if name in ("codex", "opencode"):
                    # Milestone 2 replaced the whole-volume mount with two scoped ones.
                    self.assertEqual(without_mounts(actual[name]), without_mounts(golden[name]))
                else:
                    self.assertEqual(actual[name], golden[name])
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_sandbox_coding_agents.py tests/test_sandbox_docker_parity.py`
Expected: FAIL, `ImportError: cannot import name 'agent_spec'`.

- [ ] **Step 3: Append the spec half to `coding_agents.py`**

```python
def _volume_source(profile: AgentProfile, scope: RunScope) -> DockerVolumeSource:
    prefix = profile.env_prefix
    return DockerVolumeSource(
        mount_point=scope.root,
        volume_env=(f"{prefix}_DOCKER_WORKSPACE_VOLUME",),
        host_root_env=f"{prefix}_HOST_WORKSPACE_DIR",
        label=f"{profile.label} run dir",
        missing_message=(
            f"{profile.label} Docker runner needs {prefix}_DOCKER_WORKSPACE_VOLUME, "
            f"{prefix}_HOST_WORKSPACE_DIR, or a Docker mount at {prefix}_WORKSPACE_DIR."
        ),
    )


def _agent_env(profile: AgentProfile, scope: RunScope, env: Mapping[str, str]) -> list[str]:
    items: list[str] = []
    if profile is CODEX:
        items.extend([f"CODEX_HOME={scope.home}", "HOME=/tmp"])
    else:
        home = _value(env, "HOME") or "/tmp"
        for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            if env.get(name):
                items.append(f"{name}={env[name]}")
        if not env.get("XDG_CONFIG_HOME"):
            items.append(f"XDG_CONFIG_HOME={home}/.config")
        if not env.get("XDG_DATA_HOME"):
            items.append(f"XDG_DATA_HOME={home}/.local/share")
    for name in profile.forward_env:
        if env.get(name):
            items.append(f"{name}={env[name]}")
    return items


def _deadline(env: Mapping[str, str]) -> float | None:
    raw = _value(env, DEADLINE_ENV)
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value and value > 0 else None


def agent_spec(
    profile: AgentProfile,
    scope: RunScope,
    args: Sequence[str],
    env: Mapping[str, str],
    *,
    image: str,
    name: str,
    kubernetes: bool,
    cwd: Path,
) -> SandboxSpec:
    """The runner sandbox for one Codex or OpenCode invocation."""
    prefix = profile.env_prefix
    memory = _value(env, f"{prefix}_DOCKER_MEMORY") or "4g"
    source = _volume_source(profile, scope)
    items = _agent_env(profile, scope, env)
    if kubernetes:
        items.extend(_GIT_SAFE_DIRECTORY)
    extra = tuple(shlex.split(_value(env, f"{prefix}_DOCKER_EXTRA_ARGS")))
    codex = profile is CODEX
    return SandboxSpec(
        site=profile.agent,
        name=name,
        image=image,
        entrypoint=_value(env, f"{prefix}_DOCKER_ENTRYPOINT") or profile.entrypoint,
        args=tuple(args),
        network=_value(env, f"{prefix}_DOCKER_NETWORK") or "bridge",
        user=None,
        read_only_root=not codex,
        tmpfs=() if codex else (Tmpfs("/tmp", "rw,nosuid", "512m"),),
        pids=_value(env, f"{prefix}_DOCKER_PIDS") or "1024",
        memory=memory,
        memory_swap=memory,
        cpus=_value(env, f"{prefix}_DOCKER_CPUS") or "2",
        cap_drop_all=not codex,
        no_new_privileges=not codex,
        env=tuple(items),
        workdir=str(cwd.resolve()),
        workspace_mounts=(
            WorkspaceMount(scope.workspace, str(scope.workspace), False, source),
            WorkspaceMount(scope.home, str(scope.home), False, source),
        ),
        docker_extra_args=(_CODEX_DOCKER_PRIVILEGES if codex else ()) + extra,
        deadline_seconds=_deadline(env),
        start_gate=kubernetes,
    )
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_sandbox_coding_agents.py tests/test_sandbox_docker_parity.py`
Expected: all pass. If `codex` or `opencode` parity fails, the diff shows which non-mount flag or env item drifted from the old wrapper.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/coding_agents.py backend/tests/test_sandbox_coding_agents.py backend/tests/test_sandbox_docker_parity.py
git commit -m "feat(sandbox): codex and opencode specs mount only their run"
```

## Task 13: `wrapper_cli` (Docker path)

**Files:**
- Create: `backend/app/services/sandbox/wrapper_cli.py`
- Test: `backend/tests/test_sandbox_wrapper_cli.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_wrapper_cli.py`
Expected: FAIL, `ImportError: cannot import name 'wrapper_cli'`.

- [ ] **Step 3: Write `wrapper_cli.py`**

```python
"""Entry point behind the ``heym-codex-docker`` and ``heym-opencode-docker`` shims.

The runner services start the shim with the run's workspace as cwd and its home in
the environment. This module turns that into a sandbox that sees only the run's two
directories, on whichever backend the manager selected.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from app.services.sandbox.coding_agents import PROFILES, RunScopeError, agent_spec, run_scope
from app.services.sandbox.manager import SandboxManager, get_sandbox_manager
from app.services.sandbox.spec import SandboxSpec

_FALLBACK_IMAGE = "heym-backend:local"


def main(argv: list[str]) -> int:
    """Run ``codex``/``opencode`` with ``argv[1:]`` in the run's sandbox; return its exit code."""
    if not argv or argv[0] not in PROFILES:
        print(
            "usage: python -m app.services.sandbox.wrapper_cli codex|opencode [args...]",
            file=sys.stderr,
        )
        return 2
    profile = PROFILES[argv[0]]
    env = os.environ
    cwd = Path.cwd()
    try:
        scope = run_scope(profile, cwd, env)
    except RunScopeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    manager = get_sandbox_manager()
    kubernetes = manager.backend_name == "kubernetes"
    image = manager.resolve_image((f"{profile.env_prefix}_DOCKER_IMAGE",)) or _FALLBACK_IMAGE
    run_id = (env.get(profile.run_id_env) or "").strip() if profile.run_id_env else ""
    spec = agent_spec(
        profile,
        scope,
        argv[1:],
        env,
        image=image,
        name=f"heym-{profile.agent}-{run_id or uuid.uuid4().hex}",
        kubernetes=kubernetes,
        cwd=cwd,
    )
    return _run_docker(manager, spec)


def _run_docker(manager: SandboxManager, spec: SandboxSpec) -> int:
    command = manager.process_command(spec)
    try:
        process = subprocess.Popen(command.argv, stdin=sys.stdin)
    except FileNotFoundError:
        print("Docker CLI is not installed or not on PATH", file=sys.stderr)
        return 127

    # ``docker run`` is only a client: killing it leaves the container running.
    def _stop(signum: int, _frame: object) -> None:
        manager.force_remove(spec.name)
        process.terminate()
        raise SystemExit(128 + signum)

    for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(caught, _stop)
        except (OSError, ValueError):
            pass
    try:
        return process.wait()
    finally:
        manager.force_remove(spec.name)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_wrapper_cli.py`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/wrapper_cli.py backend/tests/test_sandbox_wrapper_cli.py
git commit -m "feat(sandbox): wrapper cli runs coding agents in their scoped sandbox"
```

## Task 14: Replace the two wrapper scripts with shims

**Files:**
- Modify: `docker/heym-codex-docker`, `docker/heym-opencode-docker` (full rewrite)
- Modify: `backend/tests/test_codex_docker_wrapper.py` (rewrite)

- [ ] **Step 1: Rewrite the failing test first**

Replace `backend/tests/test_codex_docker_wrapper.py` with:

```python
"""The wrapper scripts are shims: find the backend venv and hand over to wrapper_cli."""

import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):  # noqa: ANN202
    loader = SourceFileLoader(name.replace("-", "_"), str(REPO / "docker" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ShimTest(unittest.TestCase):
    def _exec_for(self, script: str, present: str) -> tuple:
        module = _load(script)
        with (
            patch.object(module.os.path, "isfile", side_effect=lambda p: p == present),
            patch.object(module.os, "execve") as execve,
            patch.object(module.sys, "argv", [script, "exec", "--json"]),
        ):
            module.main()
        return execve.call_args.args

    def test_compose_image_layout(self) -> None:
        python, argv, env = self._exec_for("heym-codex-docker", "/app/.venv/bin/python")
        self.assertEqual(python, "/app/.venv/bin/python")
        self.assertEqual(
            argv,
            ["/app/.venv/bin/python", "-m", "app.services.sandbox.wrapper_cli", "codex", "exec", "--json"],
        )
        self.assertEqual(env["PYTHONPATH"], "/app")

    def test_release_image_layout(self) -> None:
        python, argv, env = self._exec_for("heym-opencode-docker", "/app/backend/.venv/bin/python")
        self.assertEqual(argv[3], "opencode")
        self.assertEqual(env["PYTHONPATH"], "/app/backend")

    def test_missing_venv_fails_without_running_anything(self) -> None:
        module = _load("heym-codex-docker")
        with (
            patch.object(module.os.path, "isfile", return_value=False),
            patch.object(module.os, "execve") as execve,
        ):
            self.assertEqual(module.main(), 127)
        execve.assert_not_called()
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_codex_docker_wrapper.py`
Expected: FAIL (the old scripts have no `os.execve` path).

- [ ] **Step 3: Rewrite `docker/heym-codex-docker`**

```python
#!/usr/bin/env python3
"""Run the Codex CLI in Heym's sandbox, scoped to one run.

The logic lives in app/services/sandbox/wrapper_cli.py; this shim only finds the
backend virtualenv, whose path differs between the Compose and release images.
"""

from __future__ import annotations

import os
import sys

_AGENT = "codex"
_PYTHONS = ("/app/.venv/bin/python", "/app/backend/.venv/bin/python")


def main() -> int:
    for python in _PYTHONS:
        if os.path.isfile(python):
            backend_root = os.path.dirname(os.path.dirname(os.path.dirname(python)))
            env = {**os.environ, "PYTHONPATH": backend_root}
            argv = [python, "-m", "app.services.sandbox.wrapper_cli", _AGENT, *sys.argv[1:]]
            os.execve(python, argv, env)
    print(f"heym-{_AGENT}-docker: the backend virtualenv was not found", file=sys.stderr)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rewrite `docker/heym-opencode-docker`**

Same file with `_AGENT = "opencode"` and the first docstring line `Run the OpenCode CLI in Heym's sandbox, scoped to one run.`

- [ ] **Step 5: Run the tests**

Run: `PYTEST tests/test_codex_docker_wrapper.py tests/test_sandbox_wrapper_cli.py tests/test_opencode_runner_service.py tests/test_sandbox_docker_parity.py`
Expected: all pass. `test_sandbox_docker_parity.py` no longer loads the old scripts (Task 12 replaced `agent_argv`); delete the now-unused `_load_script` and `_old_wrapper_case` from it.

- [ ] **Step 6: Commit**

```bash
git add docker/heym-codex-docker docker/heym-opencode-docker backend/tests/test_codex_docker_wrapper.py backend/tests/test_sandbox_docker_parity.py
git commit -m "fix(sandbox): codex and opencode runners mount only their own run"
```

## Task 15: Advisory test for the run scope

**Files:**
- Create: `backend/tests/test_advisory_coding_agent_run_scope.py`

- [ ] **Step 1: Write the test**

```python
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
                        agent_spec(profile, scope, [], env, image="i", name="n", kubernetes=False, cwd=root / RUN)
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
```

- [ ] **Step 2: Run it**

Run: `PYTEST tests/test_advisory_coding_agent_run_scope.py`
Expected: `2 passed`.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_advisory_coding_agent_run_scope.py
git commit -m "test(advisory): coding agent runs see only their own workspace"
```

## Task 16: Live Docker check and Milestone 2 gate

- [ ] **Step 1: Build the backend image with the new shims**

Run from the repo root: `docker compose build backend && docker compose up -d postgres backend`
Expected: backend healthy (`curl -s localhost:10105/api/health` returns JSON).

- [ ] **Step 2: Prove the scope inside the real container**

```bash
docker compose exec backend sh -c '
  set -e
  root=/app/data/codex-workspaces
  for id in aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; do
    mkdir -p $root/$id $root/$id.codex-home && echo secret-$id > $root/$id.codex-home/auth.json
  done
  cd $root/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  CODEX_HOME=$root/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.codex-home HEYM_CODEX_DOCKER_ENTRYPOINT=sh \
    heym-codex-docker -c "ls -a $root; cat $root/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.codex-home/auth.json || echo BLOCKED"
  rm -rf $root/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa* $root/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb*
'
```

Expected: the listing shows only `aaaa…` and `aaaa….codex-home` (plus `.` and `..`), then `BLOCKED`. Repeat with `heym-opencode-docker`, `HOME=<root>/<id>.oc-home`, `HEYM_OPENCODE_DOCKER_ENTRYPOINT=sh` and the `/app/data/opencode-workspaces` root.

- [ ] **Step 3: Full check**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`
Expected: green.

- [ ] **Step 4: Commit any formatting**

```bash
git add -A backend docker && git commit -m "style: ruff format" || true
```

---

# Milestone 3: Kubernetes backend for sites without a workspace

All modules in this milestone live under `backend/app/services/sandbox/kubernetes/` and import neither `app.config` nor anything that does.

## Task 17: `config.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/config.py`
- Test: `backend/tests/test_sandbox_k8s_config.py`

- [ ] **Step 1: Write the failing test**

```python
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.sandbox.kubernetes import config as kube_config
from app.services.sandbox.kubernetes.config import (
    KubeConfig,
    KubeConfigError,
    load_in_cluster,
    load_kubeconfig,
)


def _sa_dir() -> Path:
    path = Path(tempfile.mkdtemp())
    (path / "token").write_text("token-1")
    (path / "namespace").write_text("heym")
    (path / "ca.crt").write_text("unused-in-these-tests")
    return path


class InClusterTest(unittest.TestCase):
    def test_reads_service_env_and_serviceaccount_files(self) -> None:
        sa = _sa_dir()
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "KUBERNETES_SERVICE_PORT": "443"}
        with patch.object(kube_config, "SA_DIR", sa), patch.dict(os.environ, env, clear=True):
            config = load_in_cluster()
        self.assertEqual(config.server, "https://10.0.0.1:443")
        self.assertEqual((config.namespace, config.own_namespace), ("heym", "heym"))
        self.assertTrue(config.in_cluster)
        self.assertEqual(config.bearer_token(), "token-1")
        (sa / "token").write_text("token-2")
        self.assertEqual(config.bearer_token(), "token-2")

    def test_sandbox_namespace_override_and_ipv6(self) -> None:
        env = {
            "KUBERNETES_SERVICE_HOST": "fd00::1",
            "KUBERNETES_SERVICE_PORT": "6443",
            "HEYM_SANDBOX_K8S_NAMESPACE": "heym-sandbox",
        }
        with patch.object(kube_config, "SA_DIR", _sa_dir()), patch.dict(os.environ, env, clear=True):
            config = load_in_cluster()
        self.assertEqual(config.server, "https://[fd00::1]:6443")
        self.assertEqual((config.namespace, config.own_namespace), ("heym-sandbox", "heym"))

    def test_round_trips_through_a_dict(self) -> None:
        config = KubeConfig(server="https://x", namespace="a", own_namespace="b", in_cluster=False, token="t")
        self.assertEqual(KubeConfig.from_dict(config.to_dict()), config)


class KubeconfigTest(unittest.TestCase):
    def _write(self, user: dict, cluster_extra: dict | None = None) -> str:
        import yaml

        data = {
            "current-context": "dev",
            "contexts": [{"name": "dev", "context": {"cluster": "c", "user": "u", "namespace": "ns"}}],
            "clusters": [{"name": "c", "cluster": {"server": "https://127.0.0.1:26443/",
                                                   **(cluster_extra or {})}}],
            "users": [{"name": "u", "user": user}],
        }
        path = Path(tempfile.mkdtemp()) / "config"
        path.write_text(yaml.safe_dump(data))
        return str(path)

    def test_client_certificate_data(self) -> None:
        cert = base64.b64encode(b"CERT").decode()
        key = base64.b64encode(b"KEY").decode()
        path = self._write({"client-certificate-data": cert, "client-key-data": key})
        with patch.dict(os.environ, {}, clear=True):
            config = load_kubeconfig(path)
        self.assertEqual(config.server, "https://127.0.0.1:26443")
        self.assertEqual((config.client_cert_data, config.client_key_data), ("CERT", "KEY"))
        self.assertEqual(config.namespace, "ns")
        self.assertFalse(config.in_cluster)

    def test_plugins_and_insecure_tls_are_refused(self) -> None:
        with self.assertRaisesRegex(KubeConfigError, "plugins"):
            load_kubeconfig(self._write({"exec": {"command": "aws"}}))
        with self.assertRaisesRegex(KubeConfigError, "TLS"):
            load_kubeconfig(self._write({"token": "t"}, {"insecure-skip-tls-verify": True}))
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_config.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `config.py`**

```python
"""Where the Kubernetes API is and how to authenticate to it.

In a pod: the ServiceAccount token, CA and namespace files plus
``KUBERNETES_SERVICE_HOST``/``PORT``. Out of a cluster (only when
``HEYM_SANDBOX_BACKEND=kubernetes`` is forced, for development and live tests): a
kubeconfig with static credentials. Credential plugins are refused.
"""

from __future__ import annotations

import base64
import os
import ssl
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
NAMESPACE_ENV = "HEYM_SANDBOX_K8S_NAMESPACE"


class KubeConfigError(RuntimeError):
    """The API endpoint or credentials cannot be used. Callers fail closed."""


@dataclass(frozen=True)
class KubeConfig:
    """API endpoint, credentials, and the namespaces involved."""

    server: str
    namespace: str
    own_namespace: str
    in_cluster: bool
    ca_file: str | None = None
    ca_data: str | None = None
    token_file: str | None = None
    token: str | None = None
    client_cert_data: str | None = None
    client_key_data: str | None = None

    def bearer_token(self) -> str | None:
        """The bearer token, re-read from disk each time because bound tokens rotate."""
        if self.token_file:
            return Path(self.token_file).read_text(encoding="utf-8").strip()
        return self.token

    def ssl_context(self) -> ssl.SSLContext:
        """TLS context trusting the cluster CA, with the client certificate if any."""
        context = ssl.create_default_context(cafile=self.ca_file, cadata=self.ca_data)
        if self.client_cert_data and self.client_key_data:
            with tempfile.TemporaryDirectory() as tmp:
                cert = Path(tmp) / "client.crt"
                key = Path(tmp) / "client.key"
                cert.write_text(self.client_cert_data, encoding="utf-8")
                key.write_text(self.client_key_data, encoding="utf-8")
                os.chmod(key, 0o600)
                context.load_cert_chain(str(cert), str(key))
        return context

    def to_dict(self) -> dict[str, Any]:
        """Plain dict, for handing the config to the bridge process."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KubeConfig:
        """Inverse of :meth:`to_dict`."""
        return cls(**data)


def in_cluster_available() -> bool:
    """True inside a pod that has a ServiceAccount token mounted."""
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST")) and (SA_DIR / "token").is_file()


def _sandbox_namespace(default: str) -> str:
    return (os.environ.get(NAMESPACE_ENV) or "").strip() or default


def load_in_cluster() -> KubeConfig:
    """Config from the pod's ServiceAccount."""
    host = (os.environ.get("KUBERNETES_SERVICE_HOST") or "").strip()
    port = (os.environ.get("KUBERNETES_SERVICE_PORT") or "").strip() or "443"
    if not host or not (SA_DIR / "token").is_file():
        raise KubeConfigError("not running inside a Kubernetes pod with a ServiceAccount token")
    if ":" in host:
        host = f"[{host}]"
    own = (SA_DIR / "namespace").read_text(encoding="utf-8").strip()
    return KubeConfig(
        server=f"https://{host}:{port}",
        namespace=_sandbox_namespace(own),
        own_namespace=own,
        in_cluster=True,
        ca_file=str(SA_DIR / "ca.crt"),
        token_file=str(SA_DIR / "token"),
    )


def _named(items: object, name: object, kind: str) -> dict[str, Any]:
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("name") == name:
            value = item.get(kind)
            return value if isinstance(value, dict) else {}
    raise KubeConfigError(f"kubeconfig has no {kind} named {name!r}")


def _decoded(value: object) -> str | None:
    return base64.b64decode(str(value)).decode("utf-8") if value else None


def _file(value: object) -> str | None:
    return Path(str(value)).read_text(encoding="utf-8") if value else None


def load_kubeconfig(path: str | None = None) -> KubeConfig:
    """Config from the current context of a kubeconfig (token or client certificate)."""
    try:
        import yaml
    except ImportError as exc:
        raise KubeConfigError("reading a kubeconfig needs PyYAML") from exc
    raw = path or (os.environ.get("KUBECONFIG") or "").split(os.pathsep)[0]
    config_path = Path(raw) if raw else Path.home() / ".kube" / "config"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise KubeConfigError(f"cannot read kubeconfig {config_path}: {exc}") from exc
    context = _named(data.get("contexts"), data.get("current-context"), "context")
    cluster = _named(data.get("clusters"), context.get("cluster"), "cluster")
    user = _named(data.get("users"), context.get("user"), "user")
    if cluster.get("insecure-skip-tls-verify"):
        raise KubeConfigError("the kubeconfig disables TLS verification; refusing to use it")
    if "exec" in user or "auth-provider" in user:
        raise KubeConfigError(
            "kubeconfig credential plugins (exec, auth-provider) are not supported; "
            "use a token or a client certificate"
        )
    token = user.get("token") or (_file(user.get("tokenFile")) or "").strip() or None
    cert = _decoded(user.get("client-certificate-data")) or _file(user.get("client-certificate"))
    key = _decoded(user.get("client-key-data")) or _file(user.get("client-key"))
    if not token and not (cert and key):
        raise KubeConfigError("the kubeconfig user has neither a token nor a client certificate")
    namespace = str(context.get("namespace") or "default")
    return KubeConfig(
        server=str(cluster.get("server") or "").rstrip("/"),
        namespace=_sandbox_namespace(namespace),
        own_namespace=namespace,
        in_cluster=False,
        ca_file=cluster.get("certificate-authority"),
        ca_data=_decoded(cluster.get("certificate-authority-data")),
        token=token,
        client_cert_data=cert,
        client_key_data=key,
    )
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_config.py`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes backend/tests/test_sandbox_k8s_config.py
git commit -m "feat(sandbox): kubernetes api config from serviceaccount or kubeconfig"
```

## Task 18: `client.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/client.py`
- Test: `backend/tests/test_sandbox_k8s_client.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import unittest

import httpx

from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig

CONFIG = KubeConfig(server="https://k8s:443", namespace="sb", own_namespace="heym", in_cluster=True, token="t")


def _client(handler) -> tuple[KubeClient, list[httpx.Request]]:  # noqa: ANN001
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return KubeClient(CONFIG, transport=httpx.MockTransport(record)), seen


class ClientTest(unittest.TestCase):
    def test_create_pod_posts_with_bearer_token(self) -> None:
        client, seen = _client(lambda r: httpx.Response(201, json={"metadata": {"name": "p"}}))
        client.create_pod({"metadata": {"name": "p"}})
        self.assertEqual(seen[0].method, "POST")
        self.assertEqual(seen[0].url.path, "/api/v1/namespaces/sb/pods")
        self.assertEqual(seen[0].headers["Authorization"], "Bearer t")

    def test_get_missing_pod_is_none_and_own_namespace_is_explicit(self) -> None:
        client, seen = _client(lambda r: httpx.Response(404, json={"message": "nope"}))
        self.assertIsNone(client.get_pod("p", namespace="heym"))
        self.assertEqual(seen[0].url.path, "/api/v1/namespaces/heym/pods/p")

    def test_delete_is_immediate_and_tolerates_404(self) -> None:
        client, seen = _client(lambda r: httpx.Response(404))
        client.delete_pod("p")
        self.assertEqual(seen[0].url.params["gracePeriodSeconds"], "0")

    def test_errors_carry_the_api_message(self) -> None:
        client, _ = _client(lambda r: httpx.Response(403, json={"message": "forbidden: pods"}))
        with self.assertRaisesRegex(KubeApiError, "403.*forbidden: pods"):
            client.create_pod({})

    def test_can_i(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            allowed = body["spec"]["resourceAttributes"]["subresource"] == "attach"
            return httpx.Response(201, json={"status": {"allowed": allowed}})

        client, _ = _client(handler)
        self.assertTrue(client.can_i("create", "pods", "attach"))
        self.assertFalse(client.can_i("create", "pods"))

    def test_server_version_strips_plus(self) -> None:
        client, _ = _client(lambda r: httpx.Response(200, json={"major": "1", "minor": "30+"}))
        self.assertEqual(client.server_version(), (1, 30))

    def test_attach_url(self) -> None:
        client, _ = _client(lambda r: httpx.Response(200))
        self.assertEqual(
            client.attach_url("p"),
            "wss://k8s:443/api/v1/namespaces/sb/pods/p/attach"
            "?container=sandbox&stdin=true&stdout=true&stderr=true",
        )
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_client.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `client.py`**

```python
"""A small synchronous Kubernetes API client. Only the calls the sandbox needs."""

from __future__ import annotations

import ssl
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.services.sandbox.kubernetes.config import KubeConfig

CONTAINER = "sandbox"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class KubeApiError(RuntimeError):
    """The API server refused a request."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Kubernetes API {status}: {message}")
        self.status = status


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or response.text)[:500]
    except ValueError:
        return response.text[:500]


class KubeClient:
    """REST calls against one namespace, authenticated as the backend's ServiceAccount."""

    def __init__(self, config: KubeConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        verify: ssl.SSLContext | bool = True if transport is not None else config.ssl_context()
        # trust_env=False: API calls never go through an HTTP proxy from the environment.
        self._http = httpx.Client(
            base_url=config.server,
            verify=verify,
            transport=transport,
            timeout=_TIMEOUT,
            trust_env=False,
        )

    @property
    def namespace(self) -> str:
        """The namespace sandbox pods live in."""
        return self.config.namespace

    def _headers(self) -> dict[str, str]:
        token = self.config.bearer_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> Any:
        """One API call; JSON bodies come back parsed, text bodies as ``str``."""
        response = self._http.request(method, path, json=json, params=params, headers=self._headers())
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code >= 400:
            raise KubeApiError(response.status_code, _message(response))
        if not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    def _pods(self, namespace: str | None = None) -> str:
        return f"/api/v1/namespaces/{quote(namespace or self.namespace)}/pods"

    def create_pod(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Create a pod in the sandbox namespace."""
        return self.request("POST", self._pods(), json=manifest)

    def get_pod(self, name: str, namespace: str | None = None) -> dict[str, Any] | None:
        """The pod, or None when it does not exist."""
        return self.request("GET", f"{self._pods(namespace)}/{quote(name)}", allow_404=True)

    def delete_pod(self, name: str) -> None:
        """Delete now (grace period 0). A missing pod is not an error."""
        self.request(
            "DELETE", f"{self._pods()}/{quote(name)}", params={"gracePeriodSeconds": "0"}, allow_404=True
        )

    def list_pods(self, label_selector: str) -> list[dict[str, Any]]:
        """Pods in the sandbox namespace matching ``label_selector``."""
        result = self.request("GET", self._pods(), params={"labelSelector": label_selector})
        return list((result or {}).get("items") or [])

    def pod_log(self, name: str) -> str:
        """The sandbox container's log (stdout and stderr merged)."""
        log = self.request(
            "GET", f"{self._pods()}/{quote(name)}/log", params={"container": CONTAINER}, allow_404=True
        )
        return log if isinstance(log, str) else ""

    def get_pvc(self, name: str) -> dict[str, Any] | None:
        """A PersistentVolumeClaim in the sandbox namespace, or None."""
        return self.request(
            "GET",
            f"/api/v1/namespaces/{quote(self.namespace)}/persistentvolumeclaims/{quote(name)}",
            allow_404=True,
        )

    def can_i(self, verb: str, resource: str, subresource: str = "") -> bool:
        """SelfSubjectAccessReview for ``verb resource[/subresource]`` in the sandbox namespace."""
        review = {
            "apiVersion": "authorization.k8s.io/v1",
            "kind": "SelfSubjectAccessReview",
            "spec": {
                "resourceAttributes": {
                    "namespace": self.namespace,
                    "verb": verb,
                    "resource": resource,
                    "subresource": subresource,
                }
            },
        }
        result = self.request(
            "POST", "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", json=review
        )
        return bool(((result or {}).get("status") or {}).get("allowed"))

    def has_api_group(self, group: str) -> bool:
        """True when the API server serves ``group`` (discovery needs no extra RBAC)."""
        return self.request("GET", f"/apis/{group}", allow_404=True) is not None

    def server_version(self) -> tuple[int, int]:
        """``(major, minor)`` of the API server."""
        info = self.request("GET", "/version") or {}
        major = str(info.get("major") or "0").rstrip("+") or "0"
        minor = str(info.get("minor") or "0").rstrip("+") or "0"
        return int(major), int(minor)

    def attach_url(self, name: str) -> str:
        """Websocket URL attaching stdin, stdout and stderr of the sandbox container."""
        base = self.config.server.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        query = urlencode({"container": CONTAINER, "stdin": "true", "stdout": "true", "stderr": "true"})
        return f"{base}{self._pods()}/{quote(name)}/attach?{query}"

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._http.close()
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_client.py`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/client.py backend/tests/test_sandbox_k8s_client.py
git commit -m "feat(sandbox): minimal kubernetes api client"
```

## Task 19: `attach.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/attach.py`
- Test: `backend/tests/test_sandbox_k8s_attach.py`

- [ ] **Step 1: Check the websockets API this module relies on**

Run: `cd backend && uv run python -c "import inspect, websockets.sync.client as c; p = inspect.signature(c.connect).parameters; print(all(k in p for k in ('proxy', 'additional_headers', 'subprotocols', 'max_size', 'ping_interval')))"`
Expected: `True`.

- [ ] **Step 2: Write the failing test**

```python
import json
import threading
import time
import unittest

from websockets.sync.server import serve

from app.services.sandbox.kubernetes.attach import (
    SUBPROTOCOL,
    exchange,
    exit_code_from_status,
    open_attach,
)
from app.services.sandbox.kubernetes.client import KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig

_FAILURE = {
    "status": "Failure",
    "reason": "NonZeroExitCode",
    "details": {"causes": [{"reason": "ExitCode", "message": "3"}]},
}


def _echo_server(handler_log: list[str]):  # noqa: ANN202
    def handler(connection) -> None:  # noqa: ANN001
        handler_log.append(connection.subprotocol or "")
        data = b""
        while True:
            message = connection.recv()
            if message[0] == 0:
                data += message[1:]
            elif message[:2] == bytes([255, 0]):
                break
        connection.send(bytes([1]) + b"out:" + data)
        connection.send(bytes([2]) + b"err")
        connection.send(bytes([3]) + json.dumps(_FAILURE).encode())
        connection.close()

    server = serve(handler, "127.0.0.1", 0, subprotocols=[SUBPROTOCOL])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class AttachTest(unittest.TestCase):
    def test_stdin_eof_reaches_the_server_and_channels_split(self) -> None:
        log: list[str] = []
        server = _echo_server(log)
        self.addCleanup(server.shutdown)
        port = server.socket.getsockname()[1]
        config = KubeConfig(
            server=f"http://127.0.0.1:{port}", namespace="sb", own_namespace="sb", in_cluster=False
        )
        session = open_attach(KubeClient(config), "p")
        out, err, code = exchange(session, b"hello", time.monotonic() + 5)
        session.close()
        self.assertEqual(log, [SUBPROTOCOL])
        self.assertEqual((out, err, code), (b"out:hello", b"err", 3))

    def test_status_parsing(self) -> None:
        self.assertEqual(exit_code_from_status(b'{"status": "Success"}'), 0)
        self.assertEqual(exit_code_from_status(json.dumps(_FAILURE).encode()), 3)
        self.assertIsNone(exit_code_from_status(b"not json"))
```

- [ ] **Step 3: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_attach.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Write `attach.py`**

```python
"""The ``v5.channel.k8s.io`` attach protocol over a websocket.

Every binary message starts with a channel byte: 0 stdin, 1 stdout, 2 stderr,
3 status (a JSON ``metav1.Status``), 255 close. The close message, new in v5, is
the only way to give the container's stdin EOF, which every Heym runner waits for.
"""

from __future__ import annotations

import json
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from app.services.sandbox.kubernetes.client import KubeClient

SUBPROTOCOL = "v5.channel.k8s.io"
STDIN, STDOUT, STDERR, STATUS, CLOSE = 0, 1, 2, 3, 255
_CHUNK = 32 * 1024


class AttachSession:
    """One attached container: send stdin, receive ``(channel, payload)`` frames."""

    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    def send_stdin(self, data: bytes) -> None:
        """Write to the container's stdin."""
        for start in range(0, len(data), _CHUNK):
            self._connection.send(bytes([STDIN]) + data[start : start + _CHUNK])

    def close_stdin(self) -> None:
        """Give the container's stdin EOF."""
        self._connection.send(bytes([CLOSE, STDIN]))

    def receive(self, timeout: float | None) -> tuple[int, bytes] | None:
        """The next frame, None once the server closed the stream. Raises TimeoutError."""
        try:
            message = self._connection.recv(timeout=timeout)
        except ConnectionClosed:
            return None
        if isinstance(message, str):
            message = message.encode("utf-8")
        if not message:
            return (-1, b"")
        return message[0], message[1:]

    def close(self) -> None:
        """Close the websocket."""
        self._connection.close()


def open_attach(client: KubeClient, pod_name: str) -> AttachSession:
    """Attach to the sandbox container of ``pod_name``."""
    url = client.attach_url(pod_name)
    token = client.config.bearer_token()
    connection = connect(
        url,
        ssl=client.config.ssl_context() if url.startswith("wss://") else None,
        additional_headers={"Authorization": f"Bearer {token}"} if token else None,
        subprotocols=[SUBPROTOCOL],
        max_size=None,
        open_timeout=30,
        ping_interval=None,
        proxy=None,
    )
    if connection.subprotocol != SUBPROTOCOL:
        connection.close()
        raise RuntimeError(
            f"the API server did not accept {SUBPROTOCOL}; Kubernetes 1.30 or newer is required"
        )
    return AttachSession(connection)


def exit_code_from_status(payload: bytes) -> int | None:
    """Exit code from a channel-3 ``metav1.Status`` message, if it carries one."""
    try:
        status = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(status, dict):
        return None
    if status.get("status") == "Success":
        return 0
    for cause in (status.get("details") or {}).get("causes") or []:
        if isinstance(cause, dict) and cause.get("reason") == "ExitCode":
            try:
                return int(cause.get("message"))
            except (TypeError, ValueError):
                return None
    return None


def exchange(
    session: AttachSession, stdin: bytes | None, deadline: float
) -> tuple[bytes, bytes, int | None]:
    """Send ``stdin`` then EOF; collect stdout, stderr and the status exit code.

    Raises TimeoutError when ``deadline`` (``time.monotonic()``) passes.
    """
    if stdin:
        session.send_stdin(stdin)
    session.close_stdin()
    out, err = bytearray(), bytearray()
    code: int | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        frame = session.receive(timeout=remaining)
        if frame is None:
            return bytes(out), bytes(err), code
        channel, payload = frame
        if channel == STDOUT:
            out.extend(payload)
        elif channel == STDERR:
            err.extend(payload)
        elif channel == STATUS:
            code = exit_code_from_status(payload)
```

- [ ] **Step 5: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_attach.py`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/attach.py backend/tests/test_sandbox_k8s_attach.py
git commit -m "feat(sandbox): kubernetes attach over v5.channel.k8s.io"
```

## Task 20: `lifecycle.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/lifecycle.py`
- Test: `backend/tests/test_sandbox_k8s_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from unittest.mock import MagicMock

from app.services.sandbox.kubernetes.lifecycle import wait_started, wait_terminated


def _pod(state: dict | None = None, phase: str = "Pending", conditions: list | None = None) -> dict:
    statuses = [{"name": "sandbox", "state": state}] if state is not None else []
    return {"status": {"phase": phase, "containerStatuses": statuses, "conditions": conditions or []}}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _client(*pods: dict | None) -> MagicMock:
    client = MagicMock()
    client.get_pod.side_effect = list(pods)
    return client


class WaitStartedTest(unittest.TestCase):
    def _wait(self, client: MagicMock, timeout: float = 120.0):  # noqa: ANN202
        clock = _Clock()
        return wait_started(client, "p", timeout=timeout, sleep=clock.sleep, clock=clock)

    def test_running_after_creating(self) -> None:
        client = _client(_pod({"waiting": {"reason": "ContainerCreating"}}), _pod({"running": {}}))
        self.assertEqual(self._wait(client).state, "running")

    def test_image_pull_failure_is_a_start_failure(self) -> None:
        client = _client(_pod({"waiting": {"reason": "ImagePullBackOff", "message": "no such image"}}))
        start = self._wait(client)
        self.assertEqual(start.state, "failed")
        self.assertIn("ImagePullBackOff", start.reason)

    def test_start_error_is_a_start_failure(self) -> None:
        client = _client(_pod({"terminated": {"reason": "StartError", "exitCode": 128}}))
        self.assertEqual(self._wait(client).state, "failed")

    def test_finished_before_attach(self) -> None:
        client = _client(_pod({"terminated": {"reason": "Completed", "exitCode": 0}}))
        self.assertEqual(self._wait(client).state, "terminated")

    def test_unschedulable_times_out_with_the_reason(self) -> None:
        unschedulable = _pod(conditions=[{"type": "PodScheduled", "status": "False",
                                          "reason": "Unschedulable", "message": "0/1 nodes"}])
        client = MagicMock()
        client.get_pod.return_value = unschedulable
        start = self._wait(client, timeout=1.0)
        self.assertEqual(start.state, "failed")
        self.assertIn("Unschedulable", start.reason)


class WaitTerminatedTest(unittest.TestCase):
    def test_exit_code_and_oom(self) -> None:
        clock = _Clock()
        done = wait_terminated(
            _client(_pod({"running": {}}), _pod({"terminated": {"exitCode": 3}})), "p",
            sleep=clock.sleep, clock=clock,
        )
        self.assertEqual(done.code, 3)
        oom = wait_terminated(
            _client(_pod({"terminated": {"exitCode": 1, "reason": "OOMKilled"}})), "p",
            sleep=clock.sleep, clock=clock,
        )
        self.assertEqual(oom.code, 137)
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_lifecycle.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `lifecycle.py`**

```python
"""Waiting for a sandbox pod to start and to finish."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.sandbox.kubernetes.client import CONTAINER, KubeClient
from app.services.sandbox.spec import OOM_RETURNCODE

STARTUP_TIMEOUT_SECONDS = 120.0
_POLL_SECONDS = 0.25
_FAILED_WAITING = frozenset(
    {
        "ErrImagePull",
        "ImagePullBackOff",
        "InvalidImageName",
        "ErrImageNeverPull",
        "CreateContainerConfigError",
        "CreateContainerError",
        "RunContainerError",
    }
)
_FAILED_TERMINATED = frozenset({"StartError", "ContainerCannotRun"})


@dataclass(frozen=True)
class PodStart:
    """``running``, ``terminated`` (finished before attach) or ``failed`` (never started)."""

    state: str
    reason: str = ""


@dataclass(frozen=True)
class PodExit:
    """Exit code of the sandbox container; None when it could not be read."""

    code: int | None
    reason: str = ""


def _state(pod: dict[str, Any]) -> dict[str, Any]:
    for status in (pod.get("status") or {}).get("containerStatuses") or []:
        if status.get("name") == CONTAINER:
            return status.get("state") or {}
    return {}


def wait_started(
    client: KubeClient,
    name: str,
    *,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PodStart:
    """Poll until the container runs, finishes, or provably cannot start."""
    deadline = clock() + timeout
    last_reason = "the pod was not scheduled"
    while clock() < deadline:
        pod = client.get_pod(name)
        if pod is None:
            return PodStart("failed", "the pod disappeared before it started")
        state = _state(pod)
        if "running" in state:
            return PodStart("running")
        terminated = state.get("terminated")
        if terminated is not None:
            reason = str(terminated.get("reason") or "")
            if reason in _FAILED_TERMINATED:
                return PodStart("failed", f"{reason}: {terminated.get('message', '')}".strip())
            return PodStart("terminated")
        waiting = state.get("waiting") or {}
        if waiting.get("reason") in _FAILED_WAITING:
            return PodStart("failed", f"{waiting['reason']}: {waiting.get('message', '')}".strip())
        status = pod.get("status") or {}
        if status.get("phase") == "Failed":
            return PodStart("failed", str(status.get("reason") or "the pod failed"))
        for condition in status.get("conditions") or []:
            if condition.get("type") == "PodScheduled" and condition.get("status") == "False":
                last_reason = (
                    f"{condition.get('reason', 'Unschedulable')}: {condition.get('message', '')}"
                ).strip()
        sleep(_POLL_SECONDS)
    return PodStart("failed", f"the pod did not start within {timeout:.0f} seconds ({last_reason})")


def wait_terminated(
    client: KubeClient,
    name: str,
    *,
    timeout: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PodExit:
    """Poll until the container reports its exit code."""
    deadline = clock() + timeout
    while clock() < deadline:
        pod = client.get_pod(name)
        if pod is None:
            return PodExit(None, "the pod disappeared")
        terminated = _state(pod).get("terminated")
        if terminated is not None:
            reason = str(terminated.get("reason") or "")
            if reason == "OOMKilled":
                return PodExit(OOM_RETURNCODE, reason)
            code = terminated.get("exitCode")
            return PodExit(int(code) if code is not None else None, reason)
        sleep(_POLL_SECONDS)
    return PodExit(None, "the pod did not finish")
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_lifecycle.py`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/lifecycle.py backend/tests/test_sandbox_k8s_lifecycle.py
git commit -m "feat(sandbox): wait for sandbox pods to start and finish"
```

## Task 21: `pod.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/pod.py`
- Test: `backend/tests/test_sandbox_k8s_pod.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.pod import (
    PodContext,
    PodVolume,
    build_pod,
    env_entries,
    parse_overrides,
    quantity,
    run_as,
)
from app.services.sandbox.spec import SandboxSpec, Tmpfs

CTX = PodContext(instance="heym-backend-0")


def _spec(**kwargs) -> SandboxSpec:  # noqa: ANN003
    base = dict(site="pytool", name="heym-pytool-1", image="img", entrypoint="python",
                args=("-c", "x"), tmpfs=(Tmpfs("/tmp", "rw,nosuid", "64m"),), memory="256m", cpus="1")
    base.update(kwargs)
    return SandboxSpec(**base)


class PodTest(unittest.TestCase):
    def test_restricted_baseline(self) -> None:
        pod = build_pod(_spec(), CTX)
        spec = pod["spec"]
        container = spec["containers"][0]
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertFalse(spec["enableServiceLinks"])
        self.assertEqual(spec["restartPolicy"], "Never")
        self.assertEqual(spec["securityContext"]["runAsUser"], 65534)
        self.assertEqual(spec["securityContext"]["seccompProfile"], {"type": "RuntimeDefault"})
        self.assertEqual(container["securityContext"]["capabilities"], {"drop": ["ALL"]})
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["stdin"] and container["stdinOnce"])
        self.assertEqual(container["command"], ["python"])
        self.assertEqual(container["resources"]["limits"], {"memory": "256Mi", "cpu": "1"})
        self.assertEqual(spec["volumes"][0]["emptyDir"], {"medium": "Memory", "sizeLimit": "64Mi"})
        self.assertEqual(pod["metadata"]["labels"]["heym.run/network"], "none")
        self.assertEqual(spec["activeDeadlineSeconds"], 86400)

    def test_privileged_spec_fields_never_reach_the_pod(self) -> None:
        pod = build_pod(
            _spec(user=None, cap_drop_all=False, no_new_privileges=False,
                  docker_extra_args=("--cap-add", "SYS_ADMIN"), network="bridge"),
            CTX,
        )
        container = pod["spec"]["containers"][0]
        self.assertEqual(container["securityContext"]["capabilities"], {"drop": ["ALL"]})
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(pod["spec"]["securityContext"]["runAsUser"], 65534)
        self.assertEqual(pod["metadata"]["labels"]["heym.run/network"], "egress")

    def test_openshift_lets_the_scc_pick_the_uid(self) -> None:
        pod = build_pod(_spec(), PodContext(instance="i", openshift=True))
        self.assertNotIn("runAsUser", pod["spec"]["securityContext"])
        self.assertTrue(pod["spec"]["securityContext"]["runAsNonRoot"])

    def test_start_gate_and_image_default_entrypoint(self) -> None:
        gated = build_pod(_spec(entrypoint="codex", args=("exec",), start_gate=True), CTX)
        self.assertEqual(gated["spec"]["containers"][0]["command"][:3], ["sh", "-c", 'head -c1 >/dev/null; exec "$@"'])
        self.assertEqual(gated["spec"]["containers"][0]["args"], ["exec"])
        plain = build_pod(_spec(entrypoint=None, args=("serve",)), CTX)
        self.assertNotIn("command", plain["spec"]["containers"][0])

    def test_volumes_share_one_claim_and_mount_subpaths(self) -> None:
        pod = build_pod(
            _spec(),
            CTX,
            (PodVolume("data", "codex-workspaces/a", "/w/a", False),
             PodVolume("data", "codex-workspaces/a.codex-home", "/w/a.codex-home", True)),
        )
        claims = [v for v in pod["spec"]["volumes"] if "persistentVolumeClaim" in v]
        self.assertEqual(len(claims), 1)
        mounts = pod["spec"]["containers"][0]["volumeMounts"]
        self.assertIn({"name": "ws-0", "mountPath": "/w/a.codex-home",
                       "subPath": "codex-workspaces/a.codex-home", "readOnly": True}, mounts)

    def test_helpers(self) -> None:
        self.assertEqual([quantity(v) for v in ("512m", "1g", "64k", "1024")], ["512Mi", "1Gi", "64Ki", "1024"])
        self.assertEqual(run_as("1000:2000"), (1000, 2000))
        self.assertEqual(run_as("0:0"), (65534, 65534))
        self.assertEqual(run_as("nobody"), (65534, 65534))
        self.assertEqual(
            env_entries(("A=1", "BARE", "A=2", "B=x=y")),
            [{"name": "A", "value": "2"}, {"name": "B", "value": "x=y"}, {"name": "HOME", "value": "/tmp"}],
        )

    def test_overrides_allow_scheduling_keys_only(self) -> None:
        self.assertEqual(parse_overrides('{"runtimeClassName": "gvisor"}'), {"runtimeClassName": "gvisor"})
        for raw in ('{"hostNetwork": true}', '{"securityContext": {}}', '{"volumes": []}', "[]", "{bad"):
            with self.subTest(raw), self.assertRaises(SandboxConfigError):
                parse_overrides(raw)
        pod = build_pod(_spec(), PodContext(instance="i", overrides={"nodeSelector": {"pool": "sb"}}))
        self.assertEqual(pod["spec"]["nodeSelector"], {"pool": "sb"})
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_pod.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `pod.py`**

```python
"""``SandboxSpec`` -> Pod manifest. Pure: no I/O.

Whatever the spec asks for, the pod is Pod Security ``restricted``: non-root, no
capabilities, no privilege escalation, RuntimeDefault seccomp, and no
ServiceAccount token. Docker-only fields (``docker_extra_args``, ``cap_drop_all``,
``no_new_privileges``) are ignored here on purpose.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.client import CONTAINER
from app.services.sandbox.spec import SandboxSpec

LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
LABEL_SITE = "heym.run/sandbox"
LABEL_NETWORK = "heym.run/network"
LABEL_INSTANCE = "heym.run/instance"
MANAGED_BY = "heym"
DEFAULT_UID = 65534
PROCESS_DEADLINE_SECONDS = 24 * 3600
OVERRIDES_ENV = "HEYM_SANDBOX_K8S_POD_OVERRIDES"
START_GATE_SCRIPT = 'head -c1 >/dev/null; exec "$@"'
_ALLOWED_OVERRIDES = frozenset(
    {"nodeSelector", "tolerations", "runtimeClassName", "imagePullSecrets", "priorityClassName"}
)
_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_SIZE = re.compile(r"(\d+(?:\.\d+)?)([bkmgBKMG]?)")


@dataclass(frozen=True)
class PodVolume:
    """One path inside a PersistentVolumeClaim, mounted at ``target``."""

    claim: str
    sub_path: str
    target: str
    readonly: bool


@dataclass(frozen=True)
class PodContext:
    """Per-backend facts every pod needs."""

    instance: str
    openshift: bool = False
    overrides: dict[str, Any] = field(default_factory=dict, hash=False)
    node_name: str | None = None


def parse_overrides(raw: str | None) -> dict[str, Any]:
    """Validate ``HEYM_SANDBOX_K8S_POD_OVERRIDES``: scheduling keys only."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SandboxConfigError(f"{OVERRIDES_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SandboxConfigError(f"{OVERRIDES_ENV} must be a JSON object")
    refused = sorted(set(data) - _ALLOWED_OVERRIDES)
    if refused:
        raise SandboxConfigError(
            f"{OVERRIDES_ENV} may only set {', '.join(sorted(_ALLOWED_OVERRIDES))}; "
            f"refused: {', '.join(refused)}"
        )
    return data


def quantity(docker_size: str) -> str:
    """Docker size (``512m``, ``1g``, ``64k``, ``1024``) as a Kubernetes quantity."""
    match = _SIZE.fullmatch(docker_size.strip())
    if not match:
        raise SandboxConfigError(f"cannot convert size {docker_size!r} to a Kubernetes quantity")
    number, unit = match.groups()
    return number + {"": "", "b": "", "k": "Ki", "m": "Mi", "g": "Gi"}[unit.lower()]


def run_as(user: str | None) -> tuple[int, int]:
    """``UID[:GID]`` as numbers; anything else, and root, becomes 65534."""
    if not user:
        return DEFAULT_UID, DEFAULT_UID
    uid_text, _, gid_text = user.partition(":")
    try:
        uid = int(uid_text)
        gid = int(gid_text) if gid_text else uid
    except ValueError:
        return DEFAULT_UID, DEFAULT_UID
    if uid <= 0 or gid <= 0:
        return DEFAULT_UID, DEFAULT_UID
    return uid, gid


def env_entries(items: tuple[str, ...]) -> list[dict[str, str]]:
    """``KEY=value`` items as pod env. Bare keys are dropped and the last value wins, as in Docker."""
    values: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            continue
        values.pop(key, None)
        values[key] = value
    if "HOME" not in values:
        values["HOME"] = "/tmp"
    return [{"name": key, "value": value} for key, value in values.items()]


def _label(value: str) -> str:
    return _LABEL_UNSAFE.sub("-", value)[:63].strip("-.") or "unknown"


def _command(spec: SandboxSpec) -> tuple[list[str] | None, list[str]]:
    if spec.start_gate:
        if spec.entrypoint is None:
            raise SandboxConfigError("a start gate needs an explicit entrypoint")
        return ["sh", "-c", START_GATE_SCRIPT, "--", spec.entrypoint], list(spec.args)
    if spec.entrypoint is None:
        return None, list(spec.args)
    return [spec.entrypoint], list(spec.args)


def _resources(spec: SandboxSpec) -> dict[str, dict[str, str]]:
    limits: dict[str, str] = {}
    requests: dict[str, str] = {}
    if spec.memory:
        limits["memory"] = requests["memory"] = quantity(spec.memory)
    if spec.cpus:
        limits["cpu"] = spec.cpus
        requests["cpu"] = "100m"
    return {"limits": limits, "requests": requests} if limits else {}


def build_pod(
    spec: SandboxSpec, ctx: PodContext, volumes: tuple[PodVolume, ...] = ()
) -> dict[str, Any]:
    """The Pod manifest for ``spec``."""
    uid, gid = run_as(spec.user)
    pod_security: dict[str, Any] = {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}
    if not ctx.openshift:
        pod_security.update(runAsUser=uid, runAsGroup=gid)

    pod_volumes: list[dict[str, Any]] = []
    mounts: list[dict[str, Any]] = []
    for index, tmpfs in enumerate(spec.tmpfs):
        name = f"tmpfs-{index}"
        pod_volumes.append({"name": name, "emptyDir": {"medium": "Memory", "sizeLimit": quantity(tmpfs.size)}})
        mounts.append({"name": name, "mountPath": tmpfs.path})
    if spec.shm_size:
        pod_volumes.append({"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": quantity(spec.shm_size)}})
        mounts.append({"name": "shm", "mountPath": "/dev/shm"})
    claims: dict[str, str] = {}
    for volume in volumes:
        name = claims.get(volume.claim)
        if name is None:
            name = f"ws-{len(claims)}"
            claims[volume.claim] = name
            pod_volumes.append({"name": name, "persistentVolumeClaim": {"claimName": volume.claim}})
        mount: dict[str, Any] = {"name": name, "mountPath": volume.target}
        if volume.sub_path:
            mount["subPath"] = volume.sub_path
        mount["readOnly"] = volume.readonly
        mounts.append(mount)

    command, args = _command(spec)
    container: dict[str, Any] = {
        "name": CONTAINER,
        "image": spec.image,
        "imagePullPolicy": "IfNotPresent",
        "stdin": True,
        "stdinOnce": True,
        "tty": False,
        "env": env_entries(spec.env),
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": spec.read_only_root,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "volumeMounts": mounts,
    }
    if command is not None:
        container["command"] = command
    if args:
        container["args"] = args
    if spec.workdir:
        container["workingDir"] = spec.workdir
    resources = _resources(spec)
    if resources:
        container["resources"] = resources

    deadline = spec.deadline_seconds or PROCESS_DEADLINE_SECONDS
    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "activeDeadlineSeconds": int(math.ceil(deadline)),
        "securityContext": pod_security,
        "containers": [container],
        "volumes": pod_volumes,
    }
    pod_spec.update(ctx.overrides)
    if ctx.node_name:
        pod_spec["nodeName"] = ctx.node_name
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": spec.name,
            "labels": {
                LABEL_MANAGED_BY: MANAGED_BY,
                LABEL_SITE: _label(spec.site),
                LABEL_NETWORK: "none" if spec.offline else "egress",
                LABEL_INSTANCE: _label(ctx.instance),
            },
        },
        "spec": pod_spec,
    }
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_pod.py`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/pod.py backend/tests/test_sandbox_k8s_pod.py
git commit -m "feat(sandbox): render sandbox specs as restricted pods"
```

## Task 22: `network.py` (offline canary)

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/network.py`
- Test: `backend/tests/test_sandbox_k8s_network.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from unittest.mock import MagicMock

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.network import OfflineCheck
from app.services.sandbox.spec import SandboxResult


class OfflineCheckTest(unittest.TestCase):
    def test_enforced_policy_is_checked_once(self) -> None:
        run = MagicMock(return_value=SandboxResult(0, "", ""))
        check = OfflineCheck(run)
        check.ensure("img")
        check.ensure("img")
        run.assert_called_once()
        spec = run.call_args.args[0]
        self.assertTrue(spec.offline)
        self.assertEqual(spec.image, "img")

    def test_open_network_fails_closed_every_time(self) -> None:
        run = MagicMock(return_value=SandboxResult(1, "", ""))
        check = OfflineCheck(run)
        for _ in range(2):
            with self.assertRaisesRegex(SandboxConfigError, "NetworkPolicy"):
                check.ensure("img")
        self.assertEqual(run.call_count, 2)

    def test_a_canary_that_did_not_run_fails_closed(self) -> None:
        check = OfflineCheck(MagicMock(return_value=SandboxResult(125, "", "ImagePullBackOff")))
        with self.assertRaisesRegex(SandboxConfigError, "did not run"):
            check.ensure("img")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_network.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `network.py`**

```python
"""Prove that pods labeled ``heym.run/network=none`` really have no network.

On Kubernetes "no network" is a NetworkPolicy, and a policy does nothing on a CNI
that does not enforce it. Before the first offline sandbox, a canary pod with the
same label tries to reach the API server and the internet. Any connection means the
policy is missing or not enforced, and offline sandboxes fail closed.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.spec import SandboxResult, SandboxSpec, Tmpfs

CANARY_SCRIPT = (
    "import os,socket,sys\n"
    "targets=[(os.environ.get('KUBERNETES_SERVICE_HOST',''),"
    "int(os.environ.get('KUBERNETES_SERVICE_PORT') or 443)),('1.1.1.1',443)]\n"
    "for host,port in targets:\n"
    "    if not host:\n"
    "        continue\n"
    "    try:\n"
    "        socket.create_connection((host,port),timeout=3).close()\n"
    "    except OSError:\n"
    "        continue\n"
    "    sys.exit(1)\n"
    "sys.exit(0)\n"
)
_CANARY_TIMEOUT_SECONDS = 30.0

Runner = Callable[[SandboxSpec, str | None, float], SandboxResult]


class OfflineCheck:
    """Runs the canary once per process; a failure is retried on the next offline run."""

    def __init__(self, run: Runner) -> None:
        self._run = run
        self._verified = False
        self._lock = threading.Lock()

    def ensure(self, image: str) -> None:
        """Return when offline pods are offline; raise SandboxConfigError otherwise."""
        with self._lock:
            if self._verified:
                return
            spec = SandboxSpec(
                site="network-canary",
                name=f"heym-netcheck-{uuid.uuid4().hex}",
                image=image,
                entrypoint="python",
                args=("-c", CANARY_SCRIPT),
                network="none",
                tmpfs=(Tmpfs("/tmp", "rw,nosuid", "16m"),),
                memory="64m",
                cpus="0.5",
            )
            result = self._run(spec, None, _CANARY_TIMEOUT_SECONDS)
            if result.returncode == 0:
                self._verified = True
                return
            if result.returncode == 1:
                raise SandboxConfigError(
                    "Sandbox pods labeled heym.run/network=none can still open network "
                    "connections, so the NetworkPolicy that denies their egress is missing or "
                    "not enforced. Apply deploy/kubernetes/base/networkpolicies.yaml on a CNI "
                    "that enforces NetworkPolicy; offline sandboxes stay off until then."
                )
            raise SandboxConfigError(
                f"The sandbox network check did not run (exit {result.returncode}): "
                f"{result.stderr.strip()[:300]}"
            )
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_network.py`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/network.py backend/tests/test_sandbox_k8s_network.py
git commit -m "feat(sandbox): fail closed when offline pods can reach the network"
```

## Task 23: `backend.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/backend.py`
- Test: `backend/tests/test_sandbox_k8s_backend.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox.errors import SandboxConfigError, SandboxTimeout
from app.services.sandbox.kubernetes import backend as kube_backend
from app.services.sandbox.kubernetes.backend import KubernetesBackend
from app.services.sandbox.kubernetes.config import KubeConfig
from app.services.sandbox.kubernetes.lifecycle import PodExit, PodStart
from app.services.sandbox.spec import SandboxSpec

CONFIG = KubeConfig(server="https://k:443", namespace="sb", own_namespace="sb", in_cluster=True, token="t")


def _backend(client: MagicMock | None = None) -> KubernetesBackend:
    client = client or MagicMock()
    client.namespace = "sb"
    client.has_api_group.return_value = False
    backend = KubernetesBackend(CONFIG, client=client, instance="heym-0")
    backend._offline = MagicMock()
    return backend


def _spec(network: str = "bridge") -> SandboxSpec:
    return SandboxSpec(site="pytool", name="heym-pytool-1", image="img", entrypoint="python", network=network)


class RunTest(unittest.TestCase):
    def test_happy_path_attaches_and_always_deletes(self) -> None:
        backend = _backend()
        with (
            patch.object(kube_backend, "wait_started", return_value=PodStart("running")),
            patch.object(kube_backend, "open_attach") as attach,
            patch.object(kube_backend, "exchange", return_value=(b"out", b"err", 0)) as exchange,
            patch.object(kube_backend, "wait_terminated", return_value=PodExit(0)),
        ):
            result = backend.run(_spec(), "payload", 5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "out", "err"))
        manifest = backend._client.create_pod.call_args.args[0]
        self.assertEqual(manifest["spec"]["activeDeadlineSeconds"], 35)
        self.assertEqual(exchange.call_args.args[1], b"payload")
        attach.return_value.close.assert_called_once()
        backend._client.delete_pod.assert_called_once_with("heym-pytool-1")

    def test_start_failure_never_attaches(self) -> None:
        backend = _backend()
        with (
            patch.object(kube_backend, "wait_started", return_value=PodStart("failed", "ImagePullBackOff: x")),
            patch.object(kube_backend, "open_attach") as attach,
        ):
            result = backend.run(_spec(), None, 5)
        self.assertTrue(result.start_failed)
        self.assertIn("ImagePullBackOff", result.stderr)
        attach.assert_not_called()
        backend._client.delete_pod.assert_called_once()

    def test_timeout_deletes_and_raises(self) -> None:
        backend = _backend()
        with (
            patch.object(kube_backend, "wait_started", return_value=PodStart("running")),
            patch.object(kube_backend, "open_attach"),
            patch.object(kube_backend, "exchange", side_effect=TimeoutError),
        ):
            with self.assertRaises(SandboxTimeout):
                backend.run(_spec(), None, 5)
        backend._client.delete_pod.assert_called_once()

    def test_offline_specs_run_the_canary_first(self) -> None:
        backend = _backend()
        backend._offline.ensure.side_effect = SandboxConfigError("NetworkPolicy missing")
        with self.assertRaises(SandboxConfigError):
            backend.run(_spec(network="none"), None, 5)
        backend._client.create_pod.assert_not_called()

    def test_workspace_mounts_fail_closed_until_milestone_4(self) -> None:
        from pathlib import Path

        from app.services.sandbox.spec import DockerVolumeSource, WorkspaceMount

        mount = WorkspaceMount(Path("/w/x"), "/w/x", False, DockerVolumeSource(Path("/w"), (), "m"))
        spec = SandboxSpec(site="skill", name="n", image="i", entrypoint="p", workspace_mounts=(mount,))
        with self.assertRaises(SandboxConfigError):
            _backend().run(spec, None, 5)


class AvailabilityTest(unittest.TestCase):
    def test_old_server_or_missing_rbac_is_unavailable(self) -> None:
        client = MagicMock()
        client.server_version.return_value = (1, 29)
        self.assertFalse(_backend(client).available())
        client = MagicMock()
        client.server_version.return_value = (1, 31)
        client.can_i.side_effect = lambda verb, resource, sub="": sub != "attach"
        self.assertFalse(_backend(client).available())

    def test_available_when_everything_checks_out(self) -> None:
        client = MagicMock()
        client.server_version.return_value = (1, 36)
        client.can_i.return_value = True
        self.assertTrue(_backend(client).available())


class ProcessAndImageTest(unittest.TestCase):
    def test_process_command_hands_the_manifest_to_the_bridge(self) -> None:
        command = _backend().process_command(_spec())
        self.assertEqual(command.argv[1:], ["-m", "app.services.sandbox.kubernetes.process"])
        payload = json.loads(command.env["HEYM_SANDBOX_PROCESS_SPEC"])
        self.assertEqual(payload["manifest"]["metadata"]["name"], "heym-pytool-1")
        self.assertEqual(payload["kube"]["server"], "https://k:443")
        self.assertTrue(command.env["PYTHONPATH"].endswith("backend"))

    def test_image_is_the_single_container_of_the_backend_pod(self) -> None:
        client = MagicMock()
        client.get_pod.return_value = {"spec": {"containers": [{"image": "ghcr.io/heymrun/heym:1"}]}}
        self.assertEqual(_backend(client).resolve_image(), "ghcr.io/heymrun/heym:1")
        client.get_pod.return_value = {"spec": {"containers": [{"image": "a"}, {"image": "b"}]}}
        self.assertIsNone(_backend(client).resolve_image())
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_backend.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `backend.py`**

```python
"""Kubernetes backend: one restricted pod per sandbox run, through the API."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from app.services.sandbox.errors import SandboxConfigError, SandboxTimeout
from app.services.sandbox.kubernetes.attach import exchange, open_attach
from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig, KubeConfigError
from app.services.sandbox.kubernetes.lifecycle import wait_started, wait_terminated
from app.services.sandbox.kubernetes.network import OfflineCheck
from app.services.sandbox.kubernetes.pod import (
    OVERRIDES_ENV,
    PodContext,
    PodVolume,
    build_pod,
    parse_overrides,
)
from app.services.sandbox.spec import (
    START_FAILURE_RETURNCODE,
    ProcessCommand,
    SandboxResult,
    SandboxSpec,
)

logger = logging.getLogger(__name__)

MIN_MINOR_VERSION = 30
ONE_SHOT_DEADLINE_GRACE_SECONDS = 30
BACKEND_ROOT = Path(__file__).resolve().parents[4]
PROCESS_SPEC_ENV = "HEYM_SANDBOX_PROCESS_SPEC"
_REQUIRED_ACCESS = (
    ("create", "pods", ""),
    ("get", "pods", ""),
    ("delete", "pods", ""),
    ("create", "pods", "attach"),
)


class KubernetesBackend:
    """Runs each sandbox as a pod in the sandbox namespace."""

    name = "kubernetes"

    def __init__(
        self, config: KubeConfig, *, client: KubeClient | None = None, instance: str | None = None
    ) -> None:
        self.config = config
        self._client = client or KubeClient(config)
        self._instance = instance or socket.gethostname()
        self._lock = threading.Lock()
        self._available: bool | None = None
        self._context: PodContext | None = None
        self._self_pod: dict[str, Any] | None = None
        self._offline = OfflineCheck(self._run_pod)
        self.unavailable_reason = ""

    @property
    def client(self) -> KubeClient:
        """The API client (the janitor uses it)."""
        return self._client

    def available(self) -> bool:
        """API reachable, version 1.30+, RBAC in place, overrides valid (probed once)."""
        with self._lock:
            if self._available is None:
                self._available = self._probe()
            return self._available

    def _probe(self) -> bool:
        try:
            major, minor = self._client.server_version()
            if (major, minor) < (1, MIN_MINOR_VERSION):
                return self._unavailable(
                    f"Kubernetes {major}.{minor} is too old; sandbox attach needs "
                    f"1.{MIN_MINOR_VERSION} or newer"
                )
            for verb, resource, subresource in _REQUIRED_ACCESS:
                if not self._client.can_i(verb, resource, subresource):
                    target = f"{resource}/{subresource}" if subresource else resource
                    return self._unavailable(
                        f"the backend's ServiceAccount may not {verb} {target} in namespace "
                        f"{self._client.namespace}"
                    )
            self._context = self._build_context()
        except (KubeApiError, KubeConfigError, SandboxConfigError, httpx.HTTPError, OSError) as exc:
            return self._unavailable(str(exc))
        return True

    def _unavailable(self, reason: str) -> bool:
        self.unavailable_reason = reason
        logger.warning("Kubernetes sandbox backend unavailable: %s", reason)
        return False

    def _build_context(self) -> PodContext:
        return PodContext(
            instance=self._instance,
            openshift=self._client.has_api_group("security.openshift.io"),
            overrides=parse_overrides(os.environ.get(OVERRIDES_ENV)),
        )

    def pod_context(self) -> PodContext:
        """Instance, OpenShift detection and validated overrides."""
        if self._context is None:
            self._context = self._build_context()
        return self._context

    def self_pod(self) -> dict[str, Any] | None:
        """The backend's own pod (in-cluster only)."""
        if not self.config.in_cluster:
            return None
        if self._self_pod is None:
            self._self_pod = self._client.get_pod(self._instance, namespace=self.config.own_namespace)
        return self._self_pod

    def resolve_image(self) -> str | None:
        """The backend pod's image, when the pod has exactly one container."""
        containers = ((self.self_pod() or {}).get("spec") or {}).get("containers") or []
        if len(containers) == 1:
            return containers[0].get("image")
        return None

    def pod_volumes(self, spec: SandboxSpec) -> tuple[tuple[PodVolume, ...], str | None]:
        """Workspace and operator mounts as PVC subPaths, plus the node to pin to (if any)."""
        if spec.workspace_mounts or spec.operator_mount is not None:
            raise SandboxConfigError(
                "This sandbox needs a workspace volume, which the Kubernetes backend does not "
                "mount yet."
            )
        return (), None

    def manifest(self, spec: SandboxSpec, timeout_seconds: float | None) -> dict[str, Any]:
        """The pod manifest for ``spec``; one-shot runs get a deadline from their timeout."""
        if spec.deadline_seconds is None and timeout_seconds is not None:
            spec = replace(spec, deadline_seconds=timeout_seconds + ONE_SHOT_DEADLINE_GRACE_SECONDS)
        volumes, node = self.pod_volumes(spec)
        context = self.pod_context()
        if node:
            context = replace(context, node_name=node)
        return build_pod(spec, context, volumes)

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        """Run one pod to completion. Offline specs need a passing network canary first."""
        if spec.offline:
            self._offline.ensure(spec.image)
        return self._run_pod(spec, stdin, timeout_seconds)

    def _run_pod(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        manifest = self.manifest(spec, timeout_seconds)
        self._client.create_pod(manifest)
        try:
            started = wait_started(self._client, spec.name)
            if started.state == "failed":
                return SandboxResult(START_FAILURE_RETURNCODE, "", f"kubernetes: {started.reason}")
            stdout, stderr, status_code = b"", b"", None
            if started.state == "running":
                session = open_attach(self._client, spec.name)
                try:
                    stdout, stderr, status_code = exchange(
                        session,
                        stdin.encode("utf-8") if stdin is not None else None,
                        time.monotonic() + timeout_seconds,
                    )
                except TimeoutError:
                    raise SandboxTimeout(
                        f"sandbox pod {spec.name} ran past {timeout_seconds:.0f} seconds"
                    ) from None
                finally:
                    session.close()
            finished = wait_terminated(self._client, spec.name)
            if started.state == "terminated" and not stdout:
                stdout = self._client.pod_log(spec.name).encode("utf-8")
            code = finished.code if finished.code is not None else status_code
            if code is None:
                raise RuntimeError(
                    f"sandbox pod {spec.name} finished without an exit status ({finished.reason})"
                )
            return SandboxResult(
                code, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")
            )
        finally:
            self.force_remove(spec.name)

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        """The bridge command for callers that spawn the sandbox (MCP stdio)."""
        if spec.offline:
            self._offline.ensure(spec.image)
        payload = {
            "kube": self.config.to_dict(),
            "manifest": self.manifest(spec, None),
            "start_gate": spec.start_gate,
        }
        return ProcessCommand(
            argv=[sys.executable, "-m", "app.services.sandbox.kubernetes.process"],
            env={PROCESS_SPEC_ENV: json.dumps(payload), "PYTHONPATH": str(BACKEND_ROOT)},
            name=spec.name,
        )

    def force_remove(self, name: str | None) -> None:
        """Delete a sandbox pod now; failures are logged, never raised."""
        if not name:
            return
        try:
            self._client.delete_pod(name)
        except (KubeApiError, httpx.HTTPError, OSError) as exc:
            logger.warning("Could not delete sandbox pod %s: %s", name, exc)

    def uses_shared_workspace(self) -> bool:
        """Workspaces always live on the shared PVC on Kubernetes."""
        return True
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_backend.py`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/backend.py backend/tests/test_sandbox_k8s_backend.py
git commit -m "feat(sandbox): kubernetes backend runs one restricted pod per sandbox"
```

## Task 24: `process.py` (stdio bridge)

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/process.py`
- Test: `backend/tests/test_sandbox_k8s_process.py`

- [ ] **Step 1: Write the failing test**

```python
import io
import signal
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox.kubernetes import process
from app.services.sandbox.kubernetes.lifecycle import PodExit, PodStart

MANIFEST = {"metadata": {"name": "heym-mcp-stdio-1"}}


class _Session:
    def __init__(self, frames: list) -> None:
        self.frames = list(frames)
        self.sent: list[bytes] = []
        self.closed_stdin = False

    def send_stdin(self, data: bytes) -> None:
        self.sent.append(data)

    def close_stdin(self) -> None:
        self.closed_stdin = True

    def receive(self, timeout):  # noqa: ANN001, ANN201
        return self.frames.pop(0) if self.frames else None

    def close(self) -> None:
        pass


class BridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.addCleanup(signal.signal, caught, signal.getsignal(caught))

    def test_pumps_both_ways_and_returns_the_exit_code(self) -> None:
        session = _Session([(1, b'{"jsonrpc":"2.0"}\n'), (2, b"log\n")])
        client = MagicMock()
        stdout, stderr = io.BytesIO(), io.BytesIO()
        with (
            patch.object(process, "wait_started", return_value=PodStart("running")),
            patch.object(process, "open_attach", return_value=session),
            patch.object(process, "wait_terminated", return_value=PodExit(0)),
        ):
            code = process.run_attached(
                client, MANIFEST, start_gate=True, stdin=io.BytesIO(b"request\n"),
                stdout=stdout, stderr=stderr,
            )
            process.join_stdin_pump()
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), b'{"jsonrpc":"2.0"}\n')
        self.assertEqual(stderr.getvalue(), b"log\n")
        self.assertEqual(session.sent[0], b"\n")
        self.assertIn(b"request\n", session.sent)
        self.assertTrue(session.closed_stdin)
        client.delete_pod.assert_called_once_with("heym-mcp-stdio-1")

    def test_start_failure_reports_and_deletes(self) -> None:
        client = MagicMock()
        stderr = io.BytesIO()
        with patch.object(process, "wait_started", return_value=PodStart("failed", "ErrImagePull: x")):
            code = process.run_attached(
                client, MANIFEST, start_gate=False, stdin=io.BytesIO(), stdout=io.BytesIO(), stderr=stderr
            )
        self.assertEqual(code, 125)
        self.assertIn(b"ErrImagePull", stderr.getvalue())
        client.delete_pod.assert_called_once()
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_process.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `process.py`**

```python
"""Bridge this process's stdin/stdout/stderr to a sandbox pod.

MCP stdio on Kubernetes spawns ``python -m app.services.sandbox.kubernetes.process``
with the pod manifest and API connection in ``HEYM_SANDBOX_PROCESS_SPEC``. The Codex
and OpenCode wrapper calls :func:`run_attached` directly.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from typing import Any, BinaryIO

from websockets.exceptions import ConnectionClosed

from app.services.sandbox.kubernetes.attach import (
    STATUS,
    STDERR,
    STDOUT,
    AttachSession,
    exit_code_from_status,
    open_attach,
)
from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig
from app.services.sandbox.kubernetes.lifecycle import wait_started, wait_terminated
from app.services.sandbox.spec import START_FAILURE_RETURNCODE

PROCESS_SPEC_ENV = "HEYM_SANDBOX_PROCESS_SPEC"
_pump: threading.Thread | None = None


def _delete(client: KubeClient, name: str) -> None:
    try:
        client.delete_pod(name)
    except (KubeApiError, OSError):
        pass


def _pump_stdin(stdin: BinaryIO, session: AttachSession) -> None:
    try:
        while True:
            chunk = stdin.read1(65536) if hasattr(stdin, "read1") else stdin.read(65536)
            if not chunk:
                break
            session.send_stdin(chunk)
        session.close_stdin()
    except (OSError, ConnectionClosed):
        pass


def join_stdin_pump(timeout: float = 5.0) -> None:
    """Wait for the stdin pump (tests)."""
    if _pump is not None:
        _pump.join(timeout)


def run_attached(
    client: KubeClient,
    manifest: dict[str, Any],
    *,
    start_gate: bool,
    stdin: BinaryIO,
    stdout: BinaryIO,
    stderr: BinaryIO,
) -> int:
    """Create the pod, bridge stdio until it exits, delete it; return its exit code."""
    global _pump
    name = str(manifest["metadata"]["name"])

    def _stop(signum: int, _frame: object) -> None:
        _delete(client, name)
        raise SystemExit(128 + signum)

    for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(caught, _stop)
        except (OSError, ValueError):
            pass

    client.create_pod(manifest)
    try:
        started = wait_started(client, name)
        if started.state == "failed":
            stderr.write(f"kubernetes: {started.reason}\n".encode())
            stderr.flush()
            return START_FAILURE_RETURNCODE
        status_code: int | None = None
        if started.state == "running":
            session = open_attach(client, name)
            try:
                if start_gate:
                    session.send_stdin(b"\n")
                _pump = threading.Thread(target=_pump_stdin, args=(stdin, session), daemon=True)
                _pump.start()
                while True:
                    frame = session.receive(timeout=None)
                    if frame is None:
                        break
                    channel, payload = frame
                    if channel == STDOUT:
                        stdout.write(payload)
                        stdout.flush()
                    elif channel == STDERR:
                        stderr.write(payload)
                        stderr.flush()
                    elif channel == STATUS:
                        status_code = exit_code_from_status(payload)
            finally:
                session.close()
        finished = wait_terminated(client, name)
        code = finished.code if finished.code is not None else status_code
        return code if code is not None else 1
    finally:
        _delete(client, name)


def main() -> int:
    """Entry point of ``python -m app.services.sandbox.kubernetes.process``."""
    payload = json.loads(os.environ[PROCESS_SPEC_ENV])
    client = KubeClient(KubeConfig.from_dict(payload["kube"]))
    return run_attached(
        client,
        payload["manifest"],
        start_gate=bool(payload.get("start_gate")),
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

The test's fake session returns `None` after its frames, so the loop can end before the pump thread has sent `request\n`; `join_stdin_pump()` in the test makes the assertion deterministic.

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_process.py`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/process.py backend/tests/test_sandbox_k8s_process.py
git commit -m "feat(sandbox): stdio bridge for long-lived sandbox processes on kubernetes"
```

## Task 25: Backend selection in the manager

**Files:**
- Modify: `backend/app/services/sandbox/manager.py`
- Modify: `backend/tests/test_sandbox_manager.py`

- [ ] **Step 1: Add failing tests**

```python
from app.services.sandbox import manager as manager_module
from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.manager import UnavailableBackend


class SelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)

    def _select(self, env: dict, docker_up: bool, in_cluster: bool, k8s_up: bool):  # noqa: ANN202
        k8s = MagicMock()
        k8s.name = "kubernetes"
        k8s.available.return_value = k8s_up
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(manager_module.DockerBackend, "available", return_value=docker_up),
            patch("app.services.sandbox.kubernetes.config.in_cluster_available", return_value=in_cluster),
            patch("app.services.sandbox.kubernetes.config.load_in_cluster"),
            patch("app.services.sandbox.kubernetes.backend.KubernetesBackend", return_value=k8s),
        ):
            return manager_module._build_manager()

    def test_auto_prefers_a_reachable_docker(self) -> None:
        self.assertEqual(self._select({}, True, True, True).backend_name, "docker")

    def test_auto_uses_kubernetes_in_a_pod_without_docker(self) -> None:
        self.assertEqual(self._select({}, False, True, True).backend_name, "kubernetes")

    def test_auto_without_either_stays_docker_and_fails_closed(self) -> None:
        manager = self._select({}, False, False, False)
        self.assertEqual(manager.backend_name, "docker")
        self.assertFalse(manager.available())

    def test_forced_docker_never_tries_kubernetes(self) -> None:
        self.assertEqual(self._select({"HEYM_SANDBOX_BACKEND": "docker"}, False, True, True).backend_name, "docker")

    def test_forced_kubernetes_without_config_fails_closed(self) -> None:
        with (
            patch.dict(os.environ, {"HEYM_SANDBOX_BACKEND": "kubernetes", "KUBECONFIG": "/nonexistent"}, clear=True),
            patch("app.services.sandbox.kubernetes.config.in_cluster_available", return_value=False),
        ):
            manager = manager_module._build_manager()
        self.assertEqual(manager.backend_name, "kubernetes")
        self.assertFalse(manager.available())
        with self.assertRaises(SandboxConfigError):
            manager.run(MagicMock(), None, 1)

    def test_unavailable_backend(self) -> None:
        backend = UnavailableBackend("kubernetes", "why")
        self.assertIsNone(backend.resolve_image())
        backend.force_remove("x")
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_sandbox_manager.py`
Expected: FAIL, `ImportError: cannot import name 'UnavailableBackend'`.

- [ ] **Step 3: Replace `_build_manager` in `manager.py`**

Add `from app.services.sandbox.errors import SandboxConfigError` to the imports, then replace `_build_manager` with:

```python
BACKEND_ENV = "HEYM_SANDBOX_BACKEND"


class UnavailableBackend:
    """A backend that was asked for but cannot run. Every call fails closed."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    def available(self) -> bool:
        return False

    def resolve_image(self) -> str | None:
        return None

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        raise SandboxConfigError(self.reason)

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        raise SandboxConfigError(self.reason)

    def force_remove(self, name: str | None) -> None:
        return None

    def uses_shared_workspace(self) -> bool:
        return True


def backend_mode() -> str:
    """``auto`` (default), ``docker`` or ``kubernetes`` from HEYM_SANDBOX_BACKEND."""
    raw = (os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if raw not in ("auto", "docker", "kubernetes"):
        logger.warning("Unknown %s=%r; using 'auto'", BACKEND_ENV, raw)
        return "auto"
    return raw


def _kubernetes_backend(*, forced: bool) -> SandboxBackend:
    from app.services.sandbox.kubernetes import config as kube_config
    from app.services.sandbox.kubernetes.backend import KubernetesBackend

    try:
        if kube_config.in_cluster_available():
            config = kube_config.load_in_cluster()
        elif forced:
            config = kube_config.load_kubeconfig()
        else:
            return UnavailableBackend("kubernetes", "not running in a Kubernetes pod")
    except kube_config.KubeConfigError as exc:
        logger.warning("Kubernetes sandbox backend unavailable: %s", exc)
        return UnavailableBackend("kubernetes", str(exc))
    return KubernetesBackend(config)


def _build_manager() -> SandboxManager:
    mode = backend_mode()
    if mode == "docker":
        return SandboxManager(DockerBackend())
    if mode == "kubernetes":
        return SandboxManager(_kubernetes_backend(forced=True))
    docker = DockerBackend()
    if docker.available():
        return SandboxManager(docker)
    kubernetes = _kubernetes_backend(forced=False)
    if kubernetes.available():
        return SandboxManager(kubernetes)
    return SandboxManager(docker)
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_sandbox_manager.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/manager.py backend/tests/test_sandbox_manager.py
git commit -m "feat(sandbox): select docker or kubernetes once per process"
```

## Task 26: Janitor, lifespan hook, registry probe

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/janitor.py`
- Modify: `backend/app/main.py`, `backend/app/services/cluster/registry.py`
- Test: `backend/tests/test_sandbox_k8s_janitor.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.sandbox.kubernetes.janitor import sweep

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _pod(name: str, phase: str, age_minutes: int, instance: str = "heym-0") -> dict:
    created = (NOW - timedelta(minutes=age_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "metadata": {"name": name, "creationTimestamp": created, "labels": {"heym.run/instance": instance}},
        "status": {"phase": phase},
    }


class SweepTest(unittest.TestCase):
    def _client(self, pods: list[dict], live_instances: set[str]) -> MagicMock:
        client = MagicMock()
        client.list_pods.return_value = pods
        client.config.own_namespace = "heym"
        client.get_pod.side_effect = lambda name, namespace=None: {} if name in live_instances else None
        return client

    def test_finished_pods_go_after_the_grace_period(self) -> None:
        client = self._client([_pod("old", "Succeeded", 30), _pod("new", "Failed", 1)], {"heym-0"})
        self.assertEqual(sweep(client, in_cluster=True, now=NOW), ["old"])

    def test_running_pods_of_a_dead_instance_go_in_cluster_only(self) -> None:
        pods = [_pod("orphan", "Running", 5, "heym-gone"), _pod("live", "Running", 5, "heym-0")]
        self.assertEqual(sweep(self._client(pods, {"heym-0"}), in_cluster=True, now=NOW), ["orphan"])
        self.assertEqual(sweep(self._client(pods, {"heym-0"}), in_cluster=False, now=NOW), [])
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_janitor.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `janitor.py`**

```python
"""Deletes sandbox pods nobody will delete: finished ones, and those of dead instances.

Every run and the bridge delete their own pod on every exit path; this covers a
backend that died mid-run. Running pods also end at ``activeDeadlineSeconds``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.pod import LABEL_INSTANCE, LABEL_MANAGED_BY, MANAGED_BY

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 600
FINISHED_GRACE_SECONDS = 600


def _created(pod: dict[str, Any]) -> datetime | None:
    raw = (pod.get("metadata") or {}).get("creationTimestamp")
    try:
        return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def sweep(client: KubeClient, *, in_cluster: bool, now: datetime) -> list[str]:
    """Delete finished pods past the grace period and pods whose instance is gone."""
    removed: list[str] = []
    instance_alive: dict[str, bool] = {}
    for pod in client.list_pods(f"{LABEL_MANAGED_BY}={MANAGED_BY}"):
        metadata = pod.get("metadata") or {}
        name = str(metadata.get("name") or "")
        created = _created(pod)
        phase = (pod.get("status") or {}).get("phase")
        finished = (
            phase in ("Succeeded", "Failed")
            and created is not None
            and (now - created).total_seconds() > FINISHED_GRACE_SECONDS
        )
        orphan = False
        instance = (metadata.get("labels") or {}).get(LABEL_INSTANCE)
        if in_cluster and instance and not finished:
            if instance not in instance_alive:
                owner = client.get_pod(instance, namespace=client.config.own_namespace)
                instance_alive[instance] = owner is not None
            orphan = not instance_alive[instance]
        if name and (finished or orphan):
            client.delete_pod(name)
            removed.append(name)
    return removed


def _kubernetes_backend():  # noqa: ANN202
    from app.services.sandbox.manager import get_sandbox_manager

    manager = get_sandbox_manager()
    if manager.backend_name != "kubernetes" or not manager.available():
        return None
    return manager.backend


async def run_janitor() -> None:
    """Sweep every ten minutes while the Kubernetes backend is in use."""
    backend = await asyncio.to_thread(_kubernetes_backend)
    if backend is None:
        return
    while True:
        try:
            removed = await asyncio.to_thread(
                sweep, backend.client, in_cluster=backend.config.in_cluster, now=datetime.now(timezone.utc)
            )
            if removed:
                logger.info("Removed %d leftover sandbox pods: %s", len(removed), ", ".join(removed))
        except (KubeApiError, httpx.HTTPError, OSError) as exc:
            logger.warning("Sandbox pod sweep failed: %s", exc)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
```

- [ ] **Step 4: Start it from the lifespan**

In `backend/app/main.py`, next to `chat_workspace_sweeper`:

```python
    from app.services.sandbox.kubernetes.janitor import run_janitor

    sandbox_janitor = asyncio.create_task(run_janitor())
    chat_workspace_sweeper = asyncio.create_task(run_idle_sweeper())
    yield
    sandbox_janitor.cancel()
    chat_workspace_sweeper.cancel()
```

- [ ] **Step 5: Report the sandbox backend in the cluster heartbeat**

In `backend/app/services/cluster/registry.py`, add `import asyncio` (if missing) and `from app.services.sandbox import get_sandbox_manager`, then:

```python
def _sandbox_reachable() -> bool:
    """``docker_ok`` now means "a sandbox backend is reachable" (column name kept)."""
    manager = get_sandbox_manager()
    if manager.backend_name == "kubernetes":
        return manager.available()
    return _docker_reachable()
```

and in `write_heartbeat`: `docker_ok=await asyncio.to_thread(_sandbox_reachable),`

- [ ] **Step 6: Run the tests**

Run: `PYTEST tests/test_sandbox_k8s_janitor.py tests/test_cluster_*.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/janitor.py backend/app/main.py backend/app/services/cluster/registry.py backend/tests/test_sandbox_k8s_janitor.py
git commit -m "feat(sandbox): sweep leftover sandbox pods and report the backend in heartbeats"
```

## Task 27: Playwright browsers readable by a non-root sandbox

**Files:**
- Modify: `backend/Dockerfile`, `docker/release.Dockerfile`

- [ ] **Step 1: Set the browser path before the install in both Dockerfiles**

In `backend/Dockerfile`, directly above `RUN uv run python -m playwright install --with-deps chromium`:

```dockerfile
# Outside root's home so a non-root sandbox (Kubernetes runs it as 65534) can read the browsers.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
```

In `docker/release.Dockerfile`, the same two lines directly above `RUN cd /app/backend && uv run python -m playwright install --with-deps chromium`.

- [ ] **Step 2: Build and verify**

Run: `docker compose build backend && docker run --rm --user 65534:65534 --entrypoint sh heym-backend:local -c 'ls /ms-playwright && /app/.venv/bin/python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(args=[\"--no-sandbox\"]); print(\"chromium ok\"); b.close(); p.stop()"'`
Expected: the browser directory listing, then `chromium ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile docker/release.Dockerfile
git commit -m "build: install playwright browsers where a non-root sandbox can read them"
```

## Task 28: Advisory tests and the import rule

**Files:**
- Create: `backend/tests/test_advisory_k8s_sandbox.py`, `backend/tests/test_sandbox_import_rule.py`

- [ ] **Step 1: Write the advisory test**

```python
"""Every sandbox pod is Pod Security ``restricted`` and carries no backend secret.

Builds the real spec of every call site and renders it as a pod, so a new site or a
changed spec cannot quietly loosen the boundary.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import (
    code_formatter,
    code_python_executor,
    mcp_stdio_sandbox,
    playwright_sandbox,
    python_tool_executor,
    skill_python_executor,
)
from app.services.sandbox.coding_agents import CODEX, OPENCODE, agent_spec, run_scope
from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.pod import PodContext, build_pod, parse_overrides

SECRETS = {
    "SECRET_KEY": "advisory-secret-key",
    "ENCRYPTION_KEY": "advisory-encryption-key",
    "DATABASE_URL": "postgresql://advisory",
    "OPENAI_API_KEY": "sk-advisory",
}
RUN = "0123456789abcdef0123456789abcdef"


def _all_specs() -> dict:
    root = Path(tempfile.mkdtemp()).resolve()
    for name in (RUN, f"{RUN}.codex-home", f"{RUN}.oc-home"):
        (root / name).mkdir()
    codex_env = {"HEYM_CODEX_WORKSPACE_DIR": str(root), "CODEX_HOME": f"{root}/{RUN}.codex-home"}
    oc_env = {"HEYM_OPENCODE_WORKSPACE_DIR": str(root), "HOME": f"{root}/{RUN}.oc-home"}
    return {
        "pytool": python_tool_executor._tool_spec("img", "n"),
        "formatter": code_formatter._format_spec("img", "n"),
        "code_run": code_python_executor._run_spec("img", "n", False, (), None),
        "code_install": code_python_executor._install_spec("img", "n", (), Path("/r"), "uv"),
        "playwright": playwright_sandbox._playwright_spec("img", "n"),
        "skill": skill_python_executor._skill_spec("img", "n", root, root / RUN, "main.py"),
        "mcp": mcp_stdio_sandbox._mcp_spec(
            name="n", image="img", entrypoint="npx", args=[], workdir="/tmp", extra_env=[]
        ),
        "codex": agent_spec(CODEX, run_scope(CODEX, root / RUN, codex_env), [], codex_env,
                            image="img", name="n", kubernetes=True, cwd=root / RUN),
        "opencode": agent_spec(OPENCODE, run_scope(OPENCODE, root / RUN, oc_env), [], oc_env,
                               image="img", name="n", kubernetes=True, cwd=root / RUN),
    }


class RestrictedPodAdvisoryTest(unittest.TestCase):
    def test_every_site_pod_is_restricted_and_secret_free(self) -> None:
        with patch.dict(os.environ, SECRETS):
            specs = _all_specs()
        for site, spec in specs.items():
            with self.subTest(site):
                pod = build_pod(spec, PodContext(instance="heym-0"))
                pod_spec = pod["spec"]
                self.assertFalse(pod_spec["automountServiceAccountToken"])
                for key in ("hostNetwork", "hostPID", "hostIPC"):
                    self.assertNotIn(key, pod_spec)
                self.assertTrue(all("hostPath" not in v for v in pod_spec["volumes"]))
                self.assertTrue(pod_spec["securityContext"]["runAsNonRoot"])
                self.assertGreater(pod_spec["securityContext"]["runAsUser"], 0)
                self.assertGreater(pod_spec["activeDeadlineSeconds"], 0)
                for container in pod_spec["containers"]:
                    context = container["securityContext"]
                    self.assertFalse(context["allowPrivilegeEscalation"])
                    self.assertEqual(context["capabilities"], {"drop": ["ALL"]})
                    self.assertNotIn("privileged", context)
                dumped = json.dumps(pod)
                for value in SECRETS.values():
                    self.assertNotIn(value, dumped)

    def test_overrides_cannot_touch_security(self) -> None:
        for key in ("securityContext", "hostNetwork", "hostPID", "volumes", "containers",
                    "serviceAccountName", "automountServiceAccountToken"):
            with self.subTest(key), self.assertRaises(SandboxConfigError):
                parse_overrides(json.dumps({key: True}))
```

- [ ] **Step 2: Write the import rule test**

```python
"""The sandbox package must import without app.config (the wrapper and bridge run without settings)."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULES = (
    "app.services.sandbox",
    "app.services.sandbox.wrapper_cli",
    "app.services.sandbox.coding_agents",
    "app.services.sandbox.kubernetes.backend",
    "app.services.sandbox.kubernetes.process",
    "app.services.sandbox.kubernetes.janitor",
)


class ImportRuleTest(unittest.TestCase):
    def test_no_settings_import(self) -> None:
        code = (
            "import importlib, sys\n"
            f"for name in {MODULES!r}:\n"
            "    importlib.import_module(name)\n"
            "assert 'app.config' not in sys.modules, sorted(m for m in sys.modules if m.startswith('app.'))\n"
        )
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(BACKEND)}
        result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
```

- [ ] **Step 3: Run them**

Run: `PYTEST tests/test_advisory_k8s_sandbox.py tests/test_sandbox_import_rule.py`
Expected: all pass. If the import rule fails, the printed module list shows which import pulled in settings; move that import inside the function that needs it.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_advisory_k8s_sandbox.py backend/tests/test_sandbox_import_rule.py
git commit -m "test(advisory): sandbox pods are restricted and secret-free"
```

## Task 29: Example manifests

**Files:**
- Create: `deploy/kubernetes/README.md`, `deploy/kubernetes/base/{kustomization,namespace,serviceaccount,rbac,networkpolicies,pvc,deployment,service}.yaml`, `deploy/kubernetes/overlays/orbstack/{kustomization,postgres,patch-pvc}.yaml`

- [ ] **Step 1: `base/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: heym
resources:
  - namespace.yaml
  - serviceaccount.yaml
  - rbac.yaml
  - networkpolicies.yaml
  - pvc.yaml
  - deployment.yaml
  - service.yaml
```

- [ ] **Step 2: `base/namespace.yaml`, `base/serviceaccount.yaml`, `base/rbac.yaml`**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: heym
  labels:
    # The backend itself runs as root, so the namespace can only warn. Sandbox pods
    # are restricted-compliant; a dedicated sandbox namespace can enforce it (README).
    pod-security.kubernetes.io/warn: restricted
```

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: heym-backend
```

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: heym-sandbox
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["create", "get", "list", "watch", "delete"]
  - apiGroups: [""]
    resources: ["pods/attach"]
    verbs: ["create", "get"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: heym-sandbox
subjects:
  - kind: ServiceAccount
    name: heym-backend
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: heym-sandbox
```

- [ ] **Step 3: `base/networkpolicies.yaml`**

```yaml
# Sandbox pods carry app.kubernetes.io/managed-by=heym; the backend's own pods do not.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: heym-sandbox-no-ingress
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/managed-by: heym
  policyTypes: [Ingress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: heym-sandbox-offline
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/managed-by: heym
      heym.run/network: none
  policyTypes: [Egress]
  egress: []
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: heym-sandbox-egress
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/managed-by: heym
      heym.run/network: egress
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - {protocol: UDP, port: 53}
        - {protocol: TCP, port: 53}
    # Internet only: private ranges cover pod/service CIDRs and 169.254.169.254
    # (cloud metadata). Add your HTTP proxy's address here if you use one.
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10]
```

- [ ] **Step 4: `base/pvc.yaml`, `base/deployment.yaml`, `base/service.yaml`**

```yaml
# One claim for /app/data: Drive files, plugins and both workspace roots. Sandbox
# pods mount single subPaths of it, never the whole claim. ReadWriteMany lets them
# run on any node; ReadWriteOnce pins them to the backend's node.
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: heym-data
spec:
  accessModes: [ReadWriteMany]
  resources:
    requests:
      storage: 50Gi
```

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: heym
  labels:
    app.kubernetes.io/name: heym
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: heym
  template:
    metadata:
      labels:
        app.kubernetes.io/name: heym
    spec:
      serviceAccountName: heym-backend
      containers:
        - name: heym
          image: ghcr.io/heymrun/heym:latest
          ports:
            - {name: http, containerPort: 4017}
          env:
            - {name: HEYM_SANDBOX_BACKEND, value: kubernetes}
            - {name: AUTO_REWRITE_LOCAL_DATABASE_HOST, value: "false"}
            - name: DATABASE_URL
              valueFrom: {secretKeyRef: {name: heym-secrets, key: DATABASE_URL}}
            - name: SECRET_KEY
              valueFrom: {secretKeyRef: {name: heym-secrets, key: SECRET_KEY}}
            - name: ENCRYPTION_KEY
              valueFrom: {secretKeyRef: {name: heym-secrets, key: ENCRYPTION_KEY}}
          volumeMounts:
            - {name: data, mountPath: /app/data}
          readinessProbe:
            httpGet: {path: /api/health, port: http}
            periodSeconds: 10
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: heym-data
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: heym
spec:
  selector:
    app.kubernetes.io/name: heym
  ports:
    - {name: http, port: 4017, targetPort: http}
```

- [ ] **Step 5: OrbStack overlay**

`overlays/orbstack/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: heym
resources:
  - ../../base
  - postgres.yaml
images:
  - name: ghcr.io/heymrun/heym
    newName: heym-backend
    newTag: local
patches:
  - path: patch-pvc.yaml
  # The local image is the backend-only image on port 10105. A JSON patch replaces the
  # port list; a strategic merge would keep both ports under the same name.
  - target: {kind: Deployment, name: heym}
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/ports
        value: [{name: http, containerPort: 10105}]
```

The `local` tag already defaults to `imagePullPolicy: IfNotPresent`, so the node uses the image Docker built.

`overlays/orbstack/patch-pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: heym-data
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
```

`overlays/orbstack/postgres.yaml` (development only):

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels: {app.kubernetes.io/name: postgres}
  template:
    metadata:
      labels: {app.kubernetes.io/name: postgres}
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - {name: POSTGRES_USER, value: postgres}
            - {name: POSTGRES_PASSWORD, value: postgres}
            - {name: POSTGRES_DB, value: heym}
          ports:
            - {containerPort: 5432}
          volumeMounts:
            - {name: pgdata, mountPath: /var/lib/postgresql/data}
  volumeClaimTemplates:
    - metadata: {name: pgdata}
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: local-path
        resources: {requests: {storage: 5Gi}}
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  selector: {app.kubernetes.io/name: postgres}
  ports:
    - {port: 5432}
```

- [ ] **Step 6: `deploy/kubernetes/README.md`**

```markdown
# Heym on Kubernetes

Example manifests for running Heym without a Docker socket. Every sandbox (Python
tools, skills, the Code node, file analysis, Playwright, MCP stdio, Codex, OpenCode)
runs as its own pod through the Kubernetes API.

## Requirements

- Kubernetes 1.30 or newer (sandbox stdin uses the `v5.channel.k8s.io` attach protocol).
- A CNI that enforces NetworkPolicy. Heym checks this before the first offline
  sandbox and refuses to run offline sandboxes when a test pod can still connect.
- A kubelet `podPidsLimit`. Pods have no per-pod PID limit field, so this is the only
  fork-bomb guard besides memory, CPU and the deadline.

## Install

    kubectl apply -k deploy/kubernetes/base
    kubectl -n heym create secret generic heym-secrets \
      --from-literal=DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/heym \
      --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
      --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)

## Storage

`heym-data` holds Drive files, plugins and the Codex/OpenCode workspaces. Sandbox
pods mount one subPath of it per run. With `ReadWriteMany` they can run on any node.
With `ReadWriteOnce` they are pinned to the backend's node. `ReadWriteOncePod` does
not work.

## A dedicated sandbox namespace

Set `HEYM_SANDBOX_K8S_NAMESPACE` to run sandboxes elsewhere, label that namespace
`pod-security.kubernetes.io/enforce: restricted`, move the Role there, and keep a
Role in Heym's namespace that grants `get` on `pods`. Workspace sandboxes then need
a claim named `heym-data` in the sandbox namespace bound to the same RWX share
(a second, statically provisioned PersistentVolume).

## Scheduling

`HEYM_SANDBOX_K8S_POD_OVERRIDES` takes JSON with `nodeSelector`, `tolerations`,
`runtimeClassName` (for example gVisor), `imagePullSecrets` and `priorityClassName`.
Nothing else is accepted.

## Local test on OrbStack

    docker compose build backend
    kubectl --context orbstack apply -k deploy/kubernetes/overlays/orbstack
    kubectl --context orbstack -n heym create secret generic heym-secrets \
      --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/heym \
      --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
      --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)
    ./scripts/k8s-sandbox-smoke.sh
```

- [ ] **Step 7: Validate rendering**

Run: `kubectl kustomize deploy/kubernetes/base >/dev/null && kubectl kustomize deploy/kubernetes/overlays/orbstack | grep -c "^kind:"`
Expected: no error from the first command; the second prints `12` (ten base objects plus Postgres and its Service).

- [ ] **Step 8: Commit**

```bash
git add deploy/kubernetes
git commit -m "deploy: example kubernetes manifests with sandbox rbac and network policies"
```

## Task 30: Live tests against OrbStack (opt-in)

**Files:**
- Create: `backend/tests/live/test_k8s_sandbox_live.py`

- [ ] **Step 1: Write the live test**

```python
"""Live sandbox runs against a real cluster. Skipped unless HEYM_K8S_LIVE_CONTEXT is set.

    docker compose build backend
    HEYM_K8S_LIVE_CONTEXT=orbstack uv run pytest tests/live/test_k8s_sandbox_live.py -v

Runs from the host with the current kubeconfig context, so it covers the sites
without a workspace. Milestone 4's smoke script covers the rest in-cluster.
"""

import json
import os
import subprocess
import unittest
import uuid
from unittest.mock import patch

LIVE = os.environ.get("HEYM_K8S_LIVE_CONTEXT", "")
IMAGE = os.environ.get("HEYM_K8S_LIVE_IMAGE", "heym-backend:local")
_DENY_OFFLINE = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "heym-sandbox-offline"},
    "spec": {
        "podSelector": {"matchLabels": {"heym.run/network": "none"}},
        "policyTypes": ["Egress"],
        "egress": [],
    },
}


def _kubectl(*args: str) -> None:
    subprocess.run(["kubectl", "--context", LIVE, *args], check=True, capture_output=True)


@unittest.skipUnless(LIVE, "set HEYM_K8S_LIVE_CONTEXT to run live Kubernetes sandbox tests")
class LiveSandboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        current = subprocess.run(
            ["kubectl", "config", "current-context"], capture_output=True, text=True
        ).stdout.strip()
        if current != LIVE:
            # The backend reads the kubeconfig's current context, so it must be the named one.
            raise unittest.SkipTest(f"current kubectl context is {current!r}, not {LIVE!r}")

    def _namespace(self, *, deny_offline: bool) -> str:
        name = f"heym-sb-live-{uuid.uuid4().hex[:8]}"
        _kubectl("create", "namespace", name)
        self.addCleanup(_kubectl, "delete", "namespace", name, "--wait=false")
        _kubectl("label", "namespace", name, "pod-security.kubernetes.io/enforce=restricted")
        if deny_offline:
            subprocess.run(
                ["kubectl", "--context", LIVE, "-n", name, "apply", "-f", "-"],
                input=json.dumps(_DENY_OFFLINE), text=True, check=True, capture_output=True,
            )
        return name

    def _use(self, namespace: str) -> None:
        from app.services.sandbox import reset_sandbox_manager

        env = {
            "HEYM_SANDBOX_BACKEND": "kubernetes",
            "HEYM_SANDBOX_K8S_NAMESPACE": namespace,
            "HEYM_PYTHON_TOOL_IMAGE": IMAGE,
            "HEYM_PLAYWRIGHT_SANDBOX_IMAGE": IMAGE,
            "HEYM_MCP_STDIO_IMAGE": IMAGE,
            "HEYM_PYTHON_TOOL_SANDBOX": "auto",
            "HEYM_MCP_STDIO_SANDBOX": "auto",
            "HEYM_PLAYWRIGHT_SANDBOX_PYTHON": "/app/.venv/bin/python",
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)

    def test_one_shot_sites_under_restricted(self) -> None:
        from app.services.code_formatter import format_python
        from app.services.code_python_executor import execute_code
        from app.services.python_tool_executor import execute_tool

        self._use(self._namespace(deny_offline=True))
        self.assertEqual(execute_tool("def f(a):\n    return a * 2\n", "f", {"a": 21}, 60), 42)
        self.assertEqual(format_python("x=1\n"), "x = 1\n")
        result = execute_code("def main(params):\n    return params['n'] + 1\n", "", {"n": 1}, False)
        self.assertEqual(result.result, 2)

    def test_offline_sites_fail_closed_without_a_policy(self) -> None:
        from app.services.python_tool_executor import execute_tool
        from app.services.sandbox.errors import SandboxConfigError

        self._use(self._namespace(deny_offline=False))
        with self.assertRaisesRegex(SandboxConfigError, "NetworkPolicy"):
            execute_tool("def f():\n    return 1\n", "f", {}, 60)

    def test_playwright_runs_as_non_root(self) -> None:
        from app.services.playwright_sandbox import run_script

        self._use(self._namespace(deny_offline=True))
        code, out, err = run_script("import os\nprint(os.getuid())\n", 120)
        self.assertEqual((code, out.strip()), (0, "65534"), err)

    def test_mcp_stdio_bridge_round_trip(self) -> None:
        from app.services.mcp_stdio_sandbox import build_sandboxed_command

        self._use(self._namespace(deny_offline=True))
        echo = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line.upper()); sys.stdout.flush()\n"
        command = build_sandboxed_command("python", ["-c", echo], {"K": "v"})
        result = subprocess.run(
            command.argv, input="ping\n", env={**os.environ, **command.env},
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(result.stdout, "PING\n", result.stderr)
```

- [ ] **Step 2: Run it against OrbStack**

Run: `cd backend && HEYM_K8S_LIVE_CONTEXT=orbstack SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/live/test_k8s_sandbox_live.py -v`
Expected: `4 passed`. Without the variable: `4 skipped`.

- [ ] **Step 3: Confirm nothing was left behind**

Run: `kubectl --context orbstack get pods -A -l app.kubernetes.io/managed-by=heym`
Expected: `No resources found`.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/live
git commit -m "test(sandbox): opt-in live kubernetes sandbox tests"
```

## Task 31: Milestone 3 gate

- [ ] **Step 1: Full check**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`
Expected: green; the live tests skip.

- [ ] **Step 2: Commit any formatting**

```bash
git add -A backend && git commit -m "style: ruff format" || true
```

---

# Milestone 4: Workspace sites on Kubernetes

The sites already carry structured `WorkspaceMount`s since Milestone 1, and on Kubernetes `_is_containerized()` (through `uses_shared_workspace()`) puts every run directory on the workspace volume. This milestone only teaches the Kubernetes backend to turn those mounts into PVC subPaths, then wires Codex and OpenCode.

## Task 32: `workspace.py`

**Files:**
- Create: `backend/app/services/sandbox/kubernetes/workspace.py`
- Test: `backend/tests/test_sandbox_k8s_workspace.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.workspace import (
    ClaimMount,
    claim_mounts,
    placement_node,
    resolve_volume,
)

BACKEND_POD = {
    "spec": {
        "nodeName": "node-a",
        "volumes": [
            {"name": "data", "persistentVolumeClaim": {"claimName": "heym-data"}},
            {"name": "oc", "persistentVolumeClaim": {"claimName": "heym-opencode"}},
            {"name": "tmp", "emptyDir": {}},
        ],
        "containers": [
            {
                "name": "heym",
                "volumeMounts": [
                    {"name": "data", "mountPath": "/app/data"},
                    {"name": "oc", "mountPath": "/app/data/opencode-workspaces", "subPath": "ws"},
                    {"name": "tmp", "mountPath": "/tmp"},
                ],
            }
        ],
    }
}


class WorkspaceTest(unittest.TestCase):
    def test_claim_mounts_skip_non_pvc_volumes(self) -> None:
        self.assertEqual(
            claim_mounts(BACKEND_POD),
            [ClaimMount("/app/data", "heym-data", ""), ClaimMount("/app/data/opencode-workspaces", "heym-opencode", "ws")],
        )

    def test_longest_prefix_wins_and_subpaths_nest(self) -> None:
        mounts = claim_mounts(BACKEND_POD)
        code = resolve_volume(mounts, Path("/app/data/codex-workspaces/_code-runs/abc"), "/x", True)
        self.assertEqual((code.claim, code.sub_path, code.readonly), ("heym-data", "codex-workspaces/_code-runs/abc", True))
        oc = resolve_volume(mounts, Path("/app/data/opencode-workspaces/r1"), "/y", False)
        self.assertEqual((oc.claim, oc.sub_path), ("heym-opencode", "ws/r1"))

    def test_refuses_paths_off_any_claim_and_whole_claims(self) -> None:
        mounts = claim_mounts(BACKEND_POD)
        with self.assertRaisesRegex(SandboxConfigError, "not on a PersistentVolumeClaim"):
            resolve_volume(mounts, Path("/tmp/heym-code-runs/abc"), "/x", False)
        with self.assertRaisesRegex(SandboxConfigError, "whole claim"):
            resolve_volume(mounts, Path("/app/data"), "/x", False)

    def test_placement_by_access_mode(self) -> None:
        client = MagicMock()
        client.namespace = "heym"
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteMany"]}}
        self.assertIsNone(placement_node(client, {"heym-data"}, BACKEND_POD))
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteOnce"]}}
        self.assertEqual(placement_node(client, {"heym-data"}, BACKEND_POD), "node-a")
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteOncePod"]}}
        with self.assertRaises(SandboxConfigError):
            placement_node(client, {"heym-data"}, BACKEND_POD)
        client.get_pvc.return_value = None
        with self.assertRaisesRegex(SandboxConfigError, "does not exist"):
            placement_node(client, {"heym-data"}, BACKEND_POD)
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_k8s_workspace.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `workspace.py`**

```python
"""Map a backend path to the PersistentVolumeClaim behind it.

The Kubernetes counterpart of inspecting the backend container's Docker mounts: the
backend pod's own volumeMounts say which claim holds a path, so a sandbox pod can
mount exactly that subPath and nothing above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.client import KubeClient
from app.services.sandbox.kubernetes.pod import PodVolume
from app.services.sandbox.spec import OperatorMount


@dataclass(frozen=True)
class ClaimMount:
    """One PVC mount of the backend pod."""

    mount_path: str
    claim: str
    sub_path: str


def claim_mounts(pod: dict[str, Any]) -> list[ClaimMount]:
    """Every PVC the backend pod mounts, with where and which subPath."""
    spec = pod.get("spec") or {}
    claims = {
        volume.get("name"): (volume.get("persistentVolumeClaim") or {}).get("claimName")
        for volume in spec.get("volumes") or []
        if volume.get("persistentVolumeClaim")
    }
    mounts: list[ClaimMount] = []
    for container in spec.get("containers") or []:
        for mount in container.get("volumeMounts") or []:
            claim = claims.get(mount.get("name"))
            if claim:
                mounts.append(
                    ClaimMount(
                        mount_path=str(mount.get("mountPath") or "").rstrip("/") or "/",
                        claim=str(claim),
                        sub_path=str(mount.get("subPath") or "").strip("/"),
                    )
                )
    return mounts


def resolve_volume(
    mounts: list[ClaimMount], host_path: Path, target: str, readonly: bool
) -> PodVolume:
    """The claim and subPath holding ``host_path``; never a whole claim."""
    host = PurePosixPath(host_path).as_posix()
    best: ClaimMount | None = None
    for mount in mounts:
        prefix = mount.mount_path.rstrip("/") + "/"
        if host == mount.mount_path or host.startswith(prefix):
            if best is None or len(mount.mount_path) > len(best.mount_path):
                best = mount
    if best is None:
        raise SandboxConfigError(
            f"{host} is not on a PersistentVolumeClaim the backend pod mounts, so a sandbox pod "
            "cannot see it. Mount a claim at the workspace directory (see deploy/kubernetes)."
        )
    rel = host[len(best.mount_path) :].strip("/")
    if not rel:
        raise SandboxConfigError(f"refusing to mount the whole claim {best.claim} into a sandbox")
    if ".." in PurePosixPath(rel).parts:
        raise SandboxConfigError(f"{host} escapes its claim")
    sub_path = "/".join(part for part in (best.sub_path, rel) if part)
    return PodVolume(claim=best.claim, sub_path=sub_path, target=target, readonly=readonly)


def operator_volume(mount: OperatorMount) -> PodVolume:
    """The MCP files mount on Kubernetes: a claim, never a host path."""
    if mount.host_dir or not mount.volume:
        raise SandboxConfigError(
            "HEYM_MCP_STDIO_FILES_HOST_DIR names a host directory, and Kubernetes sandboxes never "
            "mount host paths. Set HEYM_MCP_STDIO_FILES_VOLUME to a PersistentVolumeClaim name."
        )
    return PodVolume(
        claim=mount.volume,
        sub_path=(mount.subpath or "").strip("/"),
        target=mount.target,
        readonly=not mount.writable,
    )


def placement_node(
    client: KubeClient, claims: set[str], self_pod: dict[str, Any] | None
) -> str | None:
    """None when every claim is ReadWriteMany; else the backend's node (ReadWriteOnce)."""
    node: str | None = None
    for claim in sorted(claims):
        pvc = client.get_pvc(claim)
        if pvc is None:
            raise SandboxConfigError(
                f"PersistentVolumeClaim {claim} does not exist in namespace {client.namespace}. "
                "A separate sandbox namespace needs its own claim on the same share "
                "(see deploy/kubernetes/README.md)."
            )
        modes = set(
            (pvc.get("status") or {}).get("accessModes")
            or (pvc.get("spec") or {}).get("accessModes")
            or []
        )
        if "ReadWriteMany" in modes:
            continue
        if "ReadWriteOncePod" in modes:
            raise SandboxConfigError(
                f"PersistentVolumeClaim {claim} is ReadWriteOncePod, so no sandbox pod can mount "
                "it next to the backend. Use ReadWriteMany, or ReadWriteOnce on one node."
            )
        node = ((self_pod or {}).get("spec") or {}).get("nodeName")
        if not node:
            raise SandboxConfigError(
                f"PersistentVolumeClaim {claim} is ReadWriteOnce, so sandboxes must run on the "
                "backend's node, and that node is unknown."
            )
    return node
```

- [ ] **Step 4: Run the test**

Run: `PYTEST tests/test_sandbox_k8s_workspace.py`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/workspace.py backend/tests/test_sandbox_k8s_workspace.py
git commit -m "feat(sandbox): map workspace paths to pvc subpaths"
```

## Task 33: Workspace and operator mounts in the Kubernetes backend

**Files:**
- Modify: `backend/app/services/sandbox/kubernetes/backend.py`
- Modify: `backend/tests/test_sandbox_k8s_backend.py`

- [ ] **Step 1: Replace the Milestone 3 placeholder test with mapping tests**

Delete `test_workspace_mounts_fail_closed_until_milestone_4` and add:

```python
from pathlib import Path

from app.services.sandbox.spec import DockerVolumeSource, OperatorMount, WorkspaceMount

BACKEND_POD = {
    "spec": {
        "nodeName": "node-a",
        "containers": [{"image": "img", "volumeMounts": [{"name": "data", "mountPath": "/app/data"}]}],
        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "heym-data"}}],
    }
}


def _mounted_spec(path: str = "/app/data/codex-workspaces/_code-runs/abc") -> SandboxSpec:
    source = DockerVolumeSource(Path("/app/data/codex-workspaces"), (), "m")
    mount = WorkspaceMount(Path(path), path, True, source)
    return SandboxSpec(site="code-run", name="n", image="i", entrypoint="python", workspace_mounts=(mount,))


class WorkspaceMountTest(unittest.TestCase):
    def _backend(self, modes: list[str]) -> KubernetesBackend:
        client = MagicMock()
        client.get_pod.return_value = BACKEND_POD
        client.get_pvc.return_value = {"status": {"accessModes": modes}}
        return _backend(client)

    def test_rwx_claim_mounts_only_the_run_subpath_anywhere(self) -> None:
        manifest = self._backend(["ReadWriteMany"]).manifest(_mounted_spec(), 5)
        mounts = manifest["spec"]["containers"][0]["volumeMounts"]
        self.assertIn(
            {"name": "ws-0", "mountPath": "/app/data/codex-workspaces/_code-runs/abc",
             "subPath": "codex-workspaces/_code-runs/abc", "readOnly": True},
            mounts,
        )
        self.assertNotIn("nodeName", manifest["spec"])

    def test_rwo_claim_pins_to_the_backend_node(self) -> None:
        manifest = self._backend(["ReadWriteOnce"]).manifest(_mounted_spec(), 5)
        self.assertEqual(manifest["spec"]["nodeName"], "node-a")

    def test_path_outside_every_claim_fails_closed(self) -> None:
        with self.assertRaises(SandboxConfigError):
            self._backend(["ReadWriteMany"]).manifest(_mounted_spec("/tmp/elsewhere/abc"), 5)

    def test_operator_host_dir_is_refused(self) -> None:
        spec = SandboxSpec(site="mcp-stdio", name="n", image="i", entrypoint="npx",
                           operator_mount=OperatorMount(target="/mnt/f", host_dir="/srv"))
        with self.assertRaises(SandboxConfigError):
            self._backend(["ReadWriteMany"]).manifest(spec, None)
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST tests/test_sandbox_k8s_backend.py`
Expected: the four new tests FAIL with the Milestone 3 message ("does not mount yet").

- [ ] **Step 3: Replace `pod_volumes` in `backend.py`**

Import `claim_mounts`, `operator_volume`, `placement_node`, `resolve_volume` from `app.services.sandbox.kubernetes.workspace`, add `self._placements: dict[frozenset[str], str | None] = {}` to `__init__`, and replace `pod_volumes`:

```python
    def pod_volumes(self, spec: SandboxSpec) -> tuple[tuple[PodVolume, ...], str | None]:
        """Workspace and operator mounts as PVC subPaths, plus the node to pin to (if any)."""
        volumes: list[PodVolume] = []
        if spec.workspace_mounts:
            mounts = claim_mounts(self.self_pod() or {})
            volumes.extend(
                resolve_volume(mounts, mount.host_path, mount.target, mount.readonly)
                for mount in spec.workspace_mounts
            )
        if spec.operator_mount is not None:
            volumes.append(operator_volume(spec.operator_mount))
        if not volumes:
            return (), None
        claims = frozenset(volume.claim for volume in volumes)
        if claims not in self._placements:
            self._placements[claims] = placement_node(self._client, set(claims), self.self_pod())
        return tuple(volumes), self._placements[claims]
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_sandbox_k8s_backend.py tests/test_advisory_k8s_sandbox.py`
Expected: all pass.

- [ ] **Step 5: Add the workspace invariant to the advisory test**

Append to `RestrictedPodAdvisoryTest` in `test_advisory_k8s_sandbox.py`:

```python
    def test_workspace_pods_never_mount_a_whole_claim(self) -> None:
        from unittest.mock import MagicMock

        from app.services.sandbox.kubernetes.backend import KubernetesBackend
        from app.services.sandbox.kubernetes.config import KubeConfig

        client = MagicMock()
        client.namespace = "heym"
        client.has_api_group.return_value = False
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteMany"]}}
        client.get_pod.return_value = {
            "spec": {
                "containers": [{"image": "i", "volumeMounts": [{"name": "d", "mountPath": "/app/data"}]}],
                "volumes": [{"name": "d", "persistentVolumeClaim": {"claimName": "heym-data"}}],
            }
        }
        config = KubeConfig(server="https://k", namespace="heym", own_namespace="heym", in_cluster=True)
        backend = KubernetesBackend(config, client=client, instance="heym-0")
        with patch.dict(os.environ, {"HEYM_CODEX_WORKSPACE_DIR": "/app/data/codex-workspaces"}):
            spec = skill_python_executor._skill_spec(
                "img", "n", Path("/app/data/codex-workspaces"),
                Path("/app/data/codex-workspaces/_skill-workspaces/_skills/abc"), "main.py",
            )
        manifest = backend.manifest(spec, 5)
        claim_mounts = [m for m in manifest["spec"]["containers"][0]["volumeMounts"] if m["name"].startswith("ws-")]
        self.assertEqual(len(claim_mounts), 1)
        self.assertEqual(claim_mounts[0]["subPath"], "codex-workspaces/_skill-workspaces/_skills/abc")
```

Run: `PYTEST tests/test_advisory_k8s_sandbox.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/sandbox/kubernetes/backend.py backend/tests/test_sandbox_k8s_backend.py backend/tests/test_advisory_k8s_sandbox.py
git commit -m "feat(sandbox): workspace sandboxes mount their run subpath on kubernetes"
```

## Task 34: Runner services pass the backend and a deadline; Codex flag; OpenCode cleanup

**Files:**
- Modify: `backend/app/services/codex_runner_service.py`, `backend/app/services/opencode_runner_service.py`
- Test: `backend/tests/test_sandbox_runner_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.codex_runner_service import CodexRunnerService
from app.services.opencode_runner_service import OpenCodeRunnerService


def _manager(name: str) -> MagicMock:
    manager = MagicMock()
    manager.backend_name = name
    return manager


class CodexWiringTest(unittest.TestCase):
    def test_danger_full_access_only_for_the_shim_on_kubernetes(self) -> None:
        cases = (
            ("/usr/local/bin/heym-codex-docker", "kubernetes", "danger-full-access"),
            ("/usr/local/bin/heym-codex-docker", "docker", "workspace-write"),
            ("codex", "kubernetes", "workspace-write"),
        )
        for cli, backend, expected in cases:
            with self.subTest(cli=cli, backend=backend), patch(
                "app.services.codex_runner_service.get_sandbox_manager", return_value=_manager(backend)
            ):
                service = CodexRunnerService(cli_command=cli, workspace_root="/tmp/x")
                self.assertEqual(service._codex_sandbox_mode(), expected)

    def test_child_env_names_the_backend(self) -> None:
        with patch("app.services.codex_runner_service.get_sandbox_manager", return_value=_manager("kubernetes")):
            env = CodexRunnerService(cli_command="codex", workspace_root="/tmp/x")._safe_env()
        self.assertEqual(env["HEYM_SANDBOX_BACKEND"], "kubernetes")


class OpenCodeWiringTest(unittest.TestCase):
    def test_kubernetes_cleanup_deletes_the_pod_by_name(self) -> None:
        manager = _manager("kubernetes")
        with patch("app.services.opencode_runner_service.get_sandbox_manager", return_value=manager):
            OpenCodeRunnerService._remove_runner_container("abc123")
        manager.force_remove.assert_called_once_with("heym-opencode-abc123")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_runner_wiring.py`
Expected: FAIL, `AttributeError: ... has no attribute 'get_sandbox_manager'`.

- [ ] **Step 3: Codex runner**

In `codex_runner_service.py` add the imports `from app.services.sandbox import get_sandbox_manager` and `from app.services.sandbox.coding_agents import DEADLINE_ENV`, then:

```python
    def _codex_sandbox_mode(self) -> str:
        """``danger-full-access`` only when Codex runs inside a Kubernetes sandbox pod.

        Bubblewrap cannot run in a restricted pod, so there the pod is the boundary. A host
        ``codex`` binary keeps Codex's own sandbox whatever the backend.
        """
        wrapped = Path(self.cli_command).name == "heym-codex-docker"
        if wrapped and get_sandbox_manager().backend_name == "kubernetes":
            return "danger-full-access"
        return "workspace-write"
```

Replace the two sandbox lines in the exec command builder:

```python
        sandbox_mode = self._codex_sandbox_mode()
        if resume_thread_id:
            # `codex exec resume` rejects --sandbox; set the sandbox via config override instead.
            cmd.extend(["-c", f'sandbox_mode="{sandbox_mode}"'])
        else:
            cmd.extend(["--sandbox", sandbox_mode])
```

In `_safe_env`, before `return env`: `env["HEYM_SANDBOX_BACKEND"] = get_sandbox_manager().backend_name`.
In `_codex_login`, after `env = self._codex_env(...)`: `env[DEADLINE_ENV] = str(int(min(timeout_seconds, 120)) + 60)`.
In the exec call, build the env first and add the deadline:

```python
        exec_env = self._codex_env(workspace, codex_access_token)
        exec_env[DEADLINE_ENV] = str(int(timeout_seconds) + 60)
```

and pass `env=exec_env` to `subprocess.run`.

- [ ] **Step 4: OpenCode runner**

In `opencode_runner_service.py` add the same two imports. In `_safe_env`: `env["HEYM_SANDBOX_BACKEND"] = get_sandbox_manager().backend_name`. In `_exec_opencode` after `env["HEYM_OPENCODE_RUN_ID"] = run_id`: `env[DEADLINE_ENV] = str(int(request.timeout_seconds) + 60)`. Replace the head of `_remove_runner_container`:

```python
    @staticmethod
    def _remove_runner_container(run_id: str) -> None:
        """Remove the runner container or pod; a no-op without a sandbox backend."""
        if not run_id:
            return
        manager = get_sandbox_manager()
        if manager.backend_name == "kubernetes":
            manager.force_remove(f"{_RUNNER_CONTAINER_PREFIX}{run_id}")
            return
        if not shutil.which("docker"):
            return
```

(the existing `docker rm -f` call stays below).

- [ ] **Step 5: Run the runner suites**

Run: `PYTEST tests/test_sandbox_runner_wiring.py tests/test_opencode_runner_service.py tests/test_codex_*.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/codex_runner_service.py backend/app/services/opencode_runner_service.py backend/tests/test_sandbox_runner_wiring.py
git commit -m "feat(sandbox): codex and opencode runners follow the sandbox backend"
```

## Task 35: `wrapper_cli` on Kubernetes

**Files:**
- Modify: `backend/app/services/sandbox/wrapper_cli.py`
- Modify: `backend/tests/test_sandbox_wrapper_cli.py`

- [ ] **Step 1: Add the failing test**

```python
class KubernetesPathTest(unittest.TestCase):
    def test_opens_the_run_to_the_pod_user_and_attaches(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        (root / RUN).mkdir()
        (root / f"{RUN}.codex-home").mkdir()
        secret = root / f"{RUN}.codex-home" / "auth.json"
        secret.write_text("{}")
        secret.chmod(0o600)
        backend = MagicMock()
        backend.manifest.return_value = {"metadata": {"name": "heym-codex-1"}}
        manager = MagicMock()
        manager.backend_name = "kubernetes"
        manager.available.return_value = True
        manager.backend = backend
        manager.resolve_image.return_value = "img"
        env = {"HEYM_CODEX_WORKSPACE_DIR": str(root), "CODEX_HOME": f"{root}/{RUN}.codex-home"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(wrapper_cli, "get_sandbox_manager", return_value=manager),
            patch.object(wrapper_cli.Path, "cwd", return_value=root / RUN),
            patch("app.services.sandbox.kubernetes.process.run_attached", return_value=7) as attached,
        ):
            self.assertEqual(wrapper_cli.main(["codex", "exec"]), 7)
        spec = backend.manifest.call_args.args[0]
        self.assertTrue(spec.start_gate)
        self.assertIn("GIT_CONFIG_VALUE_0=*", spec.env)
        self.assertEqual(attached.call_args.kwargs["start_gate"], True)
        self.assertEqual(secret.stat().st_mode & 0o666, 0o666)

    def test_unavailable_kubernetes_fails_without_a_pod(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        (root / RUN).mkdir()
        (root / f"{RUN}.codex-home").mkdir()
        manager = MagicMock()
        manager.backend_name = "kubernetes"
        manager.available.return_value = False
        manager.resolve_image.return_value = "img"
        env = {"HEYM_CODEX_WORKSPACE_DIR": str(root), "CODEX_HOME": f"{root}/{RUN}.codex-home"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(wrapper_cli, "get_sandbox_manager", return_value=manager),
            patch.object(wrapper_cli.Path, "cwd", return_value=root / RUN),
        ):
            self.assertEqual(wrapper_cli.main(["codex", "exec"]), 127)
        manager.backend.manifest.assert_not_called()
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTEST tests/test_sandbox_wrapper_cli.py`
Expected: the two new tests FAIL (the wrapper always takes the Docker path).

- [ ] **Step 3: Add the Kubernetes path**

In `wrapper_cli.py`, add `import stat` and replace the last line of `main` with:

```python
    if kubernetes:
        return _run_kubernetes(manager, spec, (scope.workspace, scope.home))
    return _run_docker(manager, spec)
```

and add:

```python
def _open_to_sandbox_user(root: Path) -> None:
    """The pod runs as 65534 (or an OpenShift-assigned uid); the backend wrote these as root."""

    def widen(path: str, directory: bool) -> None:
        try:
            info = os.lstat(path)
        except OSError:
            return
        if stat.S_ISLNK(info.st_mode):
            return
        executable = directory or bool(info.st_mode & 0o111)
        mode = stat.S_IMODE(info.st_mode) | 0o666 | (0o111 if executable else 0)
        try:
            os.chmod(path, mode)
        except OSError:
            pass

    widen(str(root), True)
    for current, dirs, files in os.walk(root):
        for name in dirs:
            widen(os.path.join(current, name), True)
        for name in files:
            widen(os.path.join(current, name), False)


def _run_kubernetes(manager: SandboxManager, spec: SandboxSpec, run_dirs: tuple[Path, Path]) -> int:
    from app.services.sandbox.kubernetes import process

    if not manager.available():
        reason = getattr(manager.backend, "unavailable_reason", "") or "unknown reason"
        print(f"The Kubernetes sandbox backend is unavailable: {reason}", file=sys.stderr)
        return 127
    for directory in run_dirs:
        _open_to_sandbox_user(directory)
    backend = manager.backend
    return process.run_attached(
        backend.client,
        backend.manifest(spec, None),
        start_gate=spec.start_gate,
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
    )
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST tests/test_sandbox_wrapper_cli.py tests/test_sandbox_import_rule.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sandbox/wrapper_cli.py backend/tests/test_sandbox_wrapper_cli.py
git commit -m "feat(sandbox): codex and opencode run as scoped pods on kubernetes"
```

## Task 36: In-cluster smoke test on OrbStack

**Files:**
- Create: `scripts/k8s-sandbox-smoke.sh`, `scripts/k8s_sandbox_smoke.py`

- [ ] **Step 1: Write `scripts/k8s_sandbox_smoke.py`**

```python
"""Exercise every sandbox site from inside the backend pod. Run by k8s-sandbox-smoke.sh."""

import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

FAILURES: list[str] = []


def check(label: str, run: Callable[[], str]) -> None:
    try:
        print(f"OK   {label}: {run()}", flush=True)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports every failure and goes on
        print(f"FAIL {label}: {exc!r}", flush=True)
        FAILURES.append(label)


def python_tool() -> str:
    from app.services.python_tool_executor import execute_tool

    assert execute_tool("def f(a):\n    return a * 2\n", "f", {"a": 21}, 120) == 42
    return "42"


def formatter() -> str:
    from app.services.code_formatter import format_python

    assert format_python("x=1\n") == "x = 1\n"
    return "formatted"


def code_with_requirements() -> str:
    from app.services.code_python_executor import execute_code

    result = execute_code("import six\ndef main(params):\n    return six.__name__\n", "six==1.16.0", {}, False)
    assert result.result == "six", result
    return f"installed with {result.install_tool}"


def file_sandbox() -> str:
    from app.services.file_sandbox.executor import build_payload, run_in_sandbox
    from app.services.file_sandbox.workspace import FileWorkspace

    workspace = FileWorkspace.for_run(uuid.uuid4())
    workspace.ensure()
    try:
        code = "open('/work/out/report.txt', 'w').write('x')\nprint('done')"
        outcome = run_in_sandbox(workspace, build_payload("python", code=code))
        assert outcome.success, outcome.error
        collected, _ = workspace.collect_outputs()
        assert [f.name for f in collected] == ["report.txt"]
        return "report.txt collected"
    finally:
        workspace.delete()


def skill() -> str:
    from app.services.skill_python_executor import execute_skill_python

    source = (
        "import json, os\n"
        "open(os.path.join(os.environ['_OUTPUT_DIR'], 'hello.txt'), 'w').write('hi')\n"
        "print(json.dumps({'ok': True}))\n"
    )
    result = execute_skill_python([{"path": "main.py", "content": source}], {"input": "x"}, 120)
    assert result.output == {"ok": True}, result.output
    assert [f["filename"] for f in result.generated_files] == ["hello.txt"]
    return "hello.txt generated"


def mcp_stdio() -> str:
    from app.services.mcp_stdio_sandbox import build_sandboxed_command

    echo = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line.upper()); sys.stdout.flush()\n"
    command = build_sandboxed_command("python", ["-c", echo], None)
    result = subprocess.run(
        command.argv, input="ping\n", env={**os.environ, **command.env},
        capture_output=True, text=True, timeout=180,
    )
    assert result.stdout == "PING\n", result.stderr
    return "PING"


def coding_agent_scope(agent: str, home_suffix: str, home_env: str) -> str:
    root = Path(os.environ.get(f"HEYM_{agent.upper()}_WORKSPACE_DIR", f"/app/data/{agent}-workspaces"))
    own, other = uuid.uuid4().hex, uuid.uuid4().hex
    for run in (own, other):
        (root / run).mkdir(parents=True)
        (root / f"{run}{home_suffix}").mkdir()
        (root / f"{run}{home_suffix}" / "auth.json").write_text(f"secret-{run}")
    try:
        env = {
            **os.environ,
            home_env: str(root / f"{own}{home_suffix}"),
            f"HEYM_{agent.upper()}_DOCKER_ENTRYPOINT": "sh",
            "HEYM_SANDBOX_DEADLINE_SECONDS": "180",
        }
        script = f"ls -a {root}; cat {root}/{other}{home_suffix}/auth.json 2>/dev/null || echo BLOCKED"
        result = subprocess.run(
            [f"/usr/local/bin/heym-{agent}-docker", "-c", script],
            cwd=root / own, env=env, capture_output=True, text=True, timeout=300,
        )
        seen = set(result.stdout.split())
        assert "BLOCKED" in seen, result.stdout + result.stderr
        assert other not in seen and f"{other}{home_suffix}" not in seen, result.stdout
        return "only its own run is visible"
    finally:
        for run in (own, other):
            shutil.rmtree(root / run, ignore_errors=True)
            shutil.rmtree(root / f"{run}{home_suffix}", ignore_errors=True)


def playwright() -> str:
    from app.services.playwright_sandbox import run_script

    code, out, err = run_script("import os\nprint(os.getuid())\n", 120)
    assert (code, out.strip()) == (0, "65534"), err
    return "uid 65534"


if __name__ == "__main__":
    from app.services.sandbox import get_sandbox_manager

    print(f"backend: {get_sandbox_manager().backend_name}", flush=True)
    check("python tool", python_tool)
    check("formatter", formatter)
    check("code node + requirements", code_with_requirements)
    check("file sandbox", file_sandbox)
    check("skill", skill)
    check("mcp stdio", mcp_stdio)
    check("playwright", playwright)
    check("codex scope", lambda: coding_agent_scope("codex", ".codex-home", "CODEX_HOME"))
    check("opencode scope", lambda: coding_agent_scope("opencode", ".oc-home", "HOME"))
    sys.exit(1 if FAILURES else 0)
```

- [ ] **Step 2: Write `scripts/k8s-sandbox-smoke.sh`**

```bash
#!/usr/bin/env bash
# In-cluster smoke test of every sandbox site. Usage: scripts/k8s-sandbox-smoke.sh [context]
set -euo pipefail
CONTEXT="${1:-orbstack}"
HERE="$(cd "$(dirname "$0")" && pwd)"
k() { kubectl --context "$CONTEXT" -n heym "$@"; }

k rollout status deploy/heym --timeout=300s
POD="$(k get pod -l app.kubernetes.io/name=heym -o jsonpath='{.items[0].metadata.name}')"
k exec -i "$POD" -- sh -c '
  for py in /app/.venv/bin/python /app/backend/.venv/bin/python; do
    if [ -x "$py" ]; then cd "$(dirname "$(dirname "$(dirname "$py")")")" && exec "$py" -; fi
  done
  echo "backend virtualenv not found" >&2; exit 127
' < "$HERE/k8s_sandbox_smoke.py"

sleep 2
LEFT="$(kubectl --context "$CONTEXT" get pods -A -l app.kubernetes.io/managed-by=heym --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [ "$LEFT" != "0" ]; then
  echo "FAIL: $LEFT sandbox pods left behind"
  kubectl --context "$CONTEXT" get pods -A -l app.kubernetes.io/managed-by=heym
  exit 1
fi
echo "OK: no sandbox pods left behind"
```

`chmod +x scripts/k8s-sandbox-smoke.sh`

- [ ] **Step 3: Deploy to OrbStack and run it**

```bash
docker compose build backend
kubectl --context orbstack apply -k deploy/kubernetes/overlays/orbstack
kubectl --context orbstack -n heym create secret generic heym-secrets \
  --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/heym \
  --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)
kubectl --context orbstack -n heym rollout restart deploy/heym
./scripts/k8s-sandbox-smoke.sh orbstack
```

Expected: `backend: kubernetes`, nine `OK` lines, then `OK: no sandbox pods left behind`. If `code node + requirements` fails on DNS, check `kubectl --context orbstack get pods -n kube-system --show-labels` still shows `k8s-app=kube-dns` on CoreDNS.

- [ ] **Step 4: Tear down**

Run: `kubectl --context orbstack delete namespace heym`

- [ ] **Step 5: Commit**

```bash
git add scripts/k8s-sandbox-smoke.sh scripts/k8s_sandbox_smoke.py
git commit -m "test(sandbox): in-cluster smoke test of every sandbox site"
```

## Task 37: Docs

**Files:**
- Modify: `ENVIRONMENT-VARIABLES.md`, `frontend/src/docs/content/getting-started/running-and-deployment.md`, `frontend/src/docs/content/reference/cluster.md`, `frontend/src/docs/content/nodes/{code-node,codex-node,opencode-go-node,playwright-node,agent-node}.md`, `frontend/src/docs/content/reference/{security,file-analysis}.md`, `AGENTS.md`

Load the `heym-documentation` skill first if it is available in the session. No release tour entry: nothing in the UI changes.

- [ ] **Step 1: `ENVIRONMENT-VARIABLES.md`, new section above the Python tool sandbox section**

```markdown
### Sandbox backend

Every sandbox (Agent Python tools, skills, the Code node and its formatter, file
analysis, custom Playwright, MCP stdio, Codex, OpenCode) runs through one sandbox
backend: Docker sibling containers, or pods created through the Kubernetes API.
Docker stays the default. Per-site variables such as `HEYM_PYTHON_TOOL_SANDBOX` still
choose between a sandbox and `subprocess`; this one chooses where sandboxes run.

| Variable | Description | Default |
|---|---|---|
| `HEYM_SANDBOX_BACKEND` | `auto` uses Docker when a daemon answers, else Kubernetes when the backend runs in a pod with a ServiceAccount, else fails closed. `docker` and `kubernetes` force one and never fall back. | `auto` |
| `HEYM_SANDBOX_K8S_NAMESPACE` | Namespace for sandbox pods. Workspace sandboxes need the workspace claim in that namespace. | backend's namespace |
| `HEYM_SANDBOX_K8S_POD_OVERRIDES` | JSON with only `nodeSelector`, `tolerations`, `runtimeClassName`, `imagePullSecrets`, `priorityClassName`. Any other key disables the backend. | none |

On Kubernetes, `HEYM_MCP_STDIO_FILES_VOLUME` names a PersistentVolumeClaim and
`HEYM_MCP_STDIO_FILES_SUBPATH` its subPath; `HEYM_MCP_STDIO_FILES_HOST_DIR` is refused.
Requirements and manifests: `deploy/kubernetes/README.md`.

Codex and OpenCode runners mount only their own run's workspace and home. With a
named workspace volume both need Docker Engine 25.0+ (`volume-subpath`).
```

- [ ] **Step 2: `running-and-deployment.md`, new section before `## Running More Than One Instance`**

```markdown
## Kubernetes

Heym runs on clusters without a Docker daemon (containerd-only nodes, Talos,
Bottlerocket, OpenShift). With `HEYM_SANDBOX_BACKEND` left at `auto`, a backend pod
with a ServiceAccount runs every sandbox as its own pod through the Kubernetes API:
non-root, no capabilities, no ServiceAccount token, Pod Security `restricted`.

Start from the example manifests in `deploy/kubernetes/`. You need Kubernetes 1.30+,
a CNI that enforces NetworkPolicy (Heym checks before the first offline sandbox and
refuses to run without it), and one PersistentVolumeClaim at `/app/data`. With
`ReadWriteMany` sandboxes can run on any node; with `ReadWriteOnce` they run on the
backend's node.
```

- [ ] **Step 3: Remaining pages**

- `reference/cluster.md` line 33: "Every instance runs the same image with its own Docker socket" becomes "Every instance runs the same image with its own sandbox backend (a Docker socket, or Kubernetes API access)". Where the page describes the instance list's Docker status, note that it means "a sandbox backend is reachable".
- `nodes/code-node.md`, `nodes/playwright-node.md`, `nodes/agent-node.md`, `reference/file-analysis.md`, `reference/security.md`: wherever a sentence says the sandbox requires Docker, say it requires a sandbox backend (Docker, or Kubernetes, see Running & Deployment). Run `grep -n "Docker" <file>` on each and change only sandbox requirements, not unrelated Docker mentions.
- `nodes/codex-node.md`, `nodes/opencode-go-node.md`: add "Each run sees only its own workspace and home directory." On Kubernetes, Codex runs with `danger-full-access` because the pod is the sandbox; say so in one sentence.
- `AGENTS.md`, "Node placement" section: "Every instance in a cluster runs the same image with its own Docker socket" becomes "...with its own Docker socket or Kubernetes API access".

- [ ] **Step 4: Frontend checks**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: pass (docs are Markdown; the manifest is untouched).

- [ ] **Step 5: Commit**

```bash
git add ENVIRONMENT-VARIABLES.md AGENTS.md frontend/src/docs/content
git commit -m "docs: kubernetes sandbox backend and scoped coding agent runs"
```

## Task 38: Final gate

- [ ] **Step 1: Bring the spec in line with what was built**

The spec already records what was settled while planning (thirteen call sites, the janitor without a startup sweep, the Codex flag only for the shim, the heartbeat in Milestone 3). Add only what changed during implementation, in `docs/superpowers/specs/2026-11-02-kubernetes-sandbox-backend-design.md`, and nothing if nothing did.

- [ ] **Step 2: Everything green**

```bash
SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
cd backend && HEYM_K8S_LIVE_CONTEXT=orbstack SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/live -v
```

Expected: `check.sh` green; live tests `4 passed`. Task 36's smoke run is the in-cluster proof; re-run it if anything under `app/services/sandbox/` changed since.

- [ ] **Step 3: Commit the spec update and any formatting**

```bash
git add -A docs backend && git commit -m "docs: align sandbox spec with the implementation" || true
```

- [ ] **Step 4: Stop here until Burak asks for the PR**

Do not push. When asked: `git push -u origin impl/native-k8s-api-and-pod-management` and `gh pr create --base main` with a body that lists the four milestones, calls out the Docker behavior change of Milestone 2 (Codex/OpenCode see only their run; OpenCode with a named volume needs Docker Engine 25+), links #832, and has no Claude attribution line.

---

## Self-review (done while writing)

- **Spec coverage:** Manager and backend selection (Tasks 4, 25), Docker parity (1, 5 to 10), run scope on Docker and Kubernetes (11 to 16, 35), API client and attach (17 to 20), restricted pods and overrides (21), offline canary (22), lifecycle and start failures (20, 23), bridge for MCP/Codex/OpenCode (24, 35), janitor (26), images and Playwright (23, 27), RBAC, NetworkPolicies and manifests (29), workspaces and RWO pinning (32, 33), operator mount (33), Codex flag and ownership (34, 35), invariants 1 to 8 (15, 28, 33), docs (37), live and smoke tests (30, 36).
- **Names used across tasks:** `SandboxSpec`, `WorkspaceMount`, `DockerVolumeSource`, `OperatorMount`, `SandboxResult.start_failed`, `get_sandbox_manager`, `reset_sandbox_manager`, `render_docker_argv`, `docker_mount_args`, `_docker_rm`, `code_spec`, `workspace_mount`, `_code_workspace_mount`, `_run_spec`, `_install_spec`, `_format_spec`, `_tool_spec`, `_playwright_spec`, `_skill_spec`, `_mcp_spec`, `run_scope`, `agent_spec`, `PROFILES`, `DEADLINE_ENV`, `KubernetesBackend.manifest`, `.client`, `.config`, `.unavailable_reason`, `run_attached`, `PodVolume`, `PodContext`. Each is defined in the task that first uses it.
- **Known edge left as is:** an empty `HEYM_PYTHON_TOOL_USER` used to render `--user ""` and now omits `--user`; both run the image's default user, so behavior is unchanged.
