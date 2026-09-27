<script setup lang="ts">
import { Info, Zap } from "lucide-vue-next";

import Tooltip from "@/components/ui/Tooltip.vue";

interface Props {
  modelValue: boolean;
  disabled?: boolean;
}

withDefaults(defineProps<Props>(), { disabled: false });
const emit = defineEmits<{ (event: "update:modelValue", value: boolean): void }>();

const EXPLANATION =
  "Runs the workflow after each change, reads the result and keeps fixing it until it does what you asked (up to 5 attempts). Can also run your other workflows when needed. Runs are real: emails, messages and API calls are actually sent.";

function onChange(event: Event): void {
  emit("update:modelValue", (event.target as HTMLInputElement).checked);
}
</script>

<template>
  <div
    class="flex w-fit items-center gap-1.5"
    data-testid="ai-assistant-yolo-toggle"
  >
    <label
      class="flex cursor-pointer select-none items-center gap-1.5 text-xs font-medium text-muted-foreground"
      :class="{ 'cursor-not-allowed opacity-60': disabled, 'text-foreground': modelValue }"
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
    <!-- Outside the label, so clicking the icon does not toggle the box. -->
    <Tooltip
      :label="EXPLANATION"
      side="top"
      content-class="max-w-[18rem] whitespace-normal font-normal leading-snug"
    >
      <button
        type="button"
        class="flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-label="What is YOLO mode?"
        data-testid="ai-assistant-yolo-info"
      >
        <Info class="h-3.5 w-3.5" />
      </button>
    </Tooltip>
  </div>
</template>
