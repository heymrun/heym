import { jsonrepair } from "jsonrepair";

import type { AssistantToolEndEvent, AssistantToolStartEvent } from "@/services/api";
import type { ToolCall, ToolCallStatus } from "@/types/chat";
import type { ExecutionResult, NodeResult } from "@/types/workflow";

import { parseWebhookJson, stringifyWebhookJson } from "@/lib/webhookBody";

/** Fence tag of the block the assistant ends every YOLO-mode response with. */
export const YOLO_FENCE = "```heym-yolo";
/** Canvas runs one loop may start before it stops. */
export const MAX_YOLO_ATTEMPTS = 5;
/** Node rows shown under one run step before the rest collapse into "+N more nodes". */
export const MAX_YOLO_NODE_ROWS = 25;
export const YOLO_REPORT_INPUTS_MAX_CHARS = 2000;
export const YOLO_REPORT_PREFIX = "[YOLO run report]";

export interface YoloRunDirective {
  action: "run";
  inputs: Record<string, unknown> | null;
  expect: string | null;
}

export interface YoloDoneDirective {
  action: "done";
  summary: string;
}

export type YoloDirective = YoloRunDirective | YoloDoneDirective;

/** What the panel found in one finished assistant response. */
export interface YoloResponseShape {
  hasClarify: boolean;
  hasWorkflowJson: boolean;
  directive: YoloDirective | null;
}

export interface YoloPauseAction {
  kind: "pause";
}

export interface YoloRunAction {
  kind: "run";
  applyWorkflow: boolean;
  inputs: Record<string, unknown> | null;
  expect: string | null;
}

export interface YoloFinishAction {
  kind: "finish";
  summary: string;
}

export interface YoloStopAction {
  kind: "stop";
}

export type YoloNextAction = YoloPauseAction | YoloRunAction | YoloFinishAction | YoloStopAction;

/** A step row for `ChatToolCall.vue`; a run step also carries its live node rows. */
export interface YoloStep extends ToolCall {
  children?: ToolCall[];
  hiddenChildCount?: number;
}

export type YoloBodyMode = "legacy" | "generic";

/** The Run panel state the test inputs card reads and fills. */
export interface YoloInputState {
  mode: YoloBodyMode;
  fieldKeys: string[];
  fieldDefaults: Record<string, string>;
  values: Record<string, string>;
  json: string;
}

export interface YoloLegacyInputDraft {
  mode: "legacy";
  values: Record<string, string>;
}

export interface YoloGenericInputDraft {
  mode: "generic";
  json: string;
}

export type YoloInputDraft = YoloLegacyInputDraft | YoloGenericInputDraft;

export interface YoloRunSummary {
  attempt: number;
  status: string;
  executionTimeMs: number | null;
}

export interface YoloRunReportInput extends YoloRunSummary {
  inputs: unknown;
  expect: string | null;
}

export interface YoloNodeRows {
  rows: ToolCall[];
  hidden: number;
}

interface FenceBounds {
  start: number;
  bodyStart: number;
  bodyEnd: number;
  end: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function findYoloFence(content: string): FenceBounds | null {
  const start = content.indexOf(YOLO_FENCE);
  if (start === -1) return null;
  const afterTag = start + YOLO_FENCE.length;
  const newline = content.indexOf("\n", afterTag);
  const bodyStart = newline === -1 ? afterTag : newline + 1;
  const close = content.indexOf("```", bodyStart);
  return {
    start,
    bodyStart,
    bodyEnd: close === -1 ? content.length : close,
    end: close === -1 ? content.length : close + 3,
  };
}

function parseObject(raw: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    return isRecord(parsed) ? parsed : null;
  } catch {
    try {
      const repaired: unknown = JSON.parse(jsonrepair(raw));
      return isRecord(repaired) ? repaired : null;
    } catch {
      return null;
    }
  }
}

/** Read the `heym-yolo` block; an invalid block or an unknown action counts as none. */
export function extractYoloDirective(content: string): YoloDirective | null {
  const fence = findYoloFence(content);
  if (!fence) return null;
  const raw = content.slice(fence.bodyStart, fence.bodyEnd).trim();
  if (!raw) return null;
  const parsed = parseObject(raw);
  if (!parsed) return null;
  if (parsed.action === "run") {
    const expect = typeof parsed.expect === "string" ? parsed.expect.trim() : "";
    return {
      action: "run",
      inputs: isRecord(parsed.inputs) ? parsed.inputs : null,
      expect: expect || null,
    };
  }
  if (parsed.action === "done") {
    return {
      action: "done",
      summary: typeof parsed.summary === "string" ? parsed.summary.trim() : "",
    };
  }
  return null;
}

/** Remove the raw block so the chat does not render it as a code block. */
export function stripYoloBlock(content: string): string {
  const fence = findYoloFence(content);
  if (!fence) return content;
  return (content.slice(0, fence.start) + content.slice(fence.end)).trim();
}

/** Clarify pauses; workflow JSON always runs; `done` without JSON finishes. */
export function decideYoloNextAction(shape: YoloResponseShape): YoloNextAction {
  if (shape.hasClarify) return { kind: "pause" };
  const directive = shape.directive;
  if (shape.hasWorkflowJson) {
    return {
      kind: "run",
      applyWorkflow: true,
      inputs: directive?.action === "run" ? directive.inputs : null,
      expect: directive?.action === "run" ? directive.expect : null,
    };
  }
  if (directive?.action === "run") {
    return {
      kind: "run",
      applyWorkflow: false,
      inputs: directive.inputs,
      expect: directive.expect,
    };
  }
  if (directive?.action === "done") return { kind: "finish", summary: directive.summary };
  return { kind: "stop" };
}

function truncate(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  const suffix = "...[truncated]";
  return `${text.slice(0, Math.max(0, maxChars - suffix.length))}${suffix}`;
}

function stringifyReportInputs(inputs: unknown): string {
  try {
    return JSON.stringify(inputs ?? {}) ?? "{}";
  } catch {
    return String(inputs);
  }
}

/** The user-role message the panel sends after each canvas run. */
export function buildYoloRunReport(input: YoloRunReportInput): string {
  const duration =
    input.executionTimeMs === null ? "" : ` in ${Math.round(input.executionTimeMs)} ms`;
  const lines = [
    `${YOLO_REPORT_PREFIX} Attempt ${input.attempt} of ${MAX_YOLO_ATTEMPTS} finished with status "${input.status}"${duration}.`,
    `Inputs: ${truncate(stringifyReportInputs(input.inputs), YOLO_REPORT_INPUTS_MAX_CHARS)}`,
  ];
  if (input.expect) lines.push(`Expected: ${input.expect}`);
  return lines.join("\n");
}

/** The compact line the chat shows for a report instead of a message bubble. */
export function yoloReportLabel(summary: YoloRunSummary): string {
  const duration =
    summary.executionTimeMs === null
      ? ""
      : ` in ${(summary.executionTimeMs / 1000).toFixed(1)}s`;
  return `Attempt ${summary.attempt} result sent · ${summary.status}${duration}`;
}

export function hasYoloTestInputs(state: YoloInputState): boolean {
  return state.mode === "generic" || state.fieldKeys.length > 0;
}

export function yoloInputSignature(state: YoloInputState): string {
  if (state.mode === "generic") return "generic";
  return `legacy:${[...state.fieldKeys].sort().join(",")}`;
}

function stringifyInputValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return JSON.stringify(value) ?? "";
}

function effectiveValue(state: YoloInputState, key: string): string {
  return state.values[key] || state.fieldDefaults[key] || "";
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (isRecord(value)) {
    const entries = Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function suggestionDiffers(state: YoloInputState, suggested: Record<string, unknown>): boolean {
  if (state.mode === "generic") {
    return stableStringify(parseWebhookJson(state.json).value) !== stableStringify(suggested);
  }
  return state.fieldKeys.some(
    (key) => key in suggested && stringifyInputValue(suggested[key]) !== effectiveValue(state, key),
  );
}

/**
 * Whether to show the test inputs card before a run: nothing confirmed yet in this
 * conversation, the input fields changed, or the assistant suggests different values.
 */
export function needsYoloTestInputs(
  state: YoloInputState,
  confirmedSignature: string | null,
  suggested: Record<string, unknown> | null,
): boolean {
  if (!hasYoloTestInputs(state)) return false;
  if (confirmedSignature !== yoloInputSignature(state)) return true;
  return suggested !== null && suggestionDiffers(state, suggested);
}

/** Prefill the card: the suggestion first, then the Run panel value, then the default. */
export function buildYoloInputDraft(
  state: YoloInputState,
  suggested: Record<string, unknown> | null,
): YoloInputDraft {
  if (state.mode === "generic") {
    return { mode: "generic", json: suggested ? stringifyWebhookJson(suggested) : state.json };
  }
  const values: Record<string, string> = {};
  for (const key of state.fieldKeys) {
    values[key] =
      suggested && key in suggested
        ? stringifyInputValue(suggested[key])
        : effectiveValue(state, key);
  }
  return { mode: "legacy", values };
}

const NODE_ROW_STATUS: Record<NodeResult["status"], ToolCallStatus | null> = {
  running: "running",
  success: "success",
  error: "error",
  pending: "pending",
  skipped: null,
};

/** Turn a run's live node results into `Executing <node>` rows, capped for the chat. */
export function buildYoloNodeRows(results: readonly NodeResult[]): YoloNodeRows {
  const listed = results.filter((result) => NODE_ROW_STATUS[result.status] !== null);
  const rows = listed.slice(0, MAX_YOLO_NODE_ROWS).map(
    (result, index): ToolCall => ({
      id: `${result.node_id}:${index}`,
      name: result.node_type,
      label: `Executing ${result.node_label}`,
      args: { node: result.node_label, type: result.node_type },
      response_summary: result.error ?? undefined,
      elapsed_ms: result.status === "running" ? undefined : result.execution_time_ms,
      status: NODE_ROW_STATUS[result.status] ?? "error",
    }),
  );
  return { rows, hidden: Math.max(0, listed.length - MAX_YOLO_NODE_ROWS) };
}

/** One line for the run step's detail: the first failing node, or the status. */
export function summarizeYoloRun(result: ExecutionResult): string {
  const failed = result.node_results.find((row) => row.status === "error");
  if (failed) return `${failed.node_label}: ${failed.error ?? "failed"}`;
  const outputs = result.outputs as Record<string, unknown> | undefined;
  if (result.status === "error" && typeof outputs?.error === "string") return outputs.error;
  return `Finished with status ${result.status}`;
}

export function applyYoloToolStart(steps: YoloStep[], event: AssistantToolStartEvent): void {
  steps.push({
    id: event.id,
    name: event.name,
    label: event.label,
    args: event.args,
    status: "running",
  });
}

export function applyYoloToolEnd(steps: YoloStep[], event: AssistantToolEndEvent): void {
  const step = steps.find((candidate) => candidate.id === event.id);
  if (!step) return;
  step.status = event.status;
  step.response_summary = event.response_summary;
  step.elapsed_ms = event.elapsed_ms;
}
