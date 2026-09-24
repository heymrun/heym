<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { CredentialListItem, CredentialType } from "@/types/credential";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { credentialsApi } from "@/services/api";

interface Props {
  credentialId: string;
  model: string;
}

interface JudgeCredentialOption {
  value: string;
  label: string;
  disabled?: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "update:credentialId", value: string): void;
  (e: "update:model", value: string): void;
}>();

// A judge writes its verdict (a model) or computes it (a decision model). A Model Router
// is left out: a judge that changes per request cannot be compared across runs.
const JUDGE_TYPE_LABELS: Partial<Record<CredentialType, string>> = {
  openai: "OpenAI",
  custom: "OpenAI compatible",
  google: "Gemini",
  decision: "Decision Model",
};

const MODEL_PLACEHOLDERS: Partial<Record<CredentialType, string>> = {
  openai: "gpt-4o-mini",
  custom: "Model name",
  google: "gemini-2.5-flash",
  decision: "jev-latest",
};

const judgeCredentials = ref<CredentialListItem[]>([]);
const loaded = ref(false);

const selectedCredential = computed((): CredentialListItem | undefined =>
  judgeCredentials.value.find((credential) => credential.id === props.credentialId),
);

const credentialOptions = computed((): JudgeCredentialOption[] => {
  const options: JudgeCredentialOption[] = judgeCredentials.value.map((credential) => {
    const label = `${credential.name} · ${JUDGE_TYPE_LABELS[credential.type] ?? credential.type}`;
    return { value: credential.id, label: credential.is_shared ? `${label} - shared` : label };
  });
  // A past run can name a judge that was deleted or unshared since; keep it visible.
  if (loaded.value && props.credentialId && !selectedCredential.value) {
    options.push({ value: props.credentialId, label: "Unavailable credential", disabled: true });
  }
  return options;
});

const credentialHint = computed((): string =>
  loaded.value && judgeCredentials.value.length === 0
    ? "Add an OpenAI, OpenAI compatible, Gemini or Decision Model credential to score with an independent judge."
    : "A separate model or decision model scores every answer against the expected output.",
);

const modelPlaceholder = computed(
  (): string =>
    (selectedCredential.value && MODEL_PLACEHOLDERS[selectedCredential.value.type]) ||
    "Model name",
);

const missingModel = computed((): boolean => !!props.credentialId && !props.model.trim());

onMounted(async () => {
  try {
    const [llm, decision] = await Promise.all([
      credentialsApi.listLLM(),
      credentialsApi.listDecision(),
    ]);
    judgeCredentials.value = [...llm, ...decision].filter(
      (credential) => credential.type in JUDGE_TYPE_LABELS,
    );
  } catch {
    judgeCredentials.value = [];
  } finally {
    loaded.value = true;
  }
});
</script>

<template>
  <div>
    <Label class="text-xs font-medium text-muted-foreground mb-2 block">
      Judge Credential (optional)
    </Label>
    <Select
      :model-value="credentialId"
      :options="credentialOptions"
      placeholder="None: each model scores itself"
      clearable
      clear-aria-label="Remove judge"
      data-testid="eval-judge-credential"
      @update:model-value="(value) => emit('update:credentialId', value ?? '')"
    />
    <p class="text-xs text-muted-foreground mt-1">
      {{ credentialHint }}
    </p>
  </div>
  <div>
    <Label class="text-xs font-medium text-muted-foreground mb-2 block">
      Judge Model
    </Label>
    <Input
      :model-value="model"
      :placeholder="modelPlaceholder"
      :disabled="!credentialId"
      :error="missingModel"
      data-testid="eval-judge-model"
      @update:model-value="(value) => emit('update:model', value)"
    />
    <p
      v-if="missingModel"
      class="text-xs text-destructive mt-1"
    >
      Enter the judge model to run with this judge.
    </p>
  </div>
</template>
