<script setup lang="ts">
import { computed } from "vue";

import Input from "@/components/ui/Input.vue";
import SettingsToggle from "@/components/Layout/settings/SettingsToggle.vue";

import type { ClusterInstance, ClusterInstanceUpdate } from "@/types/cluster";

const props = defineProps<{ instance: ClusterInstance }>();

const emit = defineEmits<{ update: [value: ClusterInstanceUpdate] }>();

const statusLabel = computed<string>(() => {
  if (!props.instance.compatible) return "Incompatible";
  if (!props.instance.live) return "Offline";
  return "Live";
});

const statusClass = computed<string>(() => {
  if (!props.instance.compatible) return "text-destructive";
  if (!props.instance.live) return "text-muted-foreground";
  return "text-emerald-600 dark:text-emerald-400";
});

const statusTitle = computed<string>(() => {
  if (!props.instance.compatible) {
    return "This instance's version, database revision or keys differ from the main instance, so it receives no work.";
  }
  if (!props.instance.live) return "No heartbeat in the last 30 seconds.";
  return `Version ${props.instance.version}`;
});

function emitUpdate(patch: Partial<ClusterInstanceUpdate>): void {
  emit("update", {
    name: props.instance.name,
    enabled: props.instance.enabled,
    weight: props.instance.weight,
    ...patch,
  });
}

function onWeight(value: string): void {
  emitUpdate({ weight: Number.parseInt(value, 10) || 0 });
}
</script>

<template>
  <div class="grid grid-cols-12 items-center gap-3 border-b border-border py-2 text-sm">
    <div class="col-span-4">
      <Input
        :model-value="instance.name"
        :placeholder="instance.id"
        @update:model-value="(value: string) => emitUpdate({ name: value })"
      />
    </div>
    <span class="col-span-2 text-muted-foreground">{{ instance.role }}</span>
    <span
      class="col-span-3"
      :class="statusClass"
      :title="statusTitle"
    >
      {{ statusLabel }} &middot; {{ Math.round(instance.db_latency_ms) }} ms
    </span>
    <div class="col-span-1">
      <SettingsToggle
        :id="`cluster-enabled-${instance.id}`"
        :model-value="instance.enabled"
        label=""
        @update:model-value="(value: boolean) => emitUpdate({ enabled: value })"
      />
    </div>
    <div class="col-span-2">
      <Input
        type="number"
        :model-value="String(instance.weight)"
        :disabled="!instance.enabled"
        @update:model-value="onWeight"
      />
    </div>
  </div>
</template>
