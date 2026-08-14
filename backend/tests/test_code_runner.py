import io
import json
import unittest
from contextlib import redirect_stdout

from app.services.code_runner import DotDict, execute_payload, run, unwrap


class DotDictTest(unittest.TestCase):
    def test_attribute_access_on_nested_dicts(self) -> None:
        params = DotDict({"user": {"name": "Ada", "address": {"city": "Istanbul"}}})
        self.assertEqual(params.user.name, "Ada")
        self.assertEqual(params.user.address.city, "Istanbul")

    def test_list_elements_are_wrapped(self) -> None:
        params = DotDict({"orders": [{"id": 1}, {"id": 2}]})
        self.assertEqual(params.orders[0].id, 1)
        self.assertEqual(len(params.orders), 2)

    def test_item_access_works_for_non_identifier_keys(self) -> None:
        params = DotDict({"my key": "value"})
        self.assertEqual(params["my key"], "value")

    def test_missing_key_names_the_key_and_lists_alternatives(self) -> None:
        params = DotDict({"name": "Ada", "age": 36})
        with self.assertRaises(AttributeError) as ctx:
            _ = params.email
        message = str(ctx.exception)
        self.assertIn("'email'", message)
        self.assertIn("age, name", message)

    def test_to_dict_returns_plain_data(self) -> None:
        raw = {"user": {"name": "Ada"}}
        self.assertEqual(DotDict(raw).to_dict(), raw)

    def test_get_and_contains(self) -> None:
        params = DotDict({"name": "Ada"})
        self.assertEqual(params.get("name"), "Ada")
        self.assertIsNone(params.get("missing"))
        self.assertIn("name", params)


class UnwrapTest(unittest.TestCase):
    def test_unwrap_converts_dotdicts_and_tuples(self) -> None:
        value = {"a": DotDict({"b": 1}), "c": ({"d": 2},)}
        self.assertEqual(unwrap(value), {"a": {"b": 1}, "c": [{"d": 2}]})


class ExecutePayloadTest(unittest.TestCase):
    def test_main_return_value_becomes_the_result(self) -> None:
        payload = {
            "code": "def main(params):\n    return {'hello': params.name}\n",
            "params": {"name": "Heym"},
        }
        envelope = execute_payload(payload)
        self.assertTrue(envelope["success"])
        self.assertEqual(envelope["result"], {"hello": "Heym"})

    def test_print_output_is_captured_into_logs(self) -> None:
        payload = {
            "code": "print('working')\n\ndef main(params):\n    print('inside')\n    return 1\n",
            "params": {},
        }
        envelope = execute_payload(payload)
        self.assertEqual(envelope["result"], 1)
        self.assertEqual(envelope["logs"], "working\ninside\n")

    def test_missing_main_is_an_error(self) -> None:
        envelope = execute_payload({"code": "x = 1\n", "params": {}})
        self.assertFalse(envelope["success"])
        self.assertIn("main", envelope["error"])

    def test_non_callable_main_is_an_error(self) -> None:
        envelope = execute_payload({"code": "main = 5\n", "params": {}})
        self.assertFalse(envelope["success"])
        self.assertIn("main", envelope["error"])

    def test_non_serializable_return_is_an_error(self) -> None:
        payload = {"code": "def main(params):\n    return object()\n", "params": {}}
        envelope = execute_payload(payload)
        self.assertFalse(envelope["success"])
        self.assertIn("JSON-serializable", envelope["error"])

    def test_raising_code_reports_the_traceback_and_keeps_logs(self) -> None:
        payload = {
            "code": "def main(params):\n    print('before')\n    raise ValueError('boom')\n",
            "params": {},
        }
        envelope = execute_payload(payload)
        self.assertFalse(envelope["success"])
        self.assertIn("ValueError: boom", envelope["error"])
        self.assertEqual(envelope["logs"], "before\n")

    def test_sys_exit_is_reported_rather_than_ending_the_process(self) -> None:
        payload = {"code": "import sys\n\ndef main(params):\n    sys.exit(3)\n", "params": {}}
        envelope = execute_payload(payload)
        self.assertFalse(envelope["success"])

    def test_returning_params_unwraps_to_plain_json(self) -> None:
        payload = {"code": "def main(params):\n    return params\n", "params": {"a": {"b": 1}}}
        envelope = execute_payload(payload)
        self.assertEqual(envelope["result"], {"a": {"b": 1}})

    def test_stdout_is_restored_after_execution(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            execute_payload(
                {"code": "def main(params):\n    print('x')\n    return 1\n", "params": {}}
            )
            print("after")
        self.assertEqual(buffer.getvalue(), "after\n")


class RunTest(unittest.TestCase):
    def test_run_writes_the_envelope_as_json_to_stdout(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            run({"code": "def main(params):\n    return {'ok': True}\n", "params": {}})
        self.assertEqual(json.loads(buffer.getvalue())["result"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
