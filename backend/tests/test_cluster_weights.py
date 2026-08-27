"""Renormalization across live instances and quota-accurate selection."""

import unittest

from app.services.cluster.weights import (
    COUNTER_RESCALE_THRESHOLD,
    normalized_weights,
    pick_instance,
    rescale_counters,
)


class NormalizationTests(unittest.TestCase):
    def test_full_pool_keeps_the_configured_split(self) -> None:
        shares = normalized_weights({"main": 70, "a": 15, "b": 15})
        self.assertAlmostEqual(shares["main"], 0.70)
        self.assertAlmostEqual(shares["a"], 0.15)

    def test_a_missing_instance_is_renormalized_away(self) -> None:
        """main=70 a=15 b=15 with a dead -> main 70/85, b 15/85."""
        shares = normalized_weights({"main": 70, "b": 15})
        self.assertAlmostEqual(shares["main"], 70 / 85)
        self.assertAlmostEqual(shares["b"], 15 / 85)

    def test_a_single_instance_takes_everything(self) -> None:
        self.assertEqual(normalized_weights({"main": 70}), {"main": 1.0})

    def test_an_empty_pool_yields_no_shares(self) -> None:
        self.assertEqual(normalized_weights({}), {})


class SelectionTests(unittest.TestCase):
    def test_the_first_pick_goes_to_the_largest_share(self) -> None:
        winner = pick_instance({"main": 70, "a": 30}, counters={})
        self.assertEqual(winner, "main")

    def test_a_long_run_converges_on_the_configured_split(self) -> None:
        counters: dict[str, int] = {}
        for _ in range(100):
            winner = pick_instance({"main": 70, "a": 30}, counters=counters)
            counters[winner] = counters.get(winner, 0) + 1
        self.assertEqual(counters["main"], 70)
        self.assertEqual(counters["a"], 30)

    def test_main_only_runs_spend_mains_quota(self) -> None:
        """30 forced runs against main=70 leave main only 40 of the next 70."""
        counters = {"main": 30}
        for _ in range(70):
            winner = pick_instance({"main": 70, "a": 30}, counters=counters)
            counters[winner] = counters.get(winner, 0) + 1
        self.assertEqual(counters["main"], 70)
        self.assertEqual(counters["a"], 30)

    def test_an_overflowing_main_starves_of_anywhere_work(self) -> None:
        """90 forced runs against main=70: every remaining run goes elsewhere."""
        counters = {"main": 90}
        for _ in range(10):
            winner = pick_instance({"main": 70, "a": 30}, counters=counters)
            counters[winner] = counters.get(winner, 0) + 1
        self.assertEqual(counters["main"], 90)
        self.assertEqual(counters["a"], 10)

    def test_an_empty_pool_returns_none(self) -> None:
        self.assertIsNone(pick_instance({}, counters={}))

    def test_selection_is_deterministic_for_the_same_state(self) -> None:
        weights = {"main": 50, "a": 50}
        self.assertEqual(
            pick_instance(weights, counters={"main": 1}),
            pick_instance(weights, counters={"main": 1}),
        )


class RescaleTests(unittest.TestCase):
    def test_counters_below_the_threshold_are_untouched(self) -> None:
        counters = {"main": 5, "a": 3}
        self.assertEqual(rescale_counters(counters), {"main": 5, "a": 3})

    def test_counters_are_halved_past_the_threshold(self) -> None:
        counters = {"main": COUNTER_RESCALE_THRESHOLD, "a": COUNTER_RESCALE_THRESHOLD // 2}
        rescaled = rescale_counters(counters)
        self.assertEqual(rescaled["main"], COUNTER_RESCALE_THRESHOLD // 2)
        self.assertEqual(rescaled["a"], COUNTER_RESCALE_THRESHOLD // 4)

    def test_rescaling_preserves_the_relative_split(self) -> None:
        counters = {"main": COUNTER_RESCALE_THRESHOLD, "a": COUNTER_RESCALE_THRESHOLD // 5}
        rescaled = rescale_counters(counters)
        self.assertAlmostEqual(rescaled["main"] / rescaled["a"], 5.0, places=1)
