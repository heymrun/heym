"""A Grist getRecords without `gristLimit` returns every record, as the editor says.

The node page and the AI builder's DSL said the limit defaulted to 100, while the editor says
"Leave empty for all records" and the node sends `limit` only when one is set.
"""

from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor


def _session() -> MagicMock:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


class GristLimitDefaultTests(unittest.TestCase):
    def _params(self, **extra: object) -> dict:
        client = MagicMock()
        client.get.return_value = httpx.Response(
            200, json={"records": []}, request=httpx.Request("GET", "https://grist.example.com")
        )
        nodes = [
            {
                "id": "start",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "start", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "n",
                "type": "grist",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "n",
                    "credentialId": "cred-1",
                    "gristOperation": "getRecords",
                    "gristDocId": "doc1",
                    "gristTableId": "Contacts",
                    **extra,
                },
            },
        ]
        config = {"api_key": "grist-api-key", "server_url": "https://grist.example.com"}
        executor = WorkflowExecutor(
            nodes=nodes,
            edges=[{"id": "e1", "source": "start", "target": "n"}],
            actor_user_id=uuid.uuid4(),
        )
        executor._get_accessible_credential = MagicMock(
            return_value=MagicMock(encrypted_config="{}")
        )
        with (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch("app.services.grist_pool.get_grist_client", return_value=client),
        ):
            executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
            )
        return client.get.call_args.kwargs["params"]

    def test_no_limit_asks_for_every_record(self) -> None:
        for extra in ({}, {"gristLimit": None}, {"gristLimit": ""}):
            with self.subTest(extra=extra):
                self.assertNotIn("limit", self._params(**extra))

    def test_a_limit_is_sent(self) -> None:
        self.assertEqual(self._params(gristLimit=25)["limit"], 25)

    def test_the_dsl_does_not_promise_a_default_limit(self) -> None:
        line = re.search(r"`gristLimit`:[^\n]*", WORKFLOW_DSL_SYSTEM_PROMPT)
        assert line is not None

        self.assertNotIn("default", line.group(0))
        self.assertIn("every record", line.group(0))

    def test_the_page_names_the_canvas_start_and_no_limit(self) -> None:
        page = (
            Path(__file__).resolve().parents[2] / "frontend/src/docs/content/nodes/grist-node.md"
        ).read_text(encoding="utf-8")
        row = next(line for line in page.splitlines() if line.startswith("| `gristLimit`"))

        self.assertIn("starts at `100`", row)
        self.assertIn("every record", row)


if __name__ == "__main__":
    unittest.main()
