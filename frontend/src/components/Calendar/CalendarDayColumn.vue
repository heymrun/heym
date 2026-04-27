<script setup lang="ts">
import { computed } from "vue";

import CalendarEventBlock from "./CalendarEventBlock.vue";

import type { ScheduleEvent } from "@/types/schedule";

const props = defineProps<{
  date: Date;
  events: ScheduleEvent[];
  showHourLabels?: boolean;
}>();

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const OVERFLOW_THRESHOLD = 3;

function eventsForHour(hour: number): ScheduleEvent[] {
  return props.events.filter((e) => new Date(e.scheduled_at).getHours() === hour);
}

function formatHour(h: number): string {
  return `${String(h).padStart(2, "0")}:00`;
}

const isToday = computed(() => {
  const now = new Date();
  return (
    props.date.getFullYear() === now.getFullYear() &&
    props.date.getMonth() === now.getMonth() &&
    props.date.getDate() === now.getDate()
  );
});
</script>

<template>
  <div class="flex flex-col min-w-0">
    <!-- Column header -->
    <div
      class="sticky top-0 z-10 text-center py-1 text-xs font-medium border-b border-border bg-background"
      :class="isToday ? 'text-violet-400' : 'text-muted-foreground'"
    >
      <slot name="header">
        {{ date.toLocaleDateString([], { weekday: "short", day: "numeric" }) }}
      </slot>
    </div>
    <!-- Hour rows -->
    <div
      v-for="hour in HOURS"
      :key="hour"
      class="relative flex flex-wrap gap-0.5 border-b border-border/40 min-h-[40px] px-0.5 py-0.5"
    >
      <span
        v-if="showHourLabels"
        class="absolute -left-9 top-1/2 -translate-y-1/2 w-8 text-right text-[10px] text-muted-foreground select-none"
      >
        {{ formatHour(hour) }}
      </span>
      <template v-if="eventsForHour(hour).length <= OVERFLOW_THRESHOLD">
        <CalendarEventBlock
          v-for="event in eventsForHour(hour)"
          :key="event.workflow_id + event.scheduled_at"
          :event="event"
        />
      </template>
      <template v-else>
        <CalendarEventBlock
          v-for="event in eventsForHour(hour).slice(0, OVERFLOW_THRESHOLD)"
          :key="event.workflow_id + event.scheduled_at"
          :event="event"
          compact
        />
        <span class="text-[10px] text-muted-foreground self-center whitespace-nowrap">
          +{{ eventsForHour(hour).length - OVERFLOW_THRESHOLD }} more
        </span>
      </template>
    </div>
  </div>
</template>
