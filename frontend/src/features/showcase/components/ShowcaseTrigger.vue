<script setup lang="ts">
import { ChevronLeft, Compass } from "lucide-vue-next";

import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  teaserVisible: boolean;
  top: string;
}

defineProps<Props>();

const emit = defineEmits<{
  (e: "toggle"): void;
}>();
</script>

<template>
  <div
    class="pointer-events-none fixed right-0 z-50"
    :style="{ top }"
  >
    <button
      type="button"
      :class="cn(
        'showcase-trigger pointer-events-auto relative flex h-44 w-9 -translate-y-1/2 items-center justify-center rounded-l-[16px] border border-r-0 border-sky-500/25 bg-card/94 shadow-xl backdrop-blur-xl transition-transform duration-300 ease-out hover:border-sky-500/40',
        open && 'showcase-trigger--open',
        teaserVisible && 'showcase-trigger--teasing'
      )"
      aria-label="Toggle page showcase"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <div class="showcase-trigger__inner">
        <Compass class="h-3.5 w-3.5 shrink-0 text-sky-500" />
        <div class="showcase-trigger__label">
          Page Guide
        </div>
        <ChevronLeft
          class="showcase-trigger__chevron h-3.5 w-3.5 shrink-0 text-muted-foreground/85 transition-transform duration-300"
          :class="open ? 'showcase-trigger__chevron--open' : ''"
        />
      </div>
    </button>
  </div>
</template>

<style scoped>
.showcase-trigger {
  transform: translate3d(0, -50%, 0);
}

.showcase-trigger--open {
  transform: translate3d(calc(var(--showcase-width) * -1), -50%, 0);
}

.showcase-trigger--teasing {
  animation: showcase-trigger-pulse 2.4s ease-in-out infinite;
}

.showcase-trigger__inner {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  transform: translate(-50%, -50%) rotate(-90deg);
}

.showcase-trigger__label {
  white-space: nowrap;
  font-size: 0.72rem;
  font-weight: 650;
  letter-spacing: -0.01em;
  color: hsl(var(--foreground));
}

.showcase-trigger__chevron {
  transform: rotate(90deg);
}

.showcase-trigger__chevron--open {
  transform: rotate(270deg);
}

@keyframes showcase-trigger-pulse {
  0%,
  100% {
    box-shadow: 0 10px 26px hsl(var(--primary) / 0.14);
  }
  50% {
    box-shadow: 0 12px 34px hsl(199 89% 48% / 0.22);
  }
}

@media (prefers-reduced-motion: reduce) {
  .showcase-trigger,
  .showcase-trigger__chevron {
    transition: none !important;
    animation: none !important;
  }
}
</style>
