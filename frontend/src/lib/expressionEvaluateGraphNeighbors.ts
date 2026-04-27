import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

/** Edge from loop body back to the loop head (see WorkflowCanvas forwardEdges). */
export function isLoopBackEdge(edge: WorkflowEdge): boolean {
  return edge.targetHandle === "loop";
}

export function sortNodesByCanvasOrder(nodes: WorkflowNode[], ids: string[]): WorkflowNode[] {
  const map = new Map(nodes.map((n) => [n.id, n]));
  const list: WorkflowNode[] = [];
  for (const id of ids) {
    const node = map.get(id);
    if (node) {
      list.push(node);
    }
  }
  list.sort((a, b) => {
    if (a.position.x !== b.position.x) {
      return a.position.x - b.position.x;
    }
    if (a.position.y !== b.position.y) {
      return a.position.y - b.position.y;
    }
    return a.id.localeCompare(b.id);
  });
  return list;
}

function dedupeIds(ids: string[]): string[] {
  return [...new Set(ids)];
}

function outgoingNonLoopBodyTargetIds(
  currentId: string,
  edges: WorkflowEdge[],
): string[] {
  const forward = edges.filter((e) => e.source === currentId && !isLoopBackEdge(e));
  return dedupeIds(forward.map((e) => e.target));
}

function doneExitTargetsFromLoop(loopHeadId: string, edges: WorkflowEdge[]): string[] {
  const doneOut = edges.filter((e) => e.source === loopHeadId && e.sourceHandle === "done");
  return dedupeIds(doneOut.map((e) => e.target));
}

/**
 * Outgoing neighbors for evaluate-dialog graph navigation: omits loop-back edges so
 * stepping "next" does not ping-pong inside the loop body; when the only outgoing edge
 * is a loop-back, jumps to the loop's "done" successors instead.
 */
export function outgoingEvaluateGraphNeighborNodes(
  currentId: string,
  edges: WorkflowEdge[],
  nodes: WorkflowNode[],
): WorkflowNode[] {
  const node = nodes.find((n) => n.id === currentId);
  if (!node) {
    return [];
  }

  if (node.type === "loop") {
    const loopTargets = edges
      .filter((e) => e.source === currentId && e.sourceHandle === "loop")
      .map((e) => e.target);
    const doneTargets = doneExitTargetsFromLoop(currentId, edges);
    const forwardIds = outgoingNonLoopBodyTargetIds(currentId, edges);
    return sortNodesByCanvasOrder(
      nodes,
      dedupeIds([...loopTargets, ...doneTargets, ...forwardIds]),
    );
  }

  const forwardIds = outgoingNonLoopBodyTargetIds(currentId, edges);
  if (forwardIds.length > 0) {
    return sortNodesByCanvasOrder(nodes, forwardIds);
  }

  const loopBackOnly = edges.filter((e) => e.source === currentId && isLoopBackEdge(e));
  if (loopBackOnly.length === 0) {
    return [];
  }
  const loopHeadId = loopBackOnly[0]!.target;
  const exitIds = doneExitTargetsFromLoop(loopHeadId, edges);
  if (exitIds.length > 0) {
    return sortNodesByCanvasOrder(nodes, exitIds);
  }
  return sortNodesByCanvasOrder(nodes, [loopHeadId]);
}

/**
 * Incoming neighbors for evaluate-dialog graph navigation: hides loop-back edges into the
 * loop head when a non-back incoming edge exists, so "prev" from the loop prefers upstream
 * outside the body.
 */
export function incomingEvaluateGraphNeighborNodes(
  currentId: string,
  edges: WorkflowEdge[],
  nodes: WorkflowNode[],
): WorkflowNode[] {
  const node = nodes.find((n) => n.id === currentId);
  if (!node) {
    return [];
  }

  const nonBack = edges.filter((e) => e.target === currentId && !isLoopBackEdge(e));
  if (nonBack.length > 0) {
    return sortNodesByCanvasOrder(nodes, dedupeIds(nonBack.map((e) => e.source)));
  }

  const backOnly = edges.filter((e) => e.target === currentId && isLoopBackEdge(e));
  return sortNodesByCanvasOrder(nodes, dedupeIds(backOnly.map((e) => e.source)));
}
