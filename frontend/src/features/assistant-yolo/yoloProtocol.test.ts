import { describe, expect, it } from "vitest";

import type { ExecutionResult, NodeResult } from "@/types/workflow";

import {
  MAX_YOLO_NODE_ROWS,
  applyYoloToolEnd,
  applyYoloToolStart,
  buildYoloInputDraft,
  buildYoloNodeRows,
  buildYoloRunReport,
  decideYoloNextAction,
  extractYoloDirective,
  needsYoloTestInputs,
  stripYoloBlock,
  summarizeYoloRun,
  yoloInputSignature,
  yoloReportLabel,
  type YoloInputState,
  type YoloStep,
} from "@/features/assistant-yolo/yoloProtocol";

const RUN_BLOCK =
  '```heym-yolo\n{"action": "run", "inputs": {"text": "hi"}, "expect": "Echoes hi"}\n```';

function legacyState(overrides: Partial<YoloInputState> = {}): YoloInputState {
  return {
    mode: "legacy",
    fieldKeys: ["text"],
    fieldDefaults: { text: "" },
    values: { text: "" },
    json: "{}",
    ...overrides,
  };
}

function nodeResult(overrides: Partial<NodeResult>): NodeResult {
  return {
    node_id: "n1",
    node_label: "request",
    node_type: "textInput",
    status: "success",
    output: {},
    execution_time_ms: 3,
    error: null,
    ...overrides,
  };
}

describe("extractYoloDirective", () => {
  it("reads a run block with inputs and an expectation", () => {
    expect(extractYoloDirective(`Here it is.\n${RUN_BLOCK}`)).toEqual({
      action: "run",
      inputs: { text: "hi" },
      expect: "Echoes hi",
    });
  });

  it("reads a done block", () => {
    expect(
      extractYoloDirective('```heym-yolo\n{"action": "done", "summary": "All good"}\n```'),
    ).toEqual({ action: "done", summary: "All good" });
  });

  it("treats a run block without inputs as reusing the current ones", () => {
    expect(extractYoloDirective('```heym-yolo\n{"action": "run"}\n```')).toEqual({
      action: "run",
      inputs: null,
      expect: null,
    });
  });

  it("ignores an unknown action, invalid JSON and a missing block", () => {
    expect(extractYoloDirective('```heym-yolo\n{"action": "explode"}\n```')).toBeNull();
    expect(extractYoloDirective("```heym-yolo\nnot json at all\n```")).toBeNull();
    expect(extractYoloDirective("No block here")).toBeNull();
  });
});

describe("stripYoloBlock", () => {
  it("removes the block and keeps the rest", () => {
    expect(stripYoloBlock(`Fixed the model.\n${RUN_BLOCK}`)).toBe("Fixed the model.");
  });

  it("leaves text without a block unchanged", () => {
    expect(stripYoloBlock("Plain answer")).toBe("Plain answer");
  });
});

describe("decideYoloNextAction", () => {
  const run = { action: "run" as const, inputs: { text: "hi" }, expect: "Echoes hi" };
  const done = { action: "done" as const, summary: "All good" };

  it("pauses on a clarify block whatever else the response holds", () => {
    expect(decideYoloNextAction({ hasClarify: true, hasWorkflowJson: true, directive: run }))
      .toEqual({ kind: "pause" });
  });

  it("applies and runs workflow JSON, with or without a block", () => {
    expect(decideYoloNextAction({ hasClarify: false, hasWorkflowJson: true, directive: run }))
      .toEqual({ kind: "run", applyWorkflow: true, inputs: { text: "hi" }, expect: "Echoes hi" });
    expect(decideYoloNextAction({ hasClarify: false, hasWorkflowJson: true, directive: null }))
      .toEqual({ kind: "run", applyWorkflow: true, inputs: null, expect: null });
  });

  it("still runs workflow JSON that comes with a done block", () => {
    expect(decideYoloNextAction({ hasClarify: false, hasWorkflowJson: true, directive: done }))
      .toEqual({ kind: "run", applyWorkflow: true, inputs: null, expect: null });
  });

  it("re-runs the canvas for a run block without JSON", () => {
    expect(decideYoloNextAction({ hasClarify: false, hasWorkflowJson: false, directive: run }))
      .toEqual({ kind: "run", applyWorkflow: false, inputs: { text: "hi" }, expect: "Echoes hi" });
  });

  it("finishes on a done block without JSON and stops on nothing usable", () => {
    expect(decideYoloNextAction({ hasClarify: false, hasWorkflowJson: false, directive: done }))
      .toEqual({ kind: "finish", summary: "All good" });
    expect(decideYoloNextAction({ hasClarify: false, hasWorkflowJson: false, directive: null }))
      .toEqual({ kind: "stop" });
  });
});

describe("buildYoloRunReport", () => {
  it("states the attempt, status, duration, inputs and expectation", () => {
    expect(
      buildYoloRunReport({
        attempt: 2,
        status: "error",
        executionTimeMs: 1240.4,
        inputs: { text: "hi" },
        expect: "Echoes hi",
      }),
    ).toBe(
      '[YOLO run report] Attempt 2 of 5 finished with status "error" in 1240 ms.\n' +
        'Inputs: {"text":"hi"}\n' +
        "Expected: Echoes hi",
    );
  });

  it("truncates long inputs", () => {
    const report = buildYoloRunReport({
      attempt: 1,
      status: "success",
      executionTimeMs: null,
      inputs: { text: "x".repeat(5000) },
      expect: null,
    });
    const inputsLine = report.split("\n")[1];

    expect(inputsLine.length).toBeLessThanOrEqual("Inputs: ".length + 2000);
    expect(inputsLine.endsWith("...[truncated]")).toBe(true);
  });
});

describe("yoloReportLabel", () => {
  it("summarises the run in one line", () => {
    expect(yoloReportLabel({ attempt: 1, status: "error", executionTimeMs: 1234 }))
      .toBe("Attempt 1 result sent · error in 1.2s");
  });
});

describe("test inputs", () => {
  it("asks before the first run of a conversation", () => {
    expect(needsYoloTestInputs(legacyState(), null, null)).toBe(true);
  });

  it("does not ask again while the fields and values stay the same", () => {
    const state = legacyState({ values: { text: "hi" } });

    expect(needsYoloTestInputs(state, yoloInputSignature(state), null)).toBe(false);
    expect(needsYoloTestInputs(state, yoloInputSignature(state), { text: "hi" })).toBe(false);
  });

  it("asks again when the fields change or the assistant wants different data", () => {
    const state = legacyState({ values: { text: "hi" } });
    const confirmed = yoloInputSignature(state);

    expect(needsYoloTestInputs(legacyState({ fieldKeys: ["text", "lang"] }), confirmed, null))
      .toBe(true);
    expect(needsYoloTestInputs(state, confirmed, { text: "" })).toBe(true);
  });

  it("never asks for a legacy workflow without input fields", () => {
    expect(needsYoloTestInputs(legacyState({ fieldKeys: [] }), null, { text: "hi" })).toBe(false);
  });

  it("compares generic bodies as JSON, ignoring key order", () => {
    const state = legacyState({ mode: "generic", fieldKeys: [], json: '{"b": 1, "a": 2}' });

    expect(needsYoloTestInputs(state, "generic", { a: 2, b: 1 })).toBe(false);
    expect(needsYoloTestInputs(state, "generic", { a: 3 })).toBe(true);
  });

  it("prefills the suggestion, then the Run panel value, then the default", () => {
    const state = legacyState({
      fieldKeys: ["text", "lang", "tone"],
      fieldDefaults: { text: "", lang: "", tone: "calm" },
      values: { text: "", lang: "tr", tone: "" },
    });

    expect(buildYoloInputDraft(state, { text: "hi", extra: 1 })).toEqual({
      mode: "legacy",
      values: { text: "hi", lang: "tr", tone: "calm" },
    });
  });

  it("prefills a generic body from the suggestion", () => {
    const draft = buildYoloInputDraft(
      legacyState({ mode: "generic", fieldKeys: [], json: "{}" }),
      { a: 1 },
    );

    if (draft.mode !== "generic") throw new Error("expected a generic draft");
    expect(JSON.parse(draft.json)).toEqual({ a: 1 });
  });
});

describe("buildYoloNodeRows", () => {
  it("lists running and finished nodes and skips skipped ones", () => {
    const { rows, hidden } = buildYoloNodeRows([
      nodeResult({ node_label: "request", status: "success", execution_time_ms: 3 }),
      nodeResult({ node_id: "n2", node_label: "echo", node_type: "output", status: "running" }),
      nodeResult({ node_id: "n3", node_label: "unused", status: "skipped" }),
    ]);

    expect(rows.map((row) => [row.label, row.status, row.elapsed_ms])).toEqual([
      ["Executing request", "success", 3],
      ["Executing echo", "running", undefined],
    ]);
    expect(hidden).toBe(0);
  });

  it("caps the rows and counts the rest", () => {
    const results = Array.from({ length: MAX_YOLO_NODE_ROWS + 3 }, (_, index) =>
      nodeResult({ node_id: `n${index}` }),
    );

    const { rows, hidden } = buildYoloNodeRows(results);

    expect(rows).toHaveLength(MAX_YOLO_NODE_ROWS);
    expect(hidden).toBe(3);
  });
});

describe("summarizeYoloRun", () => {
  function result(overrides: Partial<ExecutionResult>): ExecutionResult {
    return {
      workflow_id: "wf",
      status: "success",
      outputs: {},
      execution_time_ms: 5,
      node_results: [],
      ...overrides,
    };
  }

  it("names the first failing node", () => {
    expect(
      summarizeYoloRun(
        result({
          status: "error",
          node_results: [nodeResult({ node_label: "summarize", status: "error", error: "No model" })],
        }),
      ),
    ).toBe("summarize: No model");
  });

  it("falls back to a workflow-level error, then to the status", () => {
    expect(summarizeYoloRun(result({ status: "error", outputs: { error: "Timed out" } })))
      .toBe("Timed out");
    expect(summarizeYoloRun(result({}))).toBe("Finished with status success");
  });
});

describe("tool steps", () => {
  it("adds a running row on start and settles it on end", () => {
    const steps: YoloStep[] = [];

    applyYoloToolStart(steps, {
      id: "call-1",
      name: "execute_workflow",
      label: 'Running workflow "Lookup"...',
      args: {},
    });
    applyYoloToolEnd(steps, {
      id: "call-1",
      response_summary: "Status: success",
      elapsed_ms: 40,
      status: "success",
    });

    expect(steps).toEqual([
      {
        id: "call-1",
        name: "execute_workflow",
        label: 'Running workflow "Lookup"...',
        args: {},
        status: "success",
        response_summary: "Status: success",
        elapsed_ms: 40,
      },
    ]);
  });
});
