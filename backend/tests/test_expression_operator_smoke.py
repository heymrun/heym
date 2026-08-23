"""Exhaustive smoke matrix for the expression operator surface.

One `set` node builds a fixture, a second `set` node applies every documented operator to
it, and the workflow runs through the real executor. Each case is asserted three ways:

1. the value the `set` node writes to node output (the run path),
2. the value `ExpressionEvaluatorService` previews (the canvas dialog path),
3. the same expression rewritten onto `$global` and `$vars`, so a context root can never
   silently lose operators the way `$global` did while `global` broke `ast.parse`.

`TestExpressionOperatorCoverage` fails when a Dot wrapper method or a registered function
has no case here, so a new expression cannot ship without smoke coverage.
"""

import hashlib
import json
import re
import unittest
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from app.services.expression_evaluator import ExpressionEvaluatorService
from app.services.workflow_executor import (
    DotBool,
    DotDateTime,
    DotDict,
    DotFloat,
    DotInt,
    DotList,
    DotStr,
    WorkflowExecutor,
    execute_workflow,
)

SAMPLE_TEXT = "  Heym Workflow  "
SAMPLE_URL = "https://heym.run/docs?q=a b"
SAMPLE_JSON_TEXT = '{"name": "ada", "age": 36}'
FIXED_DATE = "2026-03-05T14:30:00"

# Values the fixture `set` node produces, mirrored here so expectations stay derived.
SAMPLE_WORDS = ["beta", "alpha", "beta"]
SAMPLE_PEOPLE = [{"name": "ada", "age": 36}, {"name": "bob", "age": 24}]
SAMPLE_PROFILE = {"name": "ada", "age": 36}

SAMPLE_MAPPINGS: list[dict[str, str]] = [
    {"key": "text", "value": SAMPLE_TEXT},
    {"key": "url", "value": SAMPLE_URL},
    {"key": "jsonText", "value": SAMPLE_JSON_TEXT},
    {"key": "encoded", "value": "SGV5bQ=="},
    {"key": "num", "value": "$int(7)"},
    {"key": "ratio", "value": "$float(2.5)"},
    {"key": "flag", "value": "$bool(1)"},
    {"key": "words", "value": "$array('beta', 'alpha', 'beta')"},
    {"key": "nullable", "value": "$array('beta', null)"},
    {"key": "nested", "value": "$array($array('a', 'b'), $array('c'))"},
    {"key": "people", "value": "$array(dict(name='ada', age=36), dict(name='bob', age=24))"},
    {"key": "profile", "value": "$dict(name='ada', age=36)"},
]

Expected = object | Callable[[Any], bool]

# key, expression, expected value (or a predicate for nondeterministic results).
# Add a row here whenever an operator is added to the Dot wrappers or the function registry.
OPERATOR_CASES: list[tuple[str, str, Expected]] = [
    # --- DotStr -----------------------------------------------------------------
    ("strTrim", "$sample.text.trim()", "Heym Workflow"),
    ("strStrip", "$sample.text.strip()", "Heym Workflow"),
    ("strUpper", "$sample.text.trim().upper()", "HEYM WORKFLOW"),
    ("strLower", "$sample.text.trim().lower()", "heym workflow"),
    ("strToUpperCase", "$sample.text.trim().toUpperCase()", "HEYM WORKFLOW"),
    ("strToLowerCase", "$sample.text.trim().toLowerCase()", "heym workflow"),
    ("strCapitalize", "$sample.text.trim().capitalize()", "Heym workflow"),
    ("strTitle", "$sample.text.trim().title()", "Heym Workflow"),
    ("strLength", "$sample.text.length", len(SAMPLE_TEXT)),
    ("strCharAt", "$sample.text.trim().charAt(0)", "H"),
    ("strSubstring", "$sample.text.trim().substring(0, 4)", "Heym"),
    ("strSubstr", "$sample.text.trim().substr(5, 8)", "Workflow"),
    ("strReplace", "$sample.text.trim().replace('Heym', 'Flow')", "Flow Workflow"),
    ("strReplaceAll", "$sample.text.trim().replaceAll(' ', '-')", "Heym-Workflow"),
    ("strStartswith", "$sample.text.trim().startswith('Heym')", True),
    ("strEndswith", "$sample.text.trim().endswith('Workflow')", True),
    ("strContains", "$sample.text.contains('Work')", True),
    ("strIndexOf", "$sample.text.trim().indexOf('Work')", 5),
    ("strReverse", "$sample.text.trim().reverse()", "wolfkroW myeH"),
    ("strSplit", "$sample.text.trim().split(' ')", ["Heym", "Workflow"]),
    ("strRegexReplace", "$sample.text.trim().regexReplace('[aeiou]', '*')", "H*ym W*rkfl*w"),
    (
        "strHash",
        "$sample.text.trim().hash()",
        hashlib.md5(b"Heym Workflow").hexdigest(),
    ),
    ("strBase64Encode", "$sample.text.trim().base64Encode()", "SGV5bSBXb3JrZmxvdw=="),
    ("strBase64Decode", "$sample.encoded.base64Decode()", "Heym"),
    ("strUrlEncode", "$sample.url.urlEncode()", quote(SAMPLE_URL, safe="")),
    ("strUrlDecode", "$sample.url.urlEncode().urlDecode()", SAMPLE_URL),
    ("strToJson", "$sample.jsonText.toJson().name", "ada"),
    ("strOrEmpty", "$sample.missing.orEmpty()", ""),
    # --- DotInt / DotFloat / DotBool --------------------------------------------
    ("intToString", "$sample.num.toString()", "7"),
    ("floatToString", "$sample.ratio.toString()", "2.5"),
    ("boolToString", "$sample.flag.toString()", "true"),
    ("intArithmetic", "$sample.num + 3", 10),
    ("floatArithmetic", "$sample.ratio - 0.5", 2.0),
    # --- DotList -----------------------------------------------------------------
    ("listLength", "$sample.words.length", 3),
    ("listFirst", "$sample.words.first()", "beta"),
    ("listLast", "$sample.words.last()", "beta"),
    ("listDistinct", "$sample.words.distinct()", ["beta", "alpha"]),
    ("listSort", "$sample.words.sort()", ["alpha", "beta", "beta"]),
    ("listReverse", "$sample.words.reverse()", ["beta", "alpha", "beta"]),
    ("listTake", "$sample.words.take(2)", ["beta", "alpha"]),
    ("listJoin", "$sample.words.join('|')", "beta|alpha|beta"),
    ("listContains", "$sample.words.contains('alpha')", True),
    ("listAdd", "$sample.words.add('gamma')", ["beta", "alpha", "beta", "gamma"]),
    ("listNotNull", "$sample.nullable.notNull()", ["beta"]),
    ("listFlat", "$sample.nested.flat()", ["a", "b", "c"]),
    ("listMap", "$sample.people.map('item.name')", ["ada", "bob"]),
    ("listFilter", "$sample.people.filter('item.age > 30')", [SAMPLE_PEOPLE[0]]),
    ("listDistinctBy", "$sample.people.distinctBy('item.name').length", 2),
    ("listSortBy", "$sample.people.sort('item.age')", [SAMPLE_PEOPLE[1], SAMPLE_PEOPLE[0]]),
    ("listToString", "$sample.words.toString()", json.dumps(SAMPLE_WORDS)),
    ("listRandom", "$sample.words.random()", lambda v: v in SAMPLE_WORDS),
    # --- DotDict -----------------------------------------------------------------
    ("dictKeys", "$sample.profile.keys()", ["name", "age"]),
    ("dictValues", "$sample.profile.values()", ["ada", 36]),
    (
        "dictEntries",
        "$sample.profile.entries()",
        [{"key": "name", "value": "ada"}, {"key": "age", "value": 36}],
    ),
    ("dictGet", "$sample.profile.get('name')", "ada"),
    ("dictMap", "$sample.profile.map('item.key')", ["name", "age"]),
    ("dictFilter", "$sample.profile.filter(\"item.key == 'name'\").length", 1),
    ("dictToString", "$sample.profile.toString()", json.dumps(SAMPLE_PROFILE)),
    # --- DotDateTime --------------------------------------------------------------
    ("dateYear", f"$Date('{FIXED_DATE}').year", 2026),
    ("dateMonth", f"$Date('{FIXED_DATE}').month", 3),
    ("dateDay", f"$Date('{FIXED_DATE}').day", 5),
    ("dateHour", f"$Date('{FIXED_DATE}').hour", 14),
    ("dateMinute", f"$Date('{FIXED_DATE}').minute", 30),
    ("dateSecond", f"$Date('{FIXED_DATE}').second", 0),
    ("dateDayOfWeek", f"$Date('{FIXED_DATE}').dayOfWeek", 3),
    ("dateFormat", f"$Date('{FIXED_DATE}').format('DD MMM YYYY HH:mm')", "05 Mar 2026 14:30"),
    ("dateToDate", f"$Date('{FIXED_DATE}').toDate()", "2026-03-05"),
    ("dateToTime", f"$Date('{FIXED_DATE}').toTime()", "14:30:00"),
    # ISO / epoch carry the workflow timezone offset, so assert shape, not the offset.
    ("dateToIso", f"$Date('{FIXED_DATE}').toISO()", lambda v: str(v).startswith(FIXED_DATE)),
    ("dateToString", f"$Date('{FIXED_DATE}').toString()", lambda v: str(v).startswith(FIXED_DATE)),
    ("dateToUnix", f"$Date('{FIXED_DATE}').toUnix()", lambda v: isinstance(v, int) and v > 0),
    (
        "dateToMillis",
        f"$Date('{FIXED_DATE}').toMillis()",
        lambda v: isinstance(v, int) and v > 1_000_000_000_000,
    ),
    ("dateAddDays", f"$Date('{FIXED_DATE}').addDays(2).toDate()", "2026-03-07"),
    ("dateAddHours", f"$Date('{FIXED_DATE}').addHours(2).toTime()", "16:30:00"),
    ("dateAddMinutes", f"$Date('{FIXED_DATE}').addMinutes(15).toTime()", "14:45:00"),
    ("dateAddMonths", f"$Date('{FIXED_DATE}').addMonths(1).toDate()", "2026-04-05"),
    ("dateAddYears", f"$Date('{FIXED_DATE}').addYears(1).toDate()", "2027-03-05"),
    ("dateStartOfDay", f"$Date('{FIXED_DATE}').startOfDay().toTime()", "00:00:00"),
    ("dateEndOfDay", f"$Date('{FIXED_DATE}').endOfDay().toTime()", "23:59:59"),
    ("dateStartOfMonth", f"$Date('{FIXED_DATE}').startOfMonth().toDate()", "2026-03-01"),
    ("dateEndOfMonth", f"$Date('{FIXED_DATE}').endOfMonth().toDate()", "2026-03-31"),
    # --- registered functions ------------------------------------------------------
    ("fnLen", "$len($sample.words)", 3),
    ("fnStr", "$str($sample.num)", "7"),
    ("fnInt", "$int($sample.ratio)", 2),
    ("fnFloat", "$float($sample.num)", 7.0),
    ("fnBool", "$bool($sample.num)", True),
    ("fnAbs", "$abs(0 - $sample.num)", 7),
    ("fnMin", "$min($sample.num, 3)", 3),
    ("fnMax", "$max($sample.num, 3)", 7),
    ("fnRound", "$round($sample.ratio)", 2),
    ("fnSum", "$sum($sample.people.map('item.age'))", 60),
    ("fnSorted", "$sorted($sample.words)", ["alpha", "beta", "beta"]),
    ("fnList", "$list($sample.words)", SAMPLE_WORDS),
    ("fnArray", "$array('a', 'b')", ["a", "b"]),
    ("fnDict", "$dict(name='ada')", {"name": "ada"}),
    ("fnNotNull", "$notNull($sample.nullable)", ["beta"]),
    ("fnUpper", "$upper($sample.text.trim())", "HEYM WORKFLOW"),
    ("fnLower", "$lower($sample.text.trim())", "heym workflow"),
    ("fnStrip", "$strip($sample.text)", "Heym Workflow"),
    ("fnCapitalize", "$capitalize('heym')", "Heym"),
    ("fnTitle", "$title('heym run')", "Heym Run"),
    ("fnSplit", "$split('a,b', ',')", ["a", "b"]),
    ("fnJoin", "$join('-', $sample.words)", "beta-alpha-beta"),
    ("fnReplace", "$replace('heym', 'h', 'H')", "Heym"),
    ("fnConcat", "$concat('a', 'b')", "ab"),
    ("fnToJson", "$toJson($sample.jsonText).age", 36),
    ("fnBase64Encode", "$base64Encode('Heym')", "SGV5bQ=="),
    ("fnBase64Decode", "$base64Decode('SGV5bQ==')", "Heym"),
    ("fnRange", "$range(1, 4)", [1, 2, 3]),
    ("fnDate", f"$Date('{FIXED_DATE}').toDate()", "2026-03-05"),
    ("fnRand", "$rand()", lambda v: isinstance(v, float) and 0.0 <= v < 1.0),
    ("fnRandint", "$randint(5)", lambda v: isinstance(v, int) and 0 <= v <= 5),
    ("fnRandomInt", "$randomInt(1, 3)", lambda v: isinstance(v, int) and 1 <= v <= 3),
    # --- operators and control flow -------------------------------------------------
    ("opTernary", "$sample.num > 5 ? 'big' : 'small'", "big"),
    ("opComparison", "$sample.num >= 7", True),
    # `and`/`or` join two refs into a text template in a `set` field, so exercise the
    # boolean operators where a `set` field really evaluates them: inside an item expression.
    ("opBooleanAnd", "$sample.people.filter('item.age > 30 and item.name == \"ada\"').length", 1),
    ("opBooleanOr", "$sample.people.filter('item.age > 30 or item.name == \"bob\"').length", 2),
    ("opStringConcat", "$sample.text.trim() + '!'", "Heym Workflow!"),
]

# Roots the same expression body must resolve identically from.
CONTEXT_ROOTS = ("sample", "vars", "global")


def _sample_fixture() -> dict[str, Any]:
    return {
        "text": SAMPLE_TEXT,
        "url": SAMPLE_URL,
        "jsonText": SAMPLE_JSON_TEXT,
        "encoded": "SGV5bQ==",
        "num": 7,
        "ratio": 2.5,
        "flag": True,
        "words": list(SAMPLE_WORDS),
        "nullable": ["beta", None],
        "nested": [["a", "b"], ["c"]],
        "people": [dict(person) for person in SAMPLE_PEOPLE],
        "profile": dict(SAMPLE_PROFILE),
    }


def _assert_case(test: unittest.TestCase, expected: Expected, actual: Any, label: str) -> None:
    if callable(expected):
        test.assertTrue(expected(actual), f"{label}: unexpected value {actual!r}")
        return
    test.assertEqual(actual, expected, label)


class TestExpressionOperatorSmokeRun(unittest.TestCase):
    """Every operator resolved by a real two-node `set` workflow."""

    @classmethod
    def setUpClass(cls) -> None:
        nodes = [
            {
                "id": "sample_node",
                "type": "set",
                "data": {"label": "sample", "mappings": SAMPLE_MAPPINGS},
            },
            {
                "id": "ops_node",
                "type": "set",
                "data": {
                    "label": "ops",
                    "mappings": [
                        {"key": key, "value": expression}
                        for key, expression, _expected in OPERATOR_CASES
                    ],
                },
            },
        ]
        edges = [{"id": "edge_1", "source": "sample_node", "target": "ops_node"}]
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs={},
            test_run=True,
        )
        cls.status = result.status
        cls.output: dict[str, Any] = {}
        for node_result in result.node_results:
            label = (
                node_result["node_label"]
                if isinstance(node_result, dict)
                else node_result.node_label
            )
            if label != "ops":
                continue
            cls.output = (
                node_result["output"] if isinstance(node_result, dict) else node_result.output
            )

    def test_workflow_succeeds(self) -> None:
        self.assertEqual(self.status, "success")

    def test_mapping_keys_are_complete(self) -> None:
        self.assertEqual(
            sorted(self.output),
            sorted(key for key, _expression, _expected in OPERATOR_CASES),
        )

    def test_every_operator_resolves_in_the_run(self) -> None:
        for key, expression, expected in OPERATOR_CASES:
            with self.subTest(expression=expression):
                _assert_case(self, expected, self.output.get(key), key)


class TestExpressionOperatorSmokePreview(unittest.TestCase):
    """The canvas evaluate dialog must answer exactly what the run produced."""

    def test_preview_matches_the_documented_result(self) -> None:
        service = ExpressionEvaluatorService()
        context = {"sample": _sample_fixture()}
        for key, expression, expected in OPERATOR_CASES:
            with self.subTest(expression=expression):
                response = service.evaluate(expression, context)
                self.assertIsNone(response.error, f"{key}: {response.error}")
                _assert_case(self, expected, response.result, key)


class TestExpressionOperatorsAcrossContextRoots(unittest.TestCase):
    """`$sample`, `$vars` and `$global` must resolve the same operator identically.

    `global` is a Python keyword, so `$global.x.substring(0, 5)` once failed `ast.parse` and
    fell through to a fallback resolver that silently returned null for most operators.
    """

    def test_roots_agree(self) -> None:
        fixture = _sample_fixture()
        executor = WorkflowExecutor(
            nodes=[],
            edges=[],
            global_variables_context=dict(fixture),
        )
        executor.vars.update(fixture)
        executor._mark_vars_context_dirty()
        inputs = {"sample": dict(fixture)}

        for key, expression, expected in OPERATOR_CASES:
            if "$sample." not in expression:
                continue
            for root in CONTEXT_ROOTS:
                rooted = expression.replace("$sample.", f"${root}.")
                with self.subTest(expression=rooted):
                    _assert_case(
                        self,
                        expected,
                        executor.resolve_expression(rooted, inputs, preserve_type=True),
                        f"{key} via ${root}",
                    )


class TestExpressionOperatorCoverage(unittest.TestCase):
    """Fails when an operator ships without a row in `OPERATOR_CASES`.

    Add the operator to the DSL prompt, the docs, and this table together — see the
    "Expression evaluation" section of AGENTS.md.
    """

    WRAPPERS = (DotStr, DotList, DotInt, DotFloat, DotBool, DotDateTime, DotDict)

    @staticmethod
    def _fold(name: str) -> str:
        """Fold `toISO`, `to_iso` and `toIso` onto one key so aliases share a case."""
        return name.replace("_", "").lower()

    def _covered_identifiers(self) -> set[str]:
        text = " ".join(expression for _key, expression, _expected in OPERATOR_CASES)
        return {self._fold(token) for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}

    def test_every_wrapper_method_has_a_case(self) -> None:
        covered = self._covered_identifiers()
        missing = [
            f"{wrapper.__name__}.{name}"
            for wrapper in self.WRAPPERS
            for name in vars(wrapper)
            if not name.startswith("_") and self._fold(name) not in covered
        ]
        self.assertEqual(missing, [], f"Expression methods without a smoke case: {missing}")

    def test_every_registered_function_has_a_case(self) -> None:
        covered = self._covered_identifiers()
        functions = WorkflowExecutor(nodes=[], edges=[])._get_evaluator_functions()
        missing = [
            name
            for name in functions
            if not name.startswith("_") and self._fold(name) not in covered
        ]
        self.assertEqual(missing, [], f"Expression functions without a smoke case: {missing}")


if __name__ == "__main__":
    unittest.main()
