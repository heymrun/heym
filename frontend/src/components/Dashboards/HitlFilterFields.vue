<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ExternalLink } from "lucide-vue-next";

import type { HitlFilter, HitlSource } from "@/types/dashboard";
import {
  STEP_FIELD_LABEL,
  chooseStep,
  chooseWorkflow,
  openableWorkflowId,
  stepChoices,
  stepValue,
  workflowChoices,
  workflowValue,
} from "@/components/Dashboards/hitlFilter";
import Select from "@/components/ui/Select.vue";
import { responseDetail } from "@/lib/responseDetail";
import { hitlApi } from "@/services/api";

const props = defineProps<{ modelValue: HitlFilter | null }>();

const emit = defineEmits<{
  (e: "update:modelValue", value: HitlFilter | null): void;
}>();

const router = useRouter();
const sources = ref<HitlSource[]>([]);
const loading = ref(true);
const loadError = ref<string | null>(null);

const workflowOptions = computed(() => workflowChoices(sources.value, props.modelValue));
const stepOptions = computed(() => stepChoices(sources.value, props.modelValue));
const workflowHref = computed((): string | null => {
  const id = openableWorkflowId(sources.value, props.modelValue);
  return id ? router.resolve({ name: "editor", params: { id } }).href : null;
});

function onWorkflow(value: string | undefined): void {
  emit("update:modelValue", chooseWorkflow(sources.value, props.modelValue, value));
}

function onStep(value: string | undefined): void {
  if (props.modelValue) emit("update:modelValue", chooseStep(props.modelValue, value));
}

onMounted(async () => {
  try {
    sources.value = await hitlApi.sources();
  } catch (error: unknown) {
    loadError.value = responseDetail(error) ?? "Your workflows could not be loaded.";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div
    class="space-y-2"
    data-testid="hitl-filter-fields"
  >
    <label class="text-sm font-medium">Workflow</label>
    <div class="flex items-center gap-2">
      <Select
        data-testid="hitl-filter-workflow"
        class="flex-1"
        :model-value="workflowValue(modelValue)"
        :options="workflowOptions"
        placeholder=""
        :disabled="loading"
        @update:model-value="onWorkflow"
      />
      <a
        v-if="workflowHref"
        :href="workflowHref"
        target="_blank"
        rel="noopener noreferrer"
        class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border text-muted-foreground hover:bg-accent hover:text-foreground md:h-10 md:w-10"
        title="Open workflow in a new tab"
        aria-label="Open workflow in a new tab"
      >
        <ExternalLink class="h-4 w-4" />
      </a>
    </div>
    <template v-if="stepOptions.length > 0">
      <label class="text-sm font-medium">{{ STEP_FIELD_LABEL }}</label>
      <Select
        data-testid="hitl-filter-step"
        :model-value="stepValue(modelValue)"
        :options="stepOptions"
        placeholder=""
        @update:model-value="onStep"
      />
    </template>
    <p
      v-if="loadError"
      class="text-xs text-destructive"
    >
      {{ loadError }}
    </p>
    <p class="text-xs text-muted-foreground">
      Show reviews from every workflow, or only one. Lists the workflows you can open, yours or
      shared with you, that have a step waiting for a person.
    </p>
  </div>
</template>
