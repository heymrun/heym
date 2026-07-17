<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { GridItem, GridLayout } from "grid-layout-plus";

import DashboardWidgetCard from "@/components/Dashboards/DashboardWidgetCard.vue";
import type { DashboardWidget, WidgetLayout } from "@/types/dashboard";

interface GridLayoutItem extends WidgetLayout {
  i: string;
}

const props = defineProps<{
  widgets: DashboardWidget[];
  editMode: boolean;
  cloningWidgetId: string | null;
}>();

const emit = defineEmits<{
  (e: "edit", workflowId: string): void;
  (e: "delete", widgetId: string): void;
  (e: "clone", widgetId: string): void;
  (e: "refine", widget: DashboardWidget): void;
  (e: "settings", widget: DashboardWidget): void;
  (e: "title-change", payload: { id: string; title: string }): void;
  (e: "layout-change", payload: { id: string; layout: WidgetLayout }): void;
}>();

const layout = ref<GridLayoutItem[]>([]);

watch(
  () => props.widgets,
  (widgets) => {
    layout.value = widgets.map((w) => ({ i: w.id, ...w.layout }));
  },
  { immediate: true, deep: true },
);

const widgetById = computed((): Record<string, DashboardWidget> => {
  return Object.fromEntries(props.widgets.map((w) => [w.id, w]));
});

function emitItemLayout(id: string): void {
  const item = layout.value.find((l) => l.i === id);
  if (!item) return;
  emit("layout-change", { id, layout: { x: item.x, y: item.y, w: item.w, h: item.h } });
}
</script>

<template>
  <GridLayout
    v-model:layout="layout"
    :col-num="12"
    :row-height="60"
    :is-draggable="editMode"
    :is-resizable="editMode"
    :margin="[12, 12]"
    :use-css-transforms="true"
  >
    <GridItem
      v-for="item in layout"
      :key="item.i"
      :x="item.x"
      :y="item.y"
      :w="item.w"
      :h="item.h"
      :i="item.i"
      drag-allow-from=".widget-drag-handle"
      @moved="emitItemLayout(item.i)"
      @resized="emitItemLayout(item.i)"
    >
      <DashboardWidgetCard
        v-if="widgetById[item.i]"
        :widget="widgetById[item.i]"
        :edit-mode="editMode"
        :cloning="cloningWidgetId === item.i"
        :class="editMode ? 'widget-drag-handle cursor-move' : ''"
        @edit="emit('edit', $event)"
        @delete="emit('delete', $event)"
        @clone="emit('clone', $event)"
        @refine="emit('refine', $event)"
        @settings="emit('settings', $event)"
        @title-change="emit('title-change', $event)"
      />
    </GridItem>
  </GridLayout>
</template>
