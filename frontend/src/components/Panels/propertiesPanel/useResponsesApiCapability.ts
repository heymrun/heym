import { computed, type ComputedRef, type Ref } from "vue";

import type { LLMModel } from "@/types/credential";

export type ResponsesCapabilityTone = "positive" | "warning" | "muted";

type ReadonlyRef<T> = Ref<T> | ComputedRef<T>;

interface ResponsesCapabilityInput {
  credentialType: ReadonlyRef<string | null>;
  batchModeEnabled: ReadonlyRef<boolean>;
  outputType: ReadonlyRef<string>;
  selectedModel: ReadonlyRef<LLMModel | null>;
}

export interface ResponsesCapability {
  visible: ComputedRef<boolean>;
  available: ComputedRef<boolean>;
  message: ComputedRef<string | null>;
  tone: ComputedRef<ResponsesCapabilityTone>;
}

const BATCH_CONFLICT_MESSAGE = "The Responses API is not available while Batch mode is on.";
const CUSTOM_CAVEAT_MESSAGE =
  "Your gateway must support the Responses API. If it does not, runs on this node will fail.";
const OPENAI_MESSAGE = "The Responses API is available for this credential.";
const NO_CREDENTIAL_MESSAGE = "Select a credential to check Responses API support.";
const GOOGLE_MESSAGE = "Google credentials do not support the Responses API.";
const MODEL_ROUTER_MESSAGE =
  "Auto Model does not support the Responses API. Pick a specific credential and model to use it.";

export function useResponsesApiCapability(input: ResponsesCapabilityInput): ResponsesCapability {
  const visible = computed((): boolean => input.outputType.value !== "image");

  const modelRejects = computed((): boolean => input.selectedModel.value?.supports_responses === false);

  const available = computed((): boolean => {
    if (!visible.value) return false;
    if (input.batchModeEnabled.value) return false;
    if (!input.credentialType.value) return false;
    if (input.credentialType.value === "google") return false;
    // Checked before the model loads too: a router's only model is the synthetic
    // `auto` row, and the toggle must be off from the moment the router is picked.
    if (input.credentialType.value === "model_router") return false;
    return !modelRejects.value;
  });

  const message = computed((): string | null => {
    if (!visible.value) return null;
    if (input.batchModeEnabled.value) return BATCH_CONFLICT_MESSAGE;
    if (!input.credentialType.value) return NO_CREDENTIAL_MESSAGE;
    if (input.credentialType.value === "google") {
      return input.selectedModel.value?.responses_support_reason ?? GOOGLE_MESSAGE;
    }
    if (input.credentialType.value === "model_router") {
      return input.selectedModel.value?.responses_support_reason ?? MODEL_ROUTER_MESSAGE;
    }
    if (modelRejects.value) {
      return (
        input.selectedModel.value?.responses_support_reason ??
        "This model does not support the Responses API."
      );
    }
    if (input.credentialType.value === "custom") return CUSTOM_CAVEAT_MESSAGE;
    if (input.credentialType.value === "openai") return OPENAI_MESSAGE;
    return null;
  });

  const tone = computed((): ResponsesCapabilityTone => {
    if (!available.value) return "warning";
    if (input.credentialType.value === "custom") return "warning";
    if (input.credentialType.value === "openai") return "positive";
    return "muted";
  });

  return { visible, available, message, tone };
}
