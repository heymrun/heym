<script setup lang="ts">
import { computed } from "vue";

import CalendarDayColumn from "./CalendarDayColumn.vue";
import CalendarMonthCell from "./CalendarMonthCell.vue";

import type { CalendarView, ScheduleEvent } from "@/types/schedule";

const props = defineProps<{
  view: CalendarView;
  currentDate: Date;
  events: ScheduleEvent[];
}>();

function eventsForDate(date: Date): ScheduleEvent[] {
  return props.events.filter((e) => {
    const d = new Date(e.scheduled_at);
    return (
      d.getFullYear() === date.getFullYear() &&
      d.getMonth() === date.getMonth() &&
      d.getDate() === date.getDate()
    );
  });
}

const dayDates = computed<Date[]>(() => [new Date(props.currentDate)]);

const weekDates = computed<Date[]>(() => {
  const d = new Date(props.currentDate);
  const monday = new Date(d);
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const date = new Date(monday);
    date.setDate(monday.getDate() + i);
    return date;
  });
});

const monthCells = computed<{ date: Date; isCurrentMonth: boolean }[]>(() => {
  const year = props.currentDate.getFullYear();
  const month = props.currentDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const cells: { date: Date; isCurrentMonth: boolean }[] = [];
  for (let i = -startOffset; i < 42 - startOffset; i++) {
    const date = new Date(year, month, 1 + i);
    cells.push({ date, isCurrentMonth: date.getMonth() === month });
  }
  return cells;
});

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
</script>

<template>
  <!-- Day view -->
  <div
    v-if="view === 'day'"
    class="relative pl-10 overflow-y-auto h-full"
  >
    <CalendarDayColumn
      :date="dayDates[0]"
      :events="eventsForDate(dayDates[0])"
      :show-hour-labels="true"
    />
  </div>

  <!-- Week view: hour labels live inside the first column's rows for perfect alignment -->
  <div
    v-else-if="view === 'week'"
    class="relative pl-10 overflow-y-auto h-full"
  >
    <div class="flex h-full">
      <CalendarDayColumn
        v-for="(date, i) in weekDates"
        :key="date.toISOString()"
        :date="date"
        :events="eventsForDate(date)"
        :show-hour-labels="i === 0"
        class="flex-1 min-w-[100px]"
      />
    </div>
  </div>

  <!-- Month view -->
  <div
    v-else
    class="overflow-y-auto h-full"
  >
    <div class="grid grid-cols-7 border-b border-border">
      <div
        v-for="name in DAY_NAMES"
        :key="name"
        class="text-center text-xs font-medium text-muted-foreground py-1"
      >
        {{ name }}
      </div>
    </div>
    <div class="grid grid-cols-7">
      <CalendarMonthCell
        v-for="cell in monthCells"
        :key="cell.date.toISOString()"
        :date="cell.date"
        :events="eventsForDate(cell.date)"
        :is-current-month="cell.isCurrentMonth"
      />
    </div>
  </div>
</template>
