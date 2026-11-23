"""A Jira node needs its operation; the node page no longer says it defaults to one.

The page said "The default operation is Search Issues" and "Defaults to searchIssues", but the
node fails with "Jira node requires an operation" when the field is missing: only the editor
sets searchIssues on a new node, so a node built from the page without it never ran.
"""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.workflow_executor import WorkflowExecutor

PAGE = (
    Path(__file__).resolve().parents[2] / "frontend/src/docs/content/nodes/jira-node.md"
).read_text(encoding="utf-8")


class JiraOperationRequiredTests(unittest.TestCase):
    def test_a_node_without_an_operation_fails(self) -> None:
        nodes = [
            {
                "id": "start",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "start", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "n",
                "type": "jira",
                "position": {"x": 200, "y": 0},
                "data": {"label": "n", "credentialId": "cred-1"},
            },
        ]
        executor = WorkflowExecutor(
            nodes=nodes,
            edges=[{"id": "e1", "source": "start", "target": "n"}],
            actor_user_id=uuid.uuid4(),
        )
        executor._get_accessible_credential = MagicMock(
            return_value=MagicMock(type=CredentialType.jira, encrypted_config="{}")
        )
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.db.session.SessionLocal", return_value=db),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"base_url": "https://jira.example.com", "email": "a@b.c"},
            ),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
            )
        row = next(r for r in result.node_results if r["node_label"] == "n")

        self.assertEqual(row["status"], "error")
        self.assertIn("requires an operation", str(row["error"]))

    def test_the_page_does_not_promise_a_default_operation(self) -> None:
        self.assertNotIn("Defaults to `searchIssues`", PAGE)
        self.assertNotIn("The default operation is", PAGE)


if __name__ == "__main__":
    unittest.main()
