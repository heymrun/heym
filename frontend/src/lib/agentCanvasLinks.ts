import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

const SUB_AGENT_SOURCE_HANDLE = "sub-agents";
const SUB_AGENT_TARGET_HANDLE = "sub-agent-input";

export function getSubAgentLabels(nodes: WorkflowNode[]): Set<string> {
  const labels = new Set<string>();

  for (const node of nodes) {
    if (node.type !== "agent" || node.data.isOrchestrator !== true) {
      continue;
    }

    for (const label of node.data.subAgentLabels ?? []) {
      labels.add(label);
    }
  }

  return labels;
}

export function buildSubAgentEdges(nodes: WorkflowNode[]): WorkflowEdge[] {
  const edges: WorkflowEdge[] = [];

  for (const node of nodes) {
    if (node.type !== "agent" || node.data.isOrchestrator !== true) {
      continue;
    }

    for (const label of node.data.subAgentLabels ?? []) {
      const targetNode = nodes.find(
        (candidate) => candidate.type === "agent" && candidate.data.label === label,
      );

      if (!targetNode) {
        continue;
      }

      edges.push({
        id: `sub-agent-edge-${node.id}-${targetNode.id}`,
        source: node.id,
        target: targetNode.id,
        sourceHandle: SUB_AGENT_SOURCE_HANDLE,
        targetHandle: SUB_AGENT_TARGET_HANDLE,
      });
    }
  }

  return edges;
}
