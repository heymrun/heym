"""Metadata JSON on insert/upsert resolves expressions against the run context."""

import unittest

from app.services.node_execution.nodes.rag_node import (
    _json_object_field,
    _metadata_from_node_data,
)
from app.services.workflow_executor import WorkflowExecutor


class TestRagMetadataExpressions(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = WorkflowExecutor(nodes=[], edges=[])
        self.inputs = {
            "start": {
                "url": "https://heym.run/docs",
                "count": 7,
                "active": True,
                "tags": ["a", "b"],
                "title": 'He said "hello"',
            }
        }

    def _resolve(self, metadata_json: str) -> dict:
        return _metadata_from_node_data(
            self.executor,
            {"documentMetadata": metadata_json},
            self.inputs,
            "rag_1",
        )

    def test_resolves_a_plain_reference(self) -> None:
        self.assertEqual(
            self._resolve('{"url": "$start.url"}'),
            {"url": "https://heym.run/docs"},
        )

    def test_keeps_the_resolved_type(self) -> None:
        resolved = self._resolve('{"count": "$start.count", "active": "$start.active"}')

        self.assertEqual(resolved["count"], 7)
        self.assertIs(type(resolved["count"]), int)
        self.assertEqual(resolved["active"], True)

    def test_resolves_inside_a_text_template(self) -> None:
        self.assertEqual(
            self._resolve('{"label": "page $start.count of docs"}'),
            {"label": "page 7 of docs"},
        )

    def test_a_quote_in_a_resolved_value_cannot_break_the_json(self) -> None:
        # The guard for resolving after the parse rather than templating the raw text.
        self.assertEqual(self._resolve('{"title": "$start.title"}'), {"title": 'He said "hello"'})

    def test_resolves_nested_objects_and_arrays(self) -> None:
        resolved = self._resolve('{"page": {"url": "$start.url"}, "list": ["$start.count", "x"]}')

        self.assertEqual(resolved["page"], {"url": "https://heym.run/docs"})
        self.assertEqual(resolved["list"], [7, "x"])

    def test_resolved_metadata_is_json_serializable(self) -> None:
        import json

        resolved = self._resolve('{"tags": "$start.tags", "url": "$start.url"}')

        self.assertEqual(json.loads(json.dumps(resolved))["tags"], ["a", "b"])

    def test_literal_values_are_left_alone(self) -> None:
        self.assertEqual(
            self._resolve('{"source": "crm", "n": 3, "ok": true, "none": null}'),
            {"source": "crm", "n": 3, "ok": True, "none": None},
        )

    def test_blank_empty_or_null_metadata_stays_empty(self) -> None:
        for blank in ("", "  ", "{}", "null"):
            with self.subTest(value=blank):
                self.assertEqual(self._resolve(blank), {})

    def test_metadata_that_is_not_a_json_object_fails(self) -> None:
        # It was stored as {}, so a search filtered on that metadata never found it.
        with self.assertRaisesRegex(ValueError, "documentMetadata is not valid JSON"):
            self._resolve('{"source": "crm",}')
        for value in ('["crm"]', "3", '"crm"', "$start.count", "$start.tags"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "documentMetadata must be a JSON object"):
                    self._resolve(value)

    def test_one_whole_expression_is_resolved_once_and_used_as_it_is(self) -> None:
        self.inputs["start"]["meta"] = {"source": "crm", "n": 5, "note": "$start.url"}
        self.inputs["start"]["meta_text"] = '{"source": "crm", "n": 5}'
        self.assertEqual(
            self._resolve("$start.meta"), {"source": "crm", "n": 5, "note": "$start.url"}
        )
        resolved = self._resolve("$start.meta_text")
        self.assertEqual(resolved, {"source": "crm", "n": 5})
        self.assertIs(type(resolved["n"]), int)
        with self.assertRaisesRegex(ValueError, "documentMetadata is not valid JSON"):
            self.inputs["start"]["bad"] = "{not json"
            self._resolve("$start.bad")


class TestRagSearchFilterExpressions(unittest.TestCase):
    """Search filters resolve by the same rules, so the dialog and the run agree."""

    def setUp(self) -> None:
        self.executor = WorkflowExecutor(nodes=[], edges=[])
        self.inputs = {
            "start": {
                "url": "https://heym.run/docs",
                "count": 7,
                "title": 'He said "hello"',
            }
        }

    def _resolve(self, parsed: object) -> dict | None:
        return _json_object_field(self.executor, parsed, self.inputs, "rag_1", "metadataFilters")

    def test_resolves_a_plain_reference(self) -> None:
        self.assertEqual(
            self._resolve({"url": "$start.url"}),
            {"url": "https://heym.run/docs"},
        )

    def test_keeps_the_resolved_type_so_a_number_filter_matches(self) -> None:
        resolved = self._resolve({"count": "$start.count"})

        assert resolved is not None
        self.assertEqual(resolved["count"], 7)
        self.assertIs(type(resolved["count"]), int)

    def test_resolves_inside_a_text_template(self) -> None:
        self.assertEqual(self._resolve({"label": "page $start.count"}), {"label": "page 7"})

    def test_literal_filters_are_left_alone(self) -> None:
        self.assertEqual(self._resolve({"category": "faq"}), {"category": "faq"})

    def test_an_empty_filter_stays_empty(self) -> None:
        self.assertEqual(self._resolve({}), {})

    def test_a_non_object_filter_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "metadataFilters must be a JSON object"):
            self._resolve(["faq"])

    def test_a_whole_expression_filter_comes_from_the_run(self) -> None:
        self.inputs["start"]["filter"] = {"count": 7, "label": "$start.url"}
        resolved = self._resolve("$start.filter")
        self.assertEqual(resolved, {"count": 7, "label": "$start.url"})
        self.assertIs(type(resolved["count"]), int)


class TestRagMetadataWorkflowSource(unittest.TestCase):
    """A document stored by a workflow says which workflow stored it."""

    def _resolve(self, metadata_json: str, workflow_name: str = "Docs sync") -> dict:
        executor = WorkflowExecutor(nodes=[], edges=[], workflow_name=workflow_name)
        return _metadata_from_node_data(
            executor,
            {"documentMetadata": metadata_json},
            {},
            "rag_1",
        )

    def test_the_workflow_becomes_the_source(self) -> None:
        self.assertEqual(self._resolve("{}")["source"], "workflow:Docs sync")

    def test_it_is_stamped_beside_the_author_s_own_metadata(self) -> None:
        resolved = self._resolve('{"category": "faq"}')

        self.assertEqual(resolved, {"category": "faq", "source": "workflow:Docs sync"})

    def test_an_explicit_source_always_wins(self) -> None:
        self.assertEqual(self._resolve('{"source": "crm"}')["source"], "crm")

    def test_a_resolved_source_expression_also_wins(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[], workflow_name="Docs sync")
        resolved = _metadata_from_node_data(
            executor,
            {"documentMetadata": '{"source": "$start.name"}'},
            {"start": {"name": "handbook.pdf"}},
            "rag_1",
        )

        self.assertEqual(resolved["source"], "handbook.pdf")

    def test_no_workflow_name_leaves_the_source_absent(self) -> None:
        # Nothing to name, so the point stays in the plain "No source" group.
        self.assertNotIn("source", self._resolve("{}", workflow_name=""))


if __name__ == "__main__":
    unittest.main()
