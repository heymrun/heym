<script setup lang="ts">
import { computed, useAttrs } from "vue";

import { cn } from "@/lib/utils";

defineOptions({
  inheritAttrs: false,
});

interface Props {
  modelValue?: string | number;
  type?: string;
  placeholder?: string;
  disabled?: boolean;
  error?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "",
  type: "text",
  placeholder: "",
  disabled: false,
  error: false,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

const attrs = useAttrs();

const classes = computed(() =>
  cn(
    "flex h-11 min-h-[44px] md:h-10 w-full rounded-xl border border-border bg-background px-4 py-2 text-sm",
    "placeholder:text-muted-foreground/60",
    "file:border-0 file:bg-transparent file:text-sm file:font-medium",
    "focus-visible:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/15",
    "hover:border-border/80",
    "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-muted/50",
    "transition-all duration-200",
    "shadow-sm",
    props.error && "border-destructive/50 focus-visible:border-destructive focus-visible:ring-destructive/15",
    attrs.class as string
  )
);

const filteredAttrs = computed(() => {
  const { class: _omit, ...rest } = attrs;
  void _omit;
  return rest;
});

function handleInput(event: Event): void {
  const target = event.target as HTMLInputElement;
  emit("update:modelValue", target.value);
}
</script>

<template>
  <input
    v-bind="filteredAttrs"
    :type="type"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :class="classes"
    @input="handleInput"
  >
</template>
