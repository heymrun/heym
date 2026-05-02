import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

function stringValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim().length > 0) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toString();
  }
  return null;
}

function stableEdgeIdSegment(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function uniqueEdgeId(baseId: string, usedIds: Set<string>): string {
  if (!usedIds.has(baseId)) {
    usedIds.add(baseId);
    return baseId;
  }

  let suffix = 2;
  let candidate = `${baseId}_${suffix}`;
  while (usedIds.has(candidate)) {
    suffix++;
    candidate = `${baseId}_${suffix}`;
  }
  usedIds.add(candidate);
  return candidate;
}

export function normalizeWorkflowEdges(
  rawEdges: unknown,
  nodes: WorkflowNode[],
): WorkflowEdge[] {
  if (!Array.isArray(rawEdges)) {
    return [];
  }

  const nodeIds = new Set(nodes.map((node) => node.id));
  const usedIds = new Set<string>();
  const normalizedEdges: WorkflowEdge[] = [];

  rawEdges.forEach((rawEdge, index) => {
    if (!rawEdge || typeof rawEdge !== "object" || Array.isArray(rawEdge)) {
      return;
    }

    const edge = rawEdge as Record<string, unknown>;
    const source = stringValue(edge.source);
    const target = stringValue(edge.target);
    if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) {
      return;
    }

    const sourceHandle = stringValue(edge.sourceHandle);
    const targetHandle = stringValue(edge.targetHandle);
    const fallbackId = `edge_${stableEdgeIdSegment(source)}_${stableEdgeIdSegment(target)}_${index}`;
    const id = uniqueEdgeId(stringValue(edge.id) ?? fallbackId, usedIds);
    const normalizedEdge: WorkflowEdge = { id, source, target };

    if (sourceHandle) {
      normalizedEdge.sourceHandle = sourceHandle;
    }
    if (targetHandle) {
      normalizedEdge.targetHandle = targetHandle;
    }

    normalizedEdges.push(normalizedEdge);
  });

  return normalizedEdges;
}
