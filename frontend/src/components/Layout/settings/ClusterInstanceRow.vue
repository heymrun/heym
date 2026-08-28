<script setup lang="ts">
import { computed } from "vue";

import Input from "@/components/ui/Input.vue";
import SettingsToggle from "@/components/Layout/settings/SettingsToggle.vue";

import type { ClusterInstance, ClusterInstanceUpdate } from "@/types/cluster";

const props = defineProps<{ instance: ClusterInstance }>();

const emit = defineEmits<{ update: [value: ClusterInstanceUpdate] }>();

const statusLabel = computed<string>(() => {
  if (!props.instance.compatible) return "Miss";
  if (!props.instance.live) return "Off";
  return "Live";
});

const statusClass = computed<string>(() => {
  if (!props.instance.compatible) return "text-destructive";
  if (!props.instance.live) return "text-muted-foreground";
  return "text-emerald-600 dark:text-emerald-400";
});

const isMain = computed<boolean>(() => props.instance.role === "main");

const dotClass = computed<string>(() => {
  if (!props.instance.compatible) return "bg-destructive";
  if (!props.instance.live) return "bg-muted-foreground/50";
  return "bg-emerald-500";
});

const statusTitle = computed<string>(() => {
  if (!props.instance.compatible) {
    return "This instance's version, database revision or keys differ from the main instance, so it receives no work.";
  }
  if (!props.instance.live) return "No heartbeat in the last 30 seconds.";
  return `Version ${props.instance.version}`;
});

/** The field grows only for a three-digit weight, so 100 is never clipped and a
 *  two-digit one is not padded out. The column is right-aligned, so the field's
 *  right edge - and the % beside it - stays put across rows either way. */
const weightWidth = computed<string>(() =>
  String(props.instance.weight).length >= 3 ? "w-12" : "w-9",
);

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
  <!-- Fixed widths rather than a 12-column grid: the weight has to stay wide
       enough to read at any dialog width, and only the name should absorb the
       rest. -->
  <div
    class="flex items-center gap-2 border-b border-border/60 py-1.5 text-sm last:border-b-0"
  >
    <!-- Reads as a table cell until you go to edit it: a full form field per row
         turns five rows into a stack of boxes. -->
    <Input
      class="h-8 min-h-0 w-32 shrink-0 rounded-md bg-transparent px-2 shadow-none focus-visible:bg-background mr-4"
      :model-value="instance.name"
      :placeholder="instance.id"
      @update:model-value="(value: string) => emitUpdate({ name: value })"
    />
    <span class="w-16 shrink-0 truncate text-muted-foreground">{{ instance.role }}</span>
    <span
      class="flex min-w-0 flex-1 items-center gap-1.5 text-xs"
      :title="statusTitle"
    >
      <span
        class="h-1.5 w-1.5 shrink-0 rounded-full"
        :class="dotClass"
      />
      <span
        class="whitespace-nowrap"
        :class="statusClass"
      >{{ statusLabel }}</span>
      <span class="whitespace-nowrap text-muted-foreground">{{ Math.round(instance.db_latency_ms) }} ms</span>
    </span>
    <div class="ml-2 w-11 shrink-0">
      <SettingsToggle
        :id="`cluster-enabled-${instance.id}`"
        :model-value="instance.enabled"
        :disabled="isMain"
        :title="
          isMain
            ? 'The main instance cannot be taken out of rotation: file, plugin and coding-agent work runs there whatever this says.'
            : undefined
        "
        label=""
        @update:model-value="(value: boolean) => emitUpdate({ enabled: value })"
      />
    </div>
    <div class="flex w-16 shrink-0 items-center justify-center gap-1">
      <Input
        class="h-8 min-h-0 rounded-md px-1.5 text-center tabular-nums transition-[width] duration-150 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        :class="weightWidth"
        type="number"
        min="0"
        max="100"
        :model-value="String(instance.weight)"
        :disabled="!instance.enabled"
        @update:model-value="onWeight"
      />
      <span class="w-3 text-xs text-muted-foreground">%</span>
    </div>
  </div>
</template>
