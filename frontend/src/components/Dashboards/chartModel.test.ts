import { describe, expect, it } from "vitest";

import type { ChartPayload } from "@/types/dashboard";
import {
  PROPORTION_COLORS,
  buildApexOptions,
  formatNumericValue,
  isChartEmpty,
  normalizeChartPayload,
  toApexSeries,
  toApexType,
  toBarGaugeRows,
  toProportionSegments,
} from "@/components/Dashboards/chartModel";

const pie: ChartPayload = {
  type: "pie",
  labels: ["Won", "Lost"],
  series: [{ name: "Deals", data: [3, 1] }],
};

describe("normalizeChartPayload", () => {
  it("accepts a chart payload or a single chart payload nested in an output", () => {
    expect(normalizeChartPayload(pie)).toBe(pie);
    expect(normalizeChartPayload({ chart: pie, note: "ok" })).toBe(pie);
  });

  it("rejects unknown types and ambiguous outputs", () => {
    expect(normalizeChartPayload({ type: "radar" })).toBeNull();
    expect(normalizeChartPayload({ a: pie, b: pie })).toBeNull();
    expect(normalizeChartPayload(null)).toBeNull();
  });
});

describe("segments and rows", () => {
  it("splits a proportion chart into percentages with the palette", () => {
    const segments = toProportionSegments({
      type: "proportion",
      labels: ["A"],
      series: [{ name: "Share", data: [1, 3] }],
    });

    expect(segments).toEqual([
      { label: "A", pct: 25, color: PROPORTION_COLORS[0] },
      { label: "Series 2", pct: 75, color: PROPORTION_COLORS[1] },
    ]);
    expect(toProportionSegments({ type: "proportion", series: [{ name: "x", data: [0] }] })).toEqual(
      [],
    );
  });

  it("scales bar-gauge rows to the maximum and colors them red to green", () => {
    const rows = toBarGaugeRows({
      type: "barGauge",
      labels: ["Low", "Mid", "Over"],
      series: [{ name: "Load", data: [0, 50, 150] }],
      max: 100,
    });

    expect(rows.map((row) => row.pct)).toEqual([0, 50, 100]);
    expect(rows[0].valueColor).toBe("rgb(239, 68, 68)");
    expect(rows[1].gradientSize).toBe("200% 100%");
    expect(rows[2].valueColor).toBe("rgb(34, 197, 94)");
  });
});

describe("values", () => {
  it("knows when a chart has nothing to show", () => {
    expect(isChartEmpty(null)).toBe(true);
    expect(isChartEmpty({ type: "table", rows: [] })).toBe(true);
    expect(isChartEmpty({ type: "text", text: "  " })).toBe(true);
    expect(isChartEmpty({ type: "hitl" })).toBe(false);
    expect(isChartEmpty(pie)).toBe(false);
  });

  it("formats numeric values with the configured decimals", () => {
    expect(formatNumericValue({ type: "numeric", value: 3.14159, decimals: 2 })).toBe("3.14");
    expect(formatNumericValue({ type: "numeric", value: "n/a" })).toBe("n/a");
    expect(formatNumericValue({ type: "numeric", value: null })).toBe("—");
  });

  it("maps chart types and series to ApexCharts", () => {
    expect(toApexType(pie)).toBe("pie");
    expect(toApexType({ type: "gauge", value: 1 })).toBe("radialBar");
    expect(toApexType({ type: "table" })).toBe("bar");
    expect(toApexSeries(pie)).toEqual([3, 1]);
    expect(toApexSeries({ type: "gauge", value: 30, min: 20, max: 40 })).toEqual([50]);
  });
});

describe("buildApexOptions", () => {
  it("follows the dark prop, not a store", () => {
    const dark = buildApexOptions(pie, { dark: true, radialHeight: 220 });
    const light = buildApexOptions(pie, { dark: false, radialHeight: 220 });

    expect(dark.theme).toEqual({ mode: "dark" });
    expect(light.theme).toEqual({ mode: "light" });
    expect(dark.stroke).toEqual({ colors: ["#0b1220"], width: 2 });
    expect(light.legend).toEqual({ position: "bottom", labels: { colors: "#0f172a" } });
  });

  it("leaves the title out when the chart has none, so ApexCharts still draws it", () => {
    expect(buildApexOptions(pie, { dark: false, radialHeight: 220 })).not.toHaveProperty("title");
    expect(
      buildApexOptions({ ...pie, title: "Deals" }, { dark: false, radialHeight: 220 }).title,
    ).toEqual({ text: "Deals" });
  });
});
