"""Every trigger hands the workflow's limit to dispatch_workflow, or nothing is gated."""

import ast
import pathlib
import unittest

CALL_SITES = [
    "app/api/telegram.py",
    "app/api/discord.py",
    "app/api/slack.py",
    "app/api/workflows.py",
    "app/api/mcp.py",
    "app/api/mcp_servers.py",
    "app/services/trigger_run_dispatch.py",
    "app/services/heym_event_dispatcher.py",
    "app/services/websocket_trigger_service.py",
    "app/services/rabbitmq_consumer.py",
    "app/services/cron_scheduler.py",
    "app/services/error_workflow_runner.py",
    "app/services/dashboard_data.py",
]


class CallSiteTests(unittest.TestCase):
    def test_every_dispatch_call_passes_concurrency_limit(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        missing: list[str] = []
        for relative in CALL_SITES:
            tree = ast.parse((root / relative).read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "dispatch_workflow"
                    and "concurrency_limit" not in {k.arg for k in node.keywords}
                ):
                    missing.append(f"{relative}:{node.lineno}")
        self.assertEqual(missing, [])
