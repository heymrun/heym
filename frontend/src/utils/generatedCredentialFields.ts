import type { CredentialListItem } from "@/types/credential";
import type { NodeData, WorkflowNode } from "@/types/workflow";

// `llm` and `agent` take the model credential the assistant runs on; DebugPanel fills them.
const MODEL_NODE_TYPES = new Set(["llm", "agent"]);

function isCredentialField(key: string): boolean {
  return key === "credentialId" || key.endsWith("CredentialId");
}

/** The owned credential id a generated value names (an id or an exact name), or "". */
export function resolveOwnedCredentialId(value: unknown, owned: CredentialListItem[]): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text) return "";
  const match = owned.find((c) => c.id === text) ?? owned.find((c) => c.name === text);
  return match?.id ?? "";
}

/**
 * Keep only owned credentials in an AI-generated node's credential fields. A value the node
 * already had on the canvas stays as it is: it was the user's own earlier choice.
 */
export function sanitizeGeneratedCredentialFields(
  node: WorkflowNode,
  credentials: CredentialListItem[],
  existing: WorkflowNode | undefined,
): WorkflowNode {
  if (MODEL_NODE_TYPES.has(node.type)) return node;
  const owned = credentials.filter((c) => !c.is_shared);
  const previous = (existing?.data ?? {}) as unknown as Record<string, unknown>;
  const data = { ...node.data } as unknown as Record<string, unknown>;
  for (const key of Object.keys(data)) {
    if (!isCredentialField(key)) continue;
    if (existing && previous[key] === data[key]) continue;
    data[key] = resolveOwnedCredentialId(data[key], owned);
  }
  return { ...node, data: data as unknown as NodeData };
}
