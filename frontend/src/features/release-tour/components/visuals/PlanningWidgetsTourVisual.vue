<script setup lang="ts">
import { useCycleStep } from "@/features/release-tour/useCycleStep";

const step = useCycleStep(4, 1500);
</script>

<template>
  <div class="flex h-full flex-col justify-center gap-4 rounded-lg bg-card p-5 text-foreground">
    <div class="text-sm font-semibold">
      {{ step < 2 ? 'Project schedule · Gantt' : 'Database · Entity relationships' }}
    </div>
    <div
      v-if="step < 2"
      class="space-y-4 rounded-lg border border-border p-4"
    >
      <div
        v-for="(label, index) in ['Design', 'Build', 'Launch']"
        :key="label"
        class="flex items-center gap-3 text-xs"
      >
        <span class="w-12">{{ label }}</span>
        <div class="h-5 flex-1 rounded bg-muted">
          <div
            class="h-full rounded bg-primary transition-all duration-700"
            :style="{ marginLeft: `${index * 20}%`, width: `${step === 1 ? 40 : 20}%` }"
          />
        </div>
      </div>
    </div>
    <div
      v-else
      class="flex items-center justify-center gap-2 text-xs"
    >
      <div class="rounded-lg border border-border p-4">
        <div class="mb-3 font-semibold">
          Customers
        </div>
        <div class="text-primary">
          PK · id
        </div>
        <div class="mt-2 text-muted-foreground">
          name · text
        </div>
      </div>
      <div
        class="flex-1 border-t-2 border-primary text-center text-primary transition-opacity duration-700"
        :class="step === 3 ? 'opacity-100' : 'opacity-30'"
      >
        1 : N
      </div>
      <div class="rounded-lg border border-border p-4">
        <div class="mb-3 font-semibold">
          Orders
        </div>
        <div class="text-primary">
          PK · id
        </div>
        <div class="mt-2 text-primary">
          FK · customer_id
        </div>
      </div>
    </div>
    <p class="text-xs text-muted-foreground">
      Describe the view. Preview it in Heym Work, then build it on your page.
    </p>
  </div>
</template>
