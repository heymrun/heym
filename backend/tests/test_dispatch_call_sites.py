"""Every trigger that dispatches a workflow run passes the workflow's own settings along.

The workflow timeout is documented to apply to manual, API and triggered runs, but it is
only enforced when the caller hands it to dispatch_workflow. A caller that passes the
workflow's concurrency_limit is running that workflow for a trigger, so it must pass the
workflow's timeout as well.
"""

import ast
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _dispatch_calls() -> list[tuple[str, int, set[str]]]:
    calls = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "dispatch_workflow":
                continue
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            calls.append((str(path.relative_to(APP_DIR.parent)), node.lineno, keywords))
    return calls


class DispatchCallSiteTests(unittest.TestCase):
    def test_the_scan_finds_the_trigger_call_sites(self) -> None:
        gated = [c for c in _dispatch_calls() if "concurrency_limit" in c[2]]
        self.assertGreaterEqual(len(gated), 10)

    def test_every_gated_dispatch_passes_the_workflow_timeout(self) -> None:
        missing = [
            f"{path}:{line}"
            for path, line, keywords in _dispatch_calls()
            if "concurrency_limit" in keywords and "timeout_seconds" not in keywords
        ]
        self.assertEqual(missing, [])
