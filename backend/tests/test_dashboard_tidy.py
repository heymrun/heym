"""The tidy arrangement chat gives a dashboard, the same as the Dashboard tab's Tidy up button."""

import unittest

from app.services.dashboard_tidy import TIDY_ROW_HEIGHT, tidy_layouts


def _draws(*values):
    """A random source that returns ``values`` in turn."""
    remaining = list(values)
    return lambda: remaining.pop(0)


def _untidy(count):
    return [{"x": 0, "y": index * 4, "w": 4, "h": 4} for index in range(count)]


class TidyLayoutsTests(unittest.TestCase):
    def test_random_rows_hold_two_or_three_widgets_with_a_short_last_row(self):
        self.assertEqual(tidy_layouts(_untidy(5), rand=lambda: 0.0).rows, [2, 2, 1])
        self.assertEqual(tidy_layouts(_untidy(5), rand=lambda: 0.9).rows, [3, 2])
        self.assertEqual(tidy_layouts(_untidy(7), rand=lambda: 0.9).rows, [3, 3, 1])

    def test_widgets_in_a_row_share_its_width(self):
        tidy = tidy_layouts(_untidy(5), rand=lambda: 0.9)

        self.assertEqual(
            tidy.layouts,
            [
                {"x": 0, "y": 0, "w": 4, "h": TIDY_ROW_HEIGHT},
                {"x": 4, "y": 0, "w": 4, "h": TIDY_ROW_HEIGHT},
                {"x": 8, "y": 0, "w": 4, "h": TIDY_ROW_HEIGHT},
                {"x": 0, "y": TIDY_ROW_HEIGHT, "w": 6, "h": TIDY_ROW_HEIGHT},
                {"x": 6, "y": TIDY_ROW_HEIGHT, "w": 6, "h": TIDY_ROW_HEIGHT},
            ],
        )

    def test_rows_that_match_the_dashboard_are_drawn_again(self):
        current = tidy_layouts(_untidy(5), rand=lambda: 0.0).layouts

        tidy = tidy_layouts(current, rand=_draws(0.0, 0.0, 0.9))

        self.assertEqual(tidy.rows, [3, 2])

    def test_a_single_possible_arrangement_is_kept(self):
        current = tidy_layouts(_untidy(2)).layouts

        self.assertEqual(tidy_layouts(current).layouts, current)

    def test_per_row_fixes_the_row_size_and_width(self):
        tidy = tidy_layouts(_untidy(5), per_row=4)

        self.assertEqual(tidy.rows, [4, 1])
        self.assertEqual([layout["w"] for layout in tidy.layouts], [3, 3, 3, 3, 3])
        self.assertEqual([layout["x"] for layout in tidy.layouts], [0, 3, 6, 9, 0])

    def test_per_row_keeps_an_arrangement_the_dashboard_already_has(self):
        current = tidy_layouts(_untidy(3), per_row=1).layouts

        self.assertEqual(tidy_layouts(current, per_row=1).layouts, current)


if __name__ == "__main__":
    unittest.main()
