<script setup lang="ts">
import { onMounted, ref } from "vue";

const STORAGE_KEY = "evals-panel-widths";
const DEFAULT_LEFT = 300;
const DEFAULT_RIGHT = 380;
const MIN_WIDTH = 180;

const leftWidth = ref(DEFAULT_LEFT);
const rightWidth = ref(DEFAULT_RIGHT);
const isResizingLeft = ref(false);
const isResizingRight = ref(false);

function loadWidths(): void {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as { left?: number; right?: number };
      if (typeof parsed.left === "number" && parsed.left >= MIN_WIDTH) {
        leftWidth.value = parsed.left;
      }
      if (typeof parsed.right === "number" && parsed.right >= MIN_WIDTH) {
        rightWidth.value = parsed.right;
      }
    }
  } catch {
    // ignore
  }
}

function saveWidths(): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ left: leftWidth.value, right: rightWidth.value }),
  );
}

function startResizeLeft(e: MouseEvent): void {
  e.preventDefault();
  isResizingLeft.value = true;
  const startX = e.clientX;
  const startW = leftWidth.value;

  function onMove(ev: MouseEvent): void {
    const delta = ev.clientX - startX;
    const newW = Math.max(MIN_WIDTH, startW + delta);
    leftWidth.value = newW;
  }

  function onUp(): void {
    isResizingLeft.value = false;
    saveWidths();
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  }

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function startResizeRight(e: MouseEvent): void {
  e.preventDefault();
  isResizingRight.value = true;
  const startX = e.clientX;
  const startW = rightWidth.value;

  function onMove(ev: MouseEvent): void {
    const delta = startX - ev.clientX;
    const newW = Math.max(MIN_WIDTH, startW + delta);
    rightWidth.value = newW;
  }

  function onUp(): void {
    isResizingRight.value = false;
    saveWidths();
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  }

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

onMounted(loadWidths);
</script>

<template>
  <!-- Mobile: flex-col + overflow-y-auto = vertical stack, top-to-down scroll -->
  <!-- Desktop (lg+): flex-row = side-by-side resizable panels -->
  <div
    class="evals-panels flex flex-1 min-h-0 flex-col overflow-y-auto overflow-x-hidden lg:flex-row lg:overflow-hidden"
    :style="{
      '--evals-left-width': `${leftWidth}px`,
      '--evals-right-width': `${rightWidth}px`,
    }"
  >
    <!-- Left panel -->
    <div
      class="evals-panel-left w-full shrink-0 overflow-hidden flex flex-col border-b border-border/40 lg:border-b-0"
    >
      <slot name="left" />
    </div>
    <!-- Resize handle (desktop only) -->
    <div
      class="hidden lg:flex w-1 shrink-0 cursor-col-resize hover:bg-primary/20 transition-colors items-center justify-center group"
      :class="{ 'bg-primary/30': isResizingLeft }"
      @mousedown="startResizeLeft"
    >
      <div
        class="w-0.5 h-8 rounded-full bg-muted-foreground/40 group-hover:bg-primary/60"
      />
    </div>
    <!-- Center panel: shrink-0 on mobile (stack), flex-1 on desktop (fills middle) -->
    <div
      class="evals-panel-center shrink-0 lg:flex-1 min-w-0 overflow-hidden flex flex-col border-b border-border/40 lg:border-b-0"
    >
      <slot name="center" />
    </div>
    <!-- Resize handle (desktop only) -->
    <div
      class="hidden lg:flex w-1 shrink-0 cursor-col-resize hover:bg-primary/20 transition-colors items-center justify-center group"
      :class="{ 'bg-primary/30': isResizingRight }"
      @mousedown="startResizeRight"
    >
      <div
        class="w-0.5 h-8 rounded-full bg-muted-foreground/40 group-hover:bg-primary/60"
      />
    </div>
    <!-- Right panel -->
    <div
      class="evals-panel-right w-full shrink-0 overflow-hidden flex flex-col"
    >
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
/* Mobile: full width panels. Desktop: fixed widths for left/right */
@media (min-width: 1024px) {
  .evals-panel-left {
    width: var(--evals-left-width);
  }
  .evals-panel-right {
    width: var(--evals-right-width);
  }
}
</style>
