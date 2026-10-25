"""NOTIFY payloads for canvas collaboration: chunking, parsing and reassembly."""

import unittest

from app.services.collab.wire import (
    MAX_CHUNK_BYTES,
    ChunkAssembler,
    MessageTooLargeError,
    WirePayload,
    encode_payloads,
    parse_payload,
    split_chunks,
)

ROOM = "0b6f3d1e-2a4c-4f53-9a51-1d6c1b0f7e10"


def _parsed(payload: str) -> WirePayload:
    parsed = parse_payload(payload)
    if parsed is None:
        raise AssertionError(f"unparsable payload: {payload[:60]}")
    return parsed


class SplitChunksTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self) -> None:
        self.assertEqual(["hello"], split_chunks("hello"))

    def test_chunks_stay_under_the_byte_limit_without_splitting_characters(self) -> None:
        text = "é" * 5000 + "😀" * 3000 + "a" * 10

        chunks = split_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.encode("utf-8")) <= MAX_CHUNK_BYTES for c in chunks))
        self.assertEqual(text, "".join(chunks))


class EncodeAndAssembleTests(unittest.TestCase):
    def test_payloads_fit_a_notify_and_reassemble(self) -> None:
        text = '{"t":"snapshot","blob":"' + "é" * 20000 + '"}'
        payloads = encode_payloads(ROOM, text)
        assembler = ChunkAssembler()

        results = [assembler.feed(_parsed(p), now=0.0) for p in payloads]

        self.assertTrue(all(len(p.encode("utf-8")) < 8000 for p in payloads))
        self.assertEqual([None] * (len(payloads) - 1) + [text], results)
        self.assertEqual(0, assembler.pending_count())

    def test_oversized_message_is_refused(self) -> None:
        with self.assertRaises(MessageTooLargeError):
            encode_payloads(ROOM, "x" * (2 * 1024 * 1024 + 1))

    def test_a_message_whose_chunks_stop_arriving_expires(self) -> None:
        first, _second = encode_payloads(ROOM, "y" * 9000)
        assembler = ChunkAssembler(ttl_seconds=5.0)

        self.assertIsNone(assembler.feed(_parsed(first), now=0.0))
        self.assertEqual(1, assembler.pending_count())
        (single,) = encode_payloads(ROOM, "next")
        self.assertEqual("next", assembler.feed(_parsed(single), now=6.0))
        self.assertEqual(0, assembler.pending_count())

    def test_a_chunk_out_of_order_drops_the_message(self) -> None:
        payloads = encode_payloads(ROOM, "z" * 15000)
        assembler = ChunkAssembler()

        self.assertIsNone(assembler.feed(_parsed(payloads[0]), now=0.0))
        self.assertIsNone(assembler.feed(_parsed(payloads[2]), now=0.0))
        self.assertEqual(0, assembler.pending_count())

    def test_parse_rejects_malformed_payloads(self) -> None:
        for bad in ("", "no-separators", "room|id|x/1|c", "room|id|2/2|c", "room|id|0/0|c"):
            self.assertIsNone(parse_payload(bad), bad)

    def test_chunk_text_may_contain_the_separator(self) -> None:
        (payload,) = encode_payloads(ROOM, "a|b|c")
        self.assertEqual("a|b|c", _parsed(payload).chunk)
