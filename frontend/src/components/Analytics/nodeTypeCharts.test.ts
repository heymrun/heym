import { describe, expect, it } from "vitest";

import type { NodeTypeAnalytics } from "@/types/analytics";
import { buildNodeTypeChart, formatDurationMs } from "@/components/Analytics/nodeTypeCharts";

const LABELS: Record<string, string> = { agent: "Agent", httpRequest: "HTTP Request", set: "Set" };

function labelFor(nodeType: string): string {
  return LABELS[nodeType] ?? nodeType;
}

const analytics: NodeTypeAnalytics = {
  time_buckets: ["2026-10-27T00:00:00+00:00", "2026-10-27T01:00:00+00:00"],
  most_duration: [
    { node_type: "agent", total: 15_120_000, average: 8_100, values: [8_100.4, null] },
    { node_type: "httpRequest", total: 60_000, average: 1_200, values: [1_200, 1_200] },
  ],
  most_errors: [{ node_type: "httpRequest", total: 42, average: null, values: [40, 2] }],
  most_calls: [{ node_type: "set", total: 1, average: null, values: [1, 0] }],
};

describe("buildNodeTypeChart", () => {
  it("plots average duration unstacked and names the leader by total time", () => {
    const chart = buildNodeTypeChart("duration", analytics, labelFor);

    expect(chart.title).toBe("Average Node Duration Over Time");
    expect(chart.stacked).toBe(false);
    expect(chart.series.map((series) => series.name)).toEqual(["Agent", "HTTP Request"]);
    expect(chart.series[0].data).toEqual([
      { x: Date.parse("2026-10-27T00:00:00+00:00"), y: 8_100 },
      { x: Date.parse("2026-10-27T01:00:00+00:00"), y: null },
    ]);
    expect(chart.leader).toBe("#1 Agent · avg 8.1s · 4h 12m total");
  });

  it("stacks errors and calls and counts them in the leader", () => {
    const errors = buildNodeTypeChart("errors", analytics, labelFor);
    const calls = buildNodeTypeChart("calls", analytics, labelFor);

    expect(errors.stacked).toBe(true);
    expect(errors.leader).toBe("#1 HTTP Request · 42 errors");
    expect(calls.stacked).toBe(true);
    expect(calls.leader).toBe("#1 Set · 1 call");
  });

  it("has no series and no leader before any data arrives", () => {
    const chart = buildNodeTypeChart("calls", null, labelFor);

    expect(chart.series).toEqual([]);
    expect(chart.leader).toBeNull();
  });
});

describe("formatDurationMs", () => {
  it("picks a unit that fits the size", () => {
    expect(formatDurationMs(120)).toBe("120ms");
    expect(formatDurationMs(8_100)).toBe("8.1s");
    expect(formatDurationMs(185_000)).toBe("3m 5s");
    expect(formatDurationMs(15_120_000)).toBe("4h 12m");
  });
});
