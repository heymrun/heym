import type { NodeData } from "@/types/workflow";

export type ChartOutputExpressionFieldKey =
  | "text"
  | "valueField"
  | "dataPath"
  | "statusColumn"
  | "labelField"
  | "xField"
  | "yField"
  | "min"
  | "max"
  | "unit"
  | "title"
  | "url";

export interface ChartOutputExpressionField {
  key: ChartOutputExpressionFieldKey;
  label: string;
}

/** The Chart Output fields the expression dialog steps through (1/n), for a chart type. */
export function getChartOutputExpressionFields(
  chartType: NodeData["chartType"] | undefined,
): ChartOutputExpressionField[] {
  const type = chartType || "bar";
  const fields: ChartOutputExpressionField[] = [];

  if (type === "text") {
    fields.push({ key: "text", label: "Text (markdown)" }, { key: "valueField", label: "Value field" });
  }

  fields.push({ key: "dataPath", label: "Data path" });

  if (type === "table") {
    fields.push({ key: "statusColumn", label: "Status column" });
  }

  if (["bar", "line", "area", "pie", "proportion", "barGauge"].includes(type)) {
    fields.push({ key: "labelField", label: "Label field" });
  }

  if (["bar", "line", "area", "pie", "numeric", "gauge", "proportion", "barGauge"].includes(type)) {
    fields.push({ key: "valueField", label: "Value field" });
  }

  if (type === "scatter") {
    fields.push({ key: "xField", label: "X field" }, { key: "yField", label: "Y field" });
  }

  if (type === "gauge") {
    fields.push({ key: "min", label: "Min" }, { key: "max", label: "Max" });
  }

  if (type === "barGauge") {
    fields.push({ key: "max", label: "Max" });
  }

  if (["numeric", "gauge", "barGauge"].includes(type)) {
    fields.push({ key: "unit", label: "Unit" });
  }

  fields.push({ key: "title", label: "Title" }, { key: "url", label: "Website URL" });
  return fields;
}
