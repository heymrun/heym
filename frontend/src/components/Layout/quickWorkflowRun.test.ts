import { describe, expect, it } from "vitest";

import type { NodeResult } from "@/types/workflow";
import {
  extractImages,
  formatExecutionTime,
  latestNodeResults,
  resultToneClasses,
} from "@/components/Layout/quickWorkflowRun";

const PNG_BASE64 = "iVBORw0KGgo".padEnd(120, "A");

function step(
  nodeId: string,
  status: NodeResult["status"],
  output: Record<string, unknown> = {},
): NodeResult {
  return {
    node_id: nodeId,
    node_label: nodeId,
    node_type: "llm",
    status,
    output,
    execution_time_ms: 5,
    error: null,
  };
}

describe("latestNodeResults", () => {
  it("keeps the latest result of each step in run order and drops skipped steps", () => {
    const results = latestNodeResults([
      step("a", "running"),
      step("b", "skipped"),
      step("c", "success"),
      step("a", "success"),
    ]);

    expect(results.map((result) => `${result.node_id}:${result.status}`)).toEqual([
      "c:success",
      "a:success",
    ]);
  });
});

describe("formatExecutionTime", () => {
  it("shows milliseconds under a second and seconds above", () => {
    expect(formatExecutionTime(null)).toBe("Pending");
    expect(formatExecutionTime(412.4)).toBe("412 ms");
    expect(formatExecutionTime(2345)).toBe("2.35 s");
  });
});

describe("extractImages", () => {
  it("collects images from outputs and steps once each", () => {
    const url = "https://cdn.example.com/chart.png";
    const images = extractImages({ result: { image: url } }, [
      step("shot", "success", { screenshot: PNG_BASE64, results: { first: url } }),
    ]);

    expect(images).toEqual([url, `data:image/png;base64,${PNG_BASE64}`]);
  });
});

describe("resultToneClasses", () => {
  it("colors finished runs by outcome", () => {
    expect(resultToneClasses("success")).toContain("text-success");
    expect(resultToneClasses("error")).toContain("text-destructive");
    expect(resultToneClasses("idle")).toContain("text-muted-foreground");
  });
});
