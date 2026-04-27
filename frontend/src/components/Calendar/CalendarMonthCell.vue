<script setup lang="ts">
import { computed } from "vue";

import CalendarEventBlock from "./CalendarEventBlock.vue";

import type { ScheduleEvent } from "@/types/schedule";

const props = defineProps<{
  date: Date;
  events: ScheduleEvent[];
  isCurrentMonth: boolean;
}>();

const OVERFLOW_THRESHOLD = 3;

const visible = computed(() => props.events.slice(0, OVERFLOW_THRESHOLD));
const overflowCount = computed(() => Math.max(0, props.events.length - OVERFLOW_THRESHOLD));

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
  <div
    class="flex flex-col gap-0.5 p-1 border border-border/40 min-h-[80px]"
    :class="!isCurrentMonth && 'opacity-40'"
  >
    <span
      class="text-xs font-medium w-5 h-5 flex items-center justify-center rounded-full mb-0.5"
      :class="isToday ? 'bg-violet-500 text-white' : 'text-muted-foreground'"
    >
      {{ date.getDate() }}
    </span>
    <CalendarEventBlock
      v-for="event in visible"
      :key="event.workflow_id + event.scheduled_at"
      :event="event"
      compact
    />
    <span
      v-if="overflowCount > 0"
      class="text-[10px] text-muted-foreground pl-1"
    >
      +{{ overflowCount }} more
    </span>
  </div>
</template>
