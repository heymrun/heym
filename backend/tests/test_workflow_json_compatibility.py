import json
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.workflow_executor import (
    DotDateTime,
    DotDict,
    DotList,
    DotStr,
    NodeResult,
    SubWorkflowExecution,
    _serialize_node_result,
    _serialize_sub_workflow_executions,
    _to_json_compatible,
)


class WorkflowJsonCompatibilityTests(unittest.TestCase):
    def test_dot_wrappers_with_method_name_keys_serialize_to_json(self) -> None:
        wrapped = DotDict(
            {
                "items": DotList([DotDict({"value": 1})]),
                "keys": DotList(["a", "b"]),
            }
        )

        plain = _to_json_compatible(wrapped)

        self.assertEqual(plain, {"items": [{"value": 1}], "keys": ["a", "b"]})
        json.dumps(plain)

    def test_postgresql_unsafe_characters_are_sanitized_recursively(self) -> None:
        wrapped = DotDict(
            {
                "unsafe\u0000key": DotList(
                    [
                        DotStr("null\u0000byte"),
                        {"controls": "before\u0001\u0008\u000b\u001f\u007f\u0080\u009fafter"},
                        {"surrogate": "before\ud800after"},
                    ]
                ),
                "whitespace": "tab\tnewline\nreturn\r",
            }
        )

        plain = _to_json_compatible(wrapped)

        self.assertEqual(
            plain,
            {
                "unsafekey": [
                    "nullbyte",
                    {"controls": "beforeafter"},
                    {"surrogate": "beforeafter"},
                ],
                "whitespace": "tab\tnewline\nreturn\r",
            },
        )
        serialized = json.dumps(plain)
        self.assertNotIn(r"\u0000", serialized)
        self.assertNotIn(r"\ud800", serialized)

    def test_node_result_serialization_removes_dot_wrappers(self) -> None:
        result = NodeResult(
            node_id="node_1",
            node_label="node",
            node_type="set",
            status="success",
            output={"items": DotList([DotDict({"value": 1})])},
            execution_time_ms=1.0,
        )

        serialized = _serialize_node_result(result)

        self.assertEqual(serialized["output"], {"items": [{"value": 1}]})
        json.dumps(serialized)

    def test_subworkflow_serialization_removes_dot_wrappers(self) -> None:
        execution = SubWorkflowExecution(
            workflow_id="00000000-0000-0000-0000-000000000001",
            inputs={"items": DotList(["input"])},
            outputs={"items": DotList(["output"])},
            status="success",
            execution_time_ms=1.0,
            node_results=[
                {
                    "node_id": "node_1",
                    "output": {"items": DotList([DotDict({"value": 1})])},
                }
            ],
        )

        serialized = _serialize_sub_workflow_executions([execution])[0]

        self.assertEqual(serialized["outputs"], {"items": ["output"]})
        self.assertEqual(serialized["node_results"][0]["output"], {"items": [{"value": 1}]})
        json.dumps(serialized)

    def test_datetime_and_date_serialize_to_iso_strings(self) -> None:
        dt_naive = datetime(2026, 11, 16, 10, 45, 30, 123456)
        dt_tz = datetime(2026, 11, 16, 10, 45, 30, tzinfo=timezone.utc)
        d = date(2026, 11, 16)

        data = {
            "dt_naive": dt_naive,
            "dt_tz": dt_tz,
            "d": d,
        }
        plain = _to_json_compatible(data)

        self.assertEqual(
            plain,
            {
                "dt_naive": "2026-11-16T10:45:30.123456",
                "dt_tz": "2026-11-16T10:45:30+00:00",
                "d": "2026-11-16",
            },
        )
        serialized = json.dumps(plain)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["dt_naive"], dt_naive.isoformat())
        self.assertEqual(deserialized["dt_tz"], dt_tz.isoformat())
        self.assertEqual(deserialized["d"], d.isoformat())

    def test_decimal_preserves_precision_as_string(self) -> None:
        dec_standard = Decimal("123.4500")
        dec_high_precision = Decimal("0.12345678901234567890")
        dec_large = Decimal("-987654321098765432109876543210.12345678901234567890")

        data = {
            "standard": dec_standard,
            "high_precision": dec_high_precision,
            "large": dec_large,
        }
        plain = _to_json_compatible(data)

        self.assertEqual(
            plain,
            {
                "standard": "123.4500",
                "high_precision": "0.12345678901234567890",
                "large": "-987654321098765432109876543210.12345678901234567890",
            },
        )
        serialized = json.dumps(plain)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["standard"], "123.4500")
        self.assertEqual(deserialized["high_precision"], "0.12345678901234567890")
        self.assertEqual(
            deserialized["large"], "-987654321098765432109876543210.12345678901234567890"
        )
        # Verify that float conversion would have lost precision while string preserved it
        self.assertNotEqual(str(float(dec_large)), deserialized["large"])
        self.assertNotEqual(str(float(dec_standard)), deserialized["standard"])

    def test_bytes_and_bytearray_utf8_decoded_with_replace_and_sanitized(self) -> None:
        valid_bytes = b"hello world"
        valid_bytearray = bytearray(b"bytearray buffer")
        invalid_bytes = b"invalid \xff\xfe byte sequence"
        invalid_bytearray = bytearray(b"invalid \x80\x81 bytearray")
        unsafe_bytes = b"safe\x00null\x00byte"
        unsafe_bytearray = bytearray(b"safe\x00null\x08control")

        data = {
            "valid_bytes": valid_bytes,
            "valid_bytearray": valid_bytearray,
            "invalid_bytes": invalid_bytes,
            "invalid_bytearray": invalid_bytearray,
            "unsafe_bytes": unsafe_bytes,
            "unsafe_bytearray": unsafe_bytearray,
        }
        plain = _to_json_compatible(data)

        self.assertEqual(plain["valid_bytes"], "hello world")
        self.assertEqual(plain["valid_bytearray"], "bytearray buffer")
        self.assertEqual(plain["invalid_bytes"], "invalid \ufffd\ufffd byte sequence")
        self.assertEqual(plain["invalid_bytearray"], "invalid \ufffd\ufffd bytearray")
        self.assertEqual(plain["unsafe_bytes"], "safenullbyte")
        self.assertEqual(plain["unsafe_bytearray"], "safenullcontrol")

        serialized = json.dumps(plain)
        self.assertNotIn(r"\u0000", serialized)

    def test_tuple_handling_recursively_converted(self) -> None:
        t = (
            1,
            "text",
            (
                Decimal("10.50"),
                datetime(2026, 1, 1, 12, 0, 0),
                b"nested bytes",
            ),
        )
        plain = _to_json_compatible(t)

        self.assertEqual(
            plain,
            [
                1,
                "text",
                [
                    "10.50",
                    "2026-01-01T12:00:00",
                    "nested bytes",
                ],
            ],
        )
        json.dumps(plain)

    def test_nested_combinations_of_all_five_types_pass_json_dumps(self) -> None:
        payload = {
            "event_time": datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc),
            "event_date": date(2026, 11, 16),
            "amount": Decimal("49.9900"),
            "raw_payload": b'{"status": "ok", \xff}',
            "buffer": bytearray(b"buffered data"),
            "tuple_group": (
                datetime(2026, 11, 15, 8, 30, 0),
                date(2026, 11, 15),
                Decimal("100.00"),
                b"amqp.bytes",
                bytearray(b"bytearray.item"),
            ),
            "deep": DotDict(
                {
                    "inner_list": DotList(
                        [
                            {
                                "nested_tuple": (
                                    Decimal("0.001"),
                                    b"inner \xfe",
                                    datetime(2026, 12, 31, 23, 59, 59),
                                )
                            }
                        ]
                    ),
                    "dot_datetime": DotDateTime(datetime(2026, 5, 1, 12, 0, 0)),
                }
            ),
        }

        result = _to_json_compatible(payload)

        # Confirm the resulting value can successfully pass through json.dumps()
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)
        deserialized = json.loads(serialized)

        self.assertEqual(deserialized["event_time"], "2026-11-16T10:00:00+00:00")
        self.assertEqual(deserialized["event_date"], "2026-11-16")
        self.assertEqual(deserialized["amount"], "49.9900")
        self.assertIn("\ufffd", deserialized["raw_payload"])
        self.assertEqual(deserialized["buffer"], "buffered data")
        self.assertEqual(
            deserialized["tuple_group"],
            [
                "2026-11-15T08:30:00",
                "2026-11-15",
                "100.00",
                "amqp.bytes",
                "bytearray.item",
            ],
        )
        self.assertEqual(
            deserialized["deep"]["inner_list"][0]["nested_tuple"],
            [
                "0.001",
                "inner \ufffd",
                "2026-12-31T23:59:59",
            ],
        )
        self.assertEqual(deserialized["deep"]["dot_datetime"], "2026-05-01T12:00:00")


if __name__ == "__main__":
    unittest.main()
