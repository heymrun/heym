<script setup lang="ts">
import { computed, type Component } from "vue";

import CostFields from "./fields/CostFields.vue";
import DurationFields from "./fields/DurationFields.vue";
import ErrorThresholdFields from "./fields/ErrorThresholdFields.vue";
import ExecutionCountFields from "./fields/ExecutionCountFields.vue";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import type { AlertConfig, AlertType } from "@/types/alerts";

interface Props {
  alertType: AlertType;
  config: AlertConfig;
}

const props = defineProps<Props>();
const emit = defineEmits<{ "update:config": [value: AlertConfig] }>();

/**
 * Per-type field components come from a lookup map, not a v-if chain. This is the
 * frontend half of the backend's handler registry: a fifth alert type is one entry
 * here, not another branch to read past.
 */
const FIELD_COMPONENTS: Record<AlertType, Component> = {
  error_threshold: ErrorThresholdFields,
  workflow_duration: DurationFields,
  token_cost: CostFields,
  execution_count: ExecutionCountFields,
};

const WINDOW_UNITS = [
  { value: "minutes", label: "minutes" },
  { value: "hours", label: "hours" },
  { value: "days", label: "days" },
];

const fieldComponent = computed((): Component => FIELD_COMPONENTS[props.alertType]);

const windowUnit = computed((): string => {
  const minutes = props.config.window_minutes;
  if (minutes % 1440 === 0 && minutes >= 1440) return "days";
  if (minutes % 60 === 0 && minutes >= 60) return "hours";
  return "minutes";
});

const windowValue = computed({
  get: (): number => {
    const minutes = props.config.window_minutes;
    if (windowUnit.value === "days") return minutes / 1440;
    if (windowUnit.value === "hours") return minutes / 60;
    return minutes;
  },
  set: (value: number): void => {
    emit("update:config", {
      ...props.config,
      window_minutes: toMinutes(Number(value) || 1, windowUnit.value),
    });
  },
});

const selectedUnit = computed({
  get: (): string => windowUnit.value,
  set: (unit: string | undefined): void => {
    emit("update:config", {
      ...props.config,
      window_minutes: toMinutes(windowValue.value, unit ?? "minutes"),
    });
  },
});

function toMinutes(value: number, unit: string): number {
  const multiplier = unit === "days" ? 1440 : unit === "hours" ? 60 : 1;
  return Math.min(10080, Math.max(1, Math.round(value * multiplier)));
}

function onConfigUpdate(value: AlertConfig): void {
  emit("update:config", value);
}
</script>

<template>
  <div class="space-y-6">
    <div class="space-y-2">
      <Label for="alert-window-value">Time window</Label>
      <div class="flex gap-2">
        <Input
          id="alert-window-value"
          v-model="windowValue"
          type="number"
          min="1"
          class="flex-1"
        />
        <Select
          v-model="selectedUnit"
          :options="WINDOW_UNITS"
          class="w-36"
        />
      </div>
      <p class="text-xs text-muted-foreground">
        Every alert is judged over a window, never on a single event. One failed run is noise; a
        burst inside a window is an incident.
      </p>
    </div>

    <component
      :is="fieldComponent"
      :model-value="config"
      @update:model-value="onConfigUpdate"
    />
  </div>
</template>
