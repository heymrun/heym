import { describe, expect, it } from "vitest";

import { getChartOutputExpressionFields } from "@/lib/chartOutputExpressionFields";

function keys(chartType: Parameters<typeof getChartOutputExpressionFields>[0]): string[] {
  return getChartOutputExpressionFields(chartType).map((field) => field.key);
}

describe("getChartOutputExpressionFields", () => {
  it("offers the status column for tables", () => {
    expect(keys("table")).toEqual(["dataPath", "statusColumn", "title", "url"]);
  });

  it("keeps the fields of the other chart types", () => {
    expect(keys(undefined)).toEqual(["dataPath", "labelField", "valueField", "title", "url"]);
    expect(keys("text")).toEqual(["text", "valueField", "dataPath", "title", "url"]);
    expect(keys("gauge")).toEqual(["dataPath", "valueField", "min", "max", "unit", "title", "url"]);
  });
});
