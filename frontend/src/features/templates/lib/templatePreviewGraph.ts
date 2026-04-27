import type { NodeTemplate, TemplateKind, WorkflowTemplate } from "../types/template.types";
import type { NodeType, WorkflowEdge, WorkflowNode } from "@/types/workflow";

export interface TemplatePreviewGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export function buildTemplatePreviewGraph(
  template: WorkflowTemplate | NodeTemplate,
  kind: TemplateKind,
): TemplatePreviewGraph {
  if (kind === "workflow") {
    const workflowTemplate = template as WorkflowTemplate;
    return {
      nodes: normalizeWorkflowNodes(workflowTemplate.nodes),
      edges: normalizeWorkflowEdges(workflowTemplate.edges),
    };
  }

  const nodeTemplate = template as NodeTemplate;
  return {
    nodes: [
      {
        id: `template-node-${nodeTemplate.id}`,
        type: nodeTemplate.node_type as NodeType,
        position: { x: 0, y: 0 },
        data: {
          ...nodeTemplate.node_data,
          label: String(nodeTemplate.node_data?.label ?? nodeTemplate.name),
        } as WorkflowNode["data"],
      },
    ],
    edges: [],
  };
}

function normalizeWorkflowNodes(nodes: Record<string, unknown>[]): WorkflowNode[] {
  return nodes.map((rawNode, index) => {
    const node = rawNode as Partial<WorkflowNode> & {
      type?: string;
      position?: { x: number; y: number };
      data?: Record<string, unknown>;
    };
    return {
      id: String(node.id ?? `template-node-${index}`),
      type: String(node.type ?? "sticky") as NodeType,
      position: node.position ?? { x: index * 220, y: 0 },
      data: {
        ...(node.data ?? {}),
        label: String(node.data?.label ?? node.type ?? `Node ${index + 1}`),
      } as WorkflowNode["data"],
    };
  });
}

function normalizeWorkflowEdges(edges: Record<string, unknown>[]): WorkflowEdge[] {
  return edges.map((rawEdge, index) => {
    const edge = rawEdge as Partial<WorkflowEdge>;
    return {
      id: String(edge.id ?? `template-edge-${index}`),
      source: String(edge.source ?? ""),
      target: String(edge.target ?? ""),
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
    };
  });
}
