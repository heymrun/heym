import unittest

from app.services.text_truncation import (
    TRUNCATED_MARKER,
    keep_ends,
    keep_head_and_tail,
    omitted_characters_marker,
)


def _split_counted(kept: str) -> tuple[str, int, str]:
    head, _, rest = kept.partition(" …[")
    count, _, tail = rest.partition(" characters truncated]… ")
    return head, int(count), tail


class TestKeepHeadAndTail(unittest.TestCase):
    """One head+tail algorithm, shared by the compressor, the model router and traces."""

    def test_a_text_that_fits_is_untouched(self) -> None:
        self.assertEqual(keep_head_and_tail("short", 100, TRUNCATED_MARKER), "short")

    def test_it_keeps_both_ends_within_the_limit(self) -> None:
        text = "START" + "x" * 5000 + "END"
        kept = keep_head_and_tail(text, 1000, TRUNCATED_MARKER)

        self.assertTrue(kept.startswith("START"))
        self.assertTrue(kept.endswith("END"))
        self.assertIn(TRUNCATED_MARKER, kept)
        self.assertLessEqual(len(kept), 1000)

    def test_the_head_gets_about_two_thirds(self) -> None:
        kept = keep_head_and_tail("x" * 5000, 1000, TRUNCATED_MARKER)
        head, tail = kept.split(TRUNCATED_MARKER)
        self.assertAlmostEqual(len(head) / (len(head) + len(tail)), 0.65, delta=0.01)

    def test_a_budget_too_small_for_the_marker_never_overflows(self) -> None:
        for limit in range(0, len(TRUNCATED_MARKER) + 4):
            kept = keep_head_and_tail("x" * 100, limit, TRUNCATED_MARKER)
            self.assertLessEqual(len(kept), limit)


class TestCountedMarker(unittest.TestCase):
    def test_the_count_is_what_was_left_out(self) -> None:
        # Whitespace trimmed at the cut is left out too, so it is counted.
        for text in ("a" * 10_000, "word " * 2_000):
            with self.subTest(text=text[:10]):
                kept = keep_head_and_tail(text, 4096, omitted_characters_marker)
                head, count, tail = _split_counted(kept)
                self.assertEqual(len(head) + count + len(tail), len(text))
                self.assertLessEqual(len(kept), 4096)

    def test_a_second_cut_counts_what_the_first_one_left_out(self) -> None:
        # Traces cut a stored record again when many tool calls share the write budget.
        text = "START " + "x" * 10_000 + " END"
        first = keep_head_and_tail(text, 4096, omitted_characters_marker)
        second = keep_head_and_tail(first, 2000, omitted_characters_marker)

        head, count, tail = _split_counted(second)
        self.assertEqual(second.count("characters truncated"), 1)
        self.assertEqual(len(head) + count + len(tail), len(text))
        self.assertTrue(second.startswith("START") and second.endswith("END"))

    def test_it_never_overflows_when_the_count_gains_a_digit(self) -> None:
        # Across these limits the count crosses 999 to 1000 while the marker is sized.
        for limit in range(900, 1100):
            with self.subTest(limit=limit):
                kept = keep_head_and_tail("b" * 2000, limit, omitted_characters_marker)
                head, count, tail = _split_counted(kept)
                self.assertLessEqual(len(kept), limit)
                self.assertEqual(len(head) + count + len(tail), 2000)


class TestKeepEnds(unittest.TestCase):
    def test_the_count_includes_the_unread_middle(self) -> None:
        kept = keep_ends("h" * 3000, "t" * 3000, 1_000_000, 1000, omitted_characters_marker)
        head, count, tail = _split_counted(kept)
        self.assertEqual(len(head) + count + len(tail), 1_000_000)

    def test_a_short_head_is_used_whole_and_never_padded(self) -> None:
        kept = keep_ends("h" * 10, "t" * 3000, 50_000, 1000, TRUNCATED_MARKER)
        self.assertTrue(kept.startswith("h" * 10 + TRUNCATED_MARKER))
        self.assertEqual(set(kept.replace(TRUNCATED_MARKER, "")), {"h", "t"})


if __name__ == "__main__":
    unittest.main()
