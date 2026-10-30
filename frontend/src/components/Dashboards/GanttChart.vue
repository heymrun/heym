<script setup lang="ts">
import { computed, useId } from "vue";

import type { GanttTask } from "@/types/dashboard";
import { dependencyPaths, ganttLayout } from "@/components/Dashboards/diagramLayout";
import { useDiagramViewport } from "@/components/Dashboards/useDiagramViewport";

const props = defineProps<{ tasks: GanttTask[] }>();
const { container, size } = useDiagramViewport();
const layout = computed(() => ganttLayout(props.tasks, size.value));
const paths = computed(() => dependencyPaths(layout.value.tasks));
const markerId = `gantt-arrow-${useId().replace(/:/g, "")}`;
</script>

<template>
  <div
    ref="container"
    class="h-full min-h-0 w-full min-w-0 overflow-auto"
    tabindex="0"
    aria-label="Gantt chart, scroll to explore tasks"
  >
    <svg
      :viewBox="`0 0 ${layout.width} ${layout.height}`"
      :width="layout.width"
      :height="layout.height"
      class="block text-foreground"
      role="img"
      aria-label="Task schedule with progress and dependencies"
    >
      <defs>
        <marker
          :id="markerId"
          markerWidth="6"
          markerHeight="6"
          refX="6"
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
          :y1="layout.gridTop"
          :y2="layout.gridBottom"
          stroke="currentColor"
          class="text-border"
        />
        <text
          :x="tick.x"
          :y="layout.axisY"
          text-anchor="middle"
          fill="currentColor"
          class="text-[11px] text-muted-foreground"
        >{{ tick.label }}</text>
      </g>
      <g
        v-for="task in layout.tasks"
        :key="task.id"
        data-diagram-task
      >
        <title>{{ task.label }}: {{ task.start }} – {{ task.end }} · {{ task.completion }}% complete{{ task.dependencies?.length ? ` · Depends on: ${task.dependencies.join(', ')}` : '' }}</title>
        <text
          x="8"
          :y="task.y + 16"
          fill="currentColor"
          class="text-xs"
        >{{ task.displayLabel }}</text>
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
          v-if="task.width > 40"
          :x="task.x + task.width - 6"
          :y="task.y + 17"
          text-anchor="end"
          fill="currentColor"
          class="text-[11px]"
          :class="task.completion > 95 ? 'text-primary-foreground' : 'text-foreground'"
        >{{ task.completion }}%</text>
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
    </svg>
  </div>
</template>
