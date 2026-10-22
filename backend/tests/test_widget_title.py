"""Widget titles say what a widget shows in a few words, never with a data table's id."""

import unittest

from app.services.widget_title import DEFAULT_WIDGET_TITLE, MAX_TITLE_WORDS, widget_title

TABLE_ID = "b7357f77-9087-467b-a5f2-ac9eaba3a423"


class TestWidgetTitle(unittest.TestCase):
    def test_a_short_name_is_kept(self) -> None:
        self.assertEqual(widget_title("Open cases"), "Open cases")
        self.assertEqual(widget_title("Aktif adaylar"), "Aktif adaylar")

    def test_a_table_id_in_parentheses_is_dropped(self) -> None:
        name = f"discovery_candidates tablosunu (dataTableId: {TABLE_ID})"

        self.assertEqual(widget_title(name), "Discovery candidates tablosunu")

    def test_a_bare_id_and_a_data_table_id_mention_are_dropped(self) -> None:
        self.assertEqual(widget_title(f"Leads {TABLE_ID}"), "Leads")
        self.assertEqual(widget_title(f"Leads dataTableId: {TABLE_ID}"), "Leads")

    def test_underscores_read_as_spaces(self) -> None:
        self.assertEqual(widget_title("active_cases"), "Active cases")

    def test_at_most_four_words_are_kept(self) -> None:
        title = widget_title("Number of active candidates by stage and source")

        self.assertEqual(title, "Number of active candidates")
        self.assertEqual(len(title.split()), MAX_TITLE_WORDS)

    def test_the_next_candidate_is_used_when_the_name_says_nothing(self) -> None:
        self.assertEqual(widget_title(None, "show open cases by priority"), "Show open cases by")
        self.assertEqual(widget_title(f"({TABLE_ID})", "Leads"), "Leads")
        self.assertEqual(widget_title("  ", ""), DEFAULT_WIDGET_TITLE)

    def test_punctuation_at_the_ends_is_trimmed(self) -> None:
        self.assertEqual(widget_title('"Open cases."'), "Open cases")


if __name__ == "__main__":
    unittest.main()
