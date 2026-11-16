import unittest
import uuid

from sqlalchemy import delete, func, select, text

from app.db.models import ExecutionHistory, LLMTrace, RunHistory, User, Workflow
from app.db.session import SessionLocal
from app.services.json_text_search import json_text_ilike
from app.services.run_history_list import run_history_rows
from app.services.trace_metrics import apply_trace_search


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class JsonTextSearchPostgresTests(unittest.TestCase):
    """History and trace search find non-ASCII words stored in `json` columns."""

    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"test-json-search-{self.user_id}@example.com",
                    hashed_password="hashed_pw",
                    name="Search Tester",
                )
            )
            db.flush()
            db.add(
                Workflow(
                    id=self.workflow_id,
                    name="Support intake",
                    owner_id=self.user_id,
                    nodes=[],
                    edges=[],
                )
            )
            db.flush()
            db.add(
                ExecutionHistory(
                    workflow_id=self.workflow_id,
                    inputs={"body": {"ticket": "refund", "city": "Malmö"}},
                    outputs={"reply": "sent"},
                    node_results=[{"node_label": "draft", "output": {"text": "réponse envoyée"}}],
                    status="success",
                    execution_time_ms=5,
                    trigger_source="Webhook",
                )
            )
            db.add(
                RunHistory(
                    user_id=self.user_id,
                    run_type="dashboard_chat",
                    inputs={"message": "Grüße aus Köln, wo bleibt die Erstattung?"},
                    outputs={"text": "queued"},
                    status="success",
                )
            )
            db.add(
                LLMTrace(
                    user_id=self.user_id,
                    workflow_id=self.workflow_id,
                    source="workflow",
                    request_type="chat",
                    request={"messages": [{"role": "user", "content": "注文 42 はどこですか"}]},
                    response={"text": "Kargoda 📦"},
                )
            )
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(LLMTrace).where(LLMTrace.user_id == self.user_id))
            db.execute(delete(RunHistory).where(RunHistory.user_id == self.user_id))
            db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow_id)
            )
            db.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _history_hits(self, search: str) -> int:
        rows = run_history_rows(self.user_id, search=search)
        with SessionLocal() as db:
            return db.execute(select(func.count()).select_from(rows)).scalar_one()

    def _trace_hits(self, search: str) -> int:
        stmt = apply_trace_search(
            select(LLMTrace.id).where(LLMTrace.user_id == self.user_id), search
        )
        with SessionLocal() as db:
            return len(db.execute(stmt).all())

    def test_history_finds_non_ascii_words_in_node_results_and_chat_runs(self) -> None:
        self.assertEqual(self._history_hits("réponse"), 1)
        self.assertEqual(self._history_hits("Grüße"), 1)
        self.assertEqual(self._history_hits("refund"), 1)

    def test_history_finds_non_ascii_words_in_jsonb_run_inputs(self) -> None:
        # execution_history.inputs is jsonb: its text holds the characters, a plain ILIKE.
        self.assertEqual(self._history_hits("Malmö"), 1)

    def test_traces_find_non_ascii_words_and_emoji(self) -> None:
        self.assertEqual(self._trace_hits("注文"), 1)
        self.assertEqual(self._trace_hits("📦"), 1)
        self.assertEqual(self._trace_hits("どこ"), 1)

    def test_a_word_that_is_not_there_still_matches_nothing(self) -> None:
        self.assertEqual(self._history_hits("Zürich"), 0)
        self.assertEqual(self._trace_hits("日本語"), 0)


class JsonTextIlikeTests(unittest.TestCase):
    @staticmethod
    def _sql(clause: object) -> tuple[str, list[object]]:
        from sqlalchemy.dialects import postgresql

        compiled = clause.compile(dialect=postgresql.dialect())
        return str(compiled), list(compiled.params.values())

    def test_an_ascii_search_is_one_ilike(self) -> None:
        sql, params = self._sql(json_text_ilike(LLMTrace.request, "refund"))

        self.assertEqual(sql.count("ILIKE"), 1)
        self.assertEqual(params, ["%refund%"])

    def test_a_non_ascii_search_also_tries_the_escaped_spelling(self) -> None:
        sql, params = self._sql(json_text_ilike(LLMTrace.request, "café"))

        self.assertEqual(sql.count("ILIKE"), 2)
        self.assertEqual(params, ["%café%", "%caf\\\\u00e9%"])


if __name__ == "__main__":
    unittest.main()
