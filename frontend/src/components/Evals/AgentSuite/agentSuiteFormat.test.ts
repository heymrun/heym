import { describe, expect, it } from "vitest";

import { baselineSourceLabel } from "@/components/Evals/AgentSuite/agentSuiteFormat";

describe("baselineSourceLabel", () => {
  it("names each source", () => {
    expect(baselineSourceLabel({ source: "manual" })).toBe("entered manually");
    expect(baselineSourceLabel({ source: "suite_run" })).toBe("from a suite run");
    expect(baselineSourceLabel({ source: "latest_runs" })).toBe("from the latest runs");
  });

  it("reads a baseline saved before sources existed as the latest runs", () => {
    expect(baselineSourceLabel({})).toBe("from the latest runs");
  });
});
