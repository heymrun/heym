import { reactive } from "vue";
import { describe, expect, it } from "vitest";

import type { YoloInputState, YoloResponseShape } from "@/features/assistant-yolo/yoloProtocol";
import type { ExecutionResult, NodeResult } from "@/types/workflow";

import {
  useAssistantYoloLoop,
  type AssistantYoloLoop,
  type YoloLoopHost,
  type YoloMessageFields,
} from "@/features/assistant-yolo/useAssistantYoloLoop";

interface TestMessage extends YoloMessageFields {
  id: string;
}

interface HostState {
  executing: boolean;
  blocked: boolean;
  result: ExecutionResult | null;
  nodeResults: NodeResult[];
  inputs: YoloInputState;
  nextStatus: ExecutionResult["status"];
}

interface HostCalls {
  applied: number;
  runs: unknown[];
  reports: Array<{ text: string; label: string }>;
  stops: number;
  verified: number;
}

const RUN_WITH_JSON: YoloResponseShape = {
  hasClarify: false,
  hasWorkflowJson: true,
  directive: { action: "run", inputs: { text: "hi" }, expect: "Echoes hi" },
};
const RERUN_JSON: YoloResponseShape = {
  hasClarify: false,
  hasWorkflowJson: true,
  directive: { action: "run", inputs: null, expect: null },
};
const DONE: YoloResponseShape = {
  hasClarify: false,
  hasWorkflowJson: false,
  directive: { action: "done", summary: "Echo works" },
};

function nodeResult(label: string, status: NodeResult["status"]): NodeResult {
  return {
    node_id: label,
    node_label: label,
    node_type: "set",
    status,
    output: {},
    execution_time_ms: 4,
    error: status === "error" ? "boom" : null,
  };
}

function createHost(): { host: YoloLoopHost<TestMessage>; hostState: HostState; calls: HostCalls } {
  const hostState = reactive<HostState>({
    executing: false,
    blocked: false,
    result: null,
    nodeResults: [],
    inputs: {
      mode: "legacy",
      fieldKeys: ["text"],
      fieldDefaults: { text: "" },
      values: { text: "" },
      json: "{}",
    },
    nextStatus: "success",
  });
  const calls: HostCalls = { applied: 0, runs: [], reports: [], stops: 0, verified: 0 };
  const host: YoloLoopHost<TestMessage> = {
    applyWorkflow: async () => {
      calls.applied += 1;
    },
    sendReport: (text, label) => {
      calls.reports.push({ text, label });
    },
    readInputs: () => ({
      ...hostState.inputs,
      fieldKeys: [...hostState.inputs.fieldKeys],
      values: { ...hostState.inputs.values },
    }),
    writeInputs: (draft) => {
      if (draft.mode === "legacy") hostState.inputs.values = { ...draft.values };
      else hostState.inputs.json = draft.json;
    },
    buildRequestBody: () => ({ ...hostState.inputs.values }),
    runWorkflow: async (body) => {
      calls.runs.push(body);
      hostState.executing = true;
      hostState.nodeResults = [nodeResult("request", "running")];
      hostState.nodeResults = [
        nodeResult("request", "success"),
        nodeResult("echo", hostState.nextStatus === "error" ? "error" : "success"),
      ];
      hostState.result = {
        workflow_id: "wf",
        status: hostState.nextStatus,
        outputs: {},
        execution_time_ms: 1200,
        node_results: hostState.nodeResults,
      };
      hostState.executing = false;
    },
    stopWorkflow: async () => {
      calls.stops += 1;
      hostState.executing = false;
    },
    isExecuting: () => hostState.executing,
    saveConflictBlockedRun: () => hostState.blocked,
    executionResult: () => hostState.result,
    nodeResults: () => hostState.nodeResults,
    onVerified: () => {
      calls.verified += 1;
    },
  };
  return { host, hostState, calls };
}

function message(id: string): TestMessage {
  return reactive<TestMessage>({ id });
}

function labels(target: TestMessage): string[] {
  return (target.yoloSteps ?? []).map((step) => step.label);
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/** Start a loop and confirm the first test inputs card with `text`. */
async function firstRun(
  loop: AssistantYoloLoop<TestMessage>,
  text = "hi",
): Promise<TestMessage> {
  const first = message("a1");
  loop.begin();
  const handled = loop.handleAssistantResponse(first, RUN_WITH_JSON);
  await settle();
  loop.confirmInputs({ mode: "legacy", values: { text } });
  await handled;
  return first;
}

describe("useAssistantYoloLoop", () => {
  it("asks for inputs once, runs, reports, and finishes on done", async () => {
    const { host, hostState, calls } = createHost();
    const loop = useAssistantYoloLoop(host);
    const first = message("a1");

    loop.begin();
    const handled = loop.handleAssistantResponse(first, RUN_WITH_JSON);
    await settle();

    expect(loop.state.value).toBe("awaitingInputs");
    expect(first.yoloInputs?.draft).toEqual({ mode: "legacy", values: { text: "hi" } });
    loop.confirmInputs({ mode: "legacy", values: { text: "hello" } });
    await handled;

    expect(calls.applied).toBe(1);
    expect(calls.runs).toEqual([{ text: "hello" }]);
    expect(hostState.inputs.values).toEqual({ text: "hello" });
    expect(first.yoloInputs?.status).toBe("confirmed");
    expect(labels(first)).toEqual([
      "Applying changes to canvas",
      "Waiting for test inputs",
      "Running workflow · attempt 1/5",
    ]);
    const runStep = first.yoloSteps?.[2];
    expect(runStep?.status).toBe("success");
    expect(runStep?.children?.map((row) => row.label)).toEqual([
      "Executing request",
      "Executing echo",
    ]);
    expect(calls.reports).toHaveLength(1);
    expect(calls.reports[0].text).toContain(
      '[YOLO run report] Attempt 1 of 5 finished with status "success"',
    );
    expect(calls.reports[0].label).toBe("Attempt 1 result sent · success in 1.2s");
    expect(loop.state.value).toBe("generating");

    const second = message("a2");
    await loop.handleAssistantResponse(second, DONE);

    expect(labels(second)).toEqual(["Verified in 1 attempt"]);
    expect(second.yoloSteps?.[0].response_summary).toBe("Echo works");
    expect(calls.verified).toBe(1);
    expect(loop.state.value).toBe("finished");
  });

  it("reuses the confirmed inputs on the next attempt", async () => {
    const { host, calls } = createHost();
    const loop = useAssistantYoloLoop(host);
    await firstRun(loop);

    const second = message("a2");
    await loop.handleAssistantResponse(second, RERUN_JSON);

    expect(second.yoloInputs).toBeUndefined();
    expect(calls.runs).toEqual([{ text: "hi" }, { text: "hi" }]);
    expect(labels(second)).toEqual([
      "Applying changes to canvas",
      "Running workflow · attempt 2/5",
    ]);
  });

  it("asks again when the assistant suggests different test data", async () => {
    const { host, calls } = createHost();
    const loop = useAssistantYoloLoop(host);
    await firstRun(loop);

    const second = message("a2");
    const handled = loop.handleAssistantResponse(second, {
      hasClarify: false,
      hasWorkflowJson: false,
      directive: { action: "run", inputs: { text: "different" }, expect: null },
    });
    await settle();

    expect(loop.state.value).toBe("awaitingInputs");
    expect(second.yoloInputs?.draft).toEqual({ mode: "legacy", values: { text: "different" } });
    loop.confirmInputs({ mode: "legacy", values: { text: "different" } });
    await handled;
    expect(calls.runs).toEqual([{ text: "hi" }, { text: "different" }]);
  });

  it("stops after five runs and applies the last fix without running it", async () => {
    const { host, calls } = createHost();
    const loop = useAssistantYoloLoop(host);
    await firstRun(loop);
    for (let attempt = 2; attempt <= 5; attempt += 1) {
      await loop.handleAssistantResponse(message(`a${attempt}`), RERUN_JSON);
    }

    const last = message("a6");
    await loop.handleAssistantResponse(last, RERUN_JSON);

    expect(calls.runs).toHaveLength(5);
    expect(calls.applied).toBe(6);
    expect(labels(last)).toEqual(["Applying changes to canvas", "Stopped after 5 attempts"]);
    expect(last.yoloSteps?.[1].response_summary).toBe("Latest changes applied but not run.");
    expect(loop.state.value).toBe("stopped");
  });

  it("pauses on a clarify block and starts a fresh budget after the answers", async () => {
    const { host } = createHost();
    const loop = useAssistantYoloLoop(host);
    loop.begin();

    await loop.handleAssistantResponse(message("a1"), {
      hasClarify: true,
      hasWorkflowJson: false,
      directive: null,
    });

    expect(loop.state.value).toBe("paused");
    expect(loop.isActive.value).toBe(false);
    loop.begin();
    expect(loop.state.value).toBe("generating");
  });

  it("stops when a save conflict blocks the run", async () => {
    const { host, hostState, calls } = createHost();
    host.runWorkflow = async () => {
      hostState.blocked = true;
    };
    const loop = useAssistantYoloLoop(host);

    const first = await firstRun(loop);

    const runStep = first.yoloSteps?.[2];
    expect(runStep?.status).toBe("error");
    expect(runStep?.response_summary).toBe(
      "Resolve the save conflict, then send a message to continue.",
    );
    expect(calls.reports).toHaveLength(0);
    expect(loop.state.value).toBe("stopped");
  });

  it("stops when the run did not start", async () => {
    const { host, calls } = createHost();
    host.runWorkflow = async () => undefined;
    const loop = useAssistantYoloLoop(host);

    const first = await firstRun(loop);

    expect(first.yoloSteps?.[2].response_summary).toBe("The run did not start.");
    expect(calls.reports).toHaveLength(0);
  });

  it("stops when the run waits for a human review", async () => {
    const { host, hostState, calls } = createHost();
    hostState.nextStatus = "pending";
    const loop = useAssistantYoloLoop(host);

    const first = await firstRun(loop);

    expect(first.yoloSteps?.[2].status).toBe("pending");
    expect(first.yoloSteps?.[2].response_summary).toContain("Waiting for human review");
    expect(calls.reports).toHaveLength(0);
    expect(loop.state.value).toBe("stopped");
  });

  it("finishes with the error row when done follows a failed run", async () => {
    const { host, hostState, calls } = createHost();
    hostState.nextStatus = "error";
    const loop = useAssistantYoloLoop(host);
    await firstRun(loop);

    const second = message("a2");
    await loop.handleAssistantResponse(second, DONE);

    expect(labels(second)).toEqual(["Finished — last run ended with an error"]);
    expect(second.yoloSteps?.[0].status).toBe("error");
    expect(calls.verified).toBe(0);
  });

  it("waits for a manual run to finish before starting its own", async () => {
    const { host, hostState, calls } = createHost();
    hostState.executing = true;
    const loop = useAssistantYoloLoop(host);
    const first = message("a1");

    loop.begin();
    const handled = loop.handleAssistantResponse(first, RUN_WITH_JSON);
    await settle();
    loop.confirmInputs({ mode: "legacy", values: { text: "hi" } });
    await settle();
    expect(calls.runs).toHaveLength(0);

    hostState.executing = false;
    await handled;
    expect(calls.runs).toHaveLength(1);
  });

  it("stop() while waiting for inputs cancels the card and ends the loop", async () => {
    const { host, calls } = createHost();
    const loop = useAssistantYoloLoop(host);
    const first = message("a1");

    loop.begin();
    const handled = loop.handleAssistantResponse(first, RUN_WITH_JSON);
    await settle();
    await loop.stop(first);
    await handled;

    expect(first.yoloInputs?.status).toBe("cancelled");
    expect(labels(first)).toEqual([
      "Applying changes to canvas",
      "Waiting for test inputs",
      "Stopped",
    ]);
    expect(first.yoloSteps?.[1].status).toBe("cancelled");
    expect(calls.runs).toHaveLength(0);
    expect(loop.state.value).toBe("stopped");
  });
});
