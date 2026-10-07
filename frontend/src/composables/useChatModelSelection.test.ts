import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatModelSelection } from "./useChatModelSelection";
import { credentialsApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import type { CredentialListItem, LLMModel } from "@/types/credential";
import type { User } from "@/types/auth";

// loadModels/loadCredentials resolve preferred defaults via useAiDefaults(),
// which internally reads useAuthStore().user - a REAL Pinia store, same
// convention as useQuickPrompts.test.ts. Set authStore.user directly to
// control the "global preferred credential/model" branch of the resolution
// order; leave it null for tests that don't care about that branch.

function buildUser(overrides: Partial<User> = {}): User {
  return {
    id: "user-1",
    email: "user@example.com",
    name: "Test User",
    is_admin: false,
    user_rules: null,
    tts_credential_id: null,
    tts_voice_id: null,
    preferred_credential_id: null,
    preferred_model: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function buildCredential(overrides: Partial<CredentialListItem> = {}): CredentialListItem {
  return {
    id: "cred-1",
    name: "Test Credential",
    type: "openai",
    masked_value: "sk-***",
    header_key: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function buildModel(overrides: Partial<LLMModel> = {}): LLMModel {
  return {
    id: "model-1",
    name: "Test Model",
    is_reasoning: false,
    supports_batch: false,
    ...overrides,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.spyOn(credentialsApi, "listLLM").mockResolvedValue([]);
  vi.spyOn(credentialsApi, "getModels").mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("loadCredentials", () => {
  it("populates credentials and marks credentialsLoaded on success", async () => {
    const creds = [buildCredential({ id: "cred-1" }), buildCredential({ id: "cred-2" })];
    vi.mocked(credentialsApi.listLLM).mockResolvedValue(creds);

    const { loadCredentials, credentials, credentialsLoaded } = useChatModelSelection();
    await loadCredentials();

    expect(credentials.value).toEqual(creds);
    expect(credentialsLoaded.value).toBe(true);
  });

  it("sets credentialError and leaves credentialsLoaded false on failure", async () => {
    vi.mocked(credentialsApi.listLLM).mockRejectedValue(new Error("network error"));

    const { loadCredentials, credentialError, credentialsLoaded } = useChatModelSelection();
    await loadCredentials();

    expect(credentialError.value).toBe("Failed to load credentials");
    expect(credentialsLoaded.value).toBe(false);
  });
});

describe("loadModels", () => {
  it("does nothing for an empty credential id", async () => {
    const { loadModels, isLoadingModels, models } = useChatModelSelection();
    await loadModels("");

    expect(credentialsApi.getModels).not.toHaveBeenCalled();
    expect(isLoadingModels.value).toBe(false);
    expect(models.value).toEqual([]);
  });

  it("selects the last model in the list when nothing is preferred", async () => {
    const list = [buildModel({ id: "m1" }), buildModel({ id: "m2" }), buildModel({ id: "m3" })];
    vi.mocked(credentialsApi.getModels).mockResolvedValue(list);

    const { loadModels, selectedModel } = useChatModelSelection();
    await loadModels("cred-1");

    expect(selectedModel.value).toBe("m3");
  });

  it("selects the given preferred model id when it exists in the list", async () => {
    const list = [buildModel({ id: "m1" }), buildModel({ id: "m2" }), buildModel({ id: "m3" })];
    vi.mocked(credentialsApi.getModels).mockResolvedValue(list);

    const { loadModels, selectedModel } = useChatModelSelection();
    await loadModels("cred-1", "m2");

    expect(selectedModel.value).toBe("m2");
  });

  it("falls back to the last model when the preferred model id is not in the list", async () => {
    const list = [buildModel({ id: "m1" }), buildModel({ id: "m2" })];
    vi.mocked(credentialsApi.getModels).mockResolvedValue(list);

    const { loadModels, selectedModel } = useChatModelSelection();
    await loadModels("cred-1", "does-not-exist");

    expect(selectedModel.value).toBe("m2");
  });

  it("uses the user's globally preferred model for this credential when nothing else is given", async () => {
    const authStore = useAuthStore();
    authStore.user = buildUser({ preferred_credential_id: "cred-1", preferred_model: "m1" });
    const list = [buildModel({ id: "m1" }), buildModel({ id: "m2" })];
    vi.mocked(credentialsApi.getModels).mockResolvedValue(list);

    const { loadModels, selectedModel } = useChatModelSelection();
    await loadModels("cred-1");

    expect(selectedModel.value).toBe("m1");
  });

  it("leaves selectedModel empty when the model list is empty", async () => {
    vi.mocked(credentialsApi.getModels).mockResolvedValue([]);

    const { loadModels, selectedModel } = useChatModelSelection();
    await loadModels("cred-1");

    expect(selectedModel.value).toBe("");
  });

  it("sets modelsLoadFailed and clears isLoadingModels on failure", async () => {
    vi.mocked(credentialsApi.getModels).mockRejectedValue(new Error("boom"));

    const { loadModels, modelsLoadFailed, isLoadingModels } = useChatModelSelection();
    await loadModels("cred-1");

    expect(modelsLoadFailed.value).toBe(true);
    expect(isLoadingModels.value).toBe(false);
  });

  it("calls onModelsSettled after both success and failure", async () => {
    const onModelsSettled = vi.fn();
    const { loadModels } = useChatModelSelection({ onModelsSettled });

    await loadModels("cred-1");
    expect(onModelsSettled).toHaveBeenCalledTimes(1);

    vi.mocked(credentialsApi.getModels).mockRejectedValue(new Error("boom"));
    await loadModels("cred-2");
    expect(onModelsSettled).toHaveBeenCalledTimes(2);
  });

  it("isLoadingModels is true while the request is pending", async () => {
    let resolveModels!: (models: LLMModel[]) => void;
    vi.mocked(credentialsApi.getModels).mockReturnValue(
      new Promise((resolve) => {
        resolveModels = resolve;
      }),
    );

    const { loadModels, isLoadingModels } = useChatModelSelection();
    const pending = loadModels("cred-1");

    expect(isLoadingModels.value).toBe(true);

    resolveModels([]);
    await pending;

    expect(isLoadingModels.value).toBe(false);
  });
});

describe("applySavedSelection", () => {
  it("does nothing when there are no credentials loaded", async () => {
    const { applySavedSelection, selectedCredentialId } = useChatModelSelection();
    await applySavedSelection({ credentialId: "cred-1" });

    expect(selectedCredentialId.value).toBe("");
    expect(credentialsApi.getModels).not.toHaveBeenCalled();
  });

  it("uses the saved credential id when it is present in the loaded credentials", async () => {
    const { loadCredentials, applySavedSelection, selectedCredentialId } =
      useChatModelSelection();
    vi.mocked(credentialsApi.listLLM).mockResolvedValue([buildCredential({ id: "cred-1" })]);
    vi.mocked(credentialsApi.getModels).mockResolvedValue([buildModel({ id: "m1" })]);
    await loadCredentials();

    await applySavedSelection({ credentialId: "cred-1", model: "m1" });

    expect(selectedCredentialId.value).toBe("cred-1");
    expect(credentialsApi.getModels).toHaveBeenCalledWith("cred-1");
  });

  it("does not override an already-selected credential when the saved one is invalid", async () => {
    const { loadCredentials, selectCredential, applySavedSelection, selectedCredentialId } =
      useChatModelSelection();
    vi.mocked(credentialsApi.listLLM).mockResolvedValue([
      buildCredential({ id: "cred-1" }),
      buildCredential({ id: "cred-2" }),
    ]);
    await loadCredentials();
    await selectCredential("cred-2");

    await applySavedSelection({ credentialId: "does-not-exist" });

    expect(selectedCredentialId.value).toBe("cred-2");
  });

  it("falls back to the resolver's default credential when nothing is saved or selected", async () => {
    const { loadCredentials, applySavedSelection, selectedCredentialId } =
      useChatModelSelection();
    vi.mocked(credentialsApi.listLLM).mockResolvedValue([buildCredential({ id: "cred-1" })]);
    await loadCredentials();

    await applySavedSelection();

    expect(selectedCredentialId.value).toBe("cred-1");
  });
});

describe("selectCredential", () => {
  it("loads models for the newly selected credential", async () => {
    vi.mocked(credentialsApi.getModels).mockResolvedValue([buildModel({ id: "m1" })]);
    const { selectCredential, selectedCredentialId, models } = useChatModelSelection();

    await selectCredential("cred-1");

    expect(selectedCredentialId.value).toBe("cred-1");
    expect(models.value).toEqual([buildModel({ id: "m1" })]);
  });

  it("clears models and selectedModel when given an empty value", async () => {
    vi.mocked(credentialsApi.getModels).mockResolvedValue([buildModel({ id: "m1" })]);
    const { selectCredential, selectedCredentialId, models, selectedModel } =
      useChatModelSelection();
    await selectCredential("cred-1");

    await selectCredential(undefined);

    expect(selectedCredentialId.value).toBe("");
    expect(models.value).toEqual([]);
    expect(selectedModel.value).toBe("");
  });
});

describe("bootstrap", () => {
  it("loads credentials then applies the saved selection", async () => {
    vi.mocked(credentialsApi.listLLM).mockResolvedValue([buildCredential({ id: "cred-1" })]);
    vi.mocked(credentialsApi.getModels).mockResolvedValue([buildModel({ id: "m1" })]);

    const { bootstrap, credentials, selectedCredentialId, selectedModel } =
      useChatModelSelection();
    await bootstrap({ credentialId: "cred-1", model: "m1" });

    expect(credentials.value).toHaveLength(1);
    expect(selectedCredentialId.value).toBe("cred-1");
    expect(selectedModel.value).toBe("m1");
  });
});

describe("computed state", () => {
  it("credentialOptions and modelOptions map to value/label pairs", async () => {
    vi.mocked(credentialsApi.listLLM).mockResolvedValue([
      buildCredential({ id: "cred-1", name: "My OpenAI Key" }),
    ]);
    vi.mocked(credentialsApi.getModels).mockResolvedValue([
      buildModel({ id: "m1", name: "GPT-4o" }),
    ]);
    const { loadCredentials, loadModels, credentialOptions, modelOptions } =
      useChatModelSelection();
    await loadCredentials();
    await loadModels("cred-1");

    expect(credentialOptions.value).toEqual([{ value: "cred-1", label: "My OpenAI Key" }]);
    expect(modelOptions.value).toEqual([{ value: "m1", label: "GPT-4o" }]);
  });

  it("isReady is true only once a credential and model are selected and models didn't fail", async () => {
    vi.mocked(credentialsApi.getModels).mockResolvedValue([buildModel({ id: "m1" })]);
    const { selectCredential, isReady } = useChatModelSelection();

    expect(isReady.value).toBe(false);

    await selectCredential("cred-1");

    expect(isReady.value).toBe(true);
  });

  it("isReady is false when models failed to load even if a credential is selected", async () => {
    vi.mocked(credentialsApi.getModels).mockRejectedValue(new Error("boom"));
    const { selectCredential, isReady } = useChatModelSelection();

    await selectCredential("cred-1");

    expect(isReady.value).toBe(false);
  });

  it("modelPlaceholder reflects loading, failed, and idle states", async () => {
    let resolveModels!: (models: LLMModel[]) => void;
    vi.mocked(credentialsApi.getModels).mockReturnValue(
      new Promise((resolve) => {
        resolveModels = resolve;
      }),
    );
    const { selectCredential, modelPlaceholder } = useChatModelSelection();

    expect(modelPlaceholder.value).toBe("Select...");

    const pending = selectCredential("cred-1");
    expect(modelPlaceholder.value).toBe("Loading...");

    resolveModels([]);
    await pending;
    expect(modelPlaceholder.value).toBe("Select...");

    vi.mocked(credentialsApi.getModels).mockRejectedValue(new Error("boom"));
    await selectCredential("cred-2");
    expect(modelPlaceholder.value).toBe("Failed to load");
  });
});
