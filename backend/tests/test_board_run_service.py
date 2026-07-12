import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import board_run_service


def _activity(kind="comment", content="hello", author_type="user"):
    return SimpleNamespace(
        kind=kind,
        author_type=author_type,
        content=content,
        data={},
        created_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )


def _card(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        title="Write launch email",
        content="Draft the launch email for the beta",
        card_metadata={"attachments": [{"name": "brief", "url": "https://x/brief"}]},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestBuildCardPayload(unittest.TestCase):
    def test_payload_contract_fields(self):
        card = _card()
        board = SimpleNamespace(id=uuid.uuid4(), name="Launch board")
        payload = board_run_service.build_card_payload(
            card=card,
            board=board,
            from_column_name="Backlog",
            to_column_name="Planning",
            comments=[_activity(content="Use friendly tone")],
            history=[_activity(kind="event", content="Card created", author_type="system")],
            previous_runs=[
                SimpleNamespace(
                    workflow_name="Research",
                    output={"summary": "done"},
                    finished_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    column_id=uuid.uuid4(),
                )
            ],
            chain_position=1,
            chain_length=2,
            previous_workflow_outputs=[{"workflow_name": "Enrich", "output": {"plan": "v1"}}],
            rerun=False,
        )

        self.assertEqual(payload["triggered_by"], "board")
        self.assertEqual(payload["card"]["title"], "Write launch email")
        self.assertEqual(payload["card"]["comments"][0]["content"], "Use friendly tone")
        self.assertEqual(payload["card"]["previous_outputs"][0]["workflow_name"], "Research")
        self.assertEqual(payload["move"], {"from_column": "Backlog", "to_column": "Planning"})
        self.assertFalse(payload["rerun"])
        self.assertEqual(payload["chain"]["position"], 1)
        self.assertEqual(payload["chain"]["length"], 2)
        self.assertEqual(payload["chain"]["previous_workflow_outputs"][0]["output"], {"plan": "v1"})
        self.assertEqual(payload["card"]["metadata"]["attachments"][0]["url"], "https://x/brief")

    def test_rerun_has_null_move_and_history_is_capped(self):
        payload = board_run_service.build_card_payload(
            card=_card(),
            board=SimpleNamespace(id=uuid.uuid4(), name="B"),
            from_column_name=None,
            to_column_name="Planning",
            comments=[],
            history=[_activity(kind="event", content=f"e{i}") for i in range(250)],
            previous_runs=[],
            chain_position=0,
            chain_length=1,
            previous_workflow_outputs=[],
            rerun=True,
        )
        self.assertIsNone(payload["move"])
        self.assertTrue(payload["rerun"])
        self.assertEqual(len(payload["card"]["history"]), 200)
        self.assertEqual(payload["card"]["history"][-1]["content"], "e249")
