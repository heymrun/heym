<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RefreshCw } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import ClusterInstanceRow from "@/components/Layout/settings/ClusterInstanceRow.vue";
import SettingsToggle from "@/components/Layout/settings/SettingsToggle.vue";
import {
  getClusterSettings,
  saveClusterInstances,
  setAutomaticWeighting,
} from "@/services/cluster";

import type { ClusterInstance, ClusterInstanceUpdate, ClusterSettings } from "@/types/cluster";

const config = ref<ClusterSettings | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);

const enabledTotal = computed<number>(() =>
  (config.value?.instances ?? [])
    .filter((instance: ClusterInstance) => instance.enabled)
    .reduce((sum: number, instance: ClusterInstance) => sum + instance.weight, 0),
);

// Only a split nothing could run on is refused. Requiring a total of 100 would
// block saving the moment an instance is disabled, even though the scheduler
// divides by the pool's own total and keeps working.
const canSave = computed<boolean>(() => enabledTotal.value > 0);

/** The instances a run can actually be assigned to, mirroring the scheduler's
 *  own filter: enabled, weighted, live and compatible. */
const eligible = computed<ClusterInstance[]>(() =>
  (config.value?.instances ?? []).filter(
    (instance: ClusterInstance) =>
      instance.enabled && instance.weight > 0 && instance.live && instance.compatible,
  ),
);

/** What each instance really receives. Weights are shares of the eligible pool,
 *  not of 100, so 41 out of 41+26 is 61% once a third instance drops out. */
const effectiveSplit = computed<string>(() => {
  const pool = eligible.value;
  const total = pool.reduce((sum: number, instance: ClusterInstance) => sum + instance.weight, 0);
  if (total === 0) return "";
  return pool
    .map(
      (instance: ClusterInstance) =>
        `${instance.name || instance.id} ${Math.round((instance.weight / total) * 100)}%`,
    )
    .join(" \u00b7 ");
});

const excluded = computed<ClusterInstance[]>(() =>
  (config.value?.instances ?? []).filter(
    (instance: ClusterInstance) => !eligible.value.includes(instance),
  ),
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    config.value = await getClusterSettings();
  } catch {
    error.value = "Failed to load load distribution settings.";
  } finally {
    loading.value = false;
  }
}

function applyUpdate(instanceId: string, patch: ClusterInstanceUpdate): void {
  const target = config.value?.instances.find(
    (instance: ClusterInstance) => instance.id === instanceId,
  );
  if (!target) return;
  target.name = patch.name;
  target.enabled = patch.enabled;
  target.weight = patch.weight;
}

async function handleAutomaticWeighting(value: boolean): Promise<void> {
  if (!config.value) return;
  const previous = config.value.automatic_weighting;
  config.value.automatic_weighting = value;
  error.value = null;
  try {
    config.value = await setAutomaticWeighting(value);
  } catch {
    if (config.value) config.value.automatic_weighting = previous;
    error.value = "Failed to change automatic weighting.";
  }
}

async function handleSave(): Promise<void> {
  if (!config.value || !canSave.value) return;
  saving.value = true;
  error.value = null;
  try {
    const updates: Record<string, ClusterInstanceUpdate> = {};
    for (const instance of config.value.instances) {
      updates[instance.id] = {
        name: instance.name,
        enabled: instance.enabled,
        weight: instance.weight,
      };
    }
    config.value = await saveClusterInstances(updates);
  } catch {
    error.value = "Failed to save load distribution settings.";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between gap-4">
      <p class="text-sm text-muted-foreground">
        Share background workflow execution across the instances connected to this database. Work
        that touches files, coding-agent workspaces or plugins always runs on the main instance.
      </p>
      <Button
        variant="outline"
        size="sm"
        class="shrink-0 px-2"
        title="Refresh"
        aria-label="Refresh"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="h-4 w-4" />
      </Button>
    </div>

    <p
      v-if="config && !config.cluster_enabled"
      class="text-sm text-muted-foreground"
    >
      Load distribution is off. Set <code>HEYM_CLUSTER_ENABLED=true</code> on the main instance to
      turn it on.
    </p>

    <div
      v-if="config"
      class="rounded-md border border-border p-3"
    >
      <SettingsToggle
        id="cluster-automatic-weighting"
        :model-value="config.automatic_weighting"
        label="Give new instances a share automatically"
        @update:model-value="handleAutomaticWeighting"
      />
      <p class="mt-1.5 text-xs text-muted-foreground">
        An instance that joins starts at 0 and would receive no work. With this on, it is given
        an equal share once, and the existing weights are scaled down keeping their ratios. An
        instance you set yourself is never changed.
      </p>
    </div>

    <p
      v-if="config"
      class="text-sm text-muted-foreground"
    >
      <template v-if="config.placement_ratio.mainOnlyPercent > 0">
        {{ config.placement_ratio.mainOnlyPercent }}% of the last 24 hours' runs could only
        execute on the main instance, so the weights below cannot move that work.
      </template>
      <template v-else>
        Every run in the last 24 hours could execute anywhere, so the weights below govern all
        of it.
      </template>
    </p>

    <div
      v-if="config"
      class="rounded-md border border-border p-3"
    >
      <div
        class="flex items-center gap-2 border-b border-border pb-2 text-xs uppercase text-muted-foreground"
      >
        <span class="mr-4 w-32 shrink-0 pl-2">Name</span>
        <span class="w-16 shrink-0">Role</span>
        <span class="min-w-0 flex-1">Status</span>
        <span class="ml-2 w-11 shrink-0">On</span>
        <span class="w-16 shrink-0 text-center">Weight</span>
      </div>
      <ClusterInstanceRow
        v-for="instance in config.instances"
        :key="instance.id"
        :instance="instance"
        @update="(patch: ClusterInstanceUpdate) => applyUpdate(instance.id, patch)"
      />
    </div>

    <p
      v-if="effectiveSplit"
      class="text-sm text-muted-foreground"
    >
      Runs are being shared
      <span class="text-foreground">{{ effectiveSplit }}</span>.
      <template v-if="excluded.length">
        The weights above are shares of the instances that can take work, so they read
        differently once
        {{ excluded.map((instance) => instance.name || instance.id).join(", ") }}
        {{ excluded.length === 1 ? "is" : "are" }} out of the pool.
      </template>
    </p>

    <p
      v-if="config && !canSave"
      class="text-sm text-destructive"
    >
      Give at least one enabled instance a weight above zero, or nothing can be scheduled.
    </p>
    <p
      v-if="error"
      class="text-sm text-destructive"
    >
      {{ error }}
    </p>

    <Button
      :disabled="!canSave || saving"
      @click="handleSave"
    >
      Save
    </Button>
  </div>
</template>
