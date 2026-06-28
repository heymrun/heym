import unittest
import uuid

from app.api.analytics import compute_time_saved_minutes


class TestComputeTimeSaved(unittest.TestCase):
    def test_sums_rate_times_success_count(self) -> None:
        wid_a = uuid.uuid4()
        wid_b = uuid.uuid4()
        success_by_workflow = {wid_a: 10, wid_b: 4}
        rate_by_workflow = {wid_a: 3.0, wid_b: 5.0}
        # 10*3 + 4*5 = 50
        self.assertEqual(compute_time_saved_minutes(success_by_workflow, rate_by_workflow), 50.0)

    def test_missing_rate_counts_zero(self) -> None:
        wid = uuid.uuid4()
        self.assertEqual(compute_time_saved_minutes({wid: 7}, {}), 0.0)

    def test_none_workflow_id_ignored(self) -> None:
        wid = uuid.uuid4()
        self.assertEqual(compute_time_saved_minutes({wid: 2, None: 99}, {wid: 4.0}), 8.0)


if __name__ == "__main__":
    unittest.main()
