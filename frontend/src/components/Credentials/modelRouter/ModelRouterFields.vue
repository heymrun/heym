<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { CheckCircle2, Info, XCircle } from "lucide-vue-next";

import type { CredentialListItem } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { credentialsApi } from "@/services/api";
import ModelRouterOptionsEditor from "./ModelRouterOptionsEditor.vue";
import type { ModelRouterForm, ModelRouterOptionForm } from "./modelRouterConfig";

const props = defineProps<{ form: ModelRouterForm }>();
const emit = defineEmits<{ "update:form": [value: ModelRouterForm] }>();

const decisionCredentials = ref<CredentialListItem[]>([]);
const llmCredentials = ref<CredentialListItem[]>([]);
const testing = ref(false);
const testSuccess = ref<boolean | null>(null);
const testMessage = ref("");

const decisionOptions = computed((): { value: string; label: string }[] => [
  { value: "", label: "Select decision model credential..." },
  ...decisionCredentials.value.map((credential) => ({
    value: credential.id,
    label: credential.is_shared ? `${credential.name} - shared` : credential.name,
  })),
]);

const canTest = computed(
  (): boolean => !!props.form.decisionCredentialId && !!props.form.decisionModel.trim(),
);

function patch(changes: Partial<ModelRouterForm>): void {
  emit("update:form", { ...props.form, ...changes });
}

function handleOptionsChange(options: ModelRouterOptionForm[]): void {
  patch({ options });
}

async function testDecisionModel(): Promise<void> {
  if (!canTest.value) return;
  testing.value = true;
  testSuccess.value = null;
  testMessage.value = "";
  try {
    const result = await credentialsApi.testConnection({
      type: "decision",
      credential_id: props.form.decisionCredentialId,
      config: { model: props.form.decisionModel.trim() },
    });
    testSuccess.value = result.success;
    testMessage.value = result.message;
  } catch (error) {
    testSuccess.value = false;
    testMessage.value = error instanceof Error ? error.message : "Connection test failed";
  } finally {
    testing.value = false;
  }
}

onMounted(async () => {
  const [decision, llm] = await Promise.all([
    credentialsApi.listDecision(),
    credentialsApi.listLLM(),
  ]);
  decisionCredentials.value = decision;
  // A router cannot route to another router.
  llmCredentials.value = llm.filter((credential) => credential.type !== "model_router");
});
</script>

<template>
  <div class="space-y-4">
    <div class="space-y-2">
      <Label for="router-decision-credential">Decision model credential</Label>
      <Select
        :model-value="form.decisionCredentialId"
        :options="decisionOptions"
        @update:model-value="patch({ decisionCredentialId: String($event ?? '') })"
      />
      <p class="text-xs text-muted-foreground">
        The model that reads each request and picks which of your models answers it.
      </p>
    </div>

    <div class="space-y-2">
      <Label for="router-decision-model">Decision model</Label>
      <div class="flex items-center gap-2">
        <Input
          id="router-decision-model"
          :model-value="form.decisionModel"
          placeholder="jev-latest"
          @update:model-value="patch({ decisionModel: String($event) })"
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          :disabled="!canTest || testing"
          data-testid="model-router-test-decision"
          @click="testDecisionModel"
        >
          {{ testing ? "Testing..." : "Test" }}
        </Button>
      </div>
      <p
        v-if="testMessage"
        class="flex items-start gap-1.5 text-xs"
        :class="testSuccess ? 'text-emerald-600' : 'text-destructive'"
      >
        <CheckCircle2
          v-if="testSuccess"
          class="mt-0.5 h-3.5 w-3.5 shrink-0"
        />
        <XCircle
          v-else
          class="mt-0.5 h-3.5 w-3.5 shrink-0"
        />
        {{ testMessage }}
      </p>
    </div>

    <div class="space-y-2">
      <Label for="router-instructions">Routing instructions</Label>
      <Textarea
        id="router-instructions"
        :model-value="form.routingInstructions"
        :rows="3"
        @update:model-value="patch({ routingInstructions: String($event) })"
      />
      <p class="text-xs text-muted-foreground">
        How to weigh the options overall. Each option's own criteria go below.
      </p>
    </div>

    <ModelRouterOptionsEditor
      :options="form.options"
      :credentials="llmCredentials"
      @update:options="handleOptionsChange"
    />

    <div class="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
      <Info class="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
      <p class="text-xs text-amber-700">
        Sharing this router lets the people you share it with run requests against every
        credential listed above. They cannot read those keys, and the credentials do not
        appear in their own list, but the requests spend them.
      </p>
    </div>
  </div>
</template>
