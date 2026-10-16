<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useElementSize } from "@vueuse/core";
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
  /**
   * False for a body that is only read: the pointer passes through it, so leaving the
   * trigger closes it and a scroll over it still moves the page underneath.
   */
  interactive?: boolean;
  /**
   * Opens with the pointer at the middle of its lower edge instead of centred on the
   * trigger, for a trigger long enough that its centre can be far from the pointer.
   * The arrow stays centred on the body, since the stock one would point at the
   * trigger's centre instead.
   */
  followPointer?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  side: "bottom",
  disabled: false,
  contentClass: "",
  interactive: true,
  followPointer: false,
});

const open = ref(false);

// Where the pointer is along the trigger. The body is aligned by its left edge, so it
// starts half its own width to the left of that, which puts the pointer at its middle.
const pointerOffset = ref(0);
// The body is measured through a wrapper of our own: it exists exactly while the body
// does, and its parent is the bordered, padded body. The component's own element is a
// comment while closed, and is not reactive.
const bodyRef = ref<HTMLElement | null>(null);
// Border box: the body's padding and border are part of the width it is centred by.
const { width: contentWidth } = useElementSize(
  computed(() => bodyRef.value?.parentElement ?? null),
  { width: 0, height: 0 },
  { box: "border-box" },
);
const alignOffset = computed(() =>
  props.followPointer ? pointerOffset.value - contentWidth.value / 2 : 0,
);

function trackPointer(event: PointerEvent): void {
  if (!props.followPointer || !(event.currentTarget instanceof HTMLElement)) return;
  pointerOffset.value = event.clientX - event.currentTarget.getBoundingClientRect().left;
}

// A tooltip left floating while the page moves under it points at nothing. The wheel
// is listened to as well as the scroll: with the pointer over the body, the wheel
// would otherwise never reach the scroller that holds the trigger.
const DISMISS_EVENTS = ["wheel", "scroll", "touchmove"] as const;
const DISMISS_OPTIONS = { capture: true, passive: true } as const;

function dismiss(): void {
  open.value = false;
}

function stopListening(): void {
  for (const name of DISMISS_EVENTS) window.removeEventListener(name, dismiss, DISMISS_OPTIONS);
}

watch(open, (isOpen) => {
  stopListening();
  if (!isOpen) return;
  for (const name of DISMISS_EVENTS) window.addEventListener(name, dismiss, DISMISS_OPTIONS);
});

onBeforeUnmount(stopListening);
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <TooltipRoot
      v-model:open="open"
      :disable-hoverable-content="!interactive"
    >
      <TooltipTrigger
        as-child
        @pointermove="trackPointer"
      >
        <slot />
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent
          v-if="!disabled && label"
          :side="side"
          :side-offset="6"
          :align="followPointer ? 'start' : 'center'"
          :align-offset="alignOffset"
          :class="cn('z-[200] select-none rounded-md border border-border/60 bg-popover px-2 py-1 text-xs font-medium text-popover-foreground shadow-md', !interactive && 'pointer-events-none', followPointer && 'relative', contentClass)"
        >
          <div
            ref="bodyRef"
            class="contents"
          >
            <slot name="content">
              {{ label }}
            </slot>
          </div>
          <TooltipArrow
            v-if="!followPointer"
            class="fill-popover"
          />
          <span
            v-else-if="side === 'top' || side === 'bottom'"
            class="absolute left-1/2 h-2.5 w-2.5 -translate-x-1/2 rotate-45 bg-popover"
            :class="side === 'top' ? '-bottom-[6px] border-b border-r border-border/60' : '-top-[6px] border-l border-t border-border/60'"
            data-testid="tooltip-centered-arrow"
          />
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>
