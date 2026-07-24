from __future__ import annotations

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.db.models import CredentialType
from app.models.chat_schemas import ToolCallRecord
from app.services.agent_tool_observability import (
    classify_tool_failure_status,
    normalize_tool_call_status,
    sanitize_persisted_tool_entry,
    sanitize_tool_payload,
    sanitize_trace_tool_payloads,
    summarize_tool_calls,
    text_indicates_cancellation,
)
from app.services.llm_service import HumanReviewPause, LLMService, _tool_result_status
from app.services.llm_trace import LLMTraceContext, record_llm_trace


class ToolCallStatusCompatibilityTests(unittest.TestCase):
    def test_cancelled_tool_call_is_accepted_by_persisted_chat_schema(self) -> None:
        record = ToolCallRecord(
            id="tool-1",
            name="example",
            label="Example",
            status="cancelled",
        )

        self.assertEqual(record.status, "cancelled")

    def test_pending_and_timeout_tool_calls_are_accepted(self) -> None:
        for status in ("pending", "timeout"):
            with self.subTest(status=status):
                record = ToolCallRecord(
                    id=f"tool-{status}",
                    name="example",
                    label="Example",
                    status=status,
                )
                self.assertEqual(record.status, status)


class ToolPayloadSanitizationTests(unittest.TestCase):
    def test_redacts_secrets_and_bounds_nested_payloads(self) -> None:
        payload = {
            "api_key": "secret-value",
            "nested": {"password": "secret-password", "value": "a" * 100},
        }

        sanitized = sanitize_tool_payload(payload, max_chars=40, max_depth=2)

        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["password"], "[REDACTED]")
        self.assertTrue(str(sanitized["nested"]["value"]).endswith("...(truncated)"))

    def test_preserves_scalar_types_for_safe_payloads(self) -> None:
        payload = {"count": 3, "enabled": True, "items": ["one", "two"]}

        sanitized = sanitize_tool_payload(payload)

        self.assertEqual(sanitized, payload)

    def test_redacts_secret_formats_inside_generic_strings(self) -> None:
        payload = {
            "message": "Authorization: Bearer super-secret",
            "text": "eyJhbGciOiJIUzI1NiJ9.payload.signature",
            "raw": "client_secret=very-secret",
        }

        sanitized = sanitize_tool_payload(payload)

        self.assertNotIn("super-secret", str(sanitized))
        self.assertNotIn("payload.signature", str(sanitized))
        self.assertNotIn("very-secret", str(sanitized))

    def test_applies_total_payload_budget_and_width_limits(self) -> None:
        payload = {f"field_{index}": "x" * 100 for index in range(250)}

        sanitized = sanitize_tool_payload(
            payload,
            max_chars=100,
            max_depth=6,
            max_total_chars=512,
        )

        self.assertIn("_truncated", sanitized)
        self.assertLessEqual(len(json.dumps(sanitized, ensure_ascii=False)), 512 + 100)

    def test_bounds_large_json_strings_without_parsing_or_leaking_secrets(self) -> None:
        raw = '{"api_key":"secret-value","payload":"' + ("x" * 100_000) + '"}'

        with patch("app.services.agent_tool_observability.json.loads") as loads:
            sanitized = sanitize_tool_payload(
                {"arguments": raw},
                max_chars=256,
                max_depth=6,
                max_total_chars=512,
            )

        loads.assert_not_called()
        serialized = json.dumps(sanitized)
        self.assertNotIn("secret-value", serialized)
        self.assertLessEqual(len(sanitized["arguments"]), 256)

    def test_sanitizes_tool_messages_inside_llm_trace_request(self) -> None:
        request = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{"function": {"arguments": '{"token":"secret"}'}}],
                },
                {"role": "tool", "content": {"password": "secret"}},
            ]
        }

        safe_request, _ = sanitize_trace_tool_payloads(
            request,
            {},
            max_chars=4096,
            max_depth=6,
        )

        self.assertEqual(
            safe_request["messages"][1]["content"]["password"],
            "[REDACTED]",
        )
        safe_arguments = json.loads(
            safe_request["messages"][0]["tool_calls"][0]["function"]["arguments"]
        )
        self.assertEqual(safe_arguments["token"], "[REDACTED]")

    def test_shares_total_budget_across_all_trace_tool_sections(self) -> None:
        request = {
            "tool_calls": [{"result": "x" * 100}],
            "messages": [
                {"role": "assistant", "tool_calls": [{"result": "y" * 100}]},
                {"role": "tool", "content": "z" * 100},
            ],
        }

        safe_request, _ = sanitize_trace_tool_payloads(
            request,
            {},
            max_chars=100,
            max_depth=6,
            max_total_chars=80,
        )

        self.assertIn("PAYLOAD_TRUNCATED", json.dumps(safe_request))

    def test_sanitizes_hitl_tool_payloads_inside_trace_response(self) -> None:
        response = {
            "_hitl_pending": {
                "tool_arguments": {"api_key": "secret-key", "safe": "value"},
                "agent_state": {
                    "messages": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {"function": {"arguments": '{"password":"secret-password"}'}}
                            ],
                        },
                        {
                            "role": "tool",
                            "content": {"access_token": "secret-token"},
                        },
                    ],
                    "tool_calls": [
                        {
                            "name": "child",
                            "arguments": {"client_secret": "secret-client"},
                        }
                    ],
                },
            }
        }

        _, safe_response = sanitize_trace_tool_payloads(
            {},
            response,
            max_chars=4096,
            max_depth=6,
        )

        serialized = json.dumps(safe_response)
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("secret-password", serialized)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("secret-client", serialized)
        self.assertEqual(
            response["_hitl_pending"]["tool_arguments"]["api_key"],
            "secret-key",
        )

    def test_preserves_token_count_keys(self) -> None:
        payload = {"token_count": 12, "tokens": 3, "access_token": "secret"}

        sanitized = sanitize_tool_payload(payload)

        self.assertEqual(sanitized["token_count"], 12)
        self.assertEqual(sanitized["tokens"], 3)
        self.assertEqual(sanitized["access_token"], "[REDACTED]")

    def test_sanitize_persisted_tool_entry_redacts_by_default(self) -> None:
        entry = {
            "name": "child",
            "arguments": {"api_key": "secret"},
            "result": {"password": "secret"},
            "status": "success",
        }

        sanitized = sanitize_persisted_tool_entry(entry, capture_raw=False)

        self.assertEqual(sanitized["arguments"]["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["result"]["password"], "[REDACTED]")
        self.assertEqual(entry["arguments"]["api_key"], "secret")

    def test_sanitize_persisted_tool_entry_can_keep_raw(self) -> None:
        entry = {"arguments": {"api_key": "secret"}, "result": {"ok": True}}

        sanitized = sanitize_persisted_tool_entry(entry, capture_raw=True)

        self.assertEqual(sanitized["arguments"]["api_key"], "secret")

    def test_classifies_timeout_and_cancelled_failures(self) -> None:
        self.assertEqual(
            classify_tool_failure_status(TimeoutError("Tool execution timed out after 30 seconds")),
            "timeout",
        )
        self.assertEqual(
            classify_tool_failure_status("Workflow execution cancelled"),
            "cancelled",
        )
        self.assertEqual(
            classify_tool_failure_status("boom", explicit_status="timeout"),
            "timeout",
        )
        self.assertEqual(classify_tool_failure_status("cannot cancel reservation"), "error")
        self.assertFalse(text_indicates_cancellation("cannot cancel reservation"))
        self.assertTrue(text_indicates_cancellation("Workflow execution cancelled"))

    def test_summarizes_tool_call_statuses_and_durations(self) -> None:
        summary = summarize_tool_calls(
            [
                {"status": "success", "elapsed_ms": 10},
                {"status": "error", "elapsed_ms": 20},
                {"status": "pending", "elapsed_ms": 5},
            ]
        )

        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["error"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["total_duration_ms"], 35.0)

    def test_summarizes_legacy_failed_and_unknown_status_as_errors(self) -> None:
        summary = summarize_tool_calls([{"status": "failed"}, {"status": "unexpected"}])

        self.assertEqual(summary["error"], 2)

    def test_excludes_context_compression_from_tool_metrics(self) -> None:
        summary = summarize_tool_calls(
            [
                {
                    "name": "_context_compression",
                    "status": "compressed",
                    "elapsed_ms": 25,
                },
                {"name": "child", "status": "success", "elapsed_ms": 10},
            ]
        )

        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["error"], 0)
        self.assertEqual(summary["total_duration_ms"], 10.0)

    def test_ok_and_completed_statuses_normalize_to_success(self) -> None:
        for status in ("ok", "completed", "complete", "done", "OK"):
            with self.subTest(status=status):
                self.assertEqual(normalize_tool_call_status(status), "success")
                self.assertEqual(_tool_result_status({"status": status}), "success")

    def test_unknown_status_falls_back_to_error_field(self) -> None:
        self.assertEqual(normalize_tool_call_status("unexpected"), "unknown")
        self.assertEqual(_tool_result_status({"status": "unexpected"}), "success")
        self.assertEqual(
            _tool_result_status({"status": "unexpected", "error": "boom"}),
            "error",
        )

    def test_trace_sanitization_does_not_mutate_original_messages(self) -> None:
        request = {"messages": [{"role": "tool", "content": {"token": "secret"}}]}

        safe_request, _ = sanitize_trace_tool_payloads(
            request,
            {},
            max_chars=4096,
            max_depth=6,
        )

        self.assertEqual(request["messages"][0]["content"]["token"], "secret")
        self.assertEqual(safe_request["messages"][0]["content"]["token"], "[REDACTED]")

    def test_unknown_status_is_not_forced_to_error_without_error_field(self) -> None:
        self.assertEqual(normalize_tool_call_status("unexpected"), "unknown")
        self.assertEqual(_tool_result_status({"status": "unexpected"}), "success")

    def test_nested_sub_workflow_error_is_not_reported_as_success(self) -> None:
        result = {"status": "error", "outputs": {"error": "child failed"}}

        self.assertEqual(_tool_result_status(result), "error")

    def test_tool_status_preserves_pending_timeout_and_cancelled(self) -> None:
        for status in ("pending", "timeout", "cancelled"):
            with self.subTest(status=status):
                self.assertEqual(_tool_result_status({"status": status}), status)


class ExecuteWithToolsObservabilityTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _response(*, content: str | None, tool_calls: list[object]) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    @staticmethod
    def _tool_call() -> SimpleNamespace:
        return SimpleNamespace(
            id="call-1",
            type="function",
            function=SimpleNamespace(name="child", arguments='{"value":"ok"}'),
        )

    async def _execute_with_tool_result(self, tool_result: object) -> tuple[dict, list[dict]]:
        responses = [
            self._response(content=None, tool_calls=[self._tool_call()]),
            self._response(content="done", tool_calls=[]),
        ]

        def create(**_kwargs: object) -> SimpleNamespace:
            return responses.pop(0)

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")
        events: list[dict] = []

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run tool",
                tools=[{"name": "child", "parameters": {"type": "object"}}],
                tool_executor=lambda *_args: tool_result,
                on_tool_call=events.append,
            )
        return result, events

    async def test_real_tool_loop_reports_nested_error_status(self) -> None:
        result, events = await self._execute_with_tool_result(
            {"status": "error", "outputs": {"error": "child failed"}}
        )

        self.assertEqual(result["tool_calls"][0]["status"], "error")
        end_event = next(event for event in events if event.get("phase") == "end")
        self.assertEqual(end_event["status"], "error")
        self.assertNotIn("child failed", json.dumps(events))

    async def test_real_tool_loop_reports_pending_terminal_events(self) -> None:
        result, events = await self._execute_with_tool_result(
            HumanReviewPause(review_markdown="Review required")
        )

        self.assertIn("_hitl_pending", result)
        terminal_events = [event for event in events if event.get("phase") in {"end", "result"}]
        self.assertEqual(len(terminal_events), 2)
        self.assertTrue(all(event["status"] == "pending" for event in terminal_events))
        pending_history = result["_hitl_pending"]["agent_state"]["tool_calls"]
        self.assertEqual(pending_history, result["tool_calls"])
        self.assertEqual(pending_history[-1]["tool_call_id"], "call-1")
        self.assertEqual(pending_history[-1]["status"], "pending")

    async def test_real_tool_loop_reports_timeout_status(self) -> None:
        def boom(*_args: object) -> object:
            raise TimeoutError("Tool execution timed out after 30 seconds")

        responses = [
            self._response(content=None, tool_calls=[self._tool_call()]),
            self._response(content="done", tool_calls=[]),
        ]

        def create(**_kwargs: object) -> SimpleNamespace:
            return responses.pop(0)

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")
        events: list[dict] = []

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run tool",
                tools=[{"name": "child", "parameters": {"type": "object"}}],
                tool_executor=boom,
                on_tool_call=events.append,
            )

        self.assertEqual(result["tool_calls"][0]["status"], "timeout")
        self.assertEqual(result["tool_metrics"]["timeout"], 1)
        self.assertNotIn("secret", json.dumps(result["tool_calls"]))
        end_event = next(event for event in events if event.get("phase") == "end")
        self.assertEqual(end_event["status"], "timeout")

    async def test_real_tool_loop_reports_cancelled_on_abort(self) -> None:
        result, _events = await self._execute_with_tool_result(
            {"error": "Workflow execution cancelled"}
        )

        # Cancel in the tool result triggers abort; entry status should be cancelled.
        self.assertEqual(result["tool_calls"][0]["status"], "cancelled")
        self.assertIn("error", result)

    async def test_cancellation_during_tool_uses_cancelled_terminal_events(self) -> None:
        responses = [self._response(content=None, tool_calls=[self._tool_call()])]

        def create(**_kwargs: object) -> SimpleNamespace:
            return responses.pop(0)

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")
        events: list[dict] = []
        abort_checks = 0

        def should_abort() -> str | None:
            nonlocal abort_checks
            abort_checks += 1
            return None if abort_checks == 1 else "Workflow execution cancelled"

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run tool",
                tools=[{"name": "child", "parameters": {"type": "object"}}],
                tool_executor=lambda *_args: {"ok": True, "status": "success"},
                on_tool_call=events.append,
                should_abort=should_abort,
            )

        terminal_events = [event for event in events if event.get("phase") in {"end", "result"}]
        self.assertEqual(result["tool_calls"][0]["status"], "cancelled")
        self.assertEqual(result["tool_calls"][0]["result"]["status"], "cancelled")
        self.assertEqual(result["tool_calls"][0]["result"]["error"], "Workflow execution cancelled")
        self.assertTrue(all(event["status"] == "cancelled" for event in terminal_events))
        result_event = next(event for event in events if event.get("phase") == "result")
        self.assertEqual(result_event["result"]["status"], "cancelled")
        self.assertTrue(result_event["result"]["has_error"])

    async def test_cannot_cancel_message_does_not_abort_as_cancelled(self) -> None:
        result, events = await self._execute_with_tool_result(
            {"error": "cannot cancel reservation"}
        )

        self.assertEqual(result["tool_calls"][0]["status"], "error")
        self.assertNotIn("error", result)
        end_event = next(event for event in events if event.get("phase") == "end")
        self.assertEqual(end_event["status"], "error")

    async def test_parallel_sub_agents_keep_siblings_on_hitl_pause(self) -> None:
        tool_a = SimpleNamespace(
            id="call-a",
            type="function",
            function=SimpleNamespace(name="agent_a", arguments="{}"),
        )
        tool_b = SimpleNamespace(
            id="call-b",
            type="function",
            function=SimpleNamespace(name="agent_b", arguments="{}"),
        )
        responses = [
            self._response(content=None, tool_calls=[tool_a, tool_b]),
        ]

        def create(**_kwargs: object) -> SimpleNamespace:
            return responses.pop(0)

        def executor(tool_def: dict, name: str, *_args: object) -> object:
            if name == "agent_a":
                return {"ok": True, "status": "success"}
            return HumanReviewPause(review_markdown="Need review")

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run tools",
                tools=[
                    {"name": "agent_a", "parameters": {"type": "object"}, "_source": "sub_agent"},
                    {"name": "agent_b", "parameters": {"type": "object"}, "_source": "sub_agent"},
                ],
                tool_executor=executor,
            )

        self.assertIn("_hitl_pending", result)
        names = [tc["name"] for tc in result["tool_calls"]]
        self.assertEqual(names, ["agent_a", "agent_b"])
        self.assertEqual(result["tool_calls"][0]["status"], "success")
        self.assertEqual(result["tool_calls"][1]["status"], "pending")
        self.assertEqual(
            [tc["name"] for tc in result["_hitl_pending"]["agent_state"]["tool_calls"]],
            ["agent_a", "agent_b"],
        )

    async def test_success_tool_entry_includes_lifecycle_fields(self) -> None:
        result, events = await self._execute_with_tool_result({"ok": True, "status": "success"})

        entry = result["tool_calls"][0]
        self.assertEqual(entry["tool_call_id"], "call-1")
        self.assertEqual(entry["status"], "success")
        self.assertIsInstance(entry["started_at"], int)
        self.assertIsInstance(entry["finished_at"], int)
        self.assertGreaterEqual(entry["finished_at"], entry["started_at"])
        self.assertIn("elapsed_ms", entry)
        start_event = next(event for event in events if event.get("phase") == "start")
        self.assertEqual(start_event["tool_call_id"], "call-1")

    async def test_parallel_sub_agents_keep_siblings_on_abort(self) -> None:
        tool_a = SimpleNamespace(
            id="call-a",
            type="function",
            function=SimpleNamespace(name="agent_a", arguments="{}"),
        )
        tool_b = SimpleNamespace(
            id="call-b",
            type="function",
            function=SimpleNamespace(name="agent_b", arguments="{}"),
        )
        responses = [self._response(content=None, tool_calls=[tool_a, tool_b])]

        def create(**_kwargs: object) -> SimpleNamespace:
            return responses.pop(0)

        def executor(_tool_def: dict, name: str, *_args: object) -> object:
            if name == "agent_a":
                return {"ok": True, "status": "success"}
            return {"error": "Workflow execution cancelled"}

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="run tools",
                tools=[
                    {"name": "agent_a", "parameters": {"type": "object"}, "_source": "sub_agent"},
                    {"name": "agent_b", "parameters": {"type": "object"}, "_source": "sub_agent"},
                ],
                tool_executor=executor,
            )

        self.assertIn("error", result)
        names = [tc["name"] for tc in result["tool_calls"]]
        self.assertEqual(names, ["agent_a", "agent_b"])
        self.assertEqual(result["tool_calls"][0]["status"], "success")
        self.assertEqual(result["tool_calls"][1]["status"], "cancelled")

    async def test_persisted_tool_entry_redacts_secrets(self) -> None:
        result, _events = await self._execute_with_tool_result(
            {"ok": True, "password": "secret-password"}
        )

        self.assertEqual(result["tool_calls"][0]["result"]["password"], "[REDACTED]")
        self.assertEqual(result["tool_metrics"]["success"], 1)


class LLMTraceSafetyTests(unittest.TestCase):
    def test_sanitization_failure_does_not_escape_trace_recording(self) -> None:
        context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
        )
        with patch(
            "app.services.llm_trace.sanitize_trace_tool_payloads",
            side_effect=RuntimeError("sanitizer failure"),
        ):
            trace_id = record_llm_trace(
                context=context,
                request_type="chat.completions",
                request={},
                response={},
            )

        self.assertIsNone(trace_id)


if __name__ == "__main__":
    unittest.main()
