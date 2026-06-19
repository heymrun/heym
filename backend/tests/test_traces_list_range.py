import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.api.traces import _apply_source_filter, list_traces


class _ExecResult:
    def __init__(self, items):
        self._items = items

    def scalar_one(self):
        return len(self._items)

    def all(self):
        return self._items


class ListRangeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = MagicMock()
        self.user.id = uuid.uuid4()

    async def _run(self, range_arg):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_ExecResult([]), _ExecResult([])])
        await list_traces(
            limit=25,
            offset=0,
            credential_id=None,
            workflow_id=None,
            source=None,
            status_filter=None,
            search=None,
            order="desc",
            range=range_arg,
            current_user=self.user,
            db=db,
        )
        return db

    async def test_range_param_applies_start_filter(self):
        with patch("app.api.traces._resolve_range") as resolve_mock:
            resolve_mock.return_value = (
                datetime(2026, 5, 19, tzinfo=timezone.utc),
                datetime(2026, 5, 26, tzinfo=timezone.utc),
                21600,
            )
            db = await self._run("7d")
        resolve_mock.assert_called_once_with("7d")
        self.assertEqual(db.execute.await_count, 2)

    async def test_range_none_keeps_backward_compat_no_resolve_call(self):
        with patch("app.api.traces._resolve_range") as resolve_mock:
            db = await self._run(None)
        resolve_mock.assert_not_called()
        self.assertEqual(db.execute.await_count, 2)

    async def test_list_includes_resolved_llm_cost(self):
        trace = MagicMock()
        trace.id = uuid.uuid4()
        trace.created_at = datetime(2026, 5, 27, tzinfo=timezone.utc)
        trace.source = "dashboard_chat"
        trace.request_type = "chat.completions"
        trace.provider = "openai"
        trace.model = "gpt-4o-mini"
        trace.credential_id = uuid.uuid4()
        trace.workflow_id = None
        trace.node_id = None
        trace.node_label = None
        trace.error = None
        trace.elapsed_ms = 123.45
        trace.prompt_tokens = 10
        trace.completion_tokens = 20
        trace.total_tokens = 30
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ExecResult([(trace, "openai", "Dashboard Chat")]),
                _ExecResult([(trace, "openai", "Dashboard Chat")]),
            ]
        )

        with patch("app.api.traces.resolve_costs_for_user", new_callable=AsyncMock) as resolve_mock:
            resolve_mock.return_value = [(Decimal("0.000123"), True)]

            result = await list_traces(
                limit=25,
                offset=0,
                credential_id=None,
                workflow_id=None,
                source=None,
                status_filter=None,
                search=None,
                order="desc",
                range=None,
                current_user=self.user,
                db=db,
            )

        resolve_mock.assert_awaited_once_with(db, self.user.id, [("gpt-4o-mini", 10, 20)])
        self.assertEqual(result.items[0].cost_usd, Decimal("0.000123"))
        self.assertTrue(result.items[0].is_priced)


class SourceFilterTests(unittest.TestCase):
    def test_expression_builder_filter_includes_legacy_assistant_traces(self) -> None:
        filters: list = []
        _apply_source_filter(filters, "expression_builder")
        self.assertEqual(len(filters), 1)
        compiled = str(
            filters[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("expression_builder", compiled)
        self.assertIn("assistant", compiled)
        self.assertIn("Expression Builder", compiled)

    def test_other_sources_use_exact_match(self) -> None:
        filters: list = []
        _apply_source_filter(filters, "workflow")
        self.assertEqual(len(filters), 1)
        compiled = str(
            filters[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("workflow", compiled)
        self.assertNotIn("expression_builder", compiled)

    def test_ai_ask_filter_matches_assistant_execution_log_traces(self) -> None:
        filters: list = []
        _apply_source_filter(filters, "ai_ask")
        self.assertEqual(len(filters), 1)
        compiled = str(
            filters[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("assistant", compiled)
        self.assertIn("AI Ask", compiled)

    def test_ai_builder_filter_matches_assistant_builder_traces(self) -> None:
        filters: list = []
        _apply_source_filter(filters, "ai_builder")
        self.assertEqual(len(filters), 1)
        compiled = str(
            filters[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("assistant", compiled)
        self.assertIn("AI Builder", compiled)
