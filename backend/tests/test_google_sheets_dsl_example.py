"""The DSL prompt's Google Sheets readRange example uses the fields the node reads.

The prompt listed `gsRange` as a required readRange field and its example read
`"gsRange": "A1:C100"`, but the node never reads `gsRange`: it reads the start row, max rows
and header fields, so a builder following the prompt got row 1 as the header and 100 rows,
whatever range it asked for.
"""

from __future__ import annotations

import json
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor


def _session() -> MagicMock:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def _read_range_example() -> dict:
    block = re.search(
        r"\*\*Example - Read a Range\*\*:\n```json\n(.+?)```", WORKFLOW_DSL_SYSTEM_PROMPT, re.S
    )
    assert block is not None
    return json.loads(block.group(1))


class GoogleSheetsDslExampleTests(unittest.TestCase):
    def test_the_prompt_never_offers_gs_range(self) -> None:
        self.assertNotIn("gsRange", WORKFLOW_DSL_SYSTEM_PROMPT)

    def test_the_read_range_example_runs_with_its_own_fields(self) -> None:
        data = _read_range_example()["data"]
        sent: list[str] = []
        config = {
            "access_token": "ya29.test-token",
            "refresh_token": "1//test-refresh",
            "token_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }

        def mock_get(url: str, **_kwargs: object) -> httpx.Response:
            sent.append(url)
            return httpx.Response(
                200, json={"values": [["Name"], ["Ada"]]}, request=httpx.Request("GET", url)
            )

        nodes = [
            {
                "id": "start",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "start", "inputFields": [{"key": "text"}]},
            },
            {"id": "n", "type": "googleSheets", "position": {"x": 200, "y": 0}, "data": data},
        ]
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
            patch("httpx.get", side_effect=mock_get),
        ):
            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
            )

        row = next(r for r in result.node_results if r["node_label"] == data["label"])
        self.assertEqual(row["status"], "success")
        expected_end = 1 + int(data["gsMaxRows"])  # header row + the example's max rows
        self.assertTrue(sent[0].endswith(f"/values/{data['gsSheetName']}!A1:Z{expected_end}"))
        self.assertEqual(row["output"]["rows"], [{"Name": "Ada", "rowIndex": 2}])


if __name__ == "__main__":
    unittest.main()
