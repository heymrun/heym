<script setup lang="ts">
import { computed } from "vue";

import Input from "@/components/ui/Input.vue";
import SettingsToggle from "@/components/Layout/settings/SettingsToggle.vue";

import type { ClusterInstance, ClusterInstanceUpdate } from "@/types/cluster";

const props = defineProps<{ instance: ClusterInstance }>();

const emit = defineEmits<{ update: [value: ClusterInstanceUpdate] }>();

/** Live and compatible, but no process has synced its Kubernetes credentials yet. */
const unsynced = computed<boolean>(
  () => props.instance.compatible && props.instance.live && !props.instance.credentials_synced,
);

const statusLabel = computed<string>(() => {
  if (!props.instance.compatible) return "Miss";
  if (!props.instance.live) return "Off";
  if (unsynced.value) return "Sync";
  return "Live";
});

const statusClass = computed<string>(() => {
  if (!props.instance.compatible) return "text-destructive";
  if (!props.instance.live) return "text-muted-foreground";
  if (unsynced.value) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
});

const isMain = computed<boolean>(() => props.instance.role === "main");

const dotClass = computed<string>(() => {
  if (!props.instance.compatible) return "bg-destructive";
  if (!props.instance.live) return "bg-muted-foreground/50";
  if (unsynced.value) return "bg-amber-500";
  return "bg-emerald-500";
});

/** Which keys it uses, by fingerprint: where an ENCRYPTION_KEY rotation stands. */
const keysLine = computed<string>(() => {
  const { primary_fingerprint: primary, decrypt_fingerprints: decrypts } = props.instance;
  if (!primary) return "";
  const extra = decrypts.filter((fingerprint) => fingerprint !== primary);
  return extra.length
    ? `\nEncrypts with key ${primary}; also decrypts with ${extra.join(", ")}.`
    : `\nEncrypts with key ${primary}.`;
});

const statusTitle = computed<string>(() => {
  let status: string;
  if (!props.instance.compatible) {
    status =
      "This instance's version, database revision or keys don't fit the main instance or the other instances, so it receives no work and can't lead.";
  } else if (!props.instance.live) {
    status = "No heartbeat in the last 30 seconds.";
  } else if (unsynced.value) {
    status =
      "No process of this instance has synced its Kubernetes credentials yet, so it receives no work.";
  } else {
    status = `Version ${props.instance.version}`;
  }
  return status + keysLine.value;
});

/** The field grows only for a three-digit weight, so 100 is never clipped and a
 *  two-digit one is not padded out. The column is right-aligned, so the field's
 *  right edge - and the % beside it - stays put across rows either way. Stacked,
 *  everything is one step larger: the row is a touch target, not a table cell. */
const weightWidth = computed<string>(() =>
  String(props.instance.weight).length >= 3 ? "w-14 sm:w-12" : "w-12 sm:w-9",
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
       rest. Too narrow for five columns, the name takes its own line and the
       rest stays one row. -->
  <div
    class="flex flex-col gap-1.5 border-b border-border/60 py-2 text-sm last:border-b-0 sm:flex-row sm:items-center sm:gap-2 sm:py-1.5"
  >
    <!-- Reads as a table cell until you go to edit it: a full form field per row
         turns five rows into a stack of boxes. -->
    <Input
      class="h-9 min-h-0 w-full rounded-md bg-transparent px-2 shadow-none focus-visible:bg-background sm:mr-4 sm:h-8 sm:w-32 sm:shrink-0"
      :model-value="instance.name"
      :placeholder="instance.id"
      @update:model-value="(value: string) => emitUpdate({ name: value })"
    />
    <!-- Stacked, the four cells span the row and the slack goes into the gaps
         between them, so nothing is stranded at an edge. Each keeps a fixed
         width so the rows line up with each other. `sm:contents` dissolves this
         wrapper once there is room, so the columns line up with the header. -->
    <div class="flex w-full items-center justify-between gap-3 px-1 sm:contents">
      <span class="w-16 shrink-0 truncate text-sm text-muted-foreground">{{ instance.role }}</span>
      <span
        class="flex w-24 min-w-0 items-center gap-1.5 text-sm sm:w-auto sm:flex-1 sm:text-xs"
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
        <span class="truncate whitespace-nowrap text-muted-foreground">{{ Math.round(instance.db_latency_ms) }} ms</span>
      </span>
      <div class="w-9 shrink-0 sm:ml-2 sm:w-11">
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
      <div class="flex shrink-0 items-center justify-center gap-1 sm:w-16">
        <Input
          class="h-9 min-h-0 rounded-md px-1.5 text-center tabular-nums sm:h-8 transition-[width] duration-150 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          :class="weightWidth"
          type="number"
          min="0"
          max="100"
          :model-value="String(instance.weight)"
          :disabled="!instance.enabled"
          @update:model-value="onWeight"
        />
        <span class="w-3 text-sm text-muted-foreground sm:text-xs">%</span>
      </div>
    </div>
  </div>
</template>
