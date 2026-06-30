<script lang="ts">
// Shared across all instances: dedupe + cache icon fetches by plugin/node.
// A resolved value of `null` means "no custom icon" (use the fallback). The cache
// is busted via clearPluginIconCache() on plugin install/uninstall/toggle so a
// reinstall is picked up without a full page reload.
const pluginIconCache = new Map<string, Promise<string | null>>();

export function clearPluginIconCache(): void {
  pluginIconCache.clear();
}
</script>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import DOMPurify from "dompurify";
import { Puzzle } from "lucide-vue-next";

import { fetchPluginIconSvg } from "@/services/plugins";

// NOTE: do not declare a `hasIcon: boolean` prop here — Vue casts an absent
// Boolean prop to `false`, which previously made callers that omit it (the
// canvas node) silently skip the fetch. We always attempt the fetch instead.
const props = defineProps<{
  pluginId?: string;
  nodeKey?: string;
  sizeClass?: string;
}>();

const svg = ref<string | null>(null);
const sizeClass = computed(() => props.sizeClass ?? "w-5 h-5");

async function load(): Promise<void> {
  svg.value = null;
  if (!props.pluginId) return;
  const key = `${props.pluginId}:${props.nodeKey ?? ""}`;
  let pending = pluginIconCache.get(key);
  if (!pending) {
    pending = fetchPluginIconSvg(props.pluginId, props.nodeKey)
      .then((raw) => (raw && raw.includes("<svg") ? raw : null))
      .catch(() => null);
    pluginIconCache.set(key, pending);
  }
  const raw = await pending;
  svg.value = raw
    ? DOMPurify.sanitize(raw, { USE_PROFILES: { svg: true, svgFilters: true } })
    : null;
}

watch(() => [props.pluginId, props.nodeKey], load, { immediate: true });
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <span
    v-if="svg"
    :class="['plugin-icon inline-flex items-center justify-center', sizeClass]"
    v-html="svg"
  />
  <!-- eslint-enable vue/no-v-html -->

  <Puzzle
    v-else
    :class="sizeClass"
  />
</template>

<style scoped>
.plugin-icon :deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
