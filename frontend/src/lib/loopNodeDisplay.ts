import { getLatestNodeResultForNode } from "@/lib/executionLog";
import type { NodeResult, WorkflowEdge, WorkflowNode } from "@/types/workflow";

/**
 * Reads loop iteration count from executor-shaped output (`total` field).
 */
export function loopIterationTotalFromOutput(output: unknown): number | null {
  if (output === null || typeof output !== "object" || Array.isArray(output)) {
    return null;
  }
  const raw = (output as Record<string, unknown>).total;
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return Math.floor(raw);
  }
  if (typeof raw === "string" && raw.trim().length > 0) {
    const n = Number.parseInt(raw, 10);
    if (!Number.isNaN(n) && n >= 0) {
      return n;
    }
  }
  return null;
}

function loopBranchFromOutput(output: unknown): string | null {
  if (output === null || typeof output !== "object" || Array.isArray(output)) {
    return null;
  }
  const raw = (output as Record<string, unknown>).branch;
  return typeof raw === "string" && raw.trim().length > 0 ? raw : null;
}

/**
 * Reads loop iteration index from executor-shaped output (`index` field on `branch=loop`).
 */
export function loopIterationIndexFromOutput(output: unknown): number | null {
  if (loopBranchFromOutput(output) !== "loop") {
    return null;
  }
  if (output === null || typeof output !== "object" || Array.isArray(output)) {
    return null;
  }
  const raw = (output as Record<string, unknown>).index;
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return Math.floor(raw);
  }
  if (typeof raw === "string" && raw.trim().length > 0) {
    const n = Number.parseInt(raw, 10);
    if (!Number.isNaN(n) && n >= 0) {
      return n;
    }
  }
  return null;
}

/**
 * When the current node is a loop, returns list size from pinned output or last run results.
 */
export function loopListSizeFromContext(
  currentNodeId: string | null | undefined,
  nodes: WorkflowNode[] | undefined,
  nodeResults: NodeResult[] | undefined,
): number | null {
  if (!currentNodeId || !nodes?.length) {
    return null;
  }
  const node = nodes.find((n) => n.id === currentNodeId);
  if (!node || node.type !== "loop") {
    return null;
  }

  const pinned = node.data.pinnedData;
  if (pinned) {
    const fromPin = loopIterationTotalFromOutput(pinned);
    if (fromPin !== null) {
      return fromPin;
    }
  }

  const row = nodeResults ? getLatestNodeResultForNode(nodeResults, currentNodeId) : null;
  if (row?.output) {
    return loopIterationTotalFromOutput(row.output);
  }
  return null;
}

function forwardEdgesExcludingLoopBack(edges: WorkflowEdge[]): WorkflowEdge[] {
  return edges.filter((e) => e.targetHandle !== "loop");
}

/**
 * Nodes in the loop body reachable from the loop handle without loop-back edges
 * (aligned with WorkflowCanvas forwardEdges / loop branch walk).
 */
export function collectLoopBodyNodeIds(loopId: string, edges: WorkflowEdge[]): Set<string> {
  const forward = forwardEdgesExcludingLoopBack(edges);
  const entryTargets = forward
    .filter((e) => e.source === loopId && e.sourceHandle === "loop")
    .map((e) => e.target);
  const out = new Set<string>();
  const queue = [...entryTargets];
  while (queue.length > 0) {
    const nid = queue.shift();
    if (!nid || nid === loopId || out.has(nid)) {
      continue;
    }
    out.add(nid);
    for (const e of forward) {
      if (e.source === nid && e.target !== loopId && !out.has(e.target)) {
        queue.push(e.target);
      }
    }
  }
  return out;
}

/**
 * If `currentNodeId` lies in a loop body, returns that loop's node id (prefers smallest body set for nesting).
 */
export function findEnclosingLoopIdForListSize(
  currentNodeId: string | null | undefined,
  nodes: WorkflowNode[] | undefined,
  edges: WorkflowEdge[] | undefined,
): string | null {
  if (!currentNodeId || !nodes?.length || !edges?.length) {
    return null;
  }
  const loopIds = nodes.filter((n) => n.type === "loop").map((n) => n.id);
  let best: string | null = null;
  let bestSize = Infinity;
  for (const lid of loopIds) {
    if (lid === currentNodeId) {
      continue;
    }
    const body = collectLoopBodyNodeIds(lid, edges);
    if (!body.has(currentNodeId)) {
      continue;
    }
    if (body.size < bestSize) {
      bestSize = body.size;
      best = lid;
    } else if (body.size === bestSize && (best === null || lid.localeCompare(best) < 0)) {
      best = lid;
    }
  }
  return best;
}

/**
 * List size for evaluate dialog title: loop node uses its own output; body nodes use the enclosing loop's `total`.
 */
export function loopListSizeForEvaluateTitle(
  currentNodeId: string | null | undefined,
  nodes: WorkflowNode[] | undefined,
  edges: WorkflowEdge[] | undefined,
  nodeResults: NodeResult[] | undefined,
): number | null {
  if (!currentNodeId || !nodes?.length) {
    return null;
  }
  const self = nodes.find((n) => n.id === currentNodeId);
  if (self?.type === "loop") {
    return loopListSizeFromContext(currentNodeId, nodes, nodeResults);
  }
  const enclosing = findEnclosingLoopIdForListSize(currentNodeId, nodes, edges);
  if (!enclosing) {
    return null;
  }
  return loopListSizeFromContext(enclosing, nodes, nodeResults);
}

export interface EnclosingLoopResultMapping {
  loopNodeId: string;
  total: number | null;
  resultIndexes: number[];
  iterationIndexes: Array<number | null>;
}

/**
 * Maps a loop-body node's result rows to the enclosing loop iteration index that produced them.
 */
export function mapNodeResultsToEnclosingLoopIterations(
  currentNodeId: string | null | undefined,
  nodes: WorkflowNode[] | undefined,
  edges: WorkflowEdge[] | undefined,
  nodeResults: NodeResult[] | undefined,
): EnclosingLoopResultMapping | null {
  if (!currentNodeId || !nodeResults?.length) {
    return null;
  }
  const loopNodeId = findEnclosingLoopIdForListSize(currentNodeId, nodes, edges);
  if (!loopNodeId) {
    return null;
  }

  const resultIndexes: number[] = [];
  const iterationIndexes: Array<number | null> = [];
  let activeIterationIndex: number | null = null;

  nodeResults.forEach((result, index) => {
    if (result.node_id === loopNodeId) {
      const branch = loopBranchFromOutput(result.output);
      if (branch === "loop") {
        activeIterationIndex = loopIterationIndexFromOutput(result.output);
      } else if (branch === "done") {
        activeIterationIndex = null;
      }
    }

    if (result.node_id === currentNodeId) {
      resultIndexes.push(index);
      iterationIndexes.push(activeIterationIndex);
    }
  });

  if (resultIndexes.length === 0) {
    return null;
  }

  return {
    loopNodeId,
    total: loopListSizeFromContext(loopNodeId, nodes, nodeResults),
    resultIndexes,
    iterationIndexes,
  };
}

/**
 * Returns the active loop iteration index for a selected node/result pairing.
 */
export function selectedLoopIterationIndexForNode(
  currentNodeId: string | null | undefined,
  selectedResultIndex: number | null | undefined,
  nodes: WorkflowNode[] | undefined,
  edges: WorkflowEdge[] | undefined,
  nodeResults: NodeResult[] | undefined,
): number | null {
  if (!currentNodeId || selectedResultIndex === null || selectedResultIndex === undefined || !nodeResults?.length) {
    return null;
  }

  const currentNode = nodes?.find((node) => node.id === currentNodeId);
  const selectedRow = nodeResults[selectedResultIndex];
  if (!currentNode || !selectedRow) {
    return null;
  }

  if (currentNode.type === "loop") {
    if (selectedRow.node_id !== currentNodeId) {
      return null;
    }
    return loopIterationIndexFromOutput(selectedRow.output);
  }

  const mapped = mapNodeResultsToEnclosingLoopIterations(
    currentNodeId,
    nodes,
    edges,
    nodeResults,
  );
  if (!mapped) {
    return null;
  }

  const position = mapped.resultIndexes.indexOf(selectedResultIndex);
  if (position < 0) {
    return null;
  }

  return mapped.iterationIndexes[position] ?? null;
}

/**
 * Finds the result row index for `targetNodeId` that belongs to the requested loop iteration.
 */
export function findNodeResultIndexForLoopIteration(
  targetNodeId: string | null | undefined,
  desiredIterationIndex: number | null | undefined,
  nodes: WorkflowNode[] | undefined,
  edges: WorkflowEdge[] | undefined,
  nodeResults: NodeResult[] | undefined,
): number | null {
  if (
    !targetNodeId ||
    desiredIterationIndex === null ||
    desiredIterationIndex === undefined ||
    desiredIterationIndex < 0 ||
    !nodeResults?.length
  ) {
    return null;
  }

  const targetNode = nodes?.find((node) => node.id === targetNodeId);
  if (!targetNode) {
    return null;
  }

  if (targetNode.type === "loop") {
    for (let index = nodeResults.length - 1; index >= 0; index -= 1) {
      const row = nodeResults[index];
      if (row.node_id !== targetNodeId) {
        continue;
      }
      if (loopIterationIndexFromOutput(row.output) === desiredIterationIndex) {
        return index;
      }
    }
    return null;
  }

  const mapped = mapNodeResultsToEnclosingLoopIterations(
    targetNodeId,
    nodes,
    edges,
    nodeResults,
  );
  if (!mapped) {
    return null;
  }

  for (let position = mapped.resultIndexes.length - 1; position >= 0; position -= 1) {
    if (mapped.iterationIndexes[position] === desiredIterationIndex) {
      return mapped.resultIndexes[position] ?? null;
    }
  }

  return null;
}
