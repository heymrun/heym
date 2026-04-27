<script setup lang="ts">
import { nextTick, watch } from "vue";
import { getRectOfNodes, getTransformForBounds, useVueFlow } from "@vue-flow/core";

interface Props {
  fitKey: number | string;
  padding: number;
  duration?: number;
}

const props = withDefaults(defineProps<Props>(), {
  duration: 0,
});

const { dimensions, fitView, getNodesInitialized, maxZoom, minZoom, setViewport } = useVueFlow();

async function fitViewAfterLoad(): Promise<void> {
  await nextTick();
  await nextTick();
  await new Promise<void>((resolve) => {
    requestAnimationFrame(() => resolve());
  });

  async function applyBoundsCenteredFit(): Promise<boolean> {
    const initializedNodes = getNodesInitialized.value;
    const { width, height } = dimensions.value;
    if (initializedNodes.length === 0 || width <= 0 || height <= 0) {
      return false;
    }
    const bounds = getRectOfNodes(initializedNodes);
    const viewport = getTransformForBounds(
      bounds,
      width,
      height,
      minZoom.value,
      maxZoom.value,
      props.padding,
    );
    await setViewport(viewport, { duration: props.duration });
    return true;
  }

  try {
    const applied = await applyBoundsCenteredFit();
    if (applied) {
      return;
    }
    await fitView({ padding: props.padding, duration: props.duration });
    await nextTick();
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve());
    });
    await applyBoundsCenteredFit();
  } catch {
    try {
      await fitView({ padding: props.padding, duration: props.duration });
    } catch {
      /* Flow not ready yet */
    }
  }
}

watch(
  () => `${props.fitKey}:${props.padding}`,
  () => {
    void fitViewAfterLoad();
  },
  { immediate: true },
);
</script>

<template>
  <span
    class="sr-only"
    aria-hidden="true"
  />
</template>
