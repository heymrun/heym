"""Google trigger nodes: handler output and every registry they must appear in."""

import unittest
from types import SimpleNamespace

from app.db.models import CredentialType
from app.services.cluster.node_placement import Placement, node_placement
from app.services.credential_catalog import NODE_CREDENTIAL_FIELDS
from app.services.dashboard_widget_policy import DASHBOARD_WIDGET_BLOCKED_NODE_TYPES
from app.services.node_execution.registry import get_node_handler
from app.services.trigger_inputs import receives_initial_inputs
from app.services.workflow_status import compute_trigger_status

TYPES = ("googleDriveTrigger", "googleSheetsTrigger")


def _ctx(node_type: str, initial_inputs: dict | None) -> SimpleNamespace:
    data: dict = {"label": "t"}
    if initial_inputs is not None:
        data["_initial_inputs"] = initial_inputs
    return SimpleNamespace(node_data=data, node_type=node_type)


class HandlerTests(unittest.TestCase):
    def test_drive_handler_returns_the_change(self) -> None:
        handler = get_node_handler("googleDriveTrigger")
        output = handler(
            _ctx(
                "googleDriveTrigger",
                {
                    "triggered_at": "2026-10-17T10:00:00+00:00",
                    "change": {
                        "event": "created",
                        "file": {"id": "a", "name": "a.pdf"},
                        "changed_fields": [],
                        "folder_id": "F1",
                    },
                },
            )
        )
        self.assertEqual(output["event"], "created")
        self.assertEqual(output["file"]["name"], "a.pdf")
        self.assertEqual(output["folder_id"], "F1")
        self.assertEqual(output["triggered_at"], "2026-10-17T10:00:00+00:00")

    def test_sheets_handler_returns_the_change(self) -> None:
        handler = get_node_handler("googleSheetsTrigger")
        output = handler(
            _ctx(
                "googleSheetsTrigger",
                {
                    "triggered_at": "t",
                    "change": {
                        "event": "updated",
                        "row": {"Status": "Paid", "rowIndex": 4},
                        "changed_columns": ["Status"],
                        "key": "a@x",
                        "spreadsheet_id": "S1",
                        "sheet_name": "Leads",
                    },
                },
            )
        )
        self.assertEqual(output["row"]["rowIndex"], 4)
        self.assertEqual(output["changed_columns"], ["Status"])
        self.assertEqual(output["key"], "a@x")

    def test_a_manual_editor_run_gets_empty_fields(self) -> None:
        drive = get_node_handler("googleDriveTrigger")(_ctx("googleDriveTrigger", None))
        sheets = get_node_handler("googleSheetsTrigger")(_ctx("googleSheetsTrigger", None))
        self.assertIsNone(drive["event"])
        self.assertEqual(drive["file"], {})
        self.assertIsNone(sheets["event"])
        self.assertEqual(sheets["row"], {})


class RegistrationTests(unittest.TestCase):
    def test_both_receive_initial_inputs(self) -> None:
        for node_type in TYPES:
            with self.subTest(node_type=node_type):
                self.assertTrue(receives_initial_inputs({"type": node_type, "data": {}}))

    def test_both_make_a_workflow_listen(self) -> None:
        for node_type in TYPES:
            with self.subTest(node_type=node_type):
                active = {"type": node_type, "data": {}}
                paused = {"type": node_type, "data": {"active": False}}
                self.assertEqual(compute_trigger_status([active]), "listening")
                self.assertEqual(compute_trigger_status([paused]), "paused")

    def test_dashboard_widgets_cannot_run_them(self) -> None:
        for node_type in TYPES:
            self.assertIn(node_type, DASHBOARD_WIDGET_BLOCKED_NODE_TYPES)

    def test_runs_may_execute_anywhere(self) -> None:
        for node_type in TYPES:
            self.assertEqual(node_placement({"type": node_type, "data": {}}), Placement.ANYWHERE)

    def test_credential_fields(self) -> None:
        [drive] = NODE_CREDENTIAL_FIELDS["googleDriveTrigger"]
        [sheets] = NODE_CREDENTIAL_FIELDS["googleSheetsTrigger"]
        self.assertEqual(drive.types, frozenset({CredentialType.google_drive}))
        self.assertEqual(sheets.types, frozenset({CredentialType.google_sheets}))


if __name__ == "__main__":
    unittest.main()
