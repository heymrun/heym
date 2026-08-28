<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: three live instances · 1: one goes offline ·
// 2: weights renormalize across the two that are left · 3: it returns.
const step = useCycleStep(4, 1600);

const workerBOffline = computed(() => step.value === 1 || step.value === 2);
const renormalized = computed(() => step.value === 2);

interface MockInstance {
  id: string;
  name: string;
  role: string;
  weight: number;
  live: boolean;
}

const instances = computed<MockInstance[]>(() => [
  {
    id: "main",
    name: "Main",
    role: "main",
    weight: renormalized.value ? 82 : 70,
    live: true,
  },
  {
    id: "worker-a",
    name: "Worker A",
    role: "worker",
    weight: renormalized.value ? 18 : 15,
    live: true,
  },
  {
    id: "worker-b",
    name: "Worker B",
    role: "worker",
    weight: workerBOffline.value ? 0 : 15,
    live: !workerBOffline.value,
  },
]);

const caption = computed<string>(() => {
  if (step.value === 1) return "Worker B stopped heartbeating";
  if (step.value === 2) return "Its share moved to the instances still running";
  return "Background runs split by weight";
});
</script>

<template>
  <div class="w-full rounded-lg border border-border bg-card p-4">
    <div class="mb-3 flex items-center justify-between">
      <span class="text-sm font-medium text-foreground">Settings &middot; Instances</span>
      <span class="text-xs text-muted-foreground">{{ caption }}</span>
    </div>

    <div class="space-y-1.5">
      <div
        v-for="instance in instances"
        :key="instance.id"
        class="flex items-center gap-3 rounded-md border border-border bg-background px-3 py-2 transition-opacity duration-500"
        :class="instance.live ? 'opacity-100' : 'opacity-50'"
      >
        <span
          class="h-2 w-2 shrink-0 rounded-full transition-colors duration-500"
          :class="instance.live ? 'bg-emerald-500' : 'bg-muted-foreground'"
        />
        <span class="w-24 shrink-0 truncate text-sm text-foreground">{{ instance.name }}</span>
        <span class="w-14 shrink-0 text-xs text-muted-foreground">{{ instance.role }}</span>

        <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary transition-all duration-700 ease-out"
            :style="{ width: `${instance.weight}%` }"
          />
        </div>

        <span class="w-10 shrink-0 text-right text-xs tabular-nums text-foreground">
          {{ instance.weight }}%
        </span>
      </div>
    </div>

    <p class="mt-3 text-xs text-muted-foreground">
      Weights are shared across the instances that are live, so a machine going down moves its
      work rather than dropping it.
    </p>
  </div>
</template>
