<script setup lang="ts">
import { computed } from "vue";
import { CalendarDays, Check, Video } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: Outlook Calendar reads the free time between busy events · 1: a visitor
// picks a free slot · 2: the node creates the invitation with a Teams link.
const step = useCycleStep(3, 2400);

interface MockSlot {
  time: string;
  label: string;
  busy: boolean;
}

const slots: MockSlot[] = [
  { time: "09:00", label: "Team standup", busy: true },
  { time: "10:00", label: "Free", busy: false },
  { time: "11:00", label: "Customer review", busy: true },
  { time: "13:00", label: "Free", busy: false },
  { time: "15:00", label: "Out of office", busy: true },
];
const picked = 3;

const choosing = computed<boolean>(() => step.value >= 1);
const booked = computed<boolean>(() => step.value === 2);

const caption = computed<string>(
  () =>
    [
      "Outlook Calendar reads the free time between your meetings",
      "A visitor picks 13:00 and enters their email",
      "The invitation goes out with a Teams link",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-1.5 rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center gap-1.5 border-b border-border pb-1 text-[10px] leading-4">
      <CalendarDays class="h-3 w-3 text-[hsl(var(--node-outlook))]" />
      <span class="font-medium text-foreground">Tue, Nov 10</span>
      <span class="ml-auto text-muted-foreground">Europe/Berlin</span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
      <div
        v-for="(slot, index) in slots"
        :key="slot.time"
        class="flex shrink-0 items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] leading-4 transition-all duration-500"
        :class="[
          slot.busy
            ? 'border-border bg-muted text-muted-foreground'
            : 'border-dashed border-[hsl(var(--node-outlook)/0.5)] text-foreground',
          choosing && index === picked ? 'border-solid border-[hsl(var(--node-outlook))] bg-[hsl(var(--node-outlook)/0.1)]' : '',
        ]"
      >
        <span class="w-9 shrink-0 text-[10px]">{{ slot.time }}</span>
        <span
          class="min-w-0 flex-1 truncate"
          :class="booked && index === picked ? 'font-medium' : ''"
        >{{ booked && index === picked ? "Intro call · visitor@example.com" : slot.label }}</span>
        <Video
          v-if="booked && index === picked"
          class="h-3 w-3 shrink-0 text-[hsl(var(--node-outlook))]"
        />
      </div>
    </div>

    <div
      class="flex shrink-0 items-center gap-1.5 rounded border border-dashed px-2 py-0.5 text-[11px] leading-4 transition-colors duration-500"
      :class="choosing ? 'border-[hsl(var(--node-outlook)/0.6)] text-foreground' : 'border-border text-muted-foreground'"
    >
      <CalendarDays class="h-3 w-3 shrink-0 text-[hsl(var(--node-outlook))]" />
      <span class="min-w-0 truncate">Outlook Calendar</span>
      <span
        v-if="!booked"
        class="ml-auto shrink-0 text-[10px] text-muted-foreground"
      >{{ choosing ? "Create meeting" : "2 free slots" }}</span>
      <span
        v-else
        class="ml-auto flex shrink-0 items-center gap-1 text-[10px]"
      >
        <Check class="h-3 w-3 text-[hsl(var(--success))]" />
        Teams link ready
      </span>
    </div>
    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
