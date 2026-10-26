<script setup lang="ts">
import { Minus, Plus } from "lucide-vue-next";

interface Props {
  modelValue: number;
  min?: number;
  max?: number;
}

const props = withDefaults(defineProps<Props>(), { min: 1, max: 20 });

const emit = defineEmits<{
  (e: "update:modelValue", value: number): void;
}>();

function clamp(value: number): number {
  return Math.max(props.min, Math.min(props.max, value));
}

function onInput(event: Event): void {
  const parsed = parseInt((event.target as HTMLInputElement).value, 10);
  if (!Number.isNaN(parsed)) emit("update:modelValue", clamp(parsed));
}

function onBlur(event: Event): void {
  (event.target as HTMLInputElement).value = String(props.modelValue);
}
</script>

<template>
  <div class="inline-flex h-7 items-center rounded-md border border-border bg-background">
    <button
      type="button"
      class="flex h-full w-6 items-center justify-center rounded-l-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
      aria-label="Fewer runs"
      :disabled="modelValue <= min"
      data-testid="agent-suite-run-count-minus"
      @click="emit('update:modelValue', clamp(modelValue - 1))"
    >
      <Minus class="h-3 w-3" />
    </button>
    <input
      :value="modelValue"
      type="text"
      inputmode="numeric"
      aria-label="Runs"
      class="h-full w-7 border-x border-border bg-transparent text-center text-xs tabular-nums text-foreground outline-none"
      data-testid="agent-suite-run-count"
      @input="onInput"
      @blur="onBlur"
    >
    <button
      type="button"
      class="flex h-full w-6 items-center justify-center rounded-r-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
      aria-label="More runs"
      :disabled="modelValue >= max"
      data-testid="agent-suite-run-count-plus"
      @click="emit('update:modelValue', clamp(modelValue + 1))"
    >
      <Plus class="h-3 w-3" />
    </button>
  </div>
</template>
