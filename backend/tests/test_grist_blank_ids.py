"""Blank Grist IDs must fail their guards instead of evaluating to str(inputs)."""

import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.grist_node import execute as grist_execute
from app.services.workflow_executor import WorkflowExecutor

_SECRET = {"password": "hunter2"}


def _run(node_data: dict) -> MagicMock:
    """Run the node; return the client mock. "$..." templates evaluate to empty."""
    executor = MagicMock()
    executor.evaluate_message_template.side_effect = lambda template, inputs, *_a, **_k: (
        str(inputs) if not template else ("" if template.startswith("$") else template)
    )
    executor.evaluate_nonempty_message_template.side_effect = lambda *args, **kw: (
        WorkflowExecutor.evaluate_nonempty_message_template(executor, *args, **kw)
    )
    client = MagicMock()
    client.get.return_value = httpx.Response(
        200, json={"records": []}, request=httpx.Request("GET", "https://g.test/")
    )
    data = {"credentialId": "c", **node_data}
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs=_SECRET,
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1", "type": "grist", "data": data},
        node_type="grist",
        node_data=data,
        node_label="grist",
    )
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.grist_pool.get_grist_client", return_value=client),
        patch(
            "app.services.encryption.decrypt_config",
            return_value={"api_key": "k", "server_url": "https://g.test"},
        ),
    ):
        grist_execute(ctx)
    return client


class GristBlankIdTests(unittest.TestCase):
    def _fails(self, node_data: dict, message: str) -> None:
        with self.assertRaises(ValueError) as cm:
            _run(node_data)
        self.assertEqual(str(cm.exception), message)
        self.assertNotIn("hunter2", str(cm.exception))

    def test_list_tables_blank_doc_id(self) -> None:
        for doc in ("", "   ", "$x.empty"):
            with self.subTest(doc=doc):
                self._fails(
                    {"gristOperation": "listTables", "gristDocId": doc},
                    "Grist listTables requires a document ID",
                )

    def test_list_columns_blank_table_id(self) -> None:
        for table in ("", "  ", "$x.empty"):
            with self.subTest(table=table):
                self._fails(
                    {"gristOperation": "listColumns", "gristDocId": "d", "gristTableId": table},
                    "Grist listColumns requires document ID and table ID",
                )

    def test_blank_record_id(self) -> None:
        cases = {
            "getRecord": "Grist getRecord requires a record ID",
            "updateRecord": "Grist updateRecord requires a record ID",
            "deleteRecord": "Grist deleteRecord requires record ID(s)",
        }
        for op, message in cases.items():
            with self.subTest(op=op):
                self._fails(
                    {
                        "gristOperation": op,
                        "gristDocId": "d",
                        "gristTableId": "t",
                        "gristRecordId": "",
                    },
                    message,
                )

    def test_blank_sort_is_not_sent(self) -> None:
        client = _run(
            {
                "gristOperation": "getRecords",
                "gristDocId": "d",
                "gristTableId": "t",
                "gristSort": "  ",
            }
        )
        self.assertNotIn("sort", client.get.call_args.kwargs["params"])


if __name__ == "__main__":
    unittest.main()
