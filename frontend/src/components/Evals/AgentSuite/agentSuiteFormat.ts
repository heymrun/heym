import axios from "axios";

import type { AgentBaseline, AgentThresholds, ToolKind } from "@/types/evals";
import type { Workflow } from "@/types/workflow";
import { TOOL_INPUT_HANDLE, isBlockedAsTool } from "@/lib/canvasConnectionRules";

export const EMPTY_THRESHOLDS: AgentThresholds = {
  latency_ms: null,
  cost_usd: null,
  total_tokens: null,
  tool_calls: null,
};

export const RUN_LIMIT_OPTIONS = [10, 20, 50];

const DASH = "—";

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)} s`;
  return `${Math.round(value)} ms`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  if (value > 0 && value < 0.0001) return "<$0.0001";
  return `$${value.toFixed(4)}`;
}

export function formatCount(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return DASH;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatDeltaPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (value === 0) return "0%";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(Math.abs(value) < 10 ? 1 : 0)}%`;
}

export function formatRunTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Nodes wired to the agent's tool input, which the agent calls as tools, in edge order. */
export function nodeToolLabels(workflow: Pick<Workflow, "nodes" | "edges">, agentNodeId: string): string[] {
  const byId = new Map(workflow.nodes.map((node) => [node.id, node]));
  const labels: string[] = [];
  for (const edge of workflow.edges) {
    if (edge.target !== agentNodeId || edge.targetHandle !== TOOL_INPUT_HANDLE) continue;
    const node = byId.get(edge.source);
    if (!node || isBlockedAsTool(node.type)) continue;
    labels.push(node.data.label || node.id);
  }
  return labels;
}

/** Where a saved baseline came from; one saved before sources existed is the latest runs. */
export function baselineSourceLabel(baseline: Pick<AgentBaseline, "source">): string {
  if (baseline.source === "manual") return "entered manually";
  if (baseline.source === "suite_run") return "from a suite run";
  return "from the latest runs";
}

export function traceLink(traceId: string): { path: string; query: Record<string, string> } {
  return { path: "/", query: { tab: "traces", traceId } };
}

export function apiErrorText(error: unknown, fallback: string): string {
  const detail: unknown = axios.isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" && detail ? detail : fallback;
}

export const TOOL_KIND_LABELS: Record<ToolKind, string> = {
  tool: "Tool",
  mcp: "MCP",
  sub_agent: "Sub-agent",
  sub_workflow: "Sub-workflow",
  skill: "Skill",
  node: "Node",
  review: "Review",
};

export function toolKey(kind: ToolKind, name: string): string {
  return `${kind}:${name}`;
}

export function inputText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** A value that was not text in the previous run goes back as JSON when it still parses. */
export function parseInputValue(previous: unknown, text: string): unknown {
  if (previous === undefined || typeof previous === "string") return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
