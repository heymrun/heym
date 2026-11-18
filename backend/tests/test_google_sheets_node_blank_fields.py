"""Blank Spreadsheet ID / Sheet Name must not fall back to str(inputs)."""

import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import google_sheets_node
from app.services.workflow_executor import WorkflowExecutor

INPUTS = {"secret": "workflow-context"}


def _executor() -> SimpleNamespace:
    ex = SimpleNamespace()
    ex.evaluate_message_template = lambda t, i, n=None: t if t else str(i)
    ex.evaluate_nonempty_message_template = MethodType(
        WorkflowExecutor.evaluate_nonempty_message_template, ex
    )
    ex._get_accessible_credential = lambda db, cid: SimpleNamespace(encrypted_config="x")
    return ex


def _ctx(**node_data: object) -> NodeExecutionContext:
    data = {"credentialId": "cred", "gsOperation": "readRange", **node_data}
    return NodeExecutionContext(
        executor=_executor(),
        node_id="n1",
        inputs=INPUTS,
        allow_branch_skip=True,
        start_time=0.0,
        node={},
        node_type="googleSheets",
        node_data=data,
        node_label="Sheets",
    )


class GoogleSheetsBlankFieldTests(unittest.TestCase):
    def _run(self, **node_data: object) -> MagicMock:
        service_cls = MagicMock()
        service_cls.parse_spreadsheet_id.side_effect = lambda s: s.strip()
        with (
            patch("app.db.session.SessionLocal"),
            patch("app.services.encryption.decrypt_config", return_value={"k": "v"}),
            patch("app.services.google_sheets_service.GoogleSheetsService", service_cls),
        ):
            google_sheets_node.execute(_ctx(**node_data))
        return service_cls

    def test_blank_spreadsheet_id_raises_without_calling_service(self) -> None:
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                service_cls = MagicMock()
                service_cls.parse_spreadsheet_id.side_effect = lambda s: s.strip()
                with (
                    patch("app.db.session.SessionLocal"),
                    patch("app.services.encryption.decrypt_config", return_value={"k": "v"}),
                    patch("app.services.google_sheets_service.GoogleSheetsService", service_cls),
                    self.assertRaisesRegex(ValueError, "requires a spreadsheet ID"),
                ):
                    google_sheets_node.execute(_ctx(gsSpreadsheetId=blank))
                service_cls.assert_not_called()

    def test_blank_sheet_name_defaults_to_sheet1(self) -> None:
        for blank in ("", "  ", None):
            with self.subTest(blank=blank):
                service_cls = self._run(gsSpreadsheetId="abc123", gsSheetName=blank)
                read = service_cls.return_value.read_range
                self.assertEqual(read.call_args.args[1], "Sheet1")

    def test_missing_sheet_name_defaults_to_sheet1(self) -> None:
        service_cls = self._run(gsSpreadsheetId="abc123")
        self.assertEqual(service_cls.return_value.read_range.call_args.args[1], "Sheet1")


if __name__ == "__main__":
    unittest.main()
