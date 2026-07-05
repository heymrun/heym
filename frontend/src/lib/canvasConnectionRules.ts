import type { NodeType } from "@/types/workflow";
import { NODE_DEFINITIONS } from "@/types/node";

export const INPUT_HANDLE = "input";
export const TOOL_INPUT_HANDLE = "tool-input";
export const TOOL_OUTPUT_HANDLE = "tool-output";
export const SUB_AGENT_INPUT_HANDLE = "sub-agent-input";

export const BLOCKED_AS_TOOL_NODE_TYPES: ReadonlySet<NodeType> = new Set<NodeType>([
  "merge",
  "switch",
  "loop",
  "agent",
  "llm",
  "condition",
  "execute",
  "sticky",
  "errorHandler",
  "cron",
  "textInput",
  "telegramTrigger",
  "websocketTrigger",
  "fileUploadTrigger",
  "slackTrigger",
  "discordTrigger",
  "imapTrigger",
  "mcpCall",
]);

export const NO_REGULAR_INPUT_NODE_TYPES: ReadonlySet<NodeType> = new Set<NodeType>([
  "textInput",
  "cron",
  "sticky",
  "merge",
  "errorHandler",
  "telegramTrigger",
  "websocketTrigger",
  "fileUploadTrigger",
  "slackTrigger",
  "discordTrigger",
  "imapTrigger",
]);

export function isBlockedAsTool(nodeType: NodeType): boolean {
  return BLOCKED_AS_TOOL_NODE_TYPES.has(nodeType);
}

export function isNoRegularInputNodeType(nodeType: NodeType): boolean {
  return NO_REGULAR_INPUT_NODE_TYPES.has(nodeType);
}

export function isTargetOnlyHandleId(handleId: string | null | undefined): boolean {
  return (
    handleId === INPUT_HANDLE ||
    handleId === TOOL_INPUT_HANDLE ||
    handleId === SUB_AGENT_INPUT_HANDLE ||
    !!handleId?.startsWith("input-")
  );
}

export function getToolConnectionValidationMessage(nodeType: NodeType): string | null {
  if (isBlockedAsTool(nodeType)) {
    return "This node type cannot be used as a tool.";
  }

  const nodeDef = NODE_DEFINITIONS[nodeType as keyof typeof NODE_DEFINITIONS];
  if (nodeDef && nodeDef.inputs === 0) {
    return "Trigger nodes cannot be used as tools.";
  }

  return null;
}
