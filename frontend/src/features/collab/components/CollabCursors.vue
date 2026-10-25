<script setup lang="ts">
import { computed } from "vue";
import { useVueFlow } from "@vue-flow/core";

import type { RemoteCursor } from "@/features/collab/usePresence";
import CollabCursorMark from "@/features/collab/components/CollabCursorMark.vue";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

// Rendered in Vue Flow's zoom pane, so positions are flow coordinates.
const collab = useCollabContext();
const { viewport } = useVueFlow();
const cursors = computed<RemoteCursor[]>(() =>
  (collab?.cursors.value ?? []).filter((cursor) => cursor.region === "canvas"),
);
const scale = computed<number>(() => 1 / (viewport.value.zoom || 1));
</script>

<template>
  <div class="pointer-events-none absolute left-0 top-0 z-[1000]">
    <div
      v-for="cursor in cursors"
      :key="cursor.sid"
      class="absolute left-0 top-0 transition-transform duration-100 ease-linear"
      :style="{
        transform: `translate(${cursor.x}px, ${cursor.y}px) scale(${scale})`,
        transformOrigin: '0 0',
      }"
    >
      <CollabCursorMark
        :color="cursor.color"
        :name="cursor.name"
        :user-id="cursor.userId"
        :click-at="cursor.clickAt"
        :hint="cursor.hint ?? null"
      />
    </div>
  </div>
</template>
