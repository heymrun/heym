<script setup lang="ts">
import { computed } from "vue";
import { CheckSquare, Clock, Square, Users, Video } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: plain busy intervals · 1: toggle on "Include Busy Event Details" · 2: enriched with title and attendees.
const step = useCycleStep(3, 2400);

interface MockBusySlot {
  time: string;
  title: string;
  attendees: string[];
}

const slots: MockBusySlot[] = [
  {
    time: "09:00 - 10:00",
    title: "Sprint Planning",
    attendees: ["alice@acme.com", "bob@acme.com"],
  },
  {
    time: "14:00 - 15:30",
    title: "Architecture Review",
    attendees: ["lead@acme.com", "dev@acme.com"],
  },
];

const enabled = computed<boolean>(() => step.value >= 1);
const enriched = computed<boolean>(() => step.value === 2);

const caption = computed<string>(
  () =>
    [
      "Google Meet availability returns standard busy intervals",
      "Turn on Include Busy Event Details in node settings",
      "Busy slots include event titles and attendee emails",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 rounded-lg bg-card p-3">
    <div class="flex shrink-0 items-center gap-2 rounded-md border bg-background px-2.5 py-1 text-[11px] leading-4 text-muted-foreground">
      <Video class="h-3 w-3 shrink-0 text-primary" />
      <span class="truncate text-foreground">Google Meet · Availability</span>
      <span
        class="ml-auto flex items-center gap-1 text-[10px] transition-colors duration-500"
        :class="enabled ? 'text-primary' : 'text-muted-foreground'"
      >
        <component
          :is="enabled ? CheckSquare : Square"
          class="h-3 w-3"
        />
        Busy Details
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1.5 overflow-hidden">
      <div
        v-for="slot in slots"
        :key="slot.time"
        class="flex flex-col gap-1 rounded-md border bg-background p-2 transition-all duration-500"
        :class="enriched ? 'border-primary/40 bg-primary/5' : 'border-border'"
      >
        <div class="flex items-center gap-1.5 text-[11px] leading-4">
          <Clock class="h-3 w-3 shrink-0 text-muted-foreground" />
          <span class="font-mono text-[10px] text-muted-foreground">{{ slot.time }}</span>
          <span
            v-if="!enriched"
            class="ml-auto rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
          >
            Busy
          </span>
          <span
            v-else
            class="ml-auto truncate font-medium text-foreground transition-opacity duration-500"
          >
            {{ slot.title }}
          </span>
        </div>

        <div
          class="flex items-center gap-1.5 text-[10px] text-muted-foreground transition-all duration-500"
          :class="enriched ? 'max-h-6 opacity-100' : 'max-h-0 overflow-hidden opacity-0'"
        >
          <Users class="h-3 w-3 shrink-0 text-primary" />
          <span class="truncate">{{ slot.attendees.join(", ") }}</span>
        </div>
      </div>
    </div>

    <p class="shrink-0 truncate text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
