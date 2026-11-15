from __future__ import annotations

import unittest

from app.services.workflow_executor import DotBool, WorkflowExecutor


class DotBoolCoercionTests(unittest.TestCase):
    def test_dotbool_integer_coercion(self) -> None:
        self.assertEqual(int(DotBool(True)), 1)
        self.assertEqual(int(DotBool(False)), 0)

    def test_dotbool_float_coercion(self) -> None:
        self.assertEqual(float(DotBool(True)), 1.0)
        self.assertEqual(float(DotBool(False)), 0.0)

    def test_dotbool_hashing_and_set_membership(self) -> None:
        true_bool = DotBool(True)
        false_bool = DotBool(False)

        self.assertEqual(hash(true_bool), hash(True))
        self.assertEqual(hash(false_bool), hash(False))

        # DotBool instances are hashable and behave as booleans in sets/dicts
        deduped = {true_bool, True, 1, false_bool, False, 0}
        self.assertEqual(len(deduped), 2)
        self.assertIn(true_bool, deduped)
        self.assertIn(false_bool, deduped)

        mapping = {true_bool: "yes", false_bool: "no"}
        self.assertEqual(mapping[True], "yes")
        self.assertEqual(mapping[False], "no")

    def test_dotbool_ordering_comparisons(self) -> None:
        t = DotBool(True)
        f = DotBool(False)

        self.assertTrue(f < t)
        self.assertTrue(f <= t)
        self.assertTrue(t > f)
        self.assertTrue(t >= f)
        self.assertTrue(t >= t)

        # Comparisons with native bools and ints
        self.assertTrue(f < True)
        self.assertTrue(t > False)
        self.assertTrue(t <= 1)
        self.assertTrue(f >= 0)

    def test_workflow_expression_coercion_on_dotbool(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        inputs = {
            "flags": [True, False, True],
        }
        res = executor.resolve_expression(
            "$flags.map('int(item)')", inputs, "test_node", preserve_type=True
        )
        self.assertEqual(res, [1, 0, 1])


if __name__ == "__main__":
    unittest.main()
