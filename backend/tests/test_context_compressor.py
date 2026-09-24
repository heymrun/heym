import unittest
from typing import Any
from unittest.mock import MagicMock


def _make_messages(n_middle: int = 3) -> list[dict[str, Any]]:
    """Build [system, user, <n_middle assistant/tool pairs>, user_last]."""
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": "Do the task."},
    ]
    for i in range(n_middle):
        msgs.append({"role": "assistant", "content": f"Calling tool {i}", "tool_calls": []})
        msgs.append({"role": "tool", "content": f"Tool result {i}", "tool_call_id": f"tc_{i}"})
    msgs.append({"role": "user", "content": "Continue from here."})
    return msgs


class TestEstimateTokens(unittest.TestCase):
    def test_empty(self) -> None:
        from app.services.context_compressor import _estimate_tokens

        self.assertEqual(_estimate_tokens([]), 0)

    def test_single_short_message(self) -> None:
        from app.services.context_compressor import _estimate_tokens

        msgs = [{"role": "user", "content": "hi"}]
        tokens = _estimate_tokens(msgs)
        self.assertGreater(tokens, 0)

    def test_longer_messages_yield_more_tokens(self) -> None:
        from app.services.context_compressor import _estimate_tokens

        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "hi " * 500}]
        self.assertGreater(_estimate_tokens(long), _estimate_tokens(short))


class TestGetContextLimit(unittest.TestCase):
    def test_known_model_skips_provider_api(self) -> None:
        from app.services.context_compressor import get_context_limit

        mock_client = MagicMock()
        result = get_context_limit("gpt-3.5-turbo", mock_client)
        self.assertEqual(result, 16_385)
        mock_client.models.retrieve.assert_not_called()

    def test_api_success_returns_api_value_for_unknown_model(self) -> None:
        from app.services.context_compressor import get_context_limit

        mock_model_info = MagicMock()
        mock_model_info.context_window = 200_000
        mock_client = MagicMock()
        mock_client.models.retrieve.return_value = mock_model_info
        result = get_context_limit("custom-provider-model-xyz", mock_client)
        self.assertEqual(result, 200_000)
        mock_client.models.retrieve.assert_called_once_with("custom-provider-model-xyz")

    def test_known_model_prefers_table_over_provider(self) -> None:
        from app.services.context_compressor import get_context_limit

        mock_model_info = MagicMock()
        mock_model_info.context_window = 999_999
        mock_client = MagicMock()
        mock_client.models.retrieve.return_value = mock_model_info
        result = get_context_limit("gpt-4o-2024-11-20", mock_client)
        self.assertEqual(result, 128_000)
        mock_client.models.retrieve.assert_not_called()

    def test_unknown_model_returns_default(self) -> None:
        from app.services.context_compressor import get_context_limit

        mock_client = MagicMock()
        mock_client.models.retrieve.side_effect = Exception("API error")
        result = get_context_limit("some-totally-unknown-model-xyz", mock_client)
        self.assertEqual(result, 128_000)

    def test_api_returns_non_int_falls_back_to_default(self) -> None:
        from app.services.context_compressor import get_context_limit

        mock_model_info = MagicMock()
        mock_model_info.context_window = None
        mock_client = MagicMock()
        mock_client.models.retrieve.return_value = mock_model_info
        result = get_context_limit("custom-provider-model-xyz", mock_client)
        self.assertEqual(result, 128_000)

    def test_gemini_model_matched_by_substring(self) -> None:
        from app.services.context_compressor import get_context_limit

        mock_client = MagicMock()
        result = get_context_limit("gemini-2.0-flash-001", mock_client)
        self.assertEqual(result, 1_048_576)
        mock_client.models.retrieve.assert_not_called()


class TestMaybeCompressMessages(unittest.IsolatedAsyncioTestCase):
    def _make_mock_client(self, summary: str = "Summary of tool results.") -> MagicMock:
        mock_choice = MagicMock()
        mock_choice.message.content = summary
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    async def test_below_threshold_returns_unchanged(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=1)
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=10_000_000
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)
        client.chat.completions.create.assert_not_called()

    async def test_above_threshold_compresses(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client("Key findings: tool 0,1,2 ran successfully.")
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertIsNotNone(info)
        self.assertLess(len(result), len(msgs))

    async def test_system_preserved_after_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        result, _ = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[0]["content"], "You are a helpful agent.")

    async def test_first_user_preserved_after_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        result, _ = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        user_msgs = [m for m in result if m["role"] == "user"]
        self.assertEqual(user_msgs[0]["content"], "Do the task.")

    async def test_last_user_preserved_after_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        result, _ = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        user_msgs = [m for m in result if m["role"] == "user"]
        self.assertEqual(user_msgs[-1]["content"], "Continue from here.")

    async def test_compressed_message_is_assistant_role(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client("Summary here.")
        result, _ = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        # result: [system, user_first, assistant(compressed), …tail]
        self.assertEqual(result[2]["role"], "assistant")
        self.assertIn("[Context compressed", result[2]["content"])

    async def test_info_dict_has_expected_keys(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        _, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertIsNotNone(info)
        assert info is not None
        for key in (
            "messages_compressed",
            "messages_before_count",
            "messages_after_count",
            "tokens_before",
            "tokens_after",
            "elapsed_ms",
        ):
            self.assertIn(key, info)

    async def test_too_few_messages_skips_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Do the task."},
        ]
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)

    async def test_single_user_no_tail_skips_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Only user message."},
            {"role": "assistant", "content": "Assistant reply."},
        ]
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)

    async def test_single_turn_many_iterations_compresses(self) -> None:
        """Single user msg + many tool iterations must compress (common agent case)."""
        from app.services.context_compressor import _SINGLE_TURN_KEEP_TAIL, maybe_compress_messages

        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "Agent."},
            {"role": "user", "content": "Do the task."},
        ]
        for i in range(6):
            msgs.append({"role": "assistant", "content": f"Tool call {i}", "tool_calls": []})
            msgs.append({"role": "tool", "content": f"Result {i}", "tool_call_id": f"tc_{i}"})

        client = self._make_mock_client("Tools 0-3 ran successfully.")
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertIsNotNone(info)
        assert info is not None
        # Anchors preserved
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[1]["role"], "user")
        # Compressed summary at index 2
        self.assertEqual(result[2]["role"], "assistant")
        self.assertIn("[Context compressed", result[2]["content"])
        # Total = system + user + compressed + tail
        self.assertEqual(len(result), 3 + _SINGLE_TURN_KEEP_TAIL)

    async def test_llm_failure_returns_original_messages(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        msgs = _make_messages(n_middle=3)
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=mock_client, context_limit_tokens=1
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)

    async def test_messages_compressed_count_matches_middle(self) -> None:
        from app.services.context_compressor import maybe_compress_messages

        # n_middle=2 → 2 assistant + 2 tool = 4 middle messages
        msgs = _make_messages(n_middle=2)
        client = self._make_mock_client()
        _, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        assert info is not None
        self.assertEqual(info["messages_compressed"], 4)

    async def test_hard_compresses_single_oversized_user_message(self) -> None:
        from app.services.context_compressor import hard_compress_messages

        msgs = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "large input " * 8000},
        ]
        client = self._make_mock_client("Compressed request summary.")

        result, info = await hard_compress_messages(
            msgs,
            model="gpt-4o",
            client=client,
            target_tokens=2_000,
        )

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["mode"], "hard")
        self.assertEqual(info["messages_compressed"], 1)
        self.assertEqual(result[0], msgs[0])
        self.assertEqual(result[1]["role"], "user")
        self.assertIn("Context hard-compressed", result[1]["content"])
        self.assertNotEqual(result[1]["content"], msgs[1]["content"])

    async def test_hard_compression_falls_back_to_excerpt_when_llm_fails(self) -> None:
        from app.services.context_compressor import hard_compress_messages

        msgs = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "oversized " * 5000},
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")

        result, info = await hard_compress_messages(
            msgs,
            model="gpt-4o",
            client=mock_client,
            target_tokens=2_000,
        )

        self.assertIsNotNone(info)
        self.assertEqual(result[1]["role"], "user")
        self.assertIn("Context hard-compressed", result[1]["content"])


class TestFitTextToTokenBudget(unittest.TestCase):
    def test_the_compressor_output_is_unchanged(self) -> None:
        from app.services.context_compressor import _fit_text_to_token_budget

        text = "alpha " * 3000 + "omega"
        # The formula _fit_text_to_token_budget used before it delegated to the helper.
        max_chars = 1000 * 4
        marker = "\n\n[... content omitted during hard context compression ...]\n\n"
        available = max(1, max_chars - len(marker))
        head_chars = max(1, int(available * 0.65))
        tail_chars = max(1, available - head_chars)
        expected = text[:head_chars].rstrip() + marker + text[-tail_chars:].lstrip()

        self.assertEqual(_fit_text_to_token_budget(text, 1000), expected)


if __name__ == "__main__":
    unittest.main()
