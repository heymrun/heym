<script setup lang="ts">
import { onMounted, ref } from "vue";
import axios from "axios";
import { Loader2, Sparkles } from "lucide-vue-next";

import type { DecisionQuestion } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useChatModelSelection } from "@/composables/useChatModelSelection";
import { decisionsApi } from "@/services/api";

const props = defineProps<{
  existingQuestionIds: string[];
  stateSample: string;
}>();

const emit = defineEmits<{
  applied: [payload: { state: string | null; questions: DecisionQuestion[] }];
  close: [];
}>();

const {
  credentialOptions,
  modelOptions,
  selectedCredentialId,
  selectedModel,
  modelPlaceholder,
  bootstrap,
  selectCredential,
} = useChatModelSelection();

const phase = ref<"input" | "review">("input");
const prompt = ref("");
const generating = ref(false);
const error = ref("");
const draftState = ref<string | null>(null);
const draftQuestions = ref<DecisionQuestion[]>([]);

onMounted(() => {
  void bootstrap();
});

async function generate(): Promise<void> {
  if (!prompt.value.trim() || !selectedCredentialId.value || !selectedModel.value) return;
  generating.value = true;
  error.value = "";
  try {
    const result = await decisionsApi.generateQuestions({
      prompt: prompt.value.trim(),
      credential_id: selectedCredentialId.value,
      model: selectedModel.value,
      existing_question_ids: props.existingQuestionIds,
      state_sample: props.stateSample || undefined,
    });
    draftState.value = result.state ?? null;
    draftQuestions.value = result.questions;
    phase.value = "review";
  } catch (err: unknown) {
    // The endpoint puts the real reason in `detail` (bad credential, unusable output).
    const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
    error.value =
      typeof detail === "string" && detail
        ? detail
        : "Couldn't generate questions. Try rephrasing what you want judged.";
  } finally {
    generating.value = false;
  }
}

function apply(): void {
  emit("applied", { state: draftState.value, questions: draftQuestions.value });
}

function describe(question: DecisionQuestion): string {
  if (question.type === "choice") {
    return (question.options ?? []).map((option) => option.key).join(" | ");
  }
  if (question.type === "score") {
    return (question.levels ?? []).join(" -> ");
  }
  return `yes: ${question.criteriaTrue || "-"} / no: ${question.criteriaFalse || "-"}`;
}
</script>

<template>
  <Dialog
    :open="true"
    size="2xl"
    title="Generate Decision Questions"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-4">
      <template v-if="phase === 'input'">
        <div class="space-y-2">
          <Label>What should the model judge?</Label>
          <Textarea
            v-model="prompt"
            :rows="5"
            placeholder="Triage an incoming support ticket: how urgent it is, which team owns it, and how frustrated the customer sounds."
          />
        </div>
        <div class="grid grid-cols-2 gap-2">
          <SearchableSelect
            :model-value="selectedCredentialId"
            :options="credentialOptions"
            placeholder="Select credential..."
            search-placeholder="Search credentials..."
            empty-text="No LLM credentials found."
            @update:model-value="selectCredential(String($event))"
          />
          <SearchableSelect
            v-model="selectedModel"
            :options="modelOptions"
            :placeholder="modelPlaceholder"
            search-placeholder="Search models..."
            empty-text="No models found."
          />
        </div>
        <p class="text-xs text-muted-foreground">
          An LLM drafts the questions. The decision model answers them when the workflow
          runs, so this picker lists LLM credentials, not decision ones.
        </p>
      </template>

      <template v-else>
        <div
          v-if="draftState"
          class="space-y-1"
        >
          <Label class="text-xs">Suggested state</Label>
          <p class="rounded bg-muted p-2 text-xs">
            {{ draftState }}
          </p>
        </div>
        <div class="space-y-2">
          <Label class="text-xs">
            Questions to add ({{ draftQuestions.length }})
          </Label>
          <div
            v-for="question in draftQuestions"
            :key="question.id"
            class="space-y-1 rounded border border-input p-2 text-xs"
          >
            <div class="flex items-center gap-2">
              <span class="font-medium">{{ question.id }}</span>
              <span class="rounded bg-muted px-1">{{ question.type }}</span>
            </div>
            <p>{{ question.instructions }}</p>
            <p class="text-muted-foreground">
              {{ describe(question) }}
            </p>
          </div>
        </div>
      </template>

      <p
        v-if="error"
        class="text-xs text-destructive"
      >
        {{ error }}
      </p>

      <div class="flex justify-end gap-2">
        <Button
          variant="outline"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          v-if="phase === 'input'"
          :disabled="generating || !prompt.trim() || !selectedCredentialId || !selectedModel"
          @click="generate"
        >
          <Loader2
            v-if="generating"
            class="mr-1 h-3 w-3 animate-spin"
          />
          <Sparkles
            v-else
            class="mr-1 h-3 w-3"
          />
          Generate
        </Button>
        <template v-else>
          <Button
            variant="outline"
            @click="phase = 'input'"
          >
            Back
          </Button>
          <Button
            :disabled="draftQuestions.length === 0"
            @click="apply"
          >
            Add to node
          </Button>
        </template>
      </div>
    </div>
  </Dialog>
</template>
