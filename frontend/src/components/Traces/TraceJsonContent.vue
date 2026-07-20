<script setup lang="ts">
import { computed, ref, watch } from "vue";

import Button from "@/components/ui/Button.vue";
import JsonTree from "@/components/ui/JsonTree.vue";
import { getTraceJsonContent } from "@/lib/traceJson";

interface Props {
  value: unknown;
  maxHeight?: "small" | "medium" | "large";
}

const props = withDefaults(defineProps<Props>(), {
  maxHeight: "medium",
});

const viewMode = ref<"tree" | "raw">("tree");
const content = computed(() => getTraceJsonContent(props.value));
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
      v-if="content.isJson"
      class="mb-1 flex justify-end"
      role="group"
      aria-label="JSON view"
    >
      <Button
        :variant="viewMode === 'tree' ? 'secondary' : 'ghost'"
        size="sm"
        class="h-7 min-h-7 rounded-r-none px-2 text-[11px] font-medium"
        :aria-pressed="viewMode === 'tree'"
        @click="viewMode = 'tree'"
      >
        Tree
      </Button>
      <Button
        :variant="viewMode === 'raw' ? 'secondary' : 'ghost'"
        size="sm"
        class="h-7 min-h-7 rounded-l-none px-2 text-[11px] font-medium"
        :aria-pressed="viewMode === 'raw'"
        @click="viewMode = 'raw'"
      >
        Raw
      </Button>
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
          :auto-expand-depth="1"
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
