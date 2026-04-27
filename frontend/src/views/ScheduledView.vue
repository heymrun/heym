<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

import { ChevronLeft, ChevronRight } from "lucide-vue-next";

import CalendarGrid from "@/components/Calendar/CalendarGrid.vue";
import { getScheduleEvents } from "@/services/schedules";
import type { CalendarView, ScheduleEvent } from "@/types/schedule";

const view = ref<CalendarView>("week");
const currentDate = ref<Date>(new Date());
const events = ref<ScheduleEvent[]>([]);
const loading = ref(false);
const includeShared = ref(true);

function getViewLabel(): string {
  const d = currentDate.value;
  if (view.value === "day") {
    return d.toLocaleDateString([], {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }
  if (view.value === "week") {
    const monday = new Date(d);
    monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    return `${monday.toLocaleDateString([], { month: "short", day: "numeric" })} – ${sunday.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`;
  }
  return d.toLocaleDateString([], { month: "long", year: "numeric" });
}

function getRange(): { start: Date; end: Date } {
  const d = new Date(currentDate.value);
  if (view.value === "day") {
    const start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0);
    const end = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59);
    return { start, end };
  }
  if (view.value === "week") {
    const monday = new Date(d);
    monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    monday.setHours(0, 0, 0, 0);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    sunday.setHours(23, 59, 59, 999);
    return { start: monday, end: sunday };
  }
  const start = new Date(d.getFullYear(), d.getMonth(), 1, 0, 0, 0);
  const end = new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59);
  return { start, end };
}

async function fetchEvents(): Promise<void> {
  loading.value = true;
  try {
    const { start, end } = getRange();
    const res = await getScheduleEvents(start, end, includeShared.value);
    events.value = res.events;
  } catch {
    events.value = [];
  } finally {
    loading.value = false;
  }
}

function navigate(direction: -1 | 1): void {
  const d = new Date(currentDate.value);
  if (view.value === "day") d.setDate(d.getDate() + direction);
  else if (view.value === "week") d.setDate(d.getDate() + direction * 7);
  else d.setMonth(d.getMonth() + direction);
  currentDate.value = d;
}

function goToday(): void {
  currentDate.value = new Date();
}

watch([view, currentDate, includeShared], fetchEvents);
onMounted(fetchEvents);
</script>

<template>
  <div class="flex flex-col h-full gap-3 p-4">
    <!-- Toolbar -->
    <div class="flex items-center justify-between flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <button
          class="rounded p-1 border border-border hover:bg-accent transition-colors"
          @click="navigate(-1)"
        >
          <ChevronLeft class="w-4 h-4" />
        </button>
        <button
          class="rounded px-3 py-1 text-sm border border-border hover:bg-accent transition-colors"
          @click="goToday"
        >
          {{ view === "month" ? "This Month" : view === "week" ? "This Week" : "Today" }}
        </button>
        <button
          class="rounded p-1 border border-border hover:bg-accent transition-colors"
          @click="navigate(1)"
        >
          <ChevronRight class="w-4 h-4" />
        </button>
        <span class="text-sm font-medium ml-2">{{ getViewLabel() }}</span>
      </div>

      <!-- Shared toggle + View switcher -->
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-1.5 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            v-model="includeShared"
            type="checkbox"
            class="rounded border-border accent-violet-600 w-3.5 h-3.5 cursor-pointer"
          >
          Show shared with me
        </label>
        <div class="flex items-center gap-1 border border-border rounded-md p-0.5 text-sm">
          <button
            v-for="v in (['day', 'week', 'month'] as CalendarView[])"
            :key="v"
            class="px-3 py-1 rounded capitalize transition-colors"
            :class="
              view === v ? 'bg-violet-600 text-white' : 'hover:bg-accent text-muted-foreground'
            "
            @click="view = v"
          >
            {{ v }}
          </button>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div
      v-if="loading"
      class="flex-1 flex items-center justify-center text-muted-foreground text-sm"
    >
      Loading schedule...
    </div>

    <!-- Calendar -->
    <div
      v-else
      class="flex-1 overflow-hidden border border-border rounded-md"
    >
      <CalendarGrid
        :view="view"
        :current-date="currentDate"
        :events="events"
      />
    </div>
  </div>
</template>
