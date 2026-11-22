"""Node pages name the outputs their handlers return, and their examples do what they say.

The Crawler page listed `$nodeLabel.body`, which the node never returns (it returns `html`,
`url`, `status` and, in extract mode, `extracted`), and its selector example had no `name`
and no `crawlerMode: "extract"`, so it extracted nothing. The Slack, Discord and Telegram
trigger pages listed `triggered_by` and `trigger_node_id`, which are run inputs the trigger
nodes do not copy into their output, and the Condition and Switch pages said the input
passes through, while they output only their branch.
"""

from __future__ import annotations

import json
import re
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services import ssrf_guard
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import (
    crawler_node,
    discord_trigger_node,
    slack_trigger_node,
    telegram_trigger_node,
)
from app.services.workflow_executor import WorkflowExecutor

DOCS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "docs" / "content" / "nodes"

PAGE_HTML = (
    "<html><body><h1>Release notes</h1>"
    '<a class="post-link" href="/posts/1">One</a><a class="post-link" href="/posts/2">Two</a>'
    "</body></html>"
)


def _page(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _overview_fields(page: str) -> set[str]:
    """The `$nodeLabel.<field>` names in the Overview table's Output row."""
    row = re.search(r"^\| Output \|(.+)\|$", page, re.MULTILINE)
    assert row is not None
    return set(re.findall(r"\$nodeLabel\.(\w+)", row.group(1)))


def _first_json_example(page: str) -> dict:
    block = re.search(r"```json\n(.+?)```", page, re.DOTALL)
    assert block is not None
    return json.loads(block.group(1))


class _Executor:
    def evaluate_nonempty_message_template(self, template: str, *_args: object) -> str:
        return "https://example.com/blog" if template.startswith("$") else template

    def _get_accessible_credential(self, _db: object, _credential_id: str) -> object:
        return types.SimpleNamespace(encrypted_config=b"ciphertext")


def _run_crawler(node_data: dict) -> dict:
    client = MagicMock()
    client.post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"solution": {"response": PAGE_HTML, "status": 200}}),
    )
    ctx = NodeExecutionContext(
        executor=_Executor(),
        node_id="crawler_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="crawler",
        node_data=node_data,
        node_label=node_data.get("label", "crawler"),
    )
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch(
            "app.services.encryption.decrypt_config",
            return_value={"flaresolverr_url": "http://localhost:8191/v1"},
        ),
        patch.object(ssrf_guard, "guard_carrier_url"),
        patch.object(ssrf_guard, "get_guarded_carrier_http_client", return_value=client),
    ):
        return crawler_node.execute(ctx)


class CrawlerPageTests(unittest.TestCase):
    def test_the_page_example_extracts_every_named_selector(self) -> None:
        data = _first_json_example(_page("crawler-node.md"))["data"]

        output = _run_crawler(data)

        self.assertEqual(
            output["extracted"],
            {
                "title": [{"text": "Release notes"}],
                "links": [
                    {"text": "One", "href": "/posts/1"},
                    {"text": "Two", "href": "/posts/2"},
                ],
            },
        )

    def test_every_output_the_page_names_is_returned(self) -> None:
        output = _run_crawler(
            {"credentialId": "c1", "crawlerUrl": "$userInput.body.url", "crawlerMode": "extract"}
        )

        self.assertLessEqual(_overview_fields(_page("crawler-node.md")), set(output))


class TriggerPageTests(unittest.TestCase):
    RUN_INPUTS = {
        "event": {},
        "interaction": {},
        "type": 2,
        "data": {},
        "update": {},
        "message": {},
        "callback_query": {},
        "headers": {},
        "triggered_by": "webhook",
        "trigger_node_id": "trigger_1",
        "triggered_at": "2026-01-01T00:00:00+00:00",
    }

    def test_every_output_the_page_names_is_returned(self) -> None:
        for page, handler in (
            ("slack-trigger-node.md", slack_trigger_node),
            ("discord-trigger-node.md", discord_trigger_node),
            ("telegram-trigger-node.md", telegram_trigger_node),
        ):
            with self.subTest(page=page):
                ctx = types.SimpleNamespace(node_data={"_initial_inputs": self.RUN_INPUTS})
                output = handler.execute(ctx)

                self.assertLessEqual(_overview_fields(_page(page)), set(output))


class BranchPageTests(unittest.TestCase):
    def _branch_output(self, node: dict) -> dict:
        nodes = [
            {
                "id": "in_1",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {**node, "position": {"x": 300, "y": 0}},
        ]
        edges = [{"id": "e1", "source": "in_1", "target": node["id"]}]
        result = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()).execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )
        return next(r for r in result.node_results if r["node_id"] == node["id"])["output"]

    def test_every_output_the_page_names_is_returned(self) -> None:
        for page, node in (
            (
                "condition-node.md",
                {
                    "id": "c1",
                    "type": "condition",
                    "data": {"label": "isLong", "condition": "$userInput.body.text.length > 1"},
                },
            ),
            (
                "switch-node.md",
                {
                    "id": "s1",
                    "type": "switch",
                    "data": {
                        "label": "route",
                        "expression": "$userInput.body.text",
                        "cases": ["hello"],
                    },
                },
            ),
        ):
            with self.subTest(page=page):
                named = _overview_fields(_page(page))

                self.assertTrue(named)
                self.assertLessEqual(named, set(self._branch_output(node)))


if __name__ == "__main__":
    unittest.main()
