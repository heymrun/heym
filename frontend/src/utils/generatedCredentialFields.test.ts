import { describe, expect, it } from "vitest";

import type { CredentialListItem } from "@/types/credential";
import type { WorkflowNode } from "@/types/workflow";

import {
  resolveOwnedCredentialId,
  sanitizeGeneratedCredentialFields,
} from "./generatedCredentialFields";

function credential(id: string, name: string, isShared = false): CredentialListItem {
  return {
    id,
    name,
    type: "github",
    masked_value: null,
    header_key: null,
    created_at: "2026-09-23T00:00:00Z",
    is_shared: isShared,
  };
}

const OWNED = credential("11111111-1111-1111-1111-111111111111", "github-work");
const SHARED = credential("22222222-2222-2222-2222-222222222222", "team-github", true);
const CREDENTIALS = [OWNED, SHARED];

function node(type: string, data: Record<string, unknown>): WorkflowNode {
  return {
    id: "n1",
    type,
    position: { x: 0, y: 0 },
    data: { label: "step", ...data },
  } as unknown as WorkflowNode;
}

function field(result: WorkflowNode, key: string): unknown {
  return (result.data as unknown as Record<string, unknown>)[key];
}

function sanitize(n: WorkflowNode, existing?: WorkflowNode): WorkflowNode {
  return sanitizeGeneratedCredentialFields(n, CREDENTIALS, existing);
}

describe("resolveOwnedCredentialId", () => {
  it("accepts an owned id or an exact owned name", () => {
    expect(resolveOwnedCredentialId(OWNED.id, [OWNED])).toBe(OWNED.id);
    expect(resolveOwnedCredentialId(" github-work ", [OWNED])).toBe(OWNED.id);
  });

  it("rejects anything else", () => {
    expect(resolveOwnedCredentialId("YOUR_CREDENTIAL_ID", [OWNED])).toBe("");
    expect(resolveOwnedCredentialId(42, [OWNED])).toBe("");
    expect(resolveOwnedCredentialId("", [OWNED])).toBe("");
  });
});

describe("sanitizeGeneratedCredentialFields", () => {
  it("keeps an owned id and rewrites an owned name", () => {
    expect(field(sanitize(node("github", { credentialId: OWNED.id })), "credentialId")).toBe(OWNED.id);
    expect(field(sanitize(node("github", { credentialId: "github-work" })), "credentialId")).toBe(OWNED.id);
  });

  it("clears shared, unknown and placeholder values", () => {
    for (const value of [SHARED.id, "33333333-3333-3333-3333-333333333333", "YOUR_CREDENTIAL_ID"]) {
      expect(field(sanitize(node("github", { credentialId: value })), "credentialId")).toBe("");
    }
  });

  it("covers secondary credential fields", () => {
    const result = sanitize(node("codex", { credentialId: "", githubCredentialId: "github-work" }));

    expect(field(result, "githubCredentialId")).toBe(OWNED.id);
  });

  it("keeps a value the node already had on the canvas, even a shared one", () => {
    const existing = node("github", { credentialId: SHARED.id });

    expect(field(sanitize(node("github", { credentialId: SHARED.id }), existing), "credentialId")).toBe(SHARED.id);
  });

  it("leaves llm and agent nodes to the model credential logic", () => {
    const llm = node("llm", { credentialId: "YOUR_CREDENTIAL_ID" });

    expect(sanitize(llm)).toBe(llm);
  });
});
