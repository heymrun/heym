<script setup lang="ts">
import { Zap } from "lucide-vue-next";

interface Props {
  modelValue: boolean;
  disabled?: boolean;
}

withDefaults(defineProps<Props>(), { disabled: false });
const emit = defineEmits<{ (event: "update:modelValue", value: boolean): void }>();

const TOOLTIP =
  "Runs the workflow after each change, reads the result and keeps fixing it until it does what you asked (up to 5 attempts). Can also run your other workflows when needed. Runs are real: emails, messages and API calls are actually sent.";

function onChange(event: Event): void {
  emit("update:modelValue", (event.target as HTMLInputElement).checked);
}
</script>

<template>
  <label
    class="flex w-fit cursor-pointer select-none items-center gap-1.5 text-xs font-medium text-muted-foreground"
    :class="{ 'cursor-not-allowed opacity-60': disabled, 'text-foreground': modelValue }"
    :title="TOOLTIP"
    data-testid="ai-assistant-yolo-toggle"
  >
    <input
      type="checkbox"
      class="h-3.5 w-3.5 rounded border-input bg-background"
      :checked="modelValue"
      :disabled="disabled"
      data-testid="ai-assistant-yolo-checkbox"
      @change="onChange"
    >
    <Zap
      class="h-3.5 w-3.5"
      :class="{ 'text-primary': modelValue }"
    />
    <span>YOLO mode</span>
  </label>
</template>
