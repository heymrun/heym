"""Link button: a Chart Output table column whose cells open a URL in a new tab."""

import unittest

from app.services.chart_payload import build_chart_payload
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT


class TablePayloadLinkTests(unittest.TestCase):
    ROWS = [
        {"ticket": "T-1", "url": "https://jira.example.com/browse/T-1"},
        {"ticket": "T-2", "url": "/dashboards"},
    ]

    def test_a_table_with_a_link_column_carries_it_and_the_label(self) -> None:
        payload = build_chart_payload(
            {"chartType": "table", "linkColumn": " url ", "linkLabel": " Open ticket "},
            self.ROWS,
        )

        self.assertEqual(payload["linkColumn"], "url")
        self.assertEqual(payload["linkLabel"], "Open ticket")
        self.assertEqual(payload["rows"][0], ["T-1", "https://jira.example.com/browse/T-1"])

    def test_the_label_is_optional(self) -> None:
        payload = build_chart_payload({"chartType": "table", "linkColumn": "url"}, self.ROWS)

        self.assertEqual(payload["linkColumn"], "url")
        self.assertNotIn("linkLabel", payload)

    def test_a_blank_label_is_dropped(self) -> None:
        payload = build_chart_payload(
            {"chartType": "table", "linkColumn": "url", "linkLabel": "  "}, self.ROWS
        )

        self.assertNotIn("linkLabel", payload)

    def test_a_link_column_that_is_not_shown_is_dropped(self) -> None:
        payload = build_chart_payload(
            {
                "chartType": "table",
                "columns": ["ticket"],
                "linkColumn": "url",
                "linkLabel": "Open",
            },
            self.ROWS,
        )

        self.assertNotIn("linkColumn", payload)
        self.assertNotIn("linkLabel", payload)

    def test_a_link_column_that_is_not_text_is_dropped(self) -> None:
        payload = build_chart_payload({"chartType": "table", "linkColumn": 3}, self.ROWS)

        self.assertNotIn("linkColumn", payload)

    def test_other_chart_types_ignore_the_link_column(self) -> None:
        payload = build_chart_payload(
            {"chartType": "bar", "labelField": "ticket", "linkColumn": "url"}, self.ROWS
        )

        self.assertNotIn("linkColumn", payload)

    def test_a_link_column_sits_beside_a_status_column(self) -> None:
        rows = [{"ticket": "T-1", "state": "Paid", "url": "https://example.com"}]
        payload = build_chart_payload(
            {"chartType": "table", "statusColumn": "state", "linkColumn": "url"}, rows
        )

        self.assertEqual(payload["statusColumn"], "state")
        self.assertEqual(payload["linkColumn"], "url")


class LinkColumnDslPromptTests(unittest.TestCase):
    def test_the_dsl_prompt_documents_the_link_fields(self) -> None:
        self.assertIn("`linkColumn`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("`linkLabel`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn('"linkColumn": "url"', WORKFLOW_DSL_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
