import { describe, expect, it } from "vitest";

import { buildTraceSteps } from "@/lib/traceSteps";
import type { LLMTraceDetail } from "@/types/trace";

function makeTrace(overrides: Partial<LLMTraceDetail> = {}): LLMTraceDetail {
  return {
    id: "trace-1",
    created_at: "2026-07-24T00:00:00Z",
    source: "workflow",
    request_type: "chat.completions",
    provider: "openai",
    model: "gpt-4o",
    credential_id: null,
    credential_name: null,
    workflow_id: null,
    workflow_name: null,
    node_id: "agent-1",
    node_label: "Agent",
    status: "success",
    elapsed_ms: 120,
    prompt_tokens: 10,
    completion_tokens: 5,
    total_tokens: 15,
    cost_usd: null,
    is_priced: false,
    request: {
      messages: [
        { role: "user", content: "run tools" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call-1",
              type: "function",
              function: { name: "lookup", arguments: '{"q":"x"}' },
            },
          ],
        },
        { role: "tool", tool_call_id: "call-1", content: '{"ok":true}' },
      ],
    },
    response: {
      text: "done",
      elapsed_ms: 120,
      tool_calls: [
        {
          tool_call_id: "call-1",
          name: "lookup",
          status: "pending",
          elapsed_ms: 40,
        },
      ],
      tool_metrics: {
        count: 2,
        success: 1,
        error: 0,
        pending: 1,
        timeout: 0,
        cancelled: 0,
        total_duration_ms: 55,
      },
    },
    error: null,
    ...overrides,
  };
}

describe("buildTraceSteps agent tool observability", () => {
  it("adds pending/timeout/cancelled badges on tool steps", () => {
    const pending = buildTraceSteps(makeTrace());
    const pendingTool = pending.find((step) => step.kind === "tool");
    expect(pendingTool?.badges?.some((badge) => badge.label === "Pending review")).toBe(true);
    expect(pendingTool?.isError).toBe(false);

    const timeout = buildTraceSteps(
      makeTrace({
        response: {
          text: "done",
          tool_calls: [{ tool_call_id: "call-1", name: "lookup", status: "timeout", elapsed_ms: 40 }],
        },
      }),
    );
    const timeoutTool = timeout.find((step) => step.kind === "tool");
    expect(timeoutTool?.badges?.some((badge) => badge.label === "Timeout")).toBe(true);
    expect(timeoutTool?.isError).toBe(true);

    const cancelled = buildTraceSteps(
      makeTrace({
        response: {
          text: "done",
          tool_calls: [
            { tool_call_id: "call-1", name: "lookup", status: "cancelled", elapsed_ms: 40 },
          ],
        },
      }),
    );
    const cancelledTool = cancelled.find((step) => step.kind === "tool");
    expect(cancelledTool?.badges?.some((badge) => badge.label === "Cancelled")).toBe(true);
  });

  it("surfaces tool_metrics on the answer step", () => {
    const steps = buildTraceSteps(makeTrace());
    const answer = steps.find((step) => step.kind === "answer");

    expect(answer?.badges?.map((badge) => badge.label)).toEqual(
      expect.arrayContaining(["2 tools", "1 ok", "1 pending", "55ms tools"]),
    );
    expect(answer?.json).toEqual(
      expect.objectContaining({
        tool_metrics: expect.objectContaining({ count: 2, pending: 1 }),
      }),
    );
  });
});
