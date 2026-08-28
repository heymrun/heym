"""Weight validation and the placement-ratio summary."""

import unittest

from app.api.admin_cluster import placement_ratio, validate_weight_map


class WeightValidationTests(unittest.TestCase):
    def test_enabled_weights_totalling_100_are_accepted(self) -> None:
        validate_weight_map({"main": (True, 70), "a": (True, 30)})

    def test_a_total_below_100_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 70), "a": (True, 20)})

    def test_a_total_above_100_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 70), "a": (True, 40)})

    def test_disabled_instances_are_excluded_from_the_total(self) -> None:
        validate_weight_map({"main": (True, 100), "a": (False, 40)})

    def test_a_negative_weight_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 110), "a": (True, -10)})

    def test_no_enabled_instance_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (False, 0)})


class PlacementRatioTests(unittest.TestCase):
    def test_ratio_is_reported_as_percentages(self) -> None:
        ratio = placement_ratio(main_only=25, anywhere=75)
        self.assertEqual(ratio, {"mainOnlyPercent": 25, "anywherePercent": 75})

    def test_no_runs_reports_zero_rather_than_dividing(self) -> None:
        self.assertEqual(
            placement_ratio(main_only=0, anywhere=0),
            {"mainOnlyPercent": 0, "anywherePercent": 0},
        )

    def test_an_all_main_only_workload_is_visible(self) -> None:
        """The number that tells an operator the cluster cannot help them."""
        self.assertEqual(placement_ratio(main_only=40, anywhere=0)["mainOnlyPercent"], 100)

    def test_the_two_percentages_always_total_100(self) -> None:
        for main_only, anywhere in ((1, 2), (7, 93), (33, 67), (1, 999)):
            ratio = placement_ratio(main_only=main_only, anywhere=anywhere)
            self.assertEqual(ratio["mainOnlyPercent"] + ratio["anywherePercent"], 100)
