import type { NodeResult, NodeType, WorkflowEdge } from "@/types/workflow";
import { NODE_DEFINITIONS } from "@/types/node";
import { isToolEdge } from "@/lib/expressionEvaluateGraphNeighbors";

/** What a timeline span received, shown next to its output in the span details. */
export interface SpanInput {
  /** Upstream outputs keyed by node label; `{ text }` for a delegated sub-agent, `{ error }` for an error handler. */
  value: Record<string, unknown> | null;
  note: string | null;
}

export interface SpanInputTarget {
  nodeId: string;
  nodeType: string;
  /** Index of the span's row in `executionRows`. */
  resultListIndex: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLiveRow(row: NodeResult): boolean {
  return row.status === "running" || row.status === "pending";
}

function resolveDelegatedInput(
  ownRow: NodeResult,
  executionRows: NodeResult[],
): SpanInput | null {
  const traceId = ownRow.metadata?.trace_id;
  if (typeof traceId === "string" && traceId !== "") {
    for (const row of executionRows) {
      const toolCalls = isRecord(row.output) ? row.output.tool_calls : undefined;
      if (!Array.isArray(toolCalls)) continue;
      const call = toolCalls.find(
        (entry) =>
          isRecord(entry) && entry.name === "call_sub_agent" && entry.trace_id === traceId,
      ) as Record<string, unknown> | undefined;
      if (!call) continue;
      const args = isRecord(call.arguments) ? call.arguments : {};
      return {
        value: { text: args.prompt ?? "" },
        note: `Delegated by ${row.node_label}`,
      };
    }
  }
  // The prompt is read from the orchestrator's tool calls, which arrive when it finishes.
  if (executionRows.some(isLiveRow)) return null;
  return { value: null, note: "Delegated by an orchestrator. Its prompt was not recorded." };
}

/**
 * Rebuild a span's input from the same run, mirroring the executor's
 * `get_node_inputs_for_edges`: the latest successful output of every node wired
 * into it, recorded before the span's own row. Null while that input has not arrived.
 */
export function resolveSpanInput(
  span: SpanInputTarget,
  executionRows: NodeResult[],
  edges: WorkflowEdge[],
): SpanInput | null {
  const candidateRow = executionRows[span.resultListIndex];
  const ownRow = candidateRow?.node_id === span.nodeId ? candidateRow : undefined;
  if (ownRow?.metadata?.invocation === "sub_agent_tool") {
    return resolveDelegatedInput(ownRow, executionRows);
  }
  // The executor feeds an error handler `{ error }`, and the handler echoes it in its output.
  if (span.nodeType === "errorHandler") {
    if (isRecord(ownRow?.output) && "error" in ownRow.output) {
      return { value: { error: ownRow.output.error }, note: null };
    }
    if (ownRow && isLiveRow(ownRow)) return null;
  }

  const sourceIds = [
    ...new Set(
      edges
        .filter((edge) => edge.target === span.nodeId && !isToolEdge(edge))
        .map((edge) => edge.source),
    ),
  ];
  if (sourceIds.length === 0) {
    const isEntryNode = NODE_DEFINITIONS[span.nodeType as NodeType]?.inputs === 0;
    return {
      value: null,
      note: isEntryNode
        ? "Entry node: it has no upstream input."
        : "No upstream node is connected.",
    };
  }

  const searchEnd = ownRow ? span.resultListIndex : executionRows.length;
  const value: Record<string, unknown> = {};
  for (const sourceId of sourceIds) {
    for (let index = searchEnd - 1; index >= 0; index -= 1) {
      const row = executionRows[index];
      if (row.node_id === sourceId && row.status === "success") {
        value[row.node_label] = row.output;
        break;
      }
    }
  }
  if (Object.keys(value).length > 0) return { value, note: null };
  if (ownRow && isLiveRow(ownRow)) return null;
  return { value: null, note: "No upstream output reached this node." };
}
