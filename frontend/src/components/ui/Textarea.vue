<script setup lang="ts">
import { computed } from "vue";

import { cn } from "@/lib/utils";

interface Props {
  modelValue?: string;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
}

withDefaults(defineProps<Props>(), {
  modelValue: "",
  placeholder: "",
  disabled: false,
  rows: 3,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

const classes = computed(() =>
  cn(
    "flex min-h-[80px] w-full rounded-xl border border-border bg-background px-4 py-3 text-sm",
    "placeholder:text-muted-foreground/60",
    "focus-visible:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/15",
    "hover:border-border/80",
    "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-muted/50",
    "resize-none transition-all duration-200",
    "shadow-sm scrollbar-thin"
  )
);

function handleInput(event: Event): void {
  const target = event.target as HTMLTextAreaElement;
  emit("update:modelValue", target.value);
}
</script>

<template>
  <textarea
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :rows="rows"
    :class="classes"
    @input="handleInput"
  />
</template>
