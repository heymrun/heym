import { LayoutTemplate } from "lucide-vue-next";
import type { Component } from "vue";

import { isTileFillingIcon, nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { describeNode, humanizeNodeType } from "@/lib/workflowPreview";
import { NODE_DEFINITIONS } from "@/types/node";
import type { NodeData, NodeType, WorkflowNode } from "@/types/workflow";

const SUMMARY_KEYS = ["url", "path", "operation", "model", "prompt", "message", "code"];

export interface NodeDisplayMetadata {
  label: string;
  summary: string;
  icon: Component;
  iconColorClass: string;
  tileFilling: boolean;
}

function knownNodeType(nodeType: string): NodeType | null {
  return Object.prototype.hasOwnProperty.call(NODE_DEFINITIONS, nodeType)
    ? (nodeType as NodeType)
    : null;
}

function nodeSpecificSummary(data: Record<string, unknown>): string | null {
  for (const key of SUMMARY_KEYS) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function unknownNodeSummary(nodeType: string, data: Record<string, unknown>): string {
  const humanizedType = humanizeNodeType(nodeType) || "Unknown node";
  const described = describeNode({
    id: "unknown-node",
    type: nodeType as NodeType,
    position: { x: 0, y: 0 },
    data: data as unknown as NodeData,
  } satisfies WorkflowNode);
  return described !== humanizedType
    ? described
    : `Unsupported node type: ${humanizedType}`;
}

export function resolveNodeDisplay(
  nodeType: string,
  data: Record<string, unknown> = {},
): NodeDisplayMetadata {
  const knownType = knownNodeType(nodeType);
  const definition = knownType ? NODE_DEFINITIONS[knownType] : undefined;
  const label = typeof data.label === "string" && data.label.trim()
    ? data.label.trim()
    : definition?.label || humanizeNodeType(nodeType) || "Unknown node";
  const summary = nodeSpecificSummary(data)
    || definition?.description
    || unknownNodeSummary(nodeType, data);

  return {
    label,
    summary,
    icon: knownType ? nodeIcons[knownType] : LayoutTemplate,
    iconColorClass: knownType ? nodeIconColorClass[knownType] : "text-muted-foreground",
    tileFilling: knownType ? isTileFillingIcon(knownType) : false,
  };
}
