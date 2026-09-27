<script setup lang="ts">
import {
  TooltipArrow,
  TooltipContent,
  TooltipPortal,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
} from "radix-vue";

import { cn } from "@/lib/utils";

interface Props {
  label: string;
  side?: "top" | "bottom" | "left" | "right";
  disabled?: boolean;
  /** Extra classes for the tooltip body, e.g. a max width so long text wraps. */
  contentClass?: string;
}

withDefaults(defineProps<Props>(), {
  side: "bottom",
  disabled: false,
  contentClass: "",
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
          :class="cn('z-[200] select-none rounded-md border border-border/60 bg-popover px-2 py-1 text-xs font-medium text-popover-foreground shadow-md', contentClass)"
        >
          {{ label }}
          <TooltipArrow class="fill-popover" />
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>
