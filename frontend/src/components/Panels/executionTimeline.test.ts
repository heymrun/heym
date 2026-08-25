import { describe, expect, it } from "vitest";

import type { TimelineEntry } from "@/components/Panels/executionTimeline";
import {
  buildTimelineModel,
  summarizeTimelineModel,
} from "@/components/Panels/executionTimeline";

function entry(
  partial: Partial<TimelineEntry> &
    Pick<TimelineEntry, "node_id" | "node_label" | "node_type" | "status">,
): TimelineEntry {
  return {
    output: {},
    execution_time_ms: 0,
    error: null,
    isSubAgent: false,
    ...partial,
  };
}

describe("buildTimelineModel HITL wait spans", () => {
  it("renders explicit hitl_wait metadata as a distinct wait span on the node row", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 1000,
        metadata: {
          sequence: 1,
          started_at_ms: 1000,
          ended_at_ms: 2000,
          hitl_phase: "pre_review",
        },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 5000,
        metadata: {
          sequence: 2,
          started_at_ms: 2000,
          ended_at_ms: 7000,
          hitl_wait: true,
        },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 500,
        metadata: {
          sequence: 3,
          started_at_ms: 7000,
          ended_at_ms: 7500,
        },
      }),
    ];

    const { rows, timeWindow } = buildTimelineModel(results, 6500, new Map());

    expect(timeWindow.totalMs).toBeGreaterThanOrEqual(6500);
    expect(rows).toHaveLength(1);
    expect(rows[0].spans).toHaveLength(3);
    expect(rows[0].spans[1].isHitlWait).toBe(true);
    expect(rows[0].spans[1].durationMs).toBe(5000);
    expect(rows[0].spans[1].startOffsetMs).toBe(1000);
    expect(rows[0].spans[0].isHitlWait).toBe(false);
    expect(rows[0].spans[2].isHitlWait).toBe(false);
    expect(rows[0].spans[0].output).toEqual({});
    expect(rows[0].spans[1].output).toBe(null);
  });

  it("synthesizes a live HITL wait span while an agent node is still pending", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "trigger-1",
        node_label: "Trigger",
        node_type: "manual_trigger",
        status: "success",
        execution_time_ms: 10,
        metadata: {
          sequence: 1,
          started_at_ms: 1000,
          ended_at_ms: 1010,
        },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "pending",
        execution_time_ms: 800,
        metadata: {
          sequence: 2,
          started_at_ms: 1010,
          ended_at_ms: 1810,
          hitl: { summary: "Needs review" },
        },
      }),
    ];

    const { rows } = buildTimelineModel(results, 800, new Map(), {
      nowMs: 6810,
    });

    const agentRow = rows.find((row) => row.nodeId === "agent-1");
    expect(agentRow).toBeDefined();
    expect(agentRow!.spans).toHaveLength(2);
    expect(agentRow!.spans[0].isHitlWait).toBe(false);
    expect(agentRow!.spans[1].isHitlWait).toBe(true);
    expect(agentRow!.spans[1].durationMs).toBe(5000);
    expect(agentRow!.spans[1].startOffsetMs).toBe(810);
  });

  it("synthesizes a live Codex follow-up wait span while codex is pending", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "codex-1",
        node_label: "Codex",
        node_type: "codex",
        status: "pending",
        execution_time_ms: 200,
        metadata: {
          sequence: 1,
          started_at_ms: 5000,
          ended_at_ms: 5200,
          codex: { kind: "codex" },
        },
      }),
    ];

    const { rows } = buildTimelineModel(results, 200, new Map(), {
      nowMs: 8200,
    });

    expect(rows).toHaveLength(1);
    expect(rows[0].spans).toHaveLength(2);
    expect(rows[0].spans[1].isHitlWait).toBe(true);
    expect(rows[0].spans[1].durationMs).toBe(3000);
  });
});

describe("summarizeTimelineModel", () => {
  it("returns a neutral summary for an empty execution", () => {
    const model = buildTimelineModel([], 0, new Map());

    expect(summarizeTimelineModel(model.rows, model.timeWindow)).toEqual({
      totalDurationMs: 1,
      spanCount: 0,
      failedSpanCount: 0,
      retryCount: 0,
    });
  });

  it("summarizes failures and retries across all rows", () => {
    const results: TimelineEntry[] = [
      entry({
        node_id: "llm-1",
        node_label: "LLM",
        node_type: "llm",
        status: "error",
        execution_time_ms: 120,
        retryFailedAttempts: 2,
        retryLastError: "Rate limit exceeded",
        metadata: { started_at_ms: 100, ended_at_ms: 220 },
      }),
      entry({
        node_id: "agent-1",
        node_label: "Agent",
        node_type: "agent",
        status: "success",
        execution_time_ms: 80,
        retryFailedAttempts: 1,
        metadata: { started_at_ms: 220, ended_at_ms: 300 },
      }),
    ];

    const model = buildTimelineModel(results, 200, new Map());
    expect(summarizeTimelineModel(model.rows, model.timeWindow)).toEqual({
      totalDurationMs: 200,
      spanCount: 2,
      failedSpanCount: 1,
      retryCount: 3,
    });
    expect(model.rows[0].spans[0].retryLastError).toBe("Rate limit exceeded");
  });
});
