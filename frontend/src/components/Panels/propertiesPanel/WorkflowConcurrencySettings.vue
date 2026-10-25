<script setup lang="ts">
import { Layers } from "lucide-vue-next";

import {
  parsePositiveInteger,
  togglePatch,
} from "@/components/Panels/propertiesPanel/concurrencySettings";
import { useWorkflowConcurrencySettings } from "@/components/Panels/propertiesPanel/useWorkflowConcurrencySettings";

const { limit, maxQueue, maxWaitSeconds, readOnly, save } = useWorkflowConcurrencySettings();

function onToggle(): void {
  void save(togglePatch(limit.value));
}

function onLimit(raw: string): void {
  void save({ concurrency_limit: parsePositiveInteger(raw) ?? 1 });
}

function onMaxQueue(raw: string): void {
  void save({ concurrency_max_queue: parsePositiveInteger(raw) });
}

function onMaxWait(raw: string): void {
  void save({ concurrency_max_wait_seconds: parsePositiveInteger(raw) });
}
</script>

<template>
  <div
    class="border-t border-border/40 pt-4 pb-4"
    data-testid="workflow-concurrency-settings"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2 min-w-0">
        <Layers class="w-4 h-4 text-muted-foreground shrink-0" />
        <span class="text-sm font-medium">Concurrency limit</span>
      </div>
      <button
        type="button"
        role="switch"
        data-testid="workflow-concurrency-toggle"
        :aria-checked="limit !== null"
        :disabled="readOnly"
        class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :class="limit !== null ? 'bg-primary' : 'bg-muted-foreground/30'"
        @click="onToggle"
      >
        <span
          class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
          :class="limit !== null ? 'translate-x-4' : 'translate-x-0.5'"
        />
      </button>
    </div>
    <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
      Production runs (webhooks, cron, MCP, Portal, triggers) above the limit wait in a
      first-in, first-out queue. Editor test runs always start right away.
    </p>

    <div
      v-if="limit !== null"
      class="mt-3 space-y-3"
    >
      <label class="block">
        <span class="text-xs font-medium">Max concurrent runs</span>
        <input
          data-testid="workflow-concurrency-limit"
          type="number"
          min="1"
          step="1"
          class="mt-1 w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="limit"
          :disabled="readOnly"
          @change="onLimit(($event.target as HTMLInputElement).value)"
        >
      </label>
      <label class="block">
        <span class="text-xs font-medium">Max queue size (optional)</span>
        <input
          data-testid="workflow-concurrency-max-queue"
          type="number"
          min="1"
          step="1"
          class="mt-1 w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="maxQueue ?? ''"
          :disabled="readOnly"
          placeholder="Empty = no limit"
          @change="onMaxQueue(($event.target as HTMLInputElement).value)"
        >
      </label>
      <label class="block">
        <span class="text-xs font-medium">Max wait (seconds, optional)</span>
        <input
          data-testid="workflow-concurrency-max-wait"
          type="number"
          min="1"
          step="1"
          class="mt-1 w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="maxWaitSeconds ?? ''"
          :disabled="readOnly"
          placeholder="Empty = wait as long as it takes"
          @change="onMaxWait(($event.target as HTMLInputElement).value)"
        >
      </label>
      <p class="text-xs text-muted-foreground leading-relaxed">
        A full queue answers 429. A run that waits longer than the max wait is
        recorded as expired.
      </p>
    </div>
  </div>
</template>
