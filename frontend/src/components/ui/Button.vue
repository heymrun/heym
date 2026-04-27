<script setup lang="ts">
import { computed } from "vue";

import { cn } from "@/lib/utils";

interface Props {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "gradient" | "success";
  size?: "default" | "sm" | "lg" | "icon";
  disabled?: boolean;
  loading?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  variant: "default",
  size: "default",
  disabled: false,
  loading: false,
});

const emit = defineEmits<{
  (e: "click", event: MouseEvent): void;
}>();

const variantClasses = {
  default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 hover:shadow-md",
  destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90 hover:shadow-md",
  success: "bg-success text-success-foreground shadow-sm hover:bg-success/90 hover:shadow-md",
  outline: "border border-border bg-background shadow-sm hover:bg-accent hover:text-accent-foreground hover:border-primary/40",
  secondary: "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  link: "text-primary underline-offset-4 hover:underline",
  gradient: "btn-gradient text-white font-medium shadow-md",
};

const sizeClasses = {
  default: "h-11 min-h-[44px] md:h-10 px-5 py-2",
  sm: "h-11 min-h-[44px] md:h-9 rounded-xl px-4 text-xs",
  lg: "h-12 min-h-[44px] rounded-xl px-8 text-base",
  icon: "h-11 w-11 min-h-[44px] min-w-[44px] md:h-10 md:w-10",
};

const classes = computed(() =>
  cn(
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium",
    "ring-offset-background transition-all duration-250",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2",
    "disabled:pointer-events-none disabled:opacity-50",
    "active:scale-[0.97]",
    variantClasses[props.variant],
    sizeClasses[props.size]
  )
);

function handleClick(event: MouseEvent): void {
  if (!props.disabled && !props.loading) {
    emit("click", event);
  }
}
</script>

<template>
  <button
    :class="classes"
    :disabled="disabled || loading"
    @click="handleClick"
  >
    <svg
      v-if="loading"
      class="h-4 w-4 animate-spin"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        class="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        stroke-width="4"
      />
      <path
        class="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
    <slot />
  </button>
</template>
