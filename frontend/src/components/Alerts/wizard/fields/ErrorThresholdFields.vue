<script setup lang="ts">
import { computed } from "vue";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import type { ErrorThresholdConfig } from "@/types/alerts";

interface Props {
  modelValue: ErrorThresholdConfig;
}

const props = defineProps<Props>();
const emit = defineEmits<{ "update:modelValue": [value: ErrorThresholdConfig] }>();

const thresholdCount = computed({
  get: (): number => props.modelValue.threshold_count,
  set: (value: number): void => {
    emit("update:modelValue", { ...props.modelValue, threshold_count: Number(value) || 1 });
  },
});
</script>

<template>
  <div class="space-y-2">
    <Label for="alert-threshold-count">Error count</Label>
    <Input
      id="alert-threshold-count"
      v-model="thresholdCount"
      type="number"
      min="1"
    />
    <p class="text-xs text-muted-foreground">
      Fires when this many runs fail inside the window.
    </p>
  </div>
</template>
