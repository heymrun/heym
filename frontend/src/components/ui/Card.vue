<script setup lang="ts">
import { cn } from "@/lib/utils";

interface Props {
  class?: string;
  variant?: "default" | "metallic" | "glass" | "interactive" | "flat" | "elevated";
  hover?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  class: undefined,
  variant: "default",
  hover: true,
});

const variantClasses = {
  default: "bg-card border-border card-default-shadow",
  metallic: "bg-card border-border card-default-shadow",
  glass: "glass",
  interactive: "card-interactive",
  flat: "bg-muted/30 border-border/60",
  elevated: "bg-card border-border card-elevated",
};

const hoverClasses = {
  default: "hover:border-primary/25 hover:-translate-y-0.5",
  metallic: "hover:border-primary/25 hover:-translate-y-0.5",
  glass: "hover:border-primary/25 hover:bg-card/75",
  interactive: "",
  flat: "hover:bg-muted/40",
  elevated: "hover:-translate-y-0.5",
};
</script>

<template>
  <div
    :class="
      cn(
        'rounded-2xl border text-card-foreground transition-all duration-300 ease-out',
        variantClasses[variant],
        hover && hoverClasses[variant],
        props.class
      )
    "
  >
    <slot />
  </div>
</template>
