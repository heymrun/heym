"""A reference built from an attacker-chosen name must never resolve another secret.

The Credentials panel, the Variable node hint and expression autocomplete write
`$credentials["name"]`, `$vars["name"]` and `$global["name"]` for names that are not plain
identifiers. A shared credential, a global variable or a variable node can carry any name, so a
quote or bracket in it must not close the key early and reach a neighbouring entry.
"""

import json
import unittest

from app.services.expression_evaluator import ExpressionEvaluatorService
from app.services.workflow_executor import WorkflowExecutor

OTHER_SECRET = "other-secret-value"
HOSTILE_NAMES = [
    'x"] + $credentials["admin',
    'x"]+$credentials["admin"]+$credentials["x',
    "a'] + $credentials['admin",
    'x\\"] + $credentials[\\"admin',
    "a]b",
]


class ContextReferenceNamesTest(unittest.TestCase):
    def _resolve(self, root: str, template: str, values: dict[str, str]) -> list[object]:
        contexts = {
            "credentials": {"credentials_context": values},
            "vars": {},
            "global": {"global_variables_context": values},
        }[root]
        executor = WorkflowExecutor(nodes=[], edges=[], **contexts)
        if root == "vars":
            executor.vars = dict(values)
        service = ExpressionEvaluatorService(
            **contexts, **({"vars_context": values} if root == "vars" else {})
        )
        return [
            executor.evaluate_message_template(template, {}, None),
            service.evaluate(template, {}).result,
        ]

    def test_hostile_name_does_not_resolve_a_neighbouring_entry(self) -> None:
        for root in ("credentials", "vars", "global"):
            for name in HOSTILE_NAMES:
                values = {name: "own-value", "admin": OTHER_SECRET, "x": "x-value", "a": "a-value"}
                reference = f"${root}[{json.dumps(name, ensure_ascii=False)}]"
                for template in (reference, f"Bearer {reference} end"):
                    with self.subTest(root=root, template=template):
                        for result in self._resolve(root, template, values):
                            self.assertNotIn(OTHER_SECRET, str(result))

    def test_bracket_form_returns_the_named_entry_not_a_shorter_prefix(self) -> None:
        """`heym-codex-support` must not fall back to the unrelated `heym` entry."""
        values = {"heym-codex-support": "the-real-secret", "heym": "prefix-secret"}
        for root in ("credentials", "vars", "global"):
            reference = f'${root}["heym-codex-support"]'
            with self.subTest(root=root):
                for result in self._resolve(root, reference, values):
                    self.assertEqual(result, "the-real-secret")


if __name__ == "__main__":
    unittest.main()
