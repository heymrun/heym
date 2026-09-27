import { computed, ref, watch, type ComputedRef, type Ref } from "vue";

import type { ToolCallStatus } from "@/types/chat";
import type { ExecutionResult, NodeResult } from "@/types/workflow";

import {
  MAX_YOLO_ATTEMPTS,
  buildYoloInputDraft,
  buildYoloNodeRows,
  buildYoloRunReport,
  decideYoloNextAction,
  needsYoloTestInputs,
  summarizeYoloRun,
  yoloInputSignature,
  yoloReportLabel,
  type YoloInputDraft,
  type YoloInputState,
  type YoloResponseShape,
  type YoloStep,
} from "@/features/assistant-yolo/yoloProtocol";

export type YoloLoopState =
  | "idle"
  | "generating"
  | "awaitingInputs"
  | "running"
  | "paused"
  | "finished"
  | "stopped";

export interface YoloInputsRequest {
  draft: YoloInputDraft;
  fieldKeys: string[];
  status: "pending" | "confirmed" | "cancelled";
}

/** Fields the loop keeps on chat messages. */
export interface YoloMessageFields {
  yoloSteps?: YoloStep[];
  yoloInputs?: YoloInputsRequest;
  kind?: "yolo-report";
  yoloReportLabel?: string;
}

/** What the loop needs from the editor, injected so the loop can run without the page. */
export interface YoloLoopHost<M extends YoloMessageFields> {
  applyWorkflow: (message: M) => Promise<void>;
  sendReport: (text: string, label: string) => void;
  readInputs: () => YoloInputState;
  writeInputs: (draft: YoloInputDraft) => void;
  buildRequestBody: () => unknown;
  runWorkflow: (body: unknown) => Promise<void>;
  stopWorkflow: () => Promise<void>;
  isExecuting: () => boolean;
  saveConflictBlockedRun: () => boolean;
  executionResult: () => ExecutionResult | null;
  nodeResults: () => readonly NodeResult[];
  onVerified: () => void;
}

export interface AssistantYoloLoop<M extends YoloMessageFields> {
  state: Ref<YoloLoopState>;
  isActive: ComputedRef<boolean>;
  begin: () => void;
  handleAssistantResponse: (message: M, shape: YoloResponseShape) => Promise<void>;
  confirmInputs: (draft: YoloInputDraft) => void;
  stop: (message?: M) => Promise<void>;
  abandon: () => void;
  reset: () => void;
}

const ACTIVE_STATES: ReadonlySet<YoloLoopState> = new Set([
  "generating",
  "awaitingInputs",
  "running",
]);

export function useAssistantYoloLoop<M extends YoloMessageFields>(
  host: YoloLoopHost<M>,
): AssistantYoloLoop<M> {
  const state = ref<YoloLoopState>("idle");
  const isActive = computed(() => ACTIVE_STATES.has(state.value));
  let generation = 0;
  let attempts = 0;
  let lastRunStatus: string | null = null;
  let lastRunIssue: string | null = null;
  let confirmedSignature: string | null = null;
  let currentMessage: M | null = null;
  let resolveInputs: ((draft: YoloInputDraft | null) => void) | null = null;
  let stepSequence = 0;

  function row(label: string, status: ToolCallStatus, detail?: string): YoloStep {
    stepSequence += 1;
    return {
      id: `yolo-step-${stepSequence}`,
      name: "yolo",
      label,
      args: {},
      status,
      response_summary: detail,
    };
  }

  /** Append a step and return the stored (reactive) copy, so later edits re-render. */
  function pushStep(message: M, step: YoloStep): YoloStep {
    if (!message.yoloSteps) message.yoloSteps = [];
    message.yoloSteps.push(step);
    return message.yoloSteps[message.yoloSteps.length - 1];
  }

  function isCurrent(loop: number): boolean {
    return loop === generation && state.value !== "stopped";
  }

  function end(next: "finished" | "stopped"): void {
    state.value = next;
    resolveInputs?.(null);
    resolveInputs = null;
  }

  function begin(): void {
    generation += 1;
    attempts = 0;
    lastRunStatus = null;
    lastRunIssue = null;
    state.value = "generating";
  }

  function syncNodeRows(step: YoloStep, results: readonly NodeResult[]): void {
    const { rows, hidden } = buildYoloNodeRows(results);
    step.children = rows;
    step.hiddenChildCount = hidden;
  }

  function untilIdle(): Promise<void> {
    if (!host.isExecuting()) return Promise.resolve();
    return new Promise((resolve) => {
      const stopWatching = watch(
        () => host.isExecuting(),
        (running) => {
          if (running) return;
          stopWatching();
          resolve();
        },
        { flush: "sync" },
      );
    });
  }

  function failRun(step: YoloStep, detail: string): void {
    step.status = "error";
    step.response_summary = detail;
    end("stopped");
  }

  function finish(message: M, summary: string): void {
    const detail = summary || undefined;
    if (attempts === 0) {
      pushStep(message, row("Done", "success", detail));
    } else if (lastRunStatus !== "success") {
      pushStep(message, row("Finished — last run ended with an error", "error", detail));
    } else {
      const noun = attempts === 1 ? "attempt" : "attempts";
      pushStep(message, row(`Verified in ${attempts} ${noun}`, "success", detail));
      host.onVerified();
    }
    end("finished");
  }

  async function requestInputs(
    message: M,
    inputs: YoloInputState,
    suggested: Record<string, unknown> | null,
  ): Promise<YoloInputDraft | null> {
    state.value = "awaitingInputs";
    const waiting = pushStep(message, row("Waiting for test inputs", "pending"));
    message.yoloInputs = {
      draft: buildYoloInputDraft(inputs, suggested),
      fieldKeys: [...inputs.fieldKeys],
      status: "pending",
    };
    const draft = await new Promise<YoloInputDraft | null>((resolve) => {
      resolveInputs = resolve;
    });
    resolveInputs = null;
    const request = message.yoloInputs;
    if (!draft) {
      if (request) request.status = "cancelled";
      waiting.status = "cancelled";
      return null;
    }
    if (request) {
      request.draft = draft;
      request.status = "confirmed";
    }
    waiting.status = "success";
    return draft;
  }

  async function runAttempt(message: M, expect: string | null, loop: number): Promise<void> {
    await untilIdle();
    if (!isCurrent(loop)) return;
    attempts += 1;
    state.value = "running";
    const step = pushStep(message, {
      ...row(`Running workflow · attempt ${attempts}/${MAX_YOLO_ATTEMPTS}`, "running"),
      children: [],
      hiddenChildCount: 0,
    });
    const body = host.buildRequestBody();
    step.args = { inputs: body };
    const before = host.executionResult();
    const stopWatching = watch(
      () => host.nodeResults(),
      (results) => syncNodeRows(step, results),
      { deep: true, flush: "sync" },
    );
    let failure: string | null = null;
    try {
      await host.runWorkflow(body);
    } catch (error: unknown) {
      failure = error instanceof Error ? error.message : String(error);
    } finally {
      stopWatching();
    }
    syncNodeRows(step, host.nodeResults());
    if (!isCurrent(loop)) {
      step.status = "cancelled";
      return;
    }
    if (failure !== null) {
      failRun(step, failure);
      return;
    }
    if (host.saveConflictBlockedRun()) {
      failRun(step, "Resolve the save conflict, then send a message to continue.");
      return;
    }
    const result = host.executionResult();
    if (!result || result === before) {
      failRun(step, "The run did not start.");
      return;
    }
    if (result.status === "pending") {
      step.status = "pending";
      step.response_summary =
        "Waiting for human review — approve it in the Debug panel, then send a message.";
      end("stopped");
      return;
    }
    if (result.status === "awaiting_file_upload") {
      failRun(step, "YOLO mode can't test a workflow that waits for a file upload.");
      return;
    }
    lastRunStatus = result.status;
    lastRunIssue = summarizeYoloRun(result);
    step.status = result.status === "success" ? "success" : "error";
    step.elapsed_ms = result.execution_time_ms;
    step.response_summary = lastRunIssue;
    state.value = "generating";
    const summary = {
      attempt: attempts,
      status: result.status,
      executionTimeMs: result.execution_time_ms,
    };
    host.sendReport(
      buildYoloRunReport({ ...summary, inputs: body, expect }),
      yoloReportLabel(summary),
    );
  }

  async function handleAssistantResponse(message: M, shape: YoloResponseShape): Promise<void> {
    if (state.value !== "generating") return;
    const loop = generation;
    currentMessage = message;
    const next = decideYoloNextAction(shape);
    if (next.kind === "pause") {
      state.value = "paused";
      return;
    }
    if (next.kind === "stop") {
      pushStep(
        message,
        row("Stopped", "error", "The response had no workflow and no heym-yolo block."),
      );
      end("stopped");
      return;
    }
    if (next.kind === "finish") {
      finish(message, next.summary);
      return;
    }
    if (next.applyWorkflow) {
      const applying = pushStep(message, row("Applying changes to canvas", "running"));
      await host.applyWorkflow(message);
      applying.status = "success";
      if (!isCurrent(loop)) return;
    }
    if (attempts >= MAX_YOLO_ATTEMPTS) {
      const detail = next.applyWorkflow
        ? "Latest changes applied but not run."
        : (lastRunIssue ?? undefined);
      pushStep(message, row(`Stopped after ${MAX_YOLO_ATTEMPTS} attempts`, "error", detail));
      end("stopped");
      return;
    }
    const inputs = host.readInputs();
    if (needsYoloTestInputs(inputs, confirmedSignature, next.inputs)) {
      const draft = await requestInputs(message, inputs, next.inputs);
      if (!draft || !isCurrent(loop)) return;
      host.writeInputs(draft);
      confirmedSignature = yoloInputSignature(host.readInputs());
    }
    await runAttempt(message, next.expect, loop);
  }

  function confirmInputs(draft: YoloInputDraft): void {
    resolveInputs?.(draft);
  }

  async function stop(message?: M): Promise<void> {
    if (!isActive.value) return;
    const wasRunning = state.value === "running";
    const target = message ?? currentMessage;
    end("stopped");
    if (target) pushStep(target, row("Stopped", "cancelled"));
    if (wasRunning && host.isExecuting()) await host.stopWorkflow();
  }

  function abandon(): void {
    if (isActive.value || state.value === "paused") end("stopped");
  }

  function reset(): void {
    abandon();
    confirmedSignature = null;
    currentMessage = null;
    state.value = "idle";
  }

  return {
    state,
    isActive,
    begin,
    handleAssistantResponse,
    confirmInputs,
    stop,
    abandon,
    reset,
  };
}
