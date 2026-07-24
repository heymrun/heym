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
      class="overflow-auto rounded-md border bg-muted/30"
      :class="maxHeightClass"
    >
      <div
        v-if="content.isJson && viewMode === 'tree'"
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
