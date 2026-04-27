<script setup lang="ts">
import { onUnmounted, watch } from "vue";
import { useVueFlow } from "@vue-flow/core";

const props = withDefaults(
  defineProps<{
    enabled?: boolean;
  }>(),
  { enabled: true },
);

const emit = defineEmits<{
  deleteSelection: [payload: { nodeIds: string[]; edgeIds: string[] }];
}>();

const { getSelectedNodes, getSelectedEdges } = useVueFlow();

function isTypingInField(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) {
    return false;
  }
  const inFormControl = target.closest(
    "input, textarea, select, [contenteditable='true'], [contenteditable='']",
  );
  return inFormControl !== null;
}

function onKeyDown(e: KeyboardEvent): void {
  if (!props.enabled) {
    return;
  }
  if (e.key !== "Backspace" && e.key !== "Delete") {
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) {
    return;
  }
  if (isTypingInField(e.target)) {
    return;
  }
  const nodes = getSelectedNodes.value;
  const edges = getSelectedEdges.value;
  if (nodes.length === 0 && edges.length === 0) {
    return;
  }
  e.preventDefault();
  e.stopPropagation();
  emit("deleteSelection", {
    nodeIds: [...new Set(nodes.map((n) => n.id))],
    edgeIds: [...new Set(edges.map((ed) => ed.id))],
  });
}

watch(
  () => props.enabled,
  (en) => {
    if (en) {
      document.addEventListener("keydown", onKeyDown, true);
    } else {
      document.removeEventListener("keydown", onKeyDown, true);
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  document.removeEventListener("keydown", onKeyDown, true);
});
</script>

<template>
  <span
    class="sr-only"
    aria-hidden="true"
  />
</template>
