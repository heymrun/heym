<script setup lang="ts">
import { computed } from "vue";

import type { RemoteCursor } from "@/features/collab/usePresence";
import CollabCursorMark from "@/features/collab/components/CollabCursorMark.vue";
import { regionElement } from "@/features/collab/regions";
import { createAnchorPlacer } from "@/features/collab/uiReplay";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

interface PlacedCursor extends RemoteCursor {
  left: number;
  top: number;
}

// Pointers over panels and dialogs: on this screen's copy of the element they are over, or,
// when it has none, at the same distance from the edge of the same region.
const collab = useCollabContext();
const placeOnAnchor = createAnchorPlacer();
const placed = computed<PlacedCursor[]>(() =>
  (collab?.cursors.value ?? []).flatMap((cursor) => {
    if (cursor.region === "canvas") return [];
    const onAnchor = cursor.on ? placeOnAnchor(cursor.on) : null;
    if (onAnchor) return [{ ...cursor, left: onAnchor.x, top: onAnchor.y }];
    const rect = regionElement(cursor)?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return [];
    const left = cursor.anchor === "end" ? rect.right - cursor.x : rect.left + cursor.x;
    const top = rect.top + cursor.y;
    if (left < rect.left || left > rect.right || top < rect.top || top > rect.bottom) return [];
    return [{ ...cursor, left, top }];
  }),
);
</script>

<template>
  <div
    class="pointer-events-none fixed inset-0 z-[10000] hidden md:block"
    data-testid="collab-panel-cursors"
  >
    <div
      v-for="cursor in placed"
      :key="cursor.sid"
      class="absolute left-0 top-0 transition-transform duration-100 ease-linear"
      :style="{ transform: `translate(${cursor.left}px, ${cursor.top}px)` }"
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
