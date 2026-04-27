<script setup lang="ts">
import { nextTick } from "vue";
import { getRectOfNodes, getTransformForBounds, useVueFlow } from "@vue-flow/core";

const { dimensions, minZoom, maxZoom, getNodesInitialized, setViewport, fitView } = useVueFlow();

async function fitViewAfterLoad(opts?: { padding?: number; duration?: number }): Promise<void> {
  await nextTick();
  await nextTick();
  await new Promise<void>((resolve) => {
    requestAnimationFrame(() => resolve());
  });

  const padding = opts?.padding ?? 0.18;
  const duration = opts?.duration ?? 200;

  async function applyBoundsCenteredFit(): Promise<boolean> {
    const inited = getNodesInitialized.value;
    const { width, height } = dimensions.value;
    if (inited.length === 0 || width <= 0 || height <= 0) {
      return false;
    }
    const rect = getRectOfNodes(inited);
    const t = getTransformForBounds(
      rect,
      width,
      height,
      minZoom.value,
      maxZoom.value,
      padding,
    );
    await setViewport(t, { duration });
    return true;
  }

  try {
    const ok = await applyBoundsCenteredFit();
    if (!ok) {
      await fitView({ padding, duration });
      await nextTick();
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
      await applyBoundsCenteredFit();
    }
  } catch {
    try {
      await fitView({ padding, duration });
    } catch {
      /* Flow not ready */
    }
  }
}

defineExpose({ fitViewAfterLoad });
</script>

<template>
  <span
    class="sr-only"
    aria-hidden="true"
  />
</template>
