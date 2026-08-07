import { computed, ref } from "vue";
import type { ComputedRef, Ref } from "vue";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import { useAiDefaults } from "@/composables/useAiDefaults";
import { credentialsApi } from "@/services/api";

export interface ChatSelectOption {
  value: string;
  label: string;
}

export interface SavedChatSelection {
  credentialId?: string | null;
  model?: string | null;
}

export interface UseChatModelSelectionOptions {
  /** Runs after every model load attempt, success or failure. */
  onModelsSettled?: () => void;
}

export interface UseChatModelSelectionResult {
  credentials: Ref<CredentialListItem[]>;
  models: Ref<LLMModel[]>;
  selectedCredentialId: Ref<string>;
  selectedModel: Ref<string>;
  credentialOptions: ComputedRef<ChatSelectOption[]>;
  modelOptions: ComputedRef<ChatSelectOption[]>;
  isLoadingModels: Ref<boolean>;
  modelsLoadFailed: Ref<boolean>;
  credentialError: Ref<string>;
  credentialsLoaded: Ref<boolean>;
  hasCredentials: ComputedRef<boolean>;
  isReady: ComputedRef<boolean>;
  modelPlaceholder: ComputedRef<string>;
  loadCredentials: () => Promise<void>;
  loadModels: (credentialId: string, preferredModelId?: string) => Promise<void>;
  applySavedSelection: (saved?: SavedChatSelection) => Promise<void>;
  selectCredential: (value: string | undefined) => Promise<void>;
  bootstrap: (saved?: SavedChatSelection) => Promise<void>;
}

/**
 * Shared LLM credential and model selection for chat surfaces.
 *
 * Resolution order matches the chat composer: a saved selection wins, then the
 * user's preferred credential and model, then the first credential and the last
 * model in the list.
 */
export function useChatModelSelection(
  options: UseChatModelSelectionOptions = {},
): UseChatModelSelectionResult {
  const aiDefaults = useAiDefaults();

  const credentials = ref<CredentialListItem[]>([]);
  const models = ref<LLMModel[]>([]);
  const selectedCredentialId = ref("");
  const selectedModel = ref("");
  const isLoadingModels = ref(false);
  const modelsLoadFailed = ref(false);
  const credentialError = ref("");
  const credentialsLoaded = ref(false);

  const credentialOptions = computed<ChatSelectOption[]>(() =>
    credentials.value.map((credential) => ({
      value: credential.id,
      label: credential.name,
    })),
  );

  const modelOptions = computed<ChatSelectOption[]>(() =>
    models.value.map((model) => ({
      value: model.id,
      label: model.name,
    })),
  );

  const hasCredentials = computed<boolean>(() => credentials.value.length > 0);

  const isReady = computed<boolean>(
    () =>
      Boolean(selectedCredentialId.value) &&
      Boolean(selectedModel.value) &&
      !modelsLoadFailed.value,
  );

  const modelPlaceholder = computed<string>(() => {
    if (isLoadingModels.value) {
      return "Loading...";
    }
    if (modelsLoadFailed.value) {
      return "Failed to load";
    }
    return "Select...";
  });

  async function loadModels(credentialId: string, preferredModelId?: string): Promise<void> {
    if (!credentialId) return;
    isLoadingModels.value = true;
    modelsLoadFailed.value = false;
    models.value = [];
    selectedModel.value = "";
    try {
      models.value = await credentialsApi.getModels(credentialId);
      if (models.value.length > 0) {
        const match = preferredModelId
          ? models.value.find((model) => model.id === preferredModelId)
          : null;
        const preferredModel = aiDefaults.resolveModel(credentialId, models.value, {
          savedModel: preferredModelId ?? null,
        });
        selectedModel.value =
          preferredModel ?? (match ? match.id : models.value[models.value.length - 1].id);
      }
    } catch {
      modelsLoadFailed.value = true;
    } finally {
      isLoadingModels.value = false;
      options.onModelsSettled?.();
    }
  }

  async function loadCredentials(): Promise<void> {
    try {
      credentials.value = await credentialsApi.listLLM();
      credentialsLoaded.value = true;
    } catch {
      credentialError.value = "Failed to load credentials";
    }
  }

  async function applySavedSelection(saved: SavedChatSelection = {}): Promise<void> {
    if (credentials.value.length === 0) return;
    const savedCredentialId = saved.credentialId ?? null;
    if (savedCredentialId && credentials.value.some((c) => c.id === savedCredentialId)) {
      selectedCredentialId.value = savedCredentialId;
      await loadModels(savedCredentialId, saved.model ?? undefined);
      return;
    }
    if (selectedCredentialId.value) return;
    const resolved = aiDefaults.resolveCredentialId(credentials.value, {});
    if (!resolved) return;
    selectedCredentialId.value = resolved;
    await loadModels(resolved);
  }

  async function selectCredential(value: string | undefined): Promise<void> {
    selectedCredentialId.value = value ?? "";
    if (!selectedCredentialId.value) {
      models.value = [];
      selectedModel.value = "";
      return;
    }
    await loadModels(selectedCredentialId.value);
  }

  async function bootstrap(saved: SavedChatSelection = {}): Promise<void> {
    await loadCredentials();
    await applySavedSelection(saved);
  }

  return {
    credentials,
    models,
    selectedCredentialId,
    selectedModel,
    credentialOptions,
    modelOptions,
    isLoadingModels,
    modelsLoadFailed,
    credentialError,
    credentialsLoaded,
    hasCredentials,
    isReady,
    modelPlaceholder,
    loadCredentials,
    loadModels,
    applySavedSelection,
    selectCredential,
    bootstrap,
  };
}
