"""Weight validation and the placement-ratio summary."""

import unittest

from app.api.admin_cluster import ensure_main_enabled, placement_ratio, validate_weight_map


class WeightValidationTests(unittest.TestCase):
    def test_enabled_weights_totalling_100_are_accepted(self) -> None:
        validate_weight_map({"main": (True, 70), "a": (True, 30)})

    def test_a_total_other_than_100_is_accepted(self) -> None:
        """Weights are shares of the live pool; the scheduler renormalizes them.

        Requiring 100 would block saving the moment an instance is disabled.
        """
        validate_weight_map({"main": (True, 70), "a": (True, 20)})
        validate_weight_map({"main": (True, 70), "a": (True, 40)})

    def test_a_disabled_instance_does_not_break_the_split(self) -> None:
        validate_weight_map({"main": (True, 41), "a": (True, 26), "b": (False, 33)})

    def test_all_enabled_weights_at_zero_is_rejected(self) -> None:
        """Nothing could be scheduled."""
        with self.assertRaises(ValueError):
            validate_weight_map({"main": (True, 0), "a": (False, 50)})

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


class MainStaysEnabledTests(unittest.TestCase):
    """Main cannot be taken out of rotation.

    MAIN_ONLY work - files, plugins, coding agents, email - routes there
    regardless, so a disabled main would be a state the toggle does not
    describe rather than a machine that stopped taking work.
    """

    def test_disabling_main_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ensure_main_enabled("main", False)

    def test_main_may_stay_enabled(self) -> None:
        ensure_main_enabled("main", True)

    def test_a_worker_may_be_disabled(self) -> None:
        ensure_main_enabled("worker", False)
