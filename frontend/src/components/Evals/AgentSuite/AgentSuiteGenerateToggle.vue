<script setup lang="ts">
import { Sparkles } from "lucide-vue-next";

interface Props {
  modelValue: boolean;
}

defineProps<Props>();

const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
}>();
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    class="flex min-h-[44px] items-center gap-2 text-sm text-foreground"
    data-testid="agent-suite-generate-toggle"
    @click="emit('update:modelValue', !modelValue)"
  >
    <span
      class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors"
      :class="modelValue ? 'bg-primary' : 'bg-muted'"
    >
      <span
        class="inline-block h-4 w-4 rounded-full bg-background shadow transition-transform"
        :class="modelValue ? 'translate-x-[18px]' : 'translate-x-0.5'"
      />
    </span>
    Generate inputs
    <Sparkles class="h-4 w-4 text-primary dark:text-brand-primary-soft" />
  </button>
</template>
