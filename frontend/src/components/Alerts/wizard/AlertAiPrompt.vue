<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Loader2, Sparkles } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useChatModelSelection } from "@/composables/useChatModelSelection";
import { useAlertsStore } from "@/stores/alerts";
import type { AlertDraft } from "@/types/alerts";

const emit = defineEmits<{ drafted: [draft: AlertDraft] }>();

const alertsStore = useAlertsStore();
const {
  credentialOptions,
  modelOptions,
  selectedCredentialId,
  selectedModel,
  isReady,
  modelPlaceholder,
  bootstrap,
  selectCredential,
} = useChatModelSelection();

const prompt = ref("");
const loading = ref(false);
const clarification = ref<string | null>(null);
const error = ref<string | null>(null);

const navigatorPlatformIsMac = computed((): boolean => {
  if (typeof navigator === "undefined") {
    return false;
  }
  return (
    navigator.platform.toLowerCase().startsWith("mac") ||
    navigator.userAgent.includes("Mac")
  );
});

onMounted(bootstrap);

async function submit(): Promise<void> {
  if (!prompt.value.trim() || !selectedCredentialId.value || !selectedModel.value) return;
  loading.value = true;
  clarification.value = null;
  error.value = null;
  try {
    const response = await alertsStore.draftFromPrompt({
      prompt: prompt.value.trim(),
      credential_id: selectedCredentialId.value,
      model: selectedModel.value,
    });
    if (response.draft) {
      // A draft can be partial. Hand it over anyway and let the wizard open on the
      // first step that still needs input; the wizard derives its own note from
      // what is actually still empty, so answering a gap clears it.
      emit("drafted", response.draft);
      prompt.value = "";
    } else {
      // Nothing usable came back, so stay here and show the model's question.
      clarification.value = response.clarification ?? "Could not build an alert from that.";
    }
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : "AI drafting failed";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="rounded-lg border border-dashed border-primary/40 bg-primary/5 p-4">
    <div class="mb-2 flex items-center gap-2 text-sm font-medium">
      <Sparkles class="h-4 w-4 text-primary" />
      Describe what you want to be told about
    </div>

    <Textarea
      v-model="prompt"
      :rows="2"
      placeholder="Warn me if the invoice sync fails more than 5 times in 10 minutes"
      :disabled="loading"
      @keydown.enter.ctrl.exact.prevent="submit"
      @keydown.enter.meta.exact.prevent="submit"
    />

    <div class="mt-2 flex flex-wrap items-center gap-2">
      <!-- SearchableSelect's root is w-full, so each one needs a wrapper to size
           against. The wrapper takes its width from the component's own sizing
           span, which is what keeps a long model name from being clipped. -->
      <div class="max-w-full shrink-0">
        <SearchableSelect
          :model-value="selectedCredentialId ?? undefined"
          :options="credentialOptions"
          placeholder="Credential"
          search-placeholder="Search credentials..."
          empty-text="No credentials found"
          @update:model-value="selectCredential"
        />
      </div>
      <div class="max-w-full shrink-0">
        <SearchableSelect
          v-model="selectedModel"
          :options="modelOptions"
          :placeholder="modelPlaceholder"
          search-placeholder="Search models..."
          empty-text="No models found"
        />
      </div>
      <Button
        type="button"
        size="sm"
        class="ml-auto"
        :disabled="!prompt.trim() || !isReady || loading"
        :title="navigatorPlatformIsMac ? 'Fill the form (⌘Enter)' : 'Fill the form (Ctrl+Enter)'"
        @click="submit"
      >
        <Loader2
          v-if="loading"
          class="mr-1 h-3.5 w-3.5 animate-spin"
        />
        Fill the form
        <span class="text-[11px] font-normal tracking-wide text-primary-foreground/80">
          {{ navigatorPlatformIsMac ? "⌘↵" : "⌃↵" }}
        </span>
      </Button>
    </div>

    <p
      v-if="clarification"
      class="mt-2 text-xs text-amber-700 dark:text-amber-400"
    >
      {{ clarification }}
    </p>
    <p
      v-if="error"
      class="mt-2 text-xs text-destructive"
    >
      {{ error }}
    </p>
  </div>
</template>
