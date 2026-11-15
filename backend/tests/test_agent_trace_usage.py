"""Regression tests for agent execution trace token accounting (issue #946).

Verifies the central invariant:
Every trace row records only the tokens spent during the current `execute_with_tools()`
invocation, while returned results and persisted `agent_state` continue carrying
cumulative totals.
"""

from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.db.models import CredentialType
from app.services.llm_service import HumanReviewPause, LLMService
from app.services.llm_trace import LLMTraceContext

TOOLS = [
    {"name": "search", "parameters": {"type": "object"}},
    {"name": "review", "parameters": {"type": "object"}, "_source": "hitl"},
]


def _call(call_id: str, arguments: str = "{}", name: str = "search") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _completion(
    *,
    content: str | None = None,
    calls: list[SimpleNamespace] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 1,
    completion_tokens: int = 1,
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=calls or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


class TestAgentTraceUsage(IsolatedAsyncioTestCase):
    """Token accounting test suite covering tool loop exits, pauses, and resumes."""

    def _make_service(self) -> tuple[LLMService, list[dict[str, Any]]]:
        trace_context = LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())
        service = LLMService(CredentialType.openai, "test-key", trace_context=trace_context)
        traces: list[dict[str, Any]] = []
        return service, traces

    def _mock_client(self, responses: list[Any]) -> tuple[SimpleNamespace, list[dict[str, Any]]]:
        sent: list[dict[str, Any]] = []

        def create(**request: Any) -> SimpleNamespace:
            sent.append(copy.deepcopy(request))
            if not responses:
                raise RuntimeError("No more mocked responses available")
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        return client, sent

    def _default_tool_executor(
        self,
        tool_def: dict[str, Any],
        name: str,
        args: dict[str, Any],
        _timeout: int,
    ) -> Any:
        if name == "review" or tool_def.get("_source") == "hitl":
            return HumanReviewPause(
                reason="Confirmation required",
                review_markdown="Please review and approve",
                tool_name=name,
                tool_arguments=args,
            )
        return {"result": f"processed {name}"}

    # =========================================================================
    # A. Tool iteration-limit exits
    # =========================================================================

    async def test_iteration_limit_trace_when_grace_turn_fails(self) -> None:
        """When grace turn fails after SDK retries, terminal trace is written with loop tokens."""
        service, _ = self._make_service()
        responses = [
            _completion(
                calls=[_call("c1", '{"q": "step 1"}')],
                finish_reason="tool_calls",
                prompt_tokens=40,
                completion_tokens=10,
            ),
            RuntimeError("Grace turn failed with 429"),
            RuntimeError("Grace turn fallback failed"),
        ]
        client, _ = self._mock_client(responses)

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run task",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                max_tool_iterations=1,
            )

        self.assertEqual(result["text"], "Tool iteration limit reached.")
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        )

        terminal_traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(terminal_traces), 1)
        trace = terminal_traces[0]
        self.assertIsNone(trace.get("error"))
        self.assertEqual(trace["prompt_tokens"], 40)
        self.assertEqual(trace["completion_tokens"], 10)
        self.assertEqual(trace["total_tokens"], 50)
        self.assertEqual(trace["response"]["text"], "Tool iteration limit reached.")

    async def test_iteration_limit_trace_when_grace_turn_returns_tool_call(self) -> None:
        """When grace turn returns another tool call, loop exits with trace containing grace tokens."""
        service, _ = self._make_service()
        responses = [
            _completion(
                calls=[_call("c1", '{"q": "step 1"}')],
                finish_reason="tool_calls",
                prompt_tokens=40,
                completion_tokens=10,
            ),
            _completion(
                calls=[_call("c2", '{"q": "extra call"}')],
                finish_reason="tool_calls",
                prompt_tokens=25,
                completion_tokens=5,
            ),
        ]
        client, _ = self._mock_client(responses)

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run task",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                max_tool_iterations=1,
            )

        self.assertEqual(result["text"], "Tool iteration limit reached.")
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 65, "completion_tokens": 15, "total_tokens": 80},
        )

        terminal_traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(terminal_traces), 1)
        trace = terminal_traces[0]
        self.assertIsNone(trace.get("error"))
        self.assertEqual(trace["prompt_tokens"], 65)
        self.assertEqual(trace["completion_tokens"], 15)
        self.assertEqual(trace["total_tokens"], 80)
        self.assertEqual(trace["response"]["text"], "Tool iteration limit reached.")

    async def test_iteration_limit_trace_when_grace_turn_returns_empty_text(self) -> None:
        """When grace turn returns whitespace text, loop exits with trace containing grace tokens."""
        service, _ = self._make_service()
        responses = [
            _completion(
                calls=[_call("c1", '{"q": "step 1"}')],
                finish_reason="tool_calls",
                prompt_tokens=40,
                completion_tokens=10,
            ),
            _completion(
                content="   ",
                calls=[],
                finish_reason="stop",
                prompt_tokens=25,
                completion_tokens=5,
            ),
        ]
        client, _ = self._mock_client(responses)

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run task",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                max_tool_iterations=1,
            )

        self.assertEqual(result["text"], "Tool iteration limit reached.")
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 65, "completion_tokens": 15, "total_tokens": 80},
        )

        terminal_traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(terminal_traces), 1)
        trace = terminal_traces[0]
        self.assertIsNone(trace.get("error"))
        self.assertEqual(trace["prompt_tokens"], 65)
        self.assertEqual(trace["completion_tokens"], 15)
        self.assertEqual(trace["total_tokens"], 80)
        self.assertEqual(trace["response"]["text"], "Tool iteration limit reached.")

    async def test_iteration_limit_trace_when_grace_turn_returns_valid_answer(self) -> None:
        """When grace turn returns valid text, grace-turn answer path records trace with all tokens."""
        service, _ = self._make_service()
        responses = [
            _completion(
                calls=[_call("c1", '{"q": "step 1"}')],
                finish_reason="tool_calls",
                prompt_tokens=40,
                completion_tokens=10,
            ),
            _completion(
                content="Final answer from grace turn.",
                calls=[],
                finish_reason="stop",
                prompt_tokens=25,
                completion_tokens=5,
            ),
        ]
        client, _ = self._mock_client(responses)

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run task",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                max_tool_iterations=1,
            )

        self.assertEqual(result["text"], "Final answer from grace turn.")
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 65, "completion_tokens": 15, "total_tokens": 80},
        )

        terminal_traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(terminal_traces), 1)
        trace = terminal_traces[0]
        self.assertIsNone(trace.get("error"))
        self.assertEqual(trace["prompt_tokens"], 65)
        self.assertEqual(trace["completion_tokens"], 15)
        self.assertEqual(trace["total_tokens"], 80)
        self.assertEqual(trace["response"]["text"], "Final answer from grace turn.")

    async def test_iteration_limit_trace_after_resume_records_only_delta(self) -> None:
        """When a resumed invocation hits the iteration limit, trace records only the delta."""
        service, _ = self._make_service()
        responses = [
            _completion(
                calls=[_call("c2", '{"q": "step 2"}')],
                finish_reason="tool_calls",
                prompt_tokens=50,
                completion_tokens=15,
            ),
            RuntimeError("Grace turn failed"),
            RuntimeError("Grace fallback failed"),
        ]
        client, _ = self._mock_client(responses)

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="resume task",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                initial_messages=[{"role": "user", "content": "initial task"}],
                initial_tool_calls=[],
                initial_prompt_tokens=5000,
                initial_completion_tokens=200,
                initial_elapsed_ms=1200.0,
                max_tool_iterations=1,
            )

        self.assertEqual(result["text"], "Tool iteration limit reached.")
        # Result cumulative usage: 5000 + 50 = 5050 prompt, 200 + 15 = 215 completion
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 5050, "completion_tokens": 215, "total_tokens": 5265},
        )

        terminal_traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(terminal_traces), 1)
        trace = terminal_traces[0]
        self.assertEqual(trace["prompt_tokens"], 50)
        self.assertEqual(trace["completion_tokens"], 15)
        self.assertEqual(trace["total_tokens"], 65)

    # =========================================================================
    # B. One human-review pause followed by an answer
    # =========================================================================

    async def test_single_hitl_pause_and_resume_trace_accounting(self) -> None:
        """Initial pause and resumed answer record exact per-invocation tokens."""
        service, _ = self._make_service()

        # Invocation 1: consumes 5,200 tokens (5,000 prompt, 200 completion) and pauses.
        inv1_responses = [
            _completion(
                calls=[_call("call-hitl-1", '{"action": "deploy"}', name="review")],
                finish_reason="tool_calls",
                prompt_tokens=5000,
                completion_tokens=200,
            )
        ]
        client1, _ = self._mock_client(inv1_responses)

        with (
            patch.object(service, "_get_client", return_value=(client1, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_inv1,
        ):
            result1 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="deploy app",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                max_tool_iterations=5,
            )

        self.assertIn("_hitl_pending", result1)
        self.assertEqual(
            result1["usage"],
            {"prompt_tokens": 5000, "completion_tokens": 200, "total_tokens": 5200},
        )

        inv1_traces = [c.kwargs for c in record_trace_inv1.call_args_list]
        self.assertEqual(len(inv1_traces), 1)
        self.assertEqual(inv1_traces[0]["prompt_tokens"], 5000)
        self.assertEqual(inv1_traces[0]["completion_tokens"], 200)
        self.assertEqual(inv1_traces[0]["total_tokens"], 5200)

        # Extract agent_state to simulate resume
        agent_state = result1["_hitl_pending"]["agent_state"]
        self.assertEqual(agent_state["prompt_tokens"], 5000)
        self.assertEqual(agent_state["completion_tokens"], 200)

        resume_messages = copy.deepcopy(agent_state["messages"])
        resume_messages.append({"role": "user", "content": "Approved: proceed"})

        # Invocation 2: consumes 150 tokens (100 prompt, 50 completion) and answers.
        inv2_responses = [
            _completion(
                content="Deployment complete.",
                calls=[],
                finish_reason="stop",
                prompt_tokens=100,
                completion_tokens=50,
            )
        ]
        client2, _ = self._mock_client(inv2_responses)

        with (
            patch.object(service, "_get_client", return_value=(client2, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_inv2,
        ):
            result2 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="deploy app",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                initial_messages=resume_messages,
                initial_tool_calls=copy.deepcopy(agent_state["tool_calls"]),
                initial_elapsed_ms=agent_state["elapsed_ms"],
                initial_prompt_tokens=agent_state["prompt_tokens"],
                initial_completion_tokens=agent_state["completion_tokens"],
                max_tool_iterations=agent_state["remaining_tool_iterations"],
            )

        self.assertEqual(result2["text"], "Deployment complete.")
        # Result cumulative usage: 5000 + 100 = 5100 prompt, 200 + 50 = 250 completion
        self.assertEqual(
            result2["usage"],
            {"prompt_tokens": 5100, "completion_tokens": 250, "total_tokens": 5350},
        )

        inv2_traces = [c.kwargs for c in record_trace_inv2.call_args_list]
        self.assertEqual(len(inv2_traces), 1)
        self.assertEqual(inv2_traces[0]["prompt_tokens"], 100)
        self.assertEqual(inv2_traces[0]["completion_tokens"], 50)
        self.assertEqual(inv2_traces[0]["total_tokens"], 150)

        # Sum of trace rows equals total provider usage (5200 + 150 = 5350)
        total_trace_tokens = inv1_traces[0]["total_tokens"] + inv2_traces[0]["total_tokens"]
        self.assertEqual(total_trace_tokens, 5350)

    # =========================================================================
    # C. Two human-review pauses followed by an answer
    # =========================================================================

    async def test_two_hitl_pauses_and_resume_trace_accounting(self) -> None:
        """Two pause/resume cycles: every trace row records only its invocation's tokens."""
        service, _ = self._make_service()

        # Invocation 1: consumes 1,000 prompt + 100 completion = 1,100 tokens, pauses.
        client1, _ = self._mock_client(
            [
                _completion(
                    calls=[_call("p1", '{"step": 1}', name="review")],
                    finish_reason="tool_calls",
                    prompt_tokens=1000,
                    completion_tokens=100,
                )
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client1, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_1,
        ):
            res1 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="start multi-step",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                max_tool_iterations=5,
            )

        traces1 = [c.kwargs for c in record_trace_1.call_args_list]
        self.assertEqual(len(traces1), 1)
        self.assertEqual(traces1[0]["prompt_tokens"], 1000)
        self.assertEqual(traces1[0]["completion_tokens"], 100)
        self.assertEqual(traces1[0]["total_tokens"], 1100)

        state1 = res1["_hitl_pending"]["agent_state"]
        msgs1 = copy.deepcopy(state1["messages"]) + [{"role": "user", "content": "Approved step 1"}]

        # Invocation 2: consumes 500 prompt + 50 completion = 550 tokens, pauses again.
        client2, _ = self._mock_client(
            [
                _completion(
                    calls=[_call("p2", '{"step": 2}', name="review")],
                    finish_reason="tool_calls",
                    prompt_tokens=500,
                    completion_tokens=50,
                )
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client2, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_2,
        ):
            res2 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="start multi-step",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                initial_messages=msgs1,
                initial_tool_calls=copy.deepcopy(state1["tool_calls"]),
                initial_elapsed_ms=state1["elapsed_ms"],
                initial_prompt_tokens=state1["prompt_tokens"],
                initial_completion_tokens=state1["completion_tokens"],
                max_tool_iterations=state1["remaining_tool_iterations"],
            )

        traces2 = [c.kwargs for c in record_trace_2.call_args_list]
        self.assertEqual(len(traces2), 1)
        self.assertEqual(traces2[0]["prompt_tokens"], 500)
        self.assertEqual(traces2[0]["completion_tokens"], 50)
        self.assertEqual(traces2[0]["total_tokens"], 550)

        state2 = res2["_hitl_pending"]["agent_state"]
        self.assertEqual(state2["prompt_tokens"], 1500)
        self.assertEqual(state2["completion_tokens"], 150)
        msgs2 = copy.deepcopy(state2["messages"]) + [{"role": "user", "content": "Approved step 2"}]

        # Invocation 3: consumes 200 prompt + 20 completion = 220 tokens, final answer.
        client3, _ = self._mock_client(
            [
                _completion(
                    content="All steps complete.",
                    calls=[],
                    finish_reason="stop",
                    prompt_tokens=200,
                    completion_tokens=20,
                )
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client3, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_3,
        ):
            res3 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="start multi-step",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                initial_messages=msgs2,
                initial_tool_calls=copy.deepcopy(state2["tool_calls"]),
                initial_elapsed_ms=state2["elapsed_ms"],
                initial_prompt_tokens=state2["prompt_tokens"],
                initial_completion_tokens=state2["completion_tokens"],
                max_tool_iterations=state2["remaining_tool_iterations"],
            )

        traces3 = [c.kwargs for c in record_trace_3.call_args_list]
        self.assertEqual(len(traces3), 1)
        self.assertEqual(traces3[0]["prompt_tokens"], 200)
        self.assertEqual(traces3[0]["completion_tokens"], 20)
        self.assertEqual(traces3[0]["total_tokens"], 220)

        # Returned usage in final result must be cumulative across all 3 invocations:
        # Prompt: 1000 + 500 + 200 = 1700
        # Completion: 100 + 50 + 20 = 170
        # Total: 1700 + 170 = 1870
        self.assertEqual(
            res3["usage"],
            {"prompt_tokens": 1700, "completion_tokens": 170, "total_tokens": 1870},
        )

        # Summing all trace rows equals provider-billed usage:
        summed_prompt = (
            traces1[0]["prompt_tokens"] + traces2[0]["prompt_tokens"] + traces3[0]["prompt_tokens"]
        )
        summed_completion = (
            traces1[0]["completion_tokens"]
            + traces2[0]["completion_tokens"]
            + traces3[0]["completion_tokens"]
        )
        summed_total = (
            traces1[0]["total_tokens"] + traces2[0]["total_tokens"] + traces3[0]["total_tokens"]
        )
        self.assertEqual(summed_prompt, 1700)
        self.assertEqual(summed_completion, 170)
        self.assertEqual(summed_total, 1870)

    # =========================================================================
    # D. Resume whose first provider request fails
    # =========================================================================

    async def test_resumed_first_request_failure_records_no_usage(self) -> None:
        """When resumed invocation's first request raises, error trace has null token fields."""
        service, _ = self._make_service()

        # Invocation 1: spends tokens and pauses
        client1, _ = self._mock_client(
            [
                _completion(
                    calls=[_call("p1", '{"step": 1}', name="review")],
                    finish_reason="tool_calls",
                    prompt_tokens=5000,
                    completion_tokens=200,
                )
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client1, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_1,
        ):
            res1 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="pause and fail",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
            )

        traces1 = [c.kwargs for c in record_trace_1.call_args_list]
        self.assertEqual(len(traces1), 1)
        self.assertEqual(traces1[0]["total_tokens"], 5200)

        state = res1["_hitl_pending"]["agent_state"]
        msgs = copy.deepcopy(state["messages"]) + [{"role": "user", "content": "Approved"}]

        # Invocation 2: first request fails immediately
        client2, _ = self._mock_client([RuntimeError("429 rate limited on resume")])
        with (
            patch.object(service, "_get_client", return_value=(client2, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_2,
            self.assertRaisesRegex(RuntimeError, "429 rate limited on resume"),
        ):
            await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="pause and fail",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                initial_messages=msgs,
                initial_tool_calls=copy.deepcopy(state["tool_calls"]),
                initial_prompt_tokens=state["prompt_tokens"],
                initial_completion_tokens=state["completion_tokens"],
                initial_elapsed_ms=state["elapsed_ms"],
                max_tool_iterations=state["remaining_tool_iterations"],
            )

        traces2 = [c.kwargs for c in record_trace_2.call_args_list]
        self.assertEqual(len(traces2), 1)
        err_trace = traces2[0]
        self.assertIn("429 rate limited on resume", err_trace.get("error") or "")
        # Must NOT repeat initial invocation's 5200 tokens
        self.assertIsNone(err_trace["prompt_tokens"])
        self.assertIsNone(err_trace["completion_tokens"])
        self.assertIsNone(err_trace["total_tokens"])

    # =========================================================================
    # E. Later-turn failure after resume
    # =========================================================================

    async def test_resumed_later_turn_failure_records_only_invocation_delta(self) -> None:
        """When a later turn fails in a resumed run, error trace records only the resumed tokens."""
        service, _ = self._make_service()

        # Invocation 1: spends 1,000 prompt + 100 completion = 1,100, pauses.
        client1, _ = self._mock_client(
            [
                _completion(
                    calls=[_call("p1", '{"step": 1}', name="review")],
                    finish_reason="tool_calls",
                    prompt_tokens=1000,
                    completion_tokens=100,
                )
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client1, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_1,
        ):
            res1 = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="pause then partial",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
            )

        traces1 = [c.kwargs for c in record_trace_1.call_args_list]
        self.assertEqual(len(traces1), 1)
        self.assertEqual(traces1[0]["prompt_tokens"], 1000)
        self.assertEqual(traces1[0]["completion_tokens"], 100)
        self.assertEqual(traces1[0]["total_tokens"], 1100)

        state = res1["_hitl_pending"]["agent_state"]
        msgs = copy.deepcopy(state["messages"]) + [{"role": "user", "content": "Approved"}]

        # Invocation 2: turn 1 succeeds (300 prompt, 30 completion), turn 2 fails (500 error).
        client2, _ = self._mock_client(
            [
                _completion(
                    calls=[_call("s1", '{"q": "query"}', name="search")],
                    finish_reason="tool_calls",
                    prompt_tokens=300,
                    completion_tokens=30,
                ),
                RuntimeError("500 internal server error on turn 2"),
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client2, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace_2,
            self.assertRaisesRegex(RuntimeError, "500 internal server error on turn 2"),
        ):
            await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="pause then partial",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                initial_messages=msgs,
                initial_tool_calls=copy.deepcopy(state["tool_calls"]),
                initial_prompt_tokens=state["prompt_tokens"],
                initial_completion_tokens=state["completion_tokens"],
                initial_elapsed_ms=state["elapsed_ms"],
                max_tool_iterations=state["remaining_tool_iterations"],
            )

        traces2 = [c.kwargs for c in record_trace_2.call_args_list]
        self.assertEqual(len(traces2), 1)
        err_trace = traces2[0]
        self.assertIn("500 internal server error on turn 2", err_trace.get("error") or "")
        # Must record ONLY the tokens spent in invocation 2 (300 prompt, 30 completion = 330)
        self.assertEqual(err_trace["prompt_tokens"], 300)
        self.assertEqual(err_trace["completion_tokens"], 30)
        self.assertEqual(err_trace["total_tokens"], 330)

    # =========================================================================
    # Additional parity checks
    # =========================================================================

    async def test_fresh_first_turn_failure_records_no_usage(self) -> None:
        """First-turn failure on fresh run retains null token fields (PR #936 invariant)."""
        service, _ = self._make_service()
        client, _ = self._mock_client([RuntimeError("Provider offline")])
        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
            self.assertRaisesRegex(RuntimeError, "Provider offline"),
        ):
            await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="hello",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
            )

        traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(traces), 1)
        self.assertIsNone(traces[0]["prompt_tokens"])
        self.assertIsNone(traces[0]["completion_tokens"])
        self.assertIsNone(traces[0]["total_tokens"])

    async def test_resumed_abort_records_only_invocation_delta(self) -> None:
        """When an abort occurs on a resumed invocation, error result trace has only the delta."""
        service, _ = self._make_service()

        abort_called = False

        def should_abort() -> str | None:
            nonlocal abort_called
            if abort_called:
                return "Execution cancelled by operator"
            return None

        # Resumed invocation: turn 1 runs and spends tokens, but next iteration should_abort triggers
        client, _ = self._mock_client(
            [
                _completion(
                    calls=[_call("s1", '{"q": "query"}', name="search")],
                    finish_reason="tool_calls",
                    prompt_tokens=80,
                    completion_tokens=20,
                )
            ]
        )

        def tool_executor_with_abort(
            tool_def: dict[str, Any],
            name: str,
            args: dict[str, Any],
            timeout: int,
        ) -> Any:
            nonlocal abort_called
            abort_called = True
            return {"result": "ok"}

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="abort test",
                tools=TOOLS,
                tool_executor=tool_executor_with_abort,
                should_abort=should_abort,
                initial_messages=[{"role": "user", "content": "prev"}],
                initial_tool_calls=[],
                initial_prompt_tokens=2000,
                initial_completion_tokens=100,
                max_tool_iterations=5,
            )

        self.assertEqual(result["error"], "Execution cancelled by operator")
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 2080, "completion_tokens": 120, "total_tokens": 2200},
        )

        traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["prompt_tokens"], 80)
        self.assertEqual(traces[0]["completion_tokens"], 20)
        self.assertEqual(traces[0]["total_tokens"], 100)

    async def test_structured_content_return_after_resume_records_only_delta(self) -> None:
        """Structured content return path records only the resumed invocation's token usage."""
        service, _ = self._make_service()
        client, _ = self._mock_client(
            [
                _completion(
                    content='{"status": "complete"}',
                    calls=[_call("c1", '{"q": "query"}', name="search")],
                    finish_reason="stop",
                    prompt_tokens=150,
                    completion_tokens=50,
                )
            ]
        )
        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace") as record_trace,
        ):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="structured resume",
                tools=TOOLS,
                tool_executor=self._default_tool_executor,
                response_format={"type": "json_object"},
                initial_messages=[{"role": "user", "content": "prev"}],
                initial_tool_calls=[{"name": "search", "arguments": {}, "result": "ok"}],
                initial_prompt_tokens=1000,
                initial_completion_tokens=100,
                max_tool_iterations=5,
            )

        self.assertEqual(result["text"], '{"status": "complete"}')
        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 1150, "completion_tokens": 150, "total_tokens": 1300},
        )

        traces = [c.kwargs for c in record_trace.call_args_list]
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["prompt_tokens"], 150)
        self.assertEqual(traces[0]["completion_tokens"], 50)
        self.assertEqual(traces[0]["total_tokens"], 200)
