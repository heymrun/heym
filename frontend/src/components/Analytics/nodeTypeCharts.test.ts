import { describe, expect, it } from "vitest";

import type { NodeTypeAnalytics } from "@/types/analytics";
import {
  buildNodeTypeChart,
  formatDurationMs,
  isolatedPointMarkers,
  NODE_TYPE_CHART_COLORS,
} from "@/components/Analytics/nodeTypeCharts";

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
  it("plots average duration unstacked, ranked by total time", () => {
    const chart = buildNodeTypeChart("duration", analytics, labelFor);

    expect(chart.title).toBe("Most Time-Consuming Node Types");
    expect(chart.subtitle).toBe("Average duration per call");
    expect(chart.stacked).toBe(false);
    expect(chart.series.map((series) => series.name)).toEqual(["Agent", "HTTP Request"]);
    expect(chart.series[0].data).toEqual([
      { x: Date.parse("2026-10-27T00:00:00+00:00"), y: 8_100, empty: false },
      { x: Date.parse("2026-10-27T01:00:00+00:00"), y: 0, empty: true },
    ]);
  });

  it("stacks errors and calls", () => {
    expect(buildNodeTypeChart("errors", analytics, labelFor).stacked).toBe(true);
    expect(buildNodeTypeChart("calls", analytics, labelFor).stacked).toBe(true);
  });

  it("marks a point that has no neighbor to draw a line to", () => {
    const chart = buildNodeTypeChart("duration", analytics, labelFor);

    expect(chart.markers).toEqual([
      {
        seriesIndex: 0,
        dataPointIndex: 0,
        fillColor: NODE_TYPE_CHART_COLORS[0],
        strokeColor: NODE_TYPE_CHART_COLORS[0],
        size: 4,
      },
    ]);
  });

  it("has no series and no markers before any data arrives", () => {
    const chart = buildNodeTypeChart("calls", null, labelFor);

    expect(chart.series).toEqual([]);
    expect(chart.markers).toEqual([]);
  });
});

describe("isolatedPointMarkers", () => {
  it("leaves points on a drawn line alone and marks the lonely ones", () => {
    const markers = isolatedPointMarkers([
      {
        name: "Set",
        data: [
          { x: 1, y: 0, empty: false },
          { x: 2, y: 5, empty: false },
          { x: 3, y: 0, empty: false },
          { x: 4, y: 2, empty: false },
          { x: 5, y: 3, empty: false },
          { x: 6, y: 0, empty: true },
          { x: 7, y: 9, empty: false },
        ],
      },
    ]);

    expect(markers.map((marker) => marker.dataPointIndex)).toEqual([1, 6]);
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
