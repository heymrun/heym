import type { CredentialListItem } from "@/types/credential";

export interface RerankerCredentialOption {
  value: string;
  label: string;
}

function optionLabel(credential: CredentialListItem, provider: string): string {
  const shared = credential.is_shared ? " - shared" : "";
  return `${credential.name} (${provider})${shared}`;
}

/** Cohere and Decision Model credentials in one list, each labelled with its provider. */
export function buildRerankerCredentialOptions(
  cohere: CredentialListItem[],
  decision: CredentialListItem[],
  selectedId: string | undefined,
): RerankerCredentialOption[] {
  const options: RerankerCredentialOption[] = [
    { value: "", label: "Select reranker credential..." },
    ...cohere.map((c) => ({ value: c.id, label: optionLabel(c, "Cohere") })),
    ...decision.map((c) => ({ value: c.id, label: optionLabel(c, "Decision Model") })),
  ];
  if (selectedId && !options.some((option) => option.value === selectedId)) {
    options.push({ value: selectedId, label: "Shared reranker credential (from owner)" });
  }
  return options;
}

/**
 * True when the selected credential reranks with a decision model, which needs a model name.
 * A credential shared from the owner is in neither list, so a stored model decides for it.
 */
export function rerankerUsesDecisionModel(
  cohere: CredentialListItem[],
  decision: CredentialListItem[],
  selectedId: string | undefined,
  model: string | undefined,
): boolean {
  if (!selectedId) return false;
  if (decision.some((c) => c.id === selectedId)) return true;
  if (cohere.some((c) => c.id === selectedId)) return false;
  return Boolean(model && model.trim());
}
