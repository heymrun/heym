import { describe, expect, it } from "vitest";
import { ref } from "vue";

import type { LLMModel } from "@/types/credential";

import { useResponsesApiCapability } from "./useResponsesApiCapability";

function model(overrides: Partial<LLMModel> = {}): LLMModel {
  return {
    id: "gpt-5",
    name: "gpt-5",
    is_reasoning: true,
    supports_batch: true,
    supports_responses: true,
    responses_support_reason: "The Responses API is available for this OpenAI credential.",
    ...overrides,
  };
}

function setup(overrides: {
  credentialType?: string | null;
  batchModeEnabled?: boolean;
  outputType?: string;
  selectedModel?: LLMModel | null;
}): ReturnType<typeof useResponsesApiCapability> {
  return useResponsesApiCapability({
    credentialType: ref(
      overrides.credentialType === undefined ? "openai" : overrides.credentialType,
    ),
    batchModeEnabled: ref(overrides.batchModeEnabled ?? false),
    outputType: ref(overrides.outputType ?? "text"),
    selectedModel: ref(
      overrides.selectedModel === undefined ? model() : overrides.selectedModel,
    ),
  });
}

describe("useResponsesApiCapability", () => {
  it("is available for an openai credential", () => {
    const cap = setup({ credentialType: "openai" });
    expect(cap.available.value).toBe(true);
    expect(cap.tone.value).toBe("positive");
  });

  it("warns but stays available for a custom credential", () => {
    const cap = setup({ credentialType: "custom" });
    expect(cap.available.value).toBe(true);
    expect(cap.tone.value).toBe("warning");
    expect(cap.message.value).toContain("gateway");
    expect(cap.message.value).toContain("fail");
  });

  it("is unavailable for a google credential", () => {
    const cap = setup({
      credentialType: "google",
      selectedModel: model({
        supports_responses: false,
        responses_support_reason: "Google credentials do not support the Responses API.",
      }),
    });
    expect(cap.available.value).toBe(false);
    expect(cap.message.value).toContain("Google");
  });

  it("is unavailable while batch mode is on", () => {
    const cap = setup({ batchModeEnabled: true });
    expect(cap.available.value).toBe(false);
    expect(cap.message.value).toContain("Batch mode");
  });

  it("is hidden in image output mode", () => {
    const cap = setup({ outputType: "image" });
    expect(cap.visible.value).toBe(false);
    expect(cap.available.value).toBe(false);
  });

  it("is visible in text output mode", () => {
    const cap = setup({ outputType: "text" });
    expect(cap.visible.value).toBe(true);
  });

  it("asks for a credential before it can judge support", () => {
    const cap = setup({ credentialType: null, selectedModel: null });
    expect(cap.available.value).toBe(false);
    expect(cap.message.value).toContain("credential");
  });

  it("trusts the model flag over the credential type", () => {
    const cap = setup({
      credentialType: "custom",
      selectedModel: model({
        supports_responses: false,
        responses_support_reason: "This model does not support the Responses API.",
      }),
    });
    expect(cap.available.value).toBe(false);
  });
});
