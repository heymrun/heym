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
  it("plots average duration per call, ranked by total time", () => {
    const chart = buildNodeTypeChart("duration", analytics, labelFor);

    expect(chart.title).toBe("Most Time Taken Nodes");
    expect(chart.subtitle).toBe("Average duration per call");
    expect(chart.series.map((series) => series.name)).toEqual(["Agent", "HTTP Request"]);
    expect(chart.series[0].data).toEqual([
      { x: Date.parse("2026-10-27T00:00:00+00:00"), y: 8_100, empty: false },
      { x: Date.parse("2026-10-27T01:00:00+00:00"), y: 0, empty: true },
    ]);
  });

  it("keeps each count at its own value instead of on top of the series before it", () => {
    const calls = buildNodeTypeChart("calls", analytics, labelFor);

    expect(calls.title).toBe("Most Called Node Types");
    expect(calls.series[0].data.map((point) => point.y)).toEqual([1, 0]);
  });

  it("has no series before any data arrives", () => {
    expect(buildNodeTypeChart("calls", null, labelFor).series).toEqual([]);
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
