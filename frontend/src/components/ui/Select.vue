<script setup lang="ts">
import { computed } from "vue";
import { ChevronDown, X } from "lucide-vue-next";

import { cn } from "@/lib/utils";

interface Option {
  value: string | undefined;
  label: string;
}

interface Props {
  modelValue?: string | undefined;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
  clearable?: boolean;
  clearAriaLabel?: string;
  class?: string;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "",
  placeholder: "Select...",
  disabled: false,
  clearable: false,
  clearAriaLabel: "Clear selection",
  class: undefined,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string | undefined): void;
}>();

const hasValue = computed<boolean>(() => {
  return typeof props.modelValue === "string" && props.modelValue.length > 0;
});

/** Width/layout classes belong on the wrapper so absolute icons align with the visible field. */
const classes = computed(() =>
  cn(
    "flex h-11 min-h-[44px] md:h-10 w-full items-center justify-between rounded-xl border border-border bg-background px-4 py-2 pr-10 text-sm",
    "placeholder:text-muted-foreground/60",
    "focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15",
    "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-muted/50",
    "appearance-none transition-all duration-200",
    "cursor-pointer hover:border-border/80",
    "shadow-sm"
  )
);

const wrapperClass = computed(() =>
  cn("relative group min-w-0 w-full", props.class)
);

function handleChange(event: Event): void {
  const target = event.target as HTMLSelectElement;
  const value = target.value === "" ? undefined : target.value;
  emit("update:modelValue", value);
}

function clearValue(): void {
  emit("update:modelValue", undefined);
}
</script>

<template>
  <div :class="wrapperClass">
    <select
      :value="modelValue"
      :disabled="disabled"
      :class="classes"
      @change="handleChange"
    >
      <option
        v-if="placeholder"
        value=""
        disabled
      >
        {{ placeholder }}
      </option>
      <option
        v-for="option in options"
        :key="option.value ?? 'undefined'"
        :value="option.value ?? ''"
      >
        {{ option.label }}
      </option>
    </select>
    <button
      v-if="clearable && hasValue && !disabled"
      type="button"
      :aria-label="clearAriaLabel"
      class="absolute right-2.5 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground opacity-0 pointer-events-none transition-all hover:bg-muted hover:text-foreground group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto"
      @mousedown.prevent.stop
      @click.prevent.stop="clearValue"
    >
      <X class="h-3.5 w-3.5" />
    </button>
    <ChevronDown
      class="absolute right-3.5 top-3 h-4 w-4 text-muted-foreground pointer-events-none transition-opacity"
      :class="clearable && hasValue ? 'group-hover:opacity-0 group-focus-within:opacity-0' : ''"
    />
  </div>
</template>
