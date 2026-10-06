import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

/** Mirrors workflow_run_scope.py so input collection and validation match execution. */
export function workflowRunNodeIds(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  targetId: string,
): Set<string> {
  const byId = new Map(nodes.filter((node) => node.type !== "sticky").map((node) => [node.id, node]));
  const included = new Set<string>();
  if (!byId.has(targetId)) return included;
  const candidates = edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target)
    && edge.source !== targetId);
  const pending = [targetId];
  while (pending.length) {
    const nodeId = pending.pop()!;
    if (included.has(nodeId)) continue;
    included.add(nodeId);
    const node = byId.get(nodeId)!;
    pending.push(...candidates.filter((edge) => edge.target === nodeId && edge.targetHandle !== "loop")
      .map((edge) => edge.source));
    if (node.type === "loop" && nodeId !== targetId) {
      const bodyPending = candidates.filter((edge) => edge.source === nodeId && edge.sourceHandle === "loop")
        .map((edge) => edge.target);
      const bodySeen = new Set<string>();
      while (bodyPending.length) {
        const bodyId = bodyPending.pop()!;
        if (bodySeen.has(bodyId) || bodyId === nodeId) continue;
        bodySeen.add(bodyId);
        bodyPending.push(...candidates.filter((edge) => edge.source === bodyId && edge.targetHandle !== "loop")
          .map((edge) => edge.target));
      }
      if (!bodySeen.has(targetId)) pending.push(...bodySeen);
    }
    if (node.type === "agent" && node.data.isOrchestrator) {
      const labels = new Set(node.data.subAgentLabels || []);
      pending.push(...nodes.filter((sub) => sub.type === "agent" && labels.has(sub.data.label))
        .map((sub) => sub.id));
    }
  }
  return included;
}
