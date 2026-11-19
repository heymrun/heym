import { describe, expect, it } from "vitest";

import type { AllExecutionHistoryEntryLight } from "@/types/workflow";

import { unlockedRunMatches, withUnlockedMatches } from "./unlockedRunSearch";

function item(id: string, startedAt: string, extra: Partial<AllExecutionHistoryEntryLight> = {}): AllExecutionHistoryEntryLight {
  return {
    id,
    workflow_id: "wf",
    workflow_name: "Payroll",
    run_type: "workflow",
    started_at: startedAt,
    status: "success",
    execution_time_ms: 1,
    ...extra,
  };
}

describe("unlockedRunSearch", () => {
  it("matches decrypted values case-insensitively", () => {
    expect(unlockedRunMatches("JANE", [{ email: "jane@example.com" }])).toBe(true);
    expect(unlockedRunMatches("bob", [{ email: "jane@example.com" }])).toBe(false);
    expect(unlockedRunMatches("  ", [{ email: "jane@example.com" }])).toBe(false);
  });

  it("adds matching unlocked runs to the server's results, newest first", () => {
    const listed = [item("a", "2026-11-19T10:00:00Z")];
    const result = withUnlockedMatches(listed, "jane", [
      { item: item("b", "2026-11-19T11:00:00Z", { encrypted: true }), data: [{ email: "jane@example.com" }] },
      { item: item("c", "2026-11-19T12:00:00Z", { encrypted: true }), data: [{ email: "bob@example.com" }] },
    ]);
    expect(result.map((entry) => entry.id)).toEqual(["b", "a"]);
  });

  it("never duplicates a listed run and respects the filters", () => {
    const listed = [item("a", "2026-11-19T10:00:00Z")];
    const candidates = [
      { item: item("a", "2026-11-19T10:00:00Z"), data: ["jane"] },
      { item: item("f", "2026-11-19T09:00:00Z", { status: "failed" }), data: ["jane"] },
      { item: item("t", "2026-11-19T08:00:00Z", { trigger_source: "cron" }), data: ["jane"] },
    ];
    expect(withUnlockedMatches(listed, "jane", candidates).map((entry) => entry.id)).toEqual(["a", "f", "t"]);
    expect(withUnlockedMatches(listed, "jane", candidates, { status: "error" }).map((entry) => entry.id)).toEqual(["a", "f"]);
    expect(withUnlockedMatches(listed, "jane", candidates, { triggerSource: "cron" }).map((entry) => entry.id)).toEqual(["a", "t"]);
    expect(withUnlockedMatches(listed, "", candidates)).toBe(listed);
  });
});
