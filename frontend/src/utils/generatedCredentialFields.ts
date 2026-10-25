import type { CredentialListItem } from "@/types/credential";
import type { NodeData, WorkflowNode } from "@/types/workflow";

// `llm` and `agent` take the model credential the assistant runs on; DebugPanel fills them.
const MODEL_NODE_TYPES = new Set(["llm", "agent"]);

function isCredentialField(key: string): boolean {
  return key === "credentialId" || key.endsWith("CredentialId");
}

/**
 * The id of a credential the user owns or was shared that a generated value names (an id or
 * an exact name), or "". An owned credential wins a name it shares with a shared one.
 */
export function resolveUsableCredentialId(value: unknown, credentials: CredentialListItem[]): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text) return "";
  const match =
    credentials.find((c) => c.id === text) ??
    credentials.find((c) => c.name === text && !c.is_shared) ??
    credentials.find((c) => c.name === text);
  return match?.id ?? "";
}

/**
 * Keep only credentials the user owns or was shared in an AI-generated node's credential
 * fields. A value the node already had on the canvas stays as it is: it was the user's own
 * earlier choice.
 */
export function sanitizeGeneratedCredentialFields(
  node: WorkflowNode,
  credentials: CredentialListItem[],
  existing: WorkflowNode | undefined,
): WorkflowNode {
  if (MODEL_NODE_TYPES.has(node.type)) return node;
  const previous = (existing?.data ?? {}) as unknown as Record<string, unknown>;
  const data = { ...node.data } as unknown as Record<string, unknown>;
  for (const key of Object.keys(data)) {
    if (!isCredentialField(key)) continue;
    if (existing && previous[key] === data[key]) continue;
    data[key] = resolveUsableCredentialId(data[key], credentials);
  }
  return { ...node, data: data as unknown as NodeData };
}
