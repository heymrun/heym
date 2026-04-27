<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import type { ScheduleEvent } from "@/types/schedule";

interface EventColor {
  bg: string;
  bgHover: string;
  border: string;
  text: string;
}

const PALETTE: EventColor[] = [
  { bg: "rgba(109,40,217,.55)",  bgHover: "rgba(109,40,217,.75)",  border: "#a78bfa", text: "#ede9fe" }, // violet
  { bg: "rgba(37,99,235,.55)",   bgHover: "rgba(37,99,235,.75)",   border: "#93c5fd", text: "#dbeafe" }, // blue
  { bg: "rgba(6,182,212,.55)",   bgHover: "rgba(6,182,212,.75)",   border: "#67e8f9", text: "#cffafe" }, // cyan
  { bg: "rgba(15,118,110,.55)",  bgHover: "rgba(15,118,110,.75)",  border: "#5eead4", text: "#ccfbf1" }, // teal
  { bg: "rgba(22,163,74,.55)",   bgHover: "rgba(22,163,74,.75)",   border: "#86efac", text: "#dcfce7" }, // green
  { bg: "rgba(217,119,6,.55)",   bgHover: "rgba(217,119,6,.75)",   border: "#fcd34d", text: "#fef3c7" }, // amber
  { bg: "rgba(234,88,12,.55)",   bgHover: "rgba(234,88,12,.75)",   border: "#fdba74", text: "#ffedd5" }, // orange
  { bg: "rgba(225,29,72,.55)",   bgHover: "rgba(225,29,72,.75)",   border: "#fda4af", text: "#ffe4e6" }, // rose
  { bg: "rgba(219,39,119,.55)",  bgHover: "rgba(219,39,119,.75)",  border: "#f9a8d4", text: "#fdf2f8" }, // pink
  { bg: "rgba(79,70,229,.55)",   bgHover: "rgba(79,70,229,.75)",   border: "#a5b4fc", text: "#e0e7ff" }, // indigo
];

function colorForId(id: string): EventColor {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) & 0x7fffffff;
  }
  return PALETTE[h % PALETTE.length];
}

const props = defineProps<{
  event: ScheduleEvent;
  compact?: boolean;
}>();

const router = useRouter();
const mousePos = ref({ x: 0, y: 0 });
const showTooltip = ref(false);
const tooltipBelow = ref(false);
const isHovered = ref(false);

const color = computed(() => colorForId(props.event.workflow_id));

const buttonStyle = computed(() => ({
  backgroundColor: isHovered.value ? color.value.bgHover : color.value.bg,
  borderLeftColor: color.value.border,
  color: color.value.text,
}));

function onMouseEnter(e: MouseEvent): void {
  mousePos.value = { x: e.clientX, y: e.clientY };
  tooltipBelow.value = e.clientY < 120;
  showTooltip.value = true;
  isHovered.value = true;
}

function onMouseMove(e: MouseEvent): void {
  mousePos.value = { x: e.clientX, y: e.clientY };
  tooltipBelow.value = e.clientY < 120;
}

function onMouseLeave(): void {
  showTooltip.value = false;
  isHovered.value = false;
}

function goToCanvas(): void {
  router.push({ name: "editor", params: { id: props.event.workflow_id } });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const tooltipStyle = computed(() => ({
  left: `${mousePos.value.x + 12}px`,
  top: tooltipBelow.value
    ? `${mousePos.value.y + 10}px`
    : `${mousePos.value.y - 10}px`,
  transform: tooltipBelow.value ? "none" : "translateY(-100%)",
}));
</script>

<template>
  <div
    class="flex-1 min-w-0 self-stretch flex flex-col"
    @mouseenter="onMouseEnter"
    @mousemove="onMouseMove"
    @mouseleave="onMouseLeave"
  >
    <button
      class="flex-1 flex items-center text-left rounded px-1.5 py-0.5 border-l-2 transition-colors min-w-0"
      :class="compact ? 'text-[10px]' : 'text-xs'"
      :style="buttonStyle"
      @click="goToCanvas"
    >
      <span class="font-medium truncate">{{ event.workflow_name }}</span>
    </button>
  </div>

  <Teleport to="body">
    <div
      v-if="showTooltip"
      class="fixed z-[9999] pointer-events-none"
      :style="tooltipStyle"
    >
      <div class="bg-popover border border-border rounded shadow-lg px-2 py-1.5 text-xs whitespace-nowrap">
        <p class="font-semibold text-foreground">
          {{ event.description || event.workflow_name }}
        </p>
        <p class="text-muted-foreground font-mono">
          {{ formatTime(event.scheduled_at) }}
        </p>
      </div>
    </div>
  </Teleport>
</template>
