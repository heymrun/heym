<script setup lang="ts">
import { computed } from "vue";
import { ChevronDown, Lock, Plus, RefreshCw } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: your dashboard · 1: switch between dashboards · 2: share it with a
// teammate · 3: the teammate's read-only view, charts running on the owner's credentials.
const step = useCycleStep(4, 1700);

const bars = [42, 68, 55, 84, 61, 73];

const menuOpen = computed<boolean>(() => step.value === 1);
const shareShown = computed<boolean>(() => step.value === 2);
const viewer = computed<boolean>(() => step.value === 3);
</script>

<template>
  <!-- Fills the tour's fixed frame and draws no border of its own: the frame already
       has one, and a second rounded edge inside it reads as a doubled line. -->
  <div class="relative flex h-full w-full flex-col rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center gap-1.5">
      <span
        class="flex w-28 items-center justify-between rounded border border-border/60 bg-background px-1.5 py-1 text-[10px] leading-none text-foreground"
      >
        Sales KPIs
        <ChevronDown class="h-2.5 w-2.5 text-muted-foreground" />
      </span>
      <Plus class="h-3 w-3 text-muted-foreground" />
      <span
        class="ml-auto truncate rounded px-1.5 py-0.5 text-[10px] leading-none transition-colors duration-500"
        :class="
          viewer
            ? 'bg-muted text-muted-foreground'
            : 'bg-primary/10 text-primary dark:bg-primary/25 dark:text-brand-primary-soft'
        "
      >
        {{ viewer ? "Shared by Alex · Can view" : "Share" }}
      </span>
    </div>

    <div
      class="absolute left-3 top-9 z-10 w-36 rounded-md border border-border/60 bg-card p-1 shadow-md transition-opacity duration-300"
      :class="menuOpen ? 'opacity-100' : 'pointer-events-none opacity-0'"
    >
      <p class="px-1 text-[9px] uppercase leading-4 text-muted-foreground">
        My dashboards
      </p>
      <p class="rounded bg-accent px-1 text-[10px] leading-4 text-foreground">
        Sales KPIs
      </p>
      <p class="px-1 text-[10px] leading-4 text-foreground">
        Ops health
      </p>
      <p class="px-1 text-[9px] uppercase leading-4 text-muted-foreground">
        Shared with me
      </p>
      <p class="px-1 text-[10px] leading-4 text-foreground">
        Growth · Sam
      </p>
    </div>

    <div class="mt-2 grid min-h-0 flex-1 grid-cols-3 gap-1.5">
      <div class="col-span-2 flex items-end gap-1 rounded-md border border-border/40 p-1.5">
        <div
          v-for="(height, index) in bars"
          :key="index"
          class="flex-1 rounded-sm bg-primary/70"
          :style="{ height: `${height}%` }"
        />
      </div>
      <div class="flex flex-col items-center justify-center rounded-md border border-border/40">
        <span class="text-sm font-semibold leading-none text-foreground">1,284</span>
        <span class="mt-1 text-[9px] leading-none text-muted-foreground">runs today</span>
      </div>
    </div>

    <!-- One fixed-height row that swaps content, so nothing above it shifts. -->
    <div class="relative mt-1.5 h-6 shrink-0">
      <div
        class="absolute inset-0 flex items-center gap-2 rounded-md bg-background px-2 transition-opacity duration-500"
        :class="shareShown ? 'opacity-100' : 'opacity-0'"
      >
        <span class="truncate text-[10px] leading-none text-foreground">sam@acme.dev</span>
        <span
          class="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] leading-none text-foreground"
        >
          Read
        </span>
        <span
          class="shrink-0 rounded bg-primary px-1.5 py-0.5 text-[10px] leading-none text-primary-foreground"
        >
          Share
        </span>
      </div>
      <div
        class="absolute inset-0 flex items-center gap-2 px-2 transition-opacity duration-500"
        :class="viewer ? 'opacity-100' : 'opacity-0'"
      >
        <span class="flex items-center gap-1 text-[10px] leading-none text-foreground">
          <RefreshCw class="h-2.5 w-2.5" />
          Refresh
        </span>
        <span class="ml-auto flex items-center gap-1 text-[10px] leading-none text-muted-foreground">
          <Lock class="h-2.5 w-2.5" />
          Runs with the owner's credentials
        </span>
      </div>
    </div>
  </div>
</template>
