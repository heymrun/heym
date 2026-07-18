import { computed } from "vue";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import { useAuthStore } from "@/stores/auth";

export type PreferredStatus = "unset" | "ok" | "invalid";

interface SavedSelection {
  savedCredentialId?: string | null;
  savedModel?: string | null;
}

interface Preferred {
  preferredCredentialId: string | null;
  preferredModel: string | null;
}

export interface AiDefaultsResolver {
  resolveCredentialId(credentials: CredentialListItem[], saved: SavedSelection): string | null;
  resolveModel(credentialId: string, models: LLMModel[], saved: SavedSelection): string | null;
  preferredStatus(credentials: CredentialListItem[]): PreferredStatus;
}

/** Pure resolver — unit-testable without a Pinia instance. */
export function createAiDefaultsResolver(preferred: Preferred): AiDefaultsResolver {
  return {
    resolveCredentialId(credentials, saved) {
      if (saved.savedCredentialId && credentials.some((c) => c.id === saved.savedCredentialId)) {
        return saved.savedCredentialId;
      }
      if (
        preferred.preferredCredentialId &&
        credentials.some((c) => c.id === preferred.preferredCredentialId)
      ) {
        return preferred.preferredCredentialId;
      }
      return credentials.length > 0 ? credentials[0].id : null;
    },
    resolveModel(credentialId, models, saved) {
      if (saved.savedModel && models.some((m) => m.id === saved.savedModel)) {
        return saved.savedModel;
      }
      if (
        credentialId === preferred.preferredCredentialId &&
        preferred.preferredModel &&
        models.some((m) => m.id === preferred.preferredModel)
      ) {
        return preferred.preferredModel;
      }
      return null;
    },
    preferredStatus(credentials) {
      if (!preferred.preferredCredentialId) return "unset";
      return credentials.some((c) => c.id === preferred.preferredCredentialId) ? "ok" : "invalid";
    },
  };
}

/** Store-bound accessor used by components/surfaces. */
export function useAiDefaults(): AiDefaultsResolver {
  const authStore = useAuthStore();
  const preferred = computed<Preferred>(() => ({
    preferredCredentialId: authStore.user?.preferred_credential_id ?? null,
    preferredModel: authStore.user?.preferred_model ?? null,
  }));
  return {
    resolveCredentialId: (credentials, saved) =>
      createAiDefaultsResolver(preferred.value).resolveCredentialId(credentials, saved),
    resolveModel: (credentialId, models, saved) =>
      createAiDefaultsResolver(preferred.value).resolveModel(credentialId, models, saved),
    preferredStatus: (credentials) =>
      createAiDefaultsResolver(preferred.value).preferredStatus(credentials),
  };
}
