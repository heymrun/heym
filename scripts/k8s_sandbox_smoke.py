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
