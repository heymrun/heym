import type { ChartPayload } from "@/types/dashboard";

export interface ChartTypeExample {
  value: ChartPayload["type"];
  label: string;
  /** What the widget shows and the rows it expects from the workflow. */
  hint: string;
  /** Sample data rendered by the real chart renderer as a preview. */
  payload: ChartPayload;
}

export const CHART_TYPE_EXAMPLES: ChartTypeExample[] = [
  {
    value: "bar",
    label: "Bar",
    hint: "Compare values across categories. Rows with a label and a value.",
    payload: {
      type: "bar",
      labels: ["Mon", "Tue", "Wed", "Thu", "Fri"],
      series: [{ name: "Runs", data: [12, 19, 9, 24, 17] }],
    },
  },
  {
    value: "line",
    label: "Line",
    hint: "Show a trend over time. One value per label, or several series.",
    payload: {
      type: "line",
      labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
      series: [{ name: "Signups", data: [30, 42, 38, 55, 61, 74] }],
    },
  },
  {
    value: "area",
    label: "Area",
    hint: "A filled trend that reads well with several series.",
    payload: {
      type: "area",
      labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
      series: [
        { name: "Succeeded", data: [40, 52, 48, 66, 71, 84] },
        { name: "Failed", data: [6, 4, 9, 5, 3, 4] },
      ],
    },
  },
  {
    value: "pie",
    label: "Pie",
    hint: "Parts of a whole. Rows with a label and a value.",
    payload: {
      type: "pie",
      labels: ["Webhook", "Cron", "Chat", "Email"],
      series: [{ name: "Runs", data: [44, 25, 18, 13] }],
    },
  },
  {
    value: "table",
    label: "Table",
    hint: "Raw rows and columns, scrollable.",
    payload: {
      type: "table",
      columns: ["Workflow", "Runs", "Success"],
      rows: [
        ["Lead intake", 128, "98%"],
        ["Invoice OCR", 64, "95%"],
        ["Support triage", 41, "100%"],
      ],
    },
  },
  {
    value: "numeric",
    label: "Numeric",
    hint: "One headline number with an optional unit.",
    payload: { type: "numeric", value: 1284, unit: "runs today" },
  },
  {
    value: "gauge",
    label: "Gauge",
    hint: "One value against a min to max range, such as a percentage.",
    payload: { type: "gauge", value: 72, min: 0, max: 100, unit: "%" },
  },
  {
    value: "scatter",
    label: "Scatter",
    hint: "How two numbers relate. Rows with an x and a y value.",
    payload: {
      type: "scatter",
      series: [
        {
          name: "Runs",
          data: [
            [1.2, 340],
            [2.1, 460],
            [2.8, 610],
            [3.6, 690],
            [4.4, 880],
            [5.1, 940],
          ],
        },
      ],
    },
  },
  {
    value: "proportion",
    label: "Proportion",
    hint: "One bar split into shares, with a percentage legend.",
    payload: {
      type: "proportion",
      labels: ["TypeScript", "Python", "Go"],
      series: [{ name: "Share", data: [52, 33, 15] }],
    },
  },
  {
    value: "barGauge",
    label: "Bar gauge",
    hint: "One gauge per row from red to green, such as free disk space.",
    payload: {
      type: "barGauge",
      labels: ["/", "/var", "/home"],
      series: [{ name: "Free", data: [72, 35, 12] }],
      max: 100,
      unit: "%",
    },
  },
  {
    value: "text",
    label: "Text",
    hint: "A markdown message. Task lists become checkboxes.",
    payload: {
      type: "text",
      text: "**Nightly sync** finished at 19:47.\n\n- [x] Backups verified\n- [ ] Rotate API keys",
    },
  },
];

export function chartTypeExample(type: ChartPayload["type"]): ChartTypeExample {
  return CHART_TYPE_EXAMPLES.find((example) => example.value === type) ?? CHART_TYPE_EXAMPLES[0];
}
