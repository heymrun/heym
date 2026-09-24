"""Persisted tool payloads keep both ends of a long string, and redact both.

Traces kept only the first 4096 characters of a long tool result, so neither a reader
nor the model router saw how it ended. Keeping the end means scanning it for secrets
too, including a secret that starts before the kept tail and runs into it.
"""

import unittest
from unittest import mock

from app.services import agent_tool_observability
from app.services.agent_tool_observability import (
    DEFAULT_MAX_PAYLOAD_CHARS,
    sanitize_persisted_tool_entry,
    sanitize_tool_payload,
    sanitize_trace_tool_payloads,
)

# About 6,600 characters, the size of an 8192-bit key: longer than the kept tail and
# than a tail-sized scan, so only the look-behind reaches the start of the key.
PEM_BODY = "QUJDREVGR0g" * 600
PEM = f"-----BEGIN RSA PRIVATE KEY-----\n{PEM_BODY}\n-----END RSA PRIVATE KEY-----"
# One size is scanned whole, the other only near its two ends.
SIZES = (6_000, 60_000)


def _record(text: str) -> str:
    entry = sanitize_persisted_tool_entry(
        {"name": "fetch", "arguments": {}, "result": {"text": text}}
    )
    return entry["result"]["text"]


class TestLongResultsKeepTheirEnd(unittest.TestCase):
    def test_the_real_ending_is_persisted(self) -> None:
        for size in SIZES:
            with self.subTest(size=size):
                record = _record("The answer starts here. " + "x" * size + " The real last line.")

                self.assertTrue(record.startswith("The answer starts here."))
                self.assertTrue(record.endswith("The real last line."))
                self.assertIn("characters truncated", record)
                self.assertLessEqual(len(record), DEFAULT_MAX_PAYLOAD_CHARS)

    def test_a_trace_with_many_tool_calls_keeps_the_true_count(self) -> None:
        # The trace write shares its budget across records and cuts each stored record
        # again; the second cut must still count from the original text.
        text = "START " + "d" * 7_640 + " REAL END"
        entries = [
            sanitize_persisted_tool_entry(
                {"tool_call_id": f"c{i}", "name": "call_sub_agent", "result": {"text": text}}
            )
            for i in range(10)
        ]
        _, response = sanitize_trace_tool_payloads(
            {}, {"tool_calls": entries}, max_chars=DEFAULT_MAX_PAYLOAD_CHARS, max_depth=6
        )
        record = response["tool_calls"][0]["result"]["text"]
        head, _, rest = record.partition(" …[")
        count, _, tail = rest.partition(" characters truncated]… ")

        self.assertLess(len(record), len(entries[0]["result"]["text"]))
        self.assertEqual(len(head) + int(count) + len(tail), len(text))
        self.assertTrue(record.endswith("REAL END"))


class TestBothEndsAreRedacted(unittest.TestCase):
    def test_a_secret_in_the_kept_tail_is_redacted(self) -> None:
        for size in SIZES:
            with self.subTest(size=size):
                record = _record("x" * size + " sent with Bearer tail-secret-token")

                self.assertNotIn("tail-secret-token", record)
                self.assertTrue(record.endswith("Bearer [REDACTED]"))

    def test_a_key_that_starts_before_the_kept_tail_is_redacted(self) -> None:
        for size in SIZES:
            with self.subTest(size=size):
                record = _record("x" * size + PEM + " closing words")

                self.assertNotIn("QUJDREVGR0g", record)
                self.assertTrue(record.endswith("[REDACTED] closing words"))

    def test_a_secret_in_the_dropped_middle_never_appears(self) -> None:
        for size in SIZES:
            with self.subTest(size=size):
                record = _record("x" * size + " api_key=middle-secret " + "y" * size)

                self.assertNotIn("middle-secret", record)

    def test_text_that_was_never_scanned_never_reaches_the_record(self) -> None:
        # The key outgrows the head's scan, so redaction shortens the head; the cut must
        # not make up the difference from the unscanned text after it.
        record = _record(PEM + " UNSCANNED-TEXT " + "x" * 60_000)

        self.assertNotIn("UNSCANNED-TEXT", record)
        self.assertNotIn("QUJDREVGR0g", record)
        self.assertTrue(record.startswith("[REDACTED]"))

    def test_a_huge_string_is_scanned_only_near_its_ends(self) -> None:
        scanned: list[int] = []
        redact = agent_tool_observability._redact_sensitive_text

        def spy(value: str) -> str:
            scanned.append(len(value))
            return redact(value)

        with mock.patch.object(agent_tool_observability, "_redact_sensitive_text", side_effect=spy):
            sanitize_tool_payload({"text": "x" * 5_000_000})

        bound = (
            2 * DEFAULT_MAX_PAYLOAD_CHARS
            + agent_tool_observability._MAX_REDACTION_LOOKAHEAD_CHARS
            + agent_tool_observability._MAX_REDACTION_LOOKBEHIND_CHARS
        )
        self.assertLessEqual(sum(scanned), bound)


if __name__ == "__main__":
    unittest.main()
