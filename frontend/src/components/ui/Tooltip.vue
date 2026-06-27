<script setup lang="ts">
import {
  TooltipArrow,
  TooltipContent,
  TooltipPortal,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
} from "radix-vue";

interface Props {
  label: string;
  side?: "top" | "bottom" | "left" | "right";
  disabled?: boolean;
}

withDefaults(defineProps<Props>(), {
  side: "bottom",
  disabled: false,
});
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <TooltipRoot>
      <TooltipTrigger as-child>
        <slot />
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent
          v-if="!disabled && label"
          :side="side"
          :side-offset="6"
          class="z-[200] select-none rounded-md border border-border/60 bg-popover px-2 py-1 text-xs font-medium text-popover-foreground shadow-md"
        >
          {{ label }}
          <TooltipArrow class="fill-popover" />
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>
