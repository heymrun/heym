<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { HitlFilter, HitlSource } from "@/types/dashboard";
import {
  STEP_FIELD_LABEL,
  chooseStep,
  chooseWorkflow,
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

const sources = ref<HitlSource[]>([]);
const loading = ref(true);
const loadError = ref<string | null>(null);

const workflowOptions = computed(() => workflowChoices(sources.value, props.modelValue));
const stepOptions = computed(() => stepChoices(sources.value, props.modelValue));

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
    <Select
      data-testid="hitl-filter-workflow"
      :model-value="workflowValue(modelValue)"
      :options="workflowOptions"
      placeholder=""
      :disabled="loading"
      @update:model-value="onWorkflow"
    />
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
      Show reviews from every workflow, or only one. Only workflows whose reviews you can see are
      listed.
    </p>
  </div>
</template>
