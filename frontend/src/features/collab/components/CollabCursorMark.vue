<script setup lang="ts">
import { computed } from "vue";

import UserAvatar from "@/components/ui/UserAvatar.vue";
import { collabTextColor } from "@/features/collab/colors";

interface Props {
  color: string;
  name: string;
  userId: string;
  /** Time of the latest click; a new value replays the ripple. */
  clickAt?: number | null;
  /** Tooltip or title text under their pointer. */
  hint?: string | null;
}

const props = withDefaults(defineProps<Props>(), { clickAt: null, hint: null });
const textColor = computed<string>(() => collabTextColor(props.color));
</script>

<template>
  <div class="relative flex items-start">
    <span
      v-if="clickAt"
      :key="clickAt"
      class="collab-click pointer-events-none absolute -left-2.5 -top-2.5 h-6 w-6 rounded-full border-2"
      :style="{ borderColor: color, backgroundColor: `${color}33` }"
      data-testid="collab-click"
    />
    <svg
      width="16"
      height="18"
      viewBox="0 0 16 18"
      class="shrink-0"
      aria-hidden="true"
    >
      <path
        d="M1 1 L15 7.5 L8.5 9.5 L6 16.5 Z"
        :fill="color"
        stroke="white"
        stroke-width="1.25"
        stroke-linejoin="round"
      />
    </svg>
    <span
      class="ml-0.5 mt-3 inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full pl-0.5 pr-2 text-[11px] font-medium leading-none shadow"
      :style="{ backgroundColor: color, color: textColor }"
    >
      <UserAvatar
        :user-id="userId"
        :name="name"
        class="h-4 w-4 bg-black/15 text-[9px] font-semibold"
      />
      {{ name }}
    </span>
    <span
      v-if="hint"
      class="absolute left-4 top-9 max-w-[240px] rounded-md border border-border/60 bg-popover px-2 py-1 text-[11px] font-medium leading-snug text-popover-foreground shadow-md"
      data-testid="collab-hint"
    >{{ hint }}</span>
  </div>
</template>

<style scoped>
/* One ring per click, centred on the arrow's tip, gone after half a second. */
.collab-click {
  animation: collab-click 500ms ease-out forwards;
}

@keyframes collab-click {
  from {
    opacity: 0.9;
    transform: scale(0.3);
  }
  to {
    opacity: 0;
    transform: scale(1.6);
  }
}
</style>
