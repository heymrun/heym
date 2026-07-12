import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import board_mapper_service


def _board():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Launch board",
        owner_id=uuid.uuid4(),
        mapper_model="gpt-4.1-mini",
        mapper_credential_id=uuid.uuid4(),
    )


def _credential():
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.type = SimpleNamespace(value="openai")
    cred.encrypted_config = "enc"
    return cred


def _context():
    return {
        "triggered_by": "board",
        "rerun": False,
        "card": {"id": "c1", "title": "Write launch email", "content": "..."},
        "board": {"id": "b1", "name": "Launch board"},
        "move": {"from_column": "Backlog", "to_column": "Planning"},
        "chain": {"position": 0, "length": 1, "previous_workflow_outputs": []},
    }


def _db_returning(credential):
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = credential
    db.execute = AsyncMock(return_value=res)
    return db


class TestConfigured(unittest.TestCase):
    def test_configured_requires_model_and_credential(self):
        self.assertTrue(board_mapper_service.board_mapper_is_configured(_board()))
        self.assertFalse(
            board_mapper_service.board_mapper_is_configured(
                SimpleNamespace(mapper_model=None, mapper_credential_id=uuid.uuid4())
            )
        )
        # duck-typed board without the fields must not raise
        self.assertFalse(board_mapper_service.board_mapper_is_configured(SimpleNamespace()))


class TestWorkflowSummary(unittest.TestCase):
    def test_is_agentic_detection(self):
        wf = SimpleNamespace(
            name="Enrich",
            description="d",
            nodes=[{"type": "input"}, {"type": "agent", "data": {"label": "A"}}],
        )
        summary = board_mapper_service._workflow_summary(wf)
        self.assertTrue(summary["is_agentic"])
        deterministic = SimpleNamespace(
            name="T", description=None, nodes=[{"type": "set"}, {"type": "output"}]
        )
        self.assertFalse(board_mapper_service._workflow_summary(deterministic)["is_agentic"])

    def test_input_field_keys(self):
        nodes = [{"data": {"inputFields": [{"key": "text"}, {"key": "topic"}]}}, {"data": {}}]
        self.assertEqual(board_mapper_service._input_field_keys(nodes), ["text", "topic"])


class TestBuildWorkflowInputs(unittest.IsolatedAsyncioTestCase):
    async def test_maps_and_merges_reserved_board_block(self):
        board = _board()
        credential = _credential()
        db = _db_returning(credential)
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            name="upString",
            description="uppercases",
            nodes=[{"type": "input", "data": {"inputFields": [{"key": "text"}]}}],
        )

        with (
            patch.object(board_mapper_service, "decrypt_config", return_value={"api_key": "k"}),
            patch.object(
                board_mapper_service,
                "execute_llm",
                AsyncMock(return_value={"text": '{"text": "WRITE LAUNCH EMAIL"}'}),
            ),
        ):
            inputs = await board_mapper_service.build_workflow_inputs(
                db,
                board=board,
                column_ai_instructions="uppercase the card title",
                available_context=_context(),
                workflow=workflow,
            )

        self.assertEqual(inputs["text"], "WRITE LAUNCH EMAIL")
        self.assertEqual(inputs["board"]["card_title"], "Write launch email")
        self.assertEqual(inputs["board"]["board_id"], str(board.id))
        self.assertEqual(inputs["board"]["move"]["to_column"], "Planning")

    async def test_invalid_json_raises(self):
        board = _board()
        db = _db_returning(_credential())
        workflow = SimpleNamespace(id=uuid.uuid4(), name="w", description=None, nodes=[])

        with (
            patch.object(board_mapper_service, "decrypt_config", return_value={"api_key": "k"}),
            patch.object(
                board_mapper_service, "execute_llm", AsyncMock(return_value={"text": "not json"})
            ),
        ):
            with self.assertRaises(ValueError):
                await board_mapper_service.build_workflow_inputs(
                    db,
                    board=board,
                    column_ai_instructions=None,
                    available_context=_context(),
                    workflow=workflow,
                )

    async def test_missing_credential_raises(self):
        board = _board()
        db = _db_returning(None)
        workflow = SimpleNamespace(id=uuid.uuid4(), name="w", description=None, nodes=[])
        with self.assertRaises(ValueError):
            await board_mapper_service.build_workflow_inputs(
                db,
                board=board,
                column_ai_instructions=None,
                available_context=_context(),
                workflow=workflow,
            )
