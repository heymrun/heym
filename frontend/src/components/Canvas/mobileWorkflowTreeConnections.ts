import { INPUT_HANDLE, TOOL_INPUT_HANDLE, isNoRegularInputNodeType } from "@/lib/canvasConnectionRules";
import type { NodeType, WorkflowEdge, WorkflowNode } from "@/types/workflow";

export type MobileWorkflowConnectionMode = "after" | "before" | "parallel";

interface ConnectionContext {
  node: WorkflowNode;
  anchor: WorkflowNode;
  mode: MobileWorkflowConnectionMode;
  edges: WorkflowEdge[];
  addEdge: (edge: WorkflowEdge) => void;
  removeEdge: (edgeId: string) => void;
  updateNodePosition: (nodeId: string, position: { x: number; y: number }) => void;
}

function regularEdges(edges: WorkflowEdge[]): WorkflowEdge[] {
  return edges.filter((edge) => edge.targetHandle !== TOOL_INPUT_HANDLE);
}

function edgeId(sourceId: string, targetId: string): string {
  return `edge_${sourceId}_${targetId}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function reconnectDetachedPath(context: ConnectionContext): void {
  const relatedEdges = regularEdges(
    context.edges.filter(
      (edge) => edge.source === context.node.id || edge.target === context.node.id,
    ),
  );
  const incomingEdges = relatedEdges.filter((edge) => edge.target === context.node.id);
  const outgoingEdges = relatedEdges.filter((edge) => edge.source === context.node.id);

  incomingEdges.forEach((incoming) => {
    outgoingEdges.forEach((outgoing) => {
      if (incoming.source === outgoing.target) return;
      context.addEdge({
        id: edgeId(incoming.source, outgoing.target),
        source: incoming.source,
        target: outgoing.target,
        sourceHandle: incoming.sourceHandle,
        targetHandle: outgoing.targetHandle,
      });
    });
  });
  relatedEdges.forEach((edge) => context.removeEdge(edge.id));
}

/** Places a regular-input node before, after, or as a parallel branch from an anchor node. */
export function connectMobileWorkflowNode(context: ConnectionContext): void {
  if (isNoRegularInputNodeType(context.node.type as NodeType)) return;
  if (
    context.mode !== "before" &&
    context.anchor.type === "output" &&
    context.anchor.data.allowDownstream !== true
  ) return;

  reconnectDetachedPath(context);
  const anchorOutgoing = regularEdges(context.edges.filter((edge) => edge.source === context.anchor.id));
  const anchorIncoming = regularEdges(context.edges.filter((edge) => edge.target === context.anchor.id));

  if (context.mode === "before" && anchorIncoming.length === 1) {
    const incoming = anchorIncoming[0];
    context.removeEdge(incoming.id);
    context.addEdge({
      id: edgeId(incoming.source, context.node.id),
      source: incoming.source,
      target: context.node.id,
      sourceHandle: incoming.sourceHandle,
      targetHandle: INPUT_HANDLE,
    });
    context.addEdge({
      id: edgeId(context.node.id, context.anchor.id),
      source: context.node.id,
      target: context.anchor.id,
      targetHandle: incoming.targetHandle,
    });
  } else if (context.mode === "after" && anchorOutgoing.length === 1) {
    const outgoing = anchorOutgoing[0];
    context.removeEdge(outgoing.id);
    context.addEdge({
      id: edgeId(context.anchor.id, context.node.id),
      source: context.anchor.id,
      target: context.node.id,
      sourceHandle: outgoing.sourceHandle,
      targetHandle: INPUT_HANDLE,
    });
    context.addEdge({
      id: edgeId(context.node.id, outgoing.target),
      source: context.node.id,
      target: outgoing.target,
      targetHandle: outgoing.targetHandle,
    });
  } else if (context.mode === "before" && anchorIncoming.length === 0) {
    context.addEdge({
      id: edgeId(context.node.id, context.anchor.id),
      source: context.node.id,
      target: context.anchor.id,
      targetHandle: INPUT_HANDLE,
    });
  } else {
    context.addEdge({
      id: edgeId(context.anchor.id, context.node.id),
      source: context.anchor.id,
      target: context.node.id,
      targetHandle: INPUT_HANDLE,
    });
  }

  context.updateNodePosition(context.node.id, {
    x: context.mode === "parallel" ? context.anchor.position.x + 48 : context.anchor.position.x,
    y: Math.max(0, context.anchor.position.y + (context.mode === "before" ? -160 : 160)),
  });
}
