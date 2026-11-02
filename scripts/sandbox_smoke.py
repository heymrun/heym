"""Exercise every container-creating sandbox from inside a backend container or pod.

Run by ``docker-sandbox-smoke.sh`` (Docker) and ``k8s-sandbox-smoke.sh`` (Kubernetes).
It goes through the same service functions the nodes, the agent and Chat call, so a
pass means the sandbox layer works end to end on that backend. Nothing here talks to
a model or to the database.
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

FAILURES: list[str] = []
SCRATCH = Path(tempfile.mkdtemp(prefix="heym-smoke-"))


def check(label: str, run: Callable[[], str]) -> None:
    try:
        print(f"OK   {label}: {run()}", flush=True)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports every failure and goes on
        print(f"FAIL {label}: {exc!r}", flush=True)
        FAILURES.append(label)


def _csv_file() -> Path:
    path = SCRATCH / "sales.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["region", "amount"])
        writer.writerows([["north", 120], ["south", 80], ["east", 45]])
    return path


def _png_file() -> Path:
    from PIL import Image

    path = SCRATCH / "chart.png"
    Image.new("RGB", (64, 32), (200, 30, 30)).save(path)
    return path


def _drive_ref(path: Path, mime: str):  # noqa: ANN202
    from app.services.file_sandbox.manifest import DriveFileRef

    return DriveFileRef(
        id=uuid.uuid4(),
        name=path.name,
        mime=mime,
        size=path.stat().st_size,
        created_at=datetime.now(timezone.utc),
        source="smoke",
        workflow_id=None,
        shared=False,
        storage_path=path,
    )


# Agent node: Python tools


def agent_python_tool() -> str:
    from app.services.python_tool_executor import execute_tool

    assert execute_tool("def f(a):\n    return a * 2\n", "f", {"a": 21}, 120) == 42
    return "42"


# Code node


def code_formatter() -> str:
    from app.services.code_formatter import format_python

    assert format_python("x=1\n") == "x = 1\n"
    return "formatted"


def code_node_offline() -> str:
    from app.services.code_python_executor import execute_code

    source = (
        "import socket\n"
        "def main(params):\n"
        "    try:\n"
        "        socket.create_connection(('1.1.1.1', 443), timeout=3).close()\n"
        "        return 'online'\n"
        "    except OSError:\n"
        "        return params['n'] + 1\n"
    )
    result = execute_code(source, "", {"n": 1}, False)
    assert result.result == 2, result
    return "ran offline"


def code_node_requirements() -> str:
    from app.services.code_python_executor import execute_code

    result = execute_code(
        "import six\ndef main(params):\n    return six.__name__\n", "six==1.16.0", {}, False
    )
    assert result.result == "six", result
    return f"installed with {result.install_tool}"


def code_node_with_files() -> str:
    from app.services.file_sandbox import code_node
    from app.services.file_sandbox.scope import RunFileScope

    ref = _drive_ref(_csv_file(), "text/csv")
    stored: list[str] = []

    def _store(collected, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        stored.extend(item.name for item in collected)
        return [], []

    source = (
        "import csv\n"
        "def main(params):\n"
        "    path = params['files'][0]['path']\n"
        "    rows = list(csv.DictReader(open(path)))\n"
        "    total = sum(int(r['amount']) for r in rows)\n"
        "    open('/work/out/total.txt', 'w').write(str(total))\n"
        "    return total\n"
    )
    with (
        patch.object(code_node, "resolve_files", return_value=[ref]),
        patch("app.db.session.SessionLocal"),
        patch.object(code_node, "store_outputs", side_effect=_store),
    ):
        result = code_node.execute_code_with_files(
            code=source,
            requirements="",
            params={},
            allow_network=False,
            file_refs=[str(ref.id)],
            actor_id=uuid.uuid4(),
            scope=RunFileScope(file_ids=frozenset({ref.id})),
            workflow_id=None,
            source_label="Code",
        )
    assert result.result == 245, result
    assert stored == ["total.txt"], stored
    return "read sales.csv, wrote total.txt"


# Chat: file analysis sandbox


def chat_file_inspection() -> str:
    from app.services.file_sandbox.executor import build_payload, run_in_sandbox
    from app.services.file_sandbox.workspace import FileWorkspace

    workspace = FileWorkspace.for_chat(uuid.uuid4(), uuid.uuid4())
    workspace.ensure()
    try:
        entries = workspace.add_inputs(
            [_drive_ref(_csv_file(), "text/csv"), _drive_ref(_png_file(), "image/png")]
        )
        for entry in entries:
            target = {"path": entry["path"], "name": entry["name"], "mime": entry["mime"]}
            outcome = run_in_sandbox(workspace, build_payload("inspect", target=target, options={}))
            assert outcome.success, (entry["name"], outcome.error)
        code = (
            "import csv\n"
            f"rows = list(csv.DictReader(open({entries[0]['path']!r})))\n"
            "open('/work/out/north.txt', 'w').write(rows[0]['amount'])\n"
            "print(len(rows))\n"
        )
        outcome = run_in_sandbox(workspace, build_payload("python", code=code))
        assert outcome.success and outcome.stdout.strip() == "3", outcome
        collected, rejected = workspace.collect_outputs()
        assert [f.name for f in collected] == ["north.txt"] and not rejected, (collected, rejected)
        return "inspected csv and png, ran python, collected north.txt"
    finally:
        workspace.delete()


# Agent node: skills (with and without the Drive files toggle)


def skill_output_file() -> str:
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


def skill_drive_files() -> str:
    from app.services.skill_python_executor import execute_skill_python

    notes = SCRATCH / "notes.txt"
    notes.write_text("quarterly target: 245", encoding="utf-8")
    drive_files = [
        {
            "id": str(uuid.uuid4()),
            "filename": "notes.txt",
            "mime_type": "text/plain",
            "size_bytes": notes.stat().st_size,
            "source_path": str(notes),
            "created_at": datetime.now(timezone.utc),
            "workflow_id": None,
        }
    ]
    source = (
        "import json\n"
        "from heym_drive import list_drive_files, read_drive_text\n"
        "print(json.dumps({'files': [f['filename'] for f in list_drive_files()],"
        " 'text': read_drive_text(filename='notes.txt')}))\n"
    )
    result = execute_skill_python(
        [{"path": "main.py", "content": source}], {"input": "x"}, 120, drive_files=drive_files
    )
    assert result.output == {"files": ["notes.txt"], "text": "quarterly target: 245"}, result.output
    return "read notes.txt through heym_drive"


# MCP stdio


def mcp_stdio() -> str:
    from app.services.mcp_stdio_sandbox import build_sandboxed_command

    echo = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line.upper()); sys.stdout.flush()\n"
    command = build_sandboxed_command("python", ["-c", echo], None)
    result = subprocess.run(
        command.argv,
        input="ping\n",
        env={**os.environ, **command.env},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.stdout == "PING\n", result.stderr
    return "PING"


# Playwright node: custom code


def playwright_isolated() -> str:
    from app.services.playwright_sandbox import run_script

    script = (
        "import os\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    browser = p.chromium.launch(args=['--no-sandbox'])\n"
        "    page = browser.new_page()\n"
        "    page.set_content('<title>sandboxed</title>')\n"
        "    print(os.getuid(), page.title())\n"
        "    browser.close()\n"
    )
    code, out, err = run_script(script, 180)
    assert code == 0 and out.strip().endswith("sandboxed"), (code, out, err[-500:])
    return f"chromium ran as uid {out.split()[0]}"


# Codex and OpenCode nodes


def backend_name() -> str:
    """The selected sandbox backend; plain Docker on code that predates the manager."""
    try:
        from app.services.sandbox import get_sandbox_manager
    except ImportError:
        return "docker"
    return get_sandbox_manager().backend_name


def coding_agent(agent: str, home_suffix: str, home_env: str) -> str:
    root = Path(
        os.environ.get(f"HEYM_{agent.upper()}_WORKSPACE_DIR", f"/app/data/{agent}-workspaces")
    )
    own, other = uuid.uuid4().hex, uuid.uuid4().hex
    for run in (own, other):
        (root / run).mkdir(parents=True)
        (root / f"{run}{home_suffix}").mkdir()
        (root / f"{run}{home_suffix}" / "auth.json").write_text(f"secret-{run}")
    wrapper = f"/usr/local/bin/heym-{agent}-docker"
    env = {
        **os.environ,
        home_env: str(root / f"{own}{home_suffix}"),
        "HEYM_SANDBOX_BACKEND": backend_name(),
        "HEYM_SANDBOX_DEADLINE_SECONDS": "300",
    }
    try:
        version = subprocess.run(
            [wrapper, "--version"],
            cwd=root / own,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert version.returncode == 0 and version.stdout.strip(), version.stderr[-500:]
        script = (
            f"ls -a {root}; cat {root}/{other}{home_suffix}/auth.json 2>/dev/null || echo BLOCKED"
        )
        scope = subprocess.run(
            [wrapper, "-c", script],
            cwd=root / own,
            env={**env, f"HEYM_{agent.upper()}_DOCKER_ENTRYPOINT": "sh"},
            capture_output=True,
            text=True,
            timeout=300,
        )
        seen = set(scope.stdout.split())
        assert "BLOCKED" in seen, scope.stdout + scope.stderr
        assert other not in seen and f"{other}{home_suffix}" not in seen, scope.stdout
        return f"{agent} {version.stdout.strip().splitlines()[-1]}; only its own run is visible"
    finally:
        for run in (own, other):
            shutil.rmtree(root / run, ignore_errors=True)
            shutil.rmtree(root / f"{run}{home_suffix}", ignore_errors=True)


if __name__ == "__main__":
    print(f"backend: {backend_name()}", flush=True)
    checks = [
        ("agent python tool", agent_python_tool),
        ("code node formatter", code_formatter),
        ("code node offline", code_node_offline),
        ("code node + requirements", code_node_requirements),
        ("code node + drive files", code_node_with_files),
        ("chat file sandbox", chat_file_inspection),
        ("agent skill", skill_output_file),
        ("agent skill + drive files toggle", skill_drive_files),
        ("mcp stdio", mcp_stdio),
        ("playwright custom code", playwright_isolated),
        ("codex", lambda: coding_agent("codex", ".codex-home", "CODEX_HOME")),
        ("opencode", lambda: coding_agent("opencode", ".oc-home", "HOME")),
    ]
    for label, run in checks:
        check(label, run)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    print(json.dumps({"backend": backend_name(), "failed": FAILURES}), flush=True)
    sys.exit(1 if FAILURES else 0)
