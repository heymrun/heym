import { describe, expect, it } from "vitest";

import { mergeEvalSuite, parseEvalSuiteSaved } from "@/lib/evalSuitePreview";

const saved = {
  type: "eval_suite_saved",
  suite_id: "s-1",
  suite_name: "Support replies",
  suite_type: "prompt",
  suite_url: "/evals?suite=s-1",
};

describe("parseEvalSuiteSaved", () => {
  it("reads a saved suite event", () => {
    expect(parseEvalSuiteSaved(saved)).toEqual({
      id: "s-1",
      name: "Support replies",
      suiteType: "prompt",
      url: "/evals?suite=s-1",
    });
  });

  it("ignores other events and broken ones", () => {
    expect(parseEvalSuiteSaved({ ...saved, type: "workflow_created" })).toBeNull();
    expect(parseEvalSuiteSaved({ ...saved, suite_id: 7 })).toBeNull();
    expect(parseEvalSuiteSaved({ ...saved, suite_type: "other" })).toBeNull();
  });

  it("keeps the link on the Evals page", () => {
    expect(parseEvalSuiteSaved({ ...saved, suite_url: "https://evil.example/x" })).toBeNull();
    expect(parseEvalSuiteSaved({ ...saved, suite_url: "javascript:alert(1)" })).toBeNull();
  });
});

describe("mergeEvalSuite", () => {
  it("adds a new suite and replaces a suite saved again", () => {
    const first = parseEvalSuiteSaved(saved)!;
    const renamed = { ...first, name: "Support replies v2" };
    const other = { ...first, id: "s-2", url: "/evals?suite=s-2" };

    expect(mergeEvalSuite([], first)).toEqual([first]);
    expect(mergeEvalSuite([first, other], renamed)).toEqual([renamed, other]);
  });
});
