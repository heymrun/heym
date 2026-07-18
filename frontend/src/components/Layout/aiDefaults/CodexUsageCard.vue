<script setup lang="ts">
import { computed } from "vue";

import type { CodexUsage } from "@/types/credential";

const props = defineProps<{ name: string; usage: CodexUsage | null; loading: boolean }>();

const bars = computed(() => props.usage?.windows ?? []);

function remaining(percent: number): number {
  return Math.max(0, Math.min(100, 100 - percent));
}

function resetText(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const hours = Math.floor(seconds / 3600);
  if (hours >= 24) return `resets in ${Math.floor(hours / 24)}d`;
  if (hours >= 1) return `resets in ${hours}h`;
  return `resets in ${Math.floor(seconds / 60)}m`;
}
</script>

<template>
  <div class="rounded-lg border border-border bg-card/60 p-3 space-y-2">
    <div class="flex items-center justify-between gap-2">
      <span class="text-sm font-medium truncate">{{ props.name }}</span>
      <span
        v-if="props.usage?.plan_type"
        class="text-[10px] rounded px-1.5 py-0.5 bg-muted text-muted-foreground uppercase"
      >
        {{ props.usage.plan_type }}
      </span>
    </div>

    <p
      v-if="props.loading"
      class="text-xs text-muted-foreground"
    >
      Loading usage…
    </p>

    <p
      v-else-if="!props.usage || !props.usage.available"
      class="text-xs text-muted-foreground"
    >
      Usage unavailable.
    </p>

    <template v-else>
      <div
        v-for="w in bars"
        :key="w.key"
        class="space-y-1"
      >
        <div class="flex items-center justify-between text-xs">
          <span>{{ w.label }}</span>
          <span class="text-muted-foreground">
            {{ remaining(w.used_percent).toFixed(0) }}% left
            <template v-if="resetText(w.reset_after_seconds)">
              · {{ resetText(w.reset_after_seconds) }}
            </template>
          </span>
        </div>
        <div class="h-2 w-full rounded-full bg-muted overflow-hidden">
          <div
            class="h-full rounded-full bg-primary transition-all"
            :style="{ width: `${remaining(w.used_percent)}%` }"
          />
        </div>
      </div>
    </template>
  </div>
</template>
