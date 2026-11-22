"""Grist updateRecords with a flat record sends `id` as the row id only.

updateRecords accepts `{"id": 1, "fields": {...}}` and, as a fallback, a flat record
`{"id": 1, "Note": "x"}`. The flat form kept `id` inside `fields`, and Grist refuses the
whole request with `Invalid column "id"`, so no record was updated.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.services.workflow_executor import WorkflowExecutor


def _session() -> MagicMock:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


class GristUpdateRecordsFlatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict] = []

        def _patch(url: str, **kwargs: object) -> httpx.Response:
            self.sent.append({"url": url, **kwargs})
            return httpx.Response(
                200, json={}, request=httpx.Request("PATCH", "https://grist.example.com")
            )

        client = MagicMock()
        client.patch.side_effect = _patch
        config = {"api_key": "grist-api-key", "server_url": "https://grist.example.com"}
        for patcher in (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch("app.services.grist_pool.get_grist_client", return_value=client),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, records: str) -> dict:
        nodes = [
            {
                "id": "start",
                "type": "textInput",
                "position": {"x": 0, "y": 0},
                "data": {"label": "start", "inputFields": [{"key": "note"}]},
            },
            {
                "id": "n",
                "type": "grist",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "n",
                    "credentialId": "cred-1",
                    "gristOperation": "updateRecords",
                    "gristDocId": "doc1",
                    "gristTableId": "Contacts",
                    "gristRecordsData": records,
                },
            },
        ]
        edges = [{"id": "e1", "source": "start", "target": "n"}]
        executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
        executor._get_accessible_credential = MagicMock(
            return_value=MagicMock(encrypted_config="{}")
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"note": "hello"}},
        )
        return next(r for r in result.node_results if r["node_label"] == "n")

    def test_flat_records_send_id_outside_fields(self) -> None:
        row = self._run('[{"id": 1, "Note": "$start.body.note"}, {"id": 2, "Note": "y"}]')

        self.assertEqual(row["status"], "success")
        self.assertEqual(
            self.sent[0]["json"],
            {
                "records": [
                    {"id": 1, "fields": {"Note": "hello"}},
                    {"id": 2, "fields": {"Note": "y"}},
                ]
            },
        )

    def test_nested_records_are_sent_as_given(self) -> None:
        row = self._run('[{"id": 1, "fields": {"Note": "x"}}]')

        self.assertEqual(row["status"], "success")
        self.assertEqual(self.sent[0]["json"], {"records": [{"id": 1, "fields": {"Note": "x"}}]})


if __name__ == "__main__":
    unittest.main()
