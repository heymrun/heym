"""The RAG outputs the docs and the DSL prompt tell a workflow to read are ones the node returns.

The AI builder writes RAG workflows from the DSL prompt, so a field name there that the node
does not return reads as null: a search's context reaches the LLM as "None".
"""

import re
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.vector_store import SearchResult
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor

DOCS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "docs" / "content"
SEARCH = {"operation": "search", "queryText": "$question.body.text"}
INSERT = {"operation": "insert", "documentContent": "$question.body.text"}


def _read(rag_data: dict, expression: str) -> object:
    """Run question -> rag -> output and return what `expression` resolved to."""
    nodes = [
        {"id": "in", "type": "textInput", "data": {"label": "question"}},
        {
            "id": "rag",
            "type": "rag",
            "data": {"label": "searchKnowledge", "vectorStoreId": str(uuid.uuid4()), **rag_data},
        },
        {"id": "out", "type": "output", "data": {"label": "answer", "message": expression}},
    ]
    edges = [
        {"id": "e1", "source": "in", "target": "rag"},
        {"id": "e2", "source": "rag", "target": "out"},
    ]
    service = MagicMock()
    service.insert.return_value = "point-1"
    service.search.return_value = [
        SearchResult(id="p1", text="Refunds are paid within 14 days.", score=0.9, metadata={})
    ]
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.encryption.decrypt_config", return_value={"db_type": "qdrant"}),
        patch(
            "app.services.vector_store.create_vector_store_service_for_credential",
            return_value=service,
        ),
    ):
        executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
        executor._get_accessible_vector_store = MagicMock(
            return_value=MagicMock(collection_name="c")
        )
        executor._get_vector_store_backing_credential = MagicMock(
            return_value=MagicMock(type="openai")
        )
        result = executor.execute(
            workflow_id=uuid.uuid4(), initial_inputs={"body": {"text": "refunds?"}}
        )
    rows = {row["node_label"]: row for row in result.node_results}
    assert rows["searchKnowledge"]["status"] == "success", rows["searchKnowledge"].get("error")
    return (rows["answer"].get("output") or {}).get("result")


class RagDocumentedOutputTests(unittest.TestCase):
    def test_the_prompt_example_hands_the_llm_the_document_text(self) -> None:
        field = re.search(
            r'\$searchKnowledge\.results\.map\("([^"]+)"\)', WORKFLOW_DSL_SYSTEM_PROMPT
        ).group(1)

        context = _read(SEARCH, f'$searchKnowledge.results.map("{field}").join("|")')

        self.assertEqual(context, "Refunds are paid within 14 days.")

    def test_every_prompt_accessor_resolves(self) -> None:
        accessors = re.findall(
            r"- `\$ragNodeLabel(\.[^`]+)` - ([^\n]*)", WORKFLOW_DSL_SYSTEM_PROMPT
        )
        self.assertTrue(accessors)
        # Hybrid-only scores and the upsert/delete fields need runs of their own.
        other_runs = ("vector_score", "replaced", "deleted", "document_id")
        for path, description in accessors:
            if any(name in path for name in other_runs):
                continue
            rag_data = INSERT if "insert" in description else SEARCH
            with self.subTest(path):
                self.assertIsNotNone(_read(rag_data, "$searchKnowledge" + path))

    def test_the_docs_insert_outputs_resolve(self) -> None:
        section = (DOCS / "nodes" / "rag-node.md").read_text().split("### Insert", 1)[1]
        names = re.findall(r"\$nodeLabel\.(\w+)", re.search(r"\*\*Output:\*\*([^\n]*)", section)[1])
        self.assertTrue(names)
        for name in names:
            with self.subTest(name):
                self.assertIsNotNone(_read(INSERT, f"$searchKnowledge.{name}"))

    def test_the_overview_example_reads_the_result_text(self) -> None:
        overview = (DOCS / "getting-started" / "why-heym.md").read_text()
        field = re.search(r'\$ragNode\.results\.map\("([^"]+)"\)', overview).group(1)

        self.assertEqual(
            _read(SEARCH, f'$searchKnowledge.results.map("{field}").join("|")'),
            "Refunds are paid within 14 days.",
        )


if __name__ == "__main__":
    unittest.main()
