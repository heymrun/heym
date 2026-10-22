import type { NodeData, WorkflowNode } from "@/types/workflow";

export type NodeEditActionId = "change" | "fix" | "other";

export interface NodeEditQuickAction {
  id: NodeEditActionId;
  label: string;
  /** Text put in the message box; the user finishes the sentence. */
  prefill: string;
}

export const NODE_EDIT_QUICK_ACTIONS: readonly NodeEditQuickAction[] = [
  { id: "change", label: "Change this node as ...", prefill: "Change this node to " },
  { id: "fix", label: "Fix error in this node ...", prefill: "Fix the error in this node. " },
  { id: "other", label: "Other", prefill: "" },
];

/** The node a node-edit reply returns for `target`, or null when the reply does not edit it. */
export function pickEditedNode(
  nodes: readonly WorkflowNode[],
  target: WorkflowNode,
): WorkflowNode | null {
  const candidate = nodes.find((node) => node.id === target.id)
    ?? (nodes.length === 1 ? nodes[0] : undefined);
  if (!candidate || candidate.type !== target.type) return null;
  if (!candidate.data || typeof candidate.data !== "object") return null;
  return candidate;
}

/** The reply's fields over the current ones; the label stays so `$label` references keep working. */
export function mergeEditedNodeData(target: WorkflowNode, edited: WorkflowNode): NodeData {
  return { ...target.data, ...edited.data, label: target.data.label };
}
