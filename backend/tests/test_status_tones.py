"""Status chips: tones for the status column of a Chart Output table."""

import unittest

from app.services.chart_payload import build_chart_payload
from app.services.status_tones import STATUS_TONES, default_tone, resolve_status_tones
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT


class DefaultToneTests(unittest.TestCase):
    def test_common_words_get_a_tone(self) -> None:
        self.assertEqual(default_tone("Paid"), "success")
        self.assertEqual(default_tone("needs review"), "attention")
        self.assertEqual(default_tone("FAILED"), "failure")
        self.assertEqual(default_tone("in_progress"), "waiting")
        self.assertEqual(default_tone("in-progress"), "waiting")

    def test_other_values_are_neutral(self) -> None:
        self.assertEqual(default_tone("Gold tier"), "neutral")
        self.assertEqual(default_tone(42), "neutral")
        self.assertEqual(default_tone(None), "neutral")


class ResolveStatusTonesTests(unittest.TestCase):
    def test_every_distinct_value_gets_one_entry(self) -> None:
        tones = resolve_status_tones(["Paid", "Overdue", "Paid", None, "Gold tier"])

        self.assertEqual(tones, {"Paid": "success", "Overdue": "attention", "Gold tier": "neutral"})

    def test_overrides_win_and_match_without_case(self) -> None:
        tones = resolve_status_tones(
            ["Paid", "Disputed", "Escalated"],
            {"disputed": "failure", "PAID": "waiting", "Escalated": "loud"},
        )

        self.assertEqual(tones, {"Paid": "waiting", "Disputed": "failure", "Escalated": "neutral"})

    def test_values_are_keyed_as_the_table_shows_them(self) -> None:
        self.assertEqual(
            resolve_status_tones([True, False]), {"true": "neutral", "false": "neutral"}
        )
        self.assertEqual(resolve_status_tones([1]), {"1": "neutral"})

    def test_overrides_that_are_not_a_mapping_are_ignored(self) -> None:
        self.assertEqual(resolve_status_tones(["Paid"], ["failure"]), {"Paid": "success"})

    def test_the_tone_set(self) -> None:
        self.assertEqual(STATUS_TONES, ("success", "attention", "failure", "waiting", "neutral"))


class TablePayloadStatusTests(unittest.TestCase):
    ROWS = [
        {"invoice": "INV-1", "state": "Paid"},
        {"invoice": "INV-2", "state": "Disputed"},
    ]

    def test_a_table_with_a_status_column_carries_its_tones(self) -> None:
        payload = build_chart_payload(
            {
                "chartType": "table",
                "statusColumn": " state ",
                "statusTones": {"Disputed": "failure"},
            },
            self.ROWS,
        )

        self.assertEqual(payload["statusColumn"], "state")
        self.assertEqual(payload["statusTones"], {"Paid": "success", "Disputed": "failure"})

    def test_a_status_column_that_is_not_shown_is_dropped(self) -> None:
        payload = build_chart_payload(
            {"chartType": "table", "columns": ["invoice"], "statusColumn": "state"}, self.ROWS
        )

        self.assertNotIn("statusColumn", payload)
        self.assertNotIn("statusTones", payload)

    def test_other_chart_types_ignore_the_status_column(self) -> None:
        payload = build_chart_payload(
            {"chartType": "bar", "labelField": "invoice", "statusColumn": "state"}, self.ROWS
        )

        self.assertNotIn("statusColumn", payload)


class StatusChipsDslPromptTests(unittest.TestCase):
    def test_the_dsl_prompt_documents_the_status_fields(self) -> None:
        self.assertIn("`statusColumn`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("`statusTones`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn('"statusColumn": "state"', WORKFLOW_DSL_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
