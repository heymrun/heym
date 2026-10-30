<script setup lang="ts">
import { computed, useId } from "vue";

import type { GanttTask } from "@/types/dashboard";
import { dependencyPaths, ganttLayout, TASK_HEIGHT } from "@/components/Dashboards/diagramLayout";

const props = defineProps<{ tasks: GanttTask[] }>();
const layout = computed(() => ganttLayout(props.tasks));
const paths = computed(() => dependencyPaths(layout.value.tasks));
const height = computed((): number => Math.max(160, 72 + layout.value.tasks.length * TASK_HEIGHT));
const markerId = `gantt-arrow-${useId().replace(/:/g, "")}`;
</script>

<template>
  <div
    class="h-full w-full overflow-auto"
    tabindex="0"
    aria-label="Gantt chart, scroll to explore tasks"
  >
    <svg
      :viewBox="`0 0 840 ${height}`"
      class="h-auto w-full min-w-[320px] max-w-[840px] text-foreground"
      role="img"
      aria-label="Task schedule with progress and dependencies"
    >
      <defs>
        <marker
          :id="markerId"
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path
            d="M 0 0 L 6 3 L 0 6 Z"
            fill="currentColor"
            class="text-muted-foreground"
          />
        </marker>
      </defs>
      <g
        v-for="tick in layout.ticks"
        :key="tick.x"
      >
        <line
          :x1="tick.x"
          :x2="tick.x"
          y1="40"
          :y2="height - 12"
          stroke="currentColor"
          class="text-border"
        />
        <text
          :x="tick.x"
          y="24"
          text-anchor="middle"
          fill="currentColor"
          class="text-[15px] text-muted-foreground"
        >{{ tick.label }}</text>
      </g>
      <path
        v-for="path in paths"
        :key="path.key"
        :d="path.path"
        fill="none"
        stroke="currentColor"
        class="text-muted-foreground"
        :marker-end="`url(#${markerId})`"
      />
      <g
        v-for="task in layout.tasks"
        :key="task.id"
      >
        <title>{{ task.label }}: {{ task.start }} – {{ task.end }} · {{ task.completion }}% complete{{ task.dependencies?.length ? ` · Depends on: ${task.dependencies.join(', ')}` : '' }}</title>
        <text
          x="8"
          :y="task.y + 16"
          fill="currentColor"
          class="text-base"
        >{{ task.label.length > 17 ? task.label.slice(0, 16) + '…' : task.label }}</text>
        <rect
          :x="task.x"
          :y="task.y"
          :width="task.width"
          height="24"
          rx="4"
          fill="currentColor"
          class="text-primary/25"
        />
        <rect
          :x="task.x"
          :y="task.y"
          :width="task.width * task.completion / 100"
          height="24"
          rx="4"
          fill="currentColor"
          class="text-primary"
        />
        <text
          v-if="task.width > 60"
          :x="task.x + task.width - 6"
          :y="task.y + 17"
          text-anchor="end"
          fill="currentColor"
          class="text-sm"
        >{{ task.completion }}%</text>
      </g>
    </svg>
  </div>
</template>
