<script setup lang="ts">
import { computed } from "vue";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import type { ExecutionCountConfig } from "@/types/alerts";

interface Props {
  modelValue: ExecutionCountConfig;
}

const props = defineProps<Props>();
const emit = defineEmits<{ "update:modelValue": [value: ExecutionCountConfig] }>();

const thresholdCount = computed({
  get: (): number => props.modelValue.threshold_count,
  set: (value: number): void => {
    emit("update:modelValue", { ...props.modelValue, threshold_count: Number(value) || 1 });
  },
});
</script>

<template>
  <div class="space-y-2">
    <Label for="alert-execution-count">Execution count</Label>
    <Input
      id="alert-execution-count"
      v-model="thresholdCount"
      type="number"
      min="1"
    />
    <p class="text-xs text-muted-foreground">
      Fires when this many runs happen inside the window. Useful for catching a trigger that has
      started firing far more often than it should.
    </p>
  </div>
</template>
