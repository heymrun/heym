import { describe, expect, it } from "vitest";

import type { CredentialListItem } from "@/types/credential";

import { buildRerankerCredentialOptions, rerankerUsesDecisionModel } from "./ragReranker";

function credential(id: string, type: "cohere" | "decision", isShared = false): CredentialListItem {
  return {
    id,
    name: id.toUpperCase(),
    type,
    masked_value: null,
    header_key: null,
    created_at: "2026-11-10T00:00:00Z",
    is_shared: isShared,
  };
}

const cohere = [credential("co", "cohere")];
const decision = [credential("dm", "decision"), credential("dm2", "decision", true)];

describe("buildRerankerCredentialOptions", () => {
  it("lists both providers, each labelled", () => {
    expect(buildRerankerCredentialOptions(cohere, decision, undefined)).toEqual([
      { value: "", label: "Select reranker credential..." },
      { value: "co", label: "CO (Cohere)" },
      { value: "dm", label: "DM (Decision Model)" },
      { value: "dm2", label: "DM2 (Decision Model) - shared" },
    ]);
  });

  it("keeps a selected credential it cannot list", () => {
    const options = buildRerankerCredentialOptions(cohere, decision, "owner-only");

    expect(options.at(-1)).toEqual({
      value: "owner-only",
      label: "Shared reranker credential (from owner)",
    });
  });
});

describe("rerankerUsesDecisionModel", () => {
  it("follows the selected credential's type", () => {
    expect(rerankerUsesDecisionModel(cohere, decision, "dm", undefined)).toBe(true);
    expect(rerankerUsesDecisionModel(cohere, decision, "co", "jev-latest")).toBe(false);
    expect(rerankerUsesDecisionModel(cohere, decision, undefined, "jev-latest")).toBe(false);
  });

  it("lets a stored model decide for a credential shared from the owner", () => {
    expect(rerankerUsesDecisionModel(cohere, decision, "owner-only", "jev-latest")).toBe(true);
    expect(rerankerUsesDecisionModel(cohere, decision, "owner-only", " ")).toBe(false);
  });
});
