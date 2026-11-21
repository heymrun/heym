"""Grist record data that is not JSON fails the node instead of writing nothing.

createRecord/updateRecord replaced unparseable `gristRecordData` with `{}` and the batch
operations replaced `gristRecordsData` with `[]`, then called Grist and reported success: an
update changed no field and a create sent an empty record. A trailing comma, or a text
expression left unquoted (`{"note": $start.body.note}` renders to `{"note": hello}`), was
enough.
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


class GristRecordJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict] = []

        def _respond(method: str):
            def handler(url: str, **kwargs: object) -> httpx.Response:
                self.sent.append({"method": method, "url": url, **kwargs})
                return httpx.Response(
                    200,
                    json={"records": [{"id": 1}]},
                    request=httpx.Request(method, "https://grist.example.com"),
                )

            return handler

        client = MagicMock()
        client.post.side_effect = _respond("POST")
        client.patch.side_effect = _respond("PATCH")
        config = {"api_key": "grist-api-key", "server_url": "https://grist.example.com"}
        for patcher in (
            patch("app.db.session.SessionLocal", return_value=_session()),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch("app.services.grist_pool.get_grist_client", return_value=client),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, data: dict) -> dict:
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
                    "gristDocId": "doc1",
                    "gristTableId": "Contacts",
                    **data,
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

    def test_invalid_record_data_fails_and_sends_nothing(self) -> None:
        cases = [
            ("updateRecord", "gristRecordData", '{"note": $start.body.note}'),
            ("updateRecord", "gristRecordData", '{"note": "x",}'),
            ("createRecord", "gristRecordData", '{"note": $start.body.note}'),
            ("createRecords", "gristRecordsData", '[{"note": "x"},]'),
            ("updateRecords", "gristRecordsData", '[{"id": 1, "fields": {"note": "x"}},]'),
        ]
        for operation, field, template in cases:
            with self.subTest(operation=operation, template=template):
                self.sent.clear()
                row = self._run(
                    {"gristOperation": operation, "gristRecordId": "1", field: template}
                )

                self.assertEqual(row["status"], "error")
                self.assertIn(f"{field} is not valid JSON", str(row.get("error")))
                self.assertEqual(self.sent, [])

    def test_valid_record_data_is_still_sent(self) -> None:
        row = self._run(
            {
                "gristOperation": "updateRecord",
                "gristRecordId": "1",
                "gristRecordData": '{"note": "$start.body.note"}',
            }
        )

        self.assertEqual(row["status"], "success")
        self.assertEqual(
            self.sent[0]["json"], {"records": [{"id": 1, "fields": {"note": "hello"}}]}
        )


if __name__ == "__main__":
    unittest.main()
