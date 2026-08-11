<script setup lang="ts">
import { computed } from "vue";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import type { CostMetric, TokenCostConfig } from "@/types/alerts";

interface Props {
  modelValue: TokenCostConfig;
}

const props = defineProps<Props>();
const emit = defineEmits<{ "update:modelValue": [value: TokenCostConfig] }>();

const METRIC_OPTIONS = [
  { value: "usd", label: "US dollars" },
  { value: "total_tokens", label: "Total tokens" },
];

const metric = computed({
  get: (): string => props.modelValue.metric,
  set: (value: string | undefined): void => {
    emit("update:modelValue", { ...props.modelValue, metric: (value ?? "usd") as CostMetric });
  },
});

const threshold = computed({
  get: (): number => props.modelValue.threshold,
  set: (value: number): void => {
    emit("update:modelValue", { ...props.modelValue, threshold: Number(value) || 1 });
  },
});

const unitHint = computed((): string =>
  props.modelValue.metric === "usd"
    ? "Dollar amounts use the same pricing table as the Traces tab, so the two always agree."
    : "Counts prompt plus completion tokens across every LLM call in the window.",
);
</script>

<template>
  <div class="space-y-4">
    <div class="space-y-2">
      <Label for="alert-cost-metric">Measure spend in</Label>
      <Select
        id="alert-cost-metric"
        v-model="metric"
        :options="METRIC_OPTIONS"
      />
    </div>

    <div class="space-y-2">
      <Label for="alert-cost-threshold">Budget for the window</Label>
      <Input
        id="alert-cost-threshold"
        v-model="threshold"
        type="number"
        min="0"
        step="0.01"
      />
      <p class="text-xs text-muted-foreground">
        {{ unitHint }}
      </p>
    </div>
  </div>
</template>
