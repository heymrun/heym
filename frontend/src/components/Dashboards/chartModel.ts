import type { ChartPayload, ChartSeries } from "@/types/dashboard";

// Palette for pie / proportion segments. All colors are mid/deep tones so a single
// white label color stays readable on every slice (no near-white colors here, and
// white is reserved for text — never used as a slice color).
export const PROPORTION_COLORS = [
  "#8b5cf6",
  "#ca8a04",
  "#3b82f6",
  "#b45309",
  "#0ea5e9",
  "#16a34a",
  "#ef4444",
  "#ec4899",
  "#0d9488",
  "#ea580c",
];

const CHART_TYPES = new Set<ChartPayload["type"]>([
  "pie",
  "bar",
  "line",
  "area",
  "table",
  "numeric",
  "gauge",
  "scatter",
  "proportion",
  "barGauge",
  "text",
  "hitl",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isChartPayload(value: unknown): value is ChartPayload {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  return CHART_TYPES.has(value.type as ChartPayload["type"]);
}

export function normalizeChartPayload(
  value: ChartPayload | Record<string, unknown> | null,
): ChartPayload | null {
  if (isChartPayload(value)) return value;
  if (!isRecord(value)) return null;

  const nestedPayloads = Object.values(value).filter(isChartPayload);
  return nestedPayloads.length === 1 ? nestedPayloads[0] : null;
}

export interface ProportionSegment {
  label: string;
  pct: number;
  color: string;
}

export function toProportionSegments(p: ChartPayload | null): ProportionSegment[] {
  if (!p || p.type !== "proportion") return [];
  const data = (p.series?.[0]?.data ?? []) as number[];
  const labels = p.labels ?? [];
  const total = data.reduce((sum, v) => sum + (typeof v === "number" ? v : 0), 0);
  if (total <= 0) return [];
  return data.map((value, i) => ({
    label: String(labels[i] ?? `Series ${i + 1}`),
    pct: (Number(value) / total) * 100,
    color: PROPORTION_COLORS[i % PROPORTION_COLORS.length],
  }));
}

// Interpolate the red -> amber -> green scale used by the bar-gauge rows.
function gradientColorAt(t: number): string {
  const stops = [
    [239, 68, 68],
    [245, 158, 11],
    [34, 197, 94],
  ];
  const clamped = Math.max(0, Math.min(1, t));
  const seg = clamped < 0.5 ? 0 : 1;
  const local = clamped < 0.5 ? clamped / 0.5 : (clamped - 0.5) / 0.5;
  const c0 = stops[seg];
  const c1 = stops[seg + 1];
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * local);
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * local);
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * local);
  return `rgb(${r}, ${g}, ${b})`;
}

export interface BarGaugeRow {
  label: string;
  value: number;
  pct: number;
  valueColor: string;
  gradientSize: string;
}

export function toBarGaugeRows(p: ChartPayload | null): BarGaugeRow[] {
  if (!p || p.type !== "barGauge") return [];
  const data = (p.series?.[0]?.data ?? []) as number[];
  const labels = p.labels ?? [];
  const values = data.map((v) => (typeof v === "number" ? v : 0));
  const max =
    typeof p.max === "number" && p.max > 0 ? p.max : Math.max(1, ...values);
  return values.map((value, i) => {
    const pct = Math.max(0, Math.min(100, (value / max) * 100));
    return {
      label: String(labels[i] ?? `Row ${i + 1}`),
      value,
      pct,
      valueColor: gradientColorAt(pct / 100),
      // Scale the gradient so the full red->green spans the whole track; the fill
      // width then reveals only the first `pct` of it (short bar = red, long = green).
      gradientSize: pct > 0 ? `${(100 / pct) * 100}% 100%` : "100% 100%",
    };
  });
}

export function isChartEmpty(p: ChartPayload | null): boolean {
  if (!p) return true;
  if (p.type === "table") return !p.rows || p.rows.length === 0;
  if (p.type === "numeric") return p.value === null || p.value === undefined;
  if (p.type === "gauge") return p.value === null || p.value === undefined;
  if (p.type === "text") return !p.text || p.text.trim().length === 0;
  if (p.type === "hitl") return false;
  return !p.series || p.series.length === 0;
}

export function formatNumericValue(p: ChartPayload | null): string {
  if (!p || p.value === null || p.value === undefined) return "—";
  const raw = p.value;
  if (typeof raw === "number" && typeof p.decimals === "number") {
    return raw.toFixed(p.decimals);
  }
  return String(raw);
}

export type ApexChartType = "pie" | "bar" | "line" | "area" | "scatter" | "radialBar";

export function toApexType(p: ChartPayload | null): ApexChartType {
  const t = p?.type;
  if (t === "pie") return "pie";
  if (t === "line") return "line";
  if (t === "area") return "area";
  if (t === "scatter") return "scatter";
  if (t === "gauge") return "radialBar";
  return "bar";
}

// Gauge value as a 0-100 percentage of [min, max].
function gaugePercent(p: ChartPayload): number {
  if (typeof p.value !== "number") return 0;
  const min = typeof p.min === "number" ? p.min : 0;
  const max = typeof p.max === "number" ? p.max : 100;
  if (max <= min) return 0;
  return Math.max(0, Math.min(100, ((p.value - min) / (max - min)) * 100));
}

export type ApexSeries = ChartSeries[] | ChartSeries["data"];

export function toApexSeries(p: ChartPayload | null): ApexSeries {
  if (!p) return [];
  if (p.type === "pie") return p.series?.[0]?.data ?? [];
  if (p.type === "gauge") return [gaugePercent(p)];
  return p.series ?? [];
}

/** How the chart is drawn: the theme ApexCharts should use, and the pie/gauge canvas size. */
export interface ApexView {
  dark: boolean;
  radialHeight: number;
}

export function buildApexOptions(p: ChartPayload | null, view: ApexView): Record<string, unknown> {
  if (!p) return {};
  const base: Record<string, unknown> = {
    chart: {
      toolbar: { show: false },
      animations: { enabled: false },
      background: "transparent",
    },
    theme: { mode: view.dark ? "dark" : "light" },
    grid: { borderColor: view.dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)" },
  };
  // Only set `title` when there is one. Passing `title: undefined` makes ApexCharts
  // choke (the chart does not render) — this is why title-less pie charts were blank.
  if (p.title) {
    base.title = { text: p.title };
  }

  if (p.type === "pie") {
    const dataLabelOffset = -Math.max(12, Math.min(24, Math.round(view.radialHeight * 0.04)));
    return {
      ...base,
      labels: p.labels ?? [],
      colors: PROPORTION_COLORS,
      plotOptions: {
        pie: {
          dataLabels: {
            offset: dataLabelOffset,
            minAngleToShowLabel: 8,
          },
        },
      },
      legend: {
        position: "bottom",
        labels: { colors: view.dark ? "#e2e8f0" : "#0f172a" },
      },
      // Slice gaps match the card background so slices read cleanly in dark mode.
      stroke: { colors: [view.dark ? "#0b1220" : "#ffffff"], width: 2 },
      dataLabels: {
        style: { colors: ["#ffffff"], fontSize: "13px", fontWeight: 700 },
        dropShadow: { enabled: false },
      },
      tooltip: { theme: view.dark ? "dark" : "light", fillSeriesColor: false },
    };
  }

  if (p.type === "gauge") {
    const raw = typeof p.value === "number" ? p.value : 0;
    const unit = p.unit ?? "";
    // Scale the center value with the chart size so it fits the hollow at any
    // widget size (a fixed size overflows small gauges).
    const valueFontPx = Math.max(13, Math.min(34, Math.round(view.radialHeight * 0.13)));
    const nameFontPx = Math.max(9, Math.min(15, Math.round(view.radialHeight * 0.06)));
    return {
      ...base,
      plotOptions: {
        radialBar: {
          hollow: { size: "58%" },
          dataLabels: {
            name: { show: !!p.title, text: p.title ?? "", fontSize: `${nameFontPx}px` },
            value: {
              offsetY: p.title ? Math.round(valueFontPx * 0.48) : Math.round(valueFontPx * 0.38),
              fontSize: `${valueFontPx}px`,
              fontWeight: 600,
              color: view.dark ? "#f8fafc" : "#0f172a",
              formatter: (): string => `${raw}${unit}`,
            },
          },
        },
      },
      labels: [p.title ?? ""],
    };
  }

  if (p.type === "scatter") {
    return { ...base, xaxis: { type: "numeric" } };
  }

  if (p.type === "area") {
    return {
      ...base,
      colors: PROPORTION_COLORS,
      xaxis: { categories: p.labels ?? [] },
      stroke: { curve: "smooth", width: 2 },
      fill: { type: "gradient", gradient: { opacityFrom: 0.45, opacityTo: 0.05 } },
      legend: { position: "bottom", labels: { colors: view.dark ? "#e2e8f0" : "#0f172a" } },
    };
  }

  return {
    ...base,
    colors: PROPORTION_COLORS,
    xaxis: { categories: p.labels ?? [] },
    plotOptions: { bar: { horizontal: p.type === "bar" && p.orientation === "horizontal" } },
  };
}
