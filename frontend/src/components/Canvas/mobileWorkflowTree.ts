import { TOOL_INPUT_HANDLE } from "@/lib/canvasConnectionRules";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export type MobileWorkflowTreeAccent = "violet" | "emerald" | "amber";

export interface MobileWorkflowTreeEntry {
  node: WorkflowNode;
  depth: number;
  accent: MobileWorkflowTreeAccent;
  parallelChildCount: number;
}

const ACCENTS: MobileWorkflowTreeAccent[] = ["violet", "emerald", "amber"];

function compareNodes(left: WorkflowNode, right: WorkflowNode): number {
  return left.position.y - right.position.y || left.position.x - right.position.x;
}

function getRegularEdges(edges: WorkflowEdge[], nodeIds: Set<string>): WorkflowEdge[] {
  return edges.filter(
    (edge) =>
      edge.targetHandle !== TOOL_INPUT_HANDLE &&
      nodeIds.has(edge.source) &&
      nodeIds.has(edge.target),
  );
}

/** Builds an indented, cycle-safe representation of the workflow's execution paths. */
export function buildMobileWorkflowTree(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): MobileWorkflowTreeEntry[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const regularEdges = getRegularEdges(edges, new Set(nodeById.keys()));
  const childrenById = new Map<string, string[]>();
  const incomingIds = new Set<string>();

  for (const edge of regularEdges) {
    const children = childrenById.get(edge.source) ?? [];
    children.push(edge.target);
    childrenById.set(edge.source, children);
    incomingIds.add(edge.target);
  }

  for (const [nodeId, childIds] of childrenById) {
    childIds.sort((leftId, rightId) => {
      const left = nodeById.get(leftId);
      const right = nodeById.get(rightId);
      if (!left || !right) return 0;
      return compareNodes(left, right);
    });
    childrenById.set(nodeId, childIds);
  }

  const roots = nodes.filter((node) => !incomingIds.has(node.id)).sort(compareNodes);
  const entries: MobileWorkflowTreeEntry[] = [];
  const visited = new Set<string>();

  function visit(nodeId: string, depth: number, accent: MobileWorkflowTreeAccent): void {
    if (visited.has(nodeId)) return;
    const node = nodeById.get(nodeId);
    if (!node) return;

    visited.add(nodeId);
    const childIds = childrenById.get(nodeId) ?? [];
    entries.push({
      node,
      depth,
      accent,
      parallelChildCount: childIds.length > 1 ? childIds.length : 0,
    });

    childIds.forEach((childId, index) => {
      const branches = childIds.length > 1;
      visit(childId, branches ? depth + 1 : depth, branches ? ACCENTS[index % ACCENTS.length] : accent);
    });
  }

  roots.forEach((node) => visit(node.id, 0, "violet"));
  [...nodes].sort(compareNodes).forEach((node) => visit(node.id, 0, "violet"));

  return entries;
}
