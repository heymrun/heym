import { ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SpanItem } from "@/components/Panels/executionTimeline";
import { useSpanTraceCost } from "@/components/Panels/useSpanTraceCost";

const { getTrace } = vi.hoisted(() => ({ getTrace: vi.fn() }));
vi.mock("@/services/api", () => ({ traceApi: { get: getTrace } }));

function span(partial: Partial<SpanItem>): SpanItem {
  return {
    key: "row:0", resultListIndex: 0, nodeId: "agent", nodeLabel: "writer", nodeType: "agent",
    traceId: null, modelRouting: null, tokenUsage: null, status: "success", durationMs: 1,
    startOffsetMs: 0, endOffsetMs: 1, error: null, leftPct: 0, widthPct: 1, colorVar: "primary",
    occurrence: 1, occurrenceCount: 1, retryFailedAttempts: 0, retryFinalAttempt: null,
    retryMaxAttempts: null, retryLastError: null, gcPauseMs: 0, gcPauseCount: 0,
    gcPauseSegments: [], isHitlWait: false, output: {},
    ...partial,
  };
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("useSpanTraceCost", () => {
  beforeEach(() => {
    getTrace.mockReset();
    getTrace.mockImplementation(async (id: string) =>
      id === "priced"
        ? { is_priced: true, cost_usd: "0.0042" }
        : { is_priced: false, cost_usd: null },
    );
  });

  it("prices each trace once and leaves unpriced models out", async () => {
    const selected = ref<SpanItem | null>(span({ traceId: "priced" }));
    const cost = useSpanTraceCost(selected);
    await settle();
    expect(cost.value).toBe("0.0042");

    selected.value = span({ traceId: "unpriced" });
    await settle();
    expect(cost.value).toBeNull();

    selected.value = span({ traceId: "priced" });
    await settle();
    expect(cost.value).toBe("0.0042");
    expect(getTrace).toHaveBeenCalledTimes(2);
  });

  it("waits until the span finished before looking its trace up", async () => {
    const selected = ref<SpanItem | null>(span({ traceId: "priced", status: "running" }));
    const cost = useSpanTraceCost(selected);
    await settle();
    expect(getTrace).not.toHaveBeenCalled();
    expect(cost.value).toBeNull();

    selected.value = span({ traceId: "priced" });
    await settle();
    expect(cost.value).toBe("0.0042");
  });
});
