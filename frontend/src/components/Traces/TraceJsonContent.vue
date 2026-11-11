<script setup lang="ts">
import { computed, ref, useSlots, watch } from "vue";

import JsonTree from "@/components/ui/JsonTree.vue";
import { getTraceJsonContent } from "@/lib/traceJson";

interface Props {
  value: unknown;
  maxHeight?: "small" | "medium" | "large";
}

const props = withDefaults(defineProps<Props>(), {
  maxHeight: "medium",
});

const slots = useSlots();
const viewMode = ref<"tree" | "raw">("tree");
const content = computed(() => getTraceJsonContent(props.value));
// The tree draws no rows for `{}` or `[]`, which reads as a blank box; show the text.
const isEmptyContainer = computed(() => {
  const tree = content.value.treeValue;
  if (!content.value.isJson || tree === null || typeof tree !== "object") return false;
  return Array.isArray(tree) ? tree.length === 0 : Object.keys(tree).length === 0;
});
const showToolbar = computed(
  () => content.value.isJson || Boolean(slots.actions) || Boolean(slots.title),
);
const maxHeightClass = computed(() => {
  if (props.maxHeight === "small") return "max-h-60";
  if (props.maxHeight === "large") return "max-h-[40vh]";
  return "max-h-72";
});

watch(
  () => props.value,
  () => {
    viewMode.value = "tree";
  },
);

// A scrolling box is its own compositor layer and takes the wheel from the page, so it
// only scrolls once the pointer is moved onto it, not when the page slides it under one.
const scrollArmed = ref(false);

function armScroll(event: PointerEvent): void {
  if (event.type === "pointermove" && event.movementX === 0 && event.movementY === 0) return;
  scrollArmed.value = true;
}

function disarmScroll(event: PointerEvent): void {
  // A drag that leaves the box is selecting text and still needs it to scroll.
  if (event.buttons !== 0) return;
  scrollArmed.value = false;
}
</script>

<template>
  <div
    class="min-w-0"
    data-testid="trace-json-content"
  >
    <div
      v-if="showToolbar"
      class="mb-1 flex items-center gap-2"
      :class="slots.title ? 'justify-between' : 'justify-end'"
    >
      <div
        v-if="slots.title"
        class="min-w-0 leading-6"
      >
        <slot name="title" />
      </div>
      <div class="flex shrink-0 items-center gap-1 -mt-0.5">
        <div
          v-if="content.isJson"
          class="inline-flex h-6 items-center rounded-md border border-border/60 bg-muted/40 p-0.5"
          role="group"
          aria-label="JSON view"
        >
          <button
            type="button"
            class="h-5 rounded px-1.5 text-[10px] font-medium leading-none transition-colors"
            :class="
              viewMode === 'tree'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            "
            :aria-pressed="viewMode === 'tree'"
            @click="viewMode = 'tree'"
          >
            Tree
          </button>
          <button
            type="button"
            class="h-5 rounded px-1.5 text-[10px] font-medium leading-none transition-colors"
            :class="
              viewMode === 'raw'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            "
            :aria-pressed="viewMode === 'raw'"
            @click="viewMode = 'raw'"
          >
            Raw
          </button>
        </div>
        <slot name="actions" />
      </div>
    </div>

    <div
      class="trace-json-scroll overflow-auto rounded-md border bg-muted/30"
      :class="[maxHeightClass, { 'trace-json-scroll--idle': !scrollArmed }]"
      data-testid="trace-json-scroll"
      @pointermove="armScroll"
      @pointerdown="armScroll"
      @pointerleave="disarmScroll"
    >
      <div
        v-if="content.isJson && viewMode === 'tree' && !isEmptyContainer"
        class="p-3 text-xs font-mono"
      >
        <JsonTree
          :data="content.treeValue"
          :auto-expand-depth="2"
          :root-expanded="true"
        />
      </div>
      <pre
        v-else
        class="p-3 text-xs whitespace-pre-wrap break-words"
      >{{ content.rawText }}</pre>
    </div>
  </div>
</template>

<style scoped>
/* Hover pointers only: a touch has to scroll the box it lands on. */
@media (hover: hover) and (pointer: fine) {
  /* The scrollbar's space is held either way, so arming a box moves nothing. */
  .trace-json-scroll {
    scrollbar-gutter: stable;
  }

  .trace-json-scroll--idle {
    overflow: hidden;
  }
}
</style>
