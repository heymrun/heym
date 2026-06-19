<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Loader2, Sparkles, X } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import { credentialsApi } from "@/services/api";
import type { CredentialListItem, LLMModel } from "@/types/credential";

const props = withDefaults(
  defineProps<{
    heading?: string;
    placeholder?: string;
    submitLabel?: string;
  }>(),
  {
    heading: "Generate widget with AI",
    placeholder: "e.g. Workflow success rate over the last 30 days as a bar chart",
    submitLabel: "Generate",
  },
);

const emit = defineEmits<{
  (e: "close"): void;
  (e: "generate", payload: { prompt: string; credentialId: string; model: string }): void;
}>();

const prompt = ref("");
const promptInputRef = ref<HTMLTextAreaElement | null>(null);
const credentials = ref<CredentialListItem[]>([]);
const models = ref<LLMModel[]>([]);
const selectedCredentialId = ref("");
const selectedModel = ref("");
const generating = ref(false);
const loadError = ref<string | null>(null);

const credentialOptions = computed(() =>
  credentials.value.map((c) => ({ value: c.id, label: c.name })),
);
const modelOptions = computed(() => models.value.map((m) => ({ value: m.id, label: m.id })));

const canGenerate = computed(
  (): boolean =>
    prompt.value.trim().length > 0 &&
    selectedCredentialId.value.length > 0 &&
    selectedModel.value.length > 0 &&
    !generating.value,
);

async function loadModels(): Promise<void> {
  if (!selectedCredentialId.value) return;
  try {
    models.value = await credentialsApi.getModels(selectedCredentialId.value);
    selectedModel.value = models.value.length > 0 ? models.value[models.value.length - 1].id : "";
  } catch {
    models.value = [];
    selectedModel.value = "";
  }
}

watch(selectedCredentialId, () => {
  void loadModels();
});

function submit(): void {
  if (!canGenerate.value) return;
  generating.value = true;
  emit("generate", {
    prompt: prompt.value.trim(),
    credentialId: selectedCredentialId.value,
    model: selectedModel.value,
  });
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
  }
}

// Capture phase so Escape reaches us before any ancestor keydown handler can
// stopPropagation (several exist in the dashboard view) and swallow the event.
onUnmounted(() => window.removeEventListener("keydown", onKeydown, true));

function focusPromptInput(): void {
  nextTick(() => {
    promptInputRef.value?.focus();
  });
}

onMounted(async () => {
  window.addEventListener("keydown", onKeydown, true);
  focusPromptInput();
  try {
    credentials.value = await credentialsApi.listLLM();
    if (credentials.value.length > 0) {
      selectedCredentialId.value = credentials.value[0].id;
    } else {
      loadError.value = "No LLM credentials found. Add one in the Credentials tab.";
    }
  } catch {
    loadError.value = "Failed to load credentials.";
  }
});
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      @click.self="emit('close')"
    >
      <div class="w-full max-w-lg rounded-lg border bg-card p-5 shadow-lg">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="flex items-center gap-2 text-base font-semibold">
            <Sparkles class="h-4 w-4" /> {{ props.heading }}
          </h2>
          <button
            class="rounded p-1 text-muted-foreground hover:bg-accent"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </button>
        </div>

        <div
          v-if="loadError"
          class="mb-3 rounded border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          {{ loadError }}
        </div>

        <div class="space-y-3">
          <div class="space-y-1">
            <label class="text-sm font-medium">What should this widget show?</label>
            <textarea
              ref="promptInputRef"
              v-model="prompt"
              rows="3"
              class="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              :placeholder="props.placeholder"
            />
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-1">
              <label class="text-sm font-medium">Credential</label>
              <Select
                v-model="selectedCredentialId"
                :options="credentialOptions"
              />
            </div>
            <div class="space-y-1">
              <label class="text-sm font-medium">Model</label>
              <Select
                v-model="selectedModel"
                :options="modelOptions"
              />
            </div>
          </div>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <Button
            variant="ghost"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            :disabled="!canGenerate"
            @click="submit"
          >
            <Loader2
              v-if="generating"
              class="mr-1 h-4 w-4 animate-spin"
            />
            {{ props.submitLabel }}
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
