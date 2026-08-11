<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { Plus } from "lucide-vue-next";

import AlertEventsPanel from "./AlertEventsPanel.vue";
import AlertList from "./AlertList.vue";
import AlertShareDialog from "./AlertShareDialog.vue";
import AlertWizardDialog from "./wizard/AlertWizardDialog.vue";

import Button from "@/components/ui/Button.vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { workflowApi } from "@/services/api";
import { useAlertsStore } from "@/stores/alerts";
import type { Alert, AlertEvent, AlertEventTimeRange } from "@/types/alerts";

const alertsStore = useAlertsStore();
const workflowOptions = ref<{ value: string; label: string }[]>([]);

const wizardOpen = ref(false);
const editing = ref<Alert | null>(null);
const sharing = ref<Alert | null>(null);
const timeRange = ref<AlertEventTimeRange>("7d");

async function loadWorkflowOptions(): Promise<void> {
  const workflows = await workflowApi.list();
  workflowOptions.value = workflows.map((workflow) => ({
    value: workflow.id,
    label: workflow.name,
  }));
}

async function refresh(): Promise<void> {
  await Promise.all([
    alertsStore.fetchAlerts(),
    alertsStore.fetchEvents({ time_range: timeRange.value }),
    // Saving an alert can create a notify workflow, so the picker would otherwise
    // not offer it until the tab is remounted.
    loadWorkflowOptions(),
  ]);
}

let removeOverlayDismiss: (() => void) | null = null;

onMounted(async () => {
  // The app-level Escape handler runs in the capture phase and calls
  // preventDefault(), so Dialog's own close-on-escape never fires. Overlays opt in
  // here instead; without this the wizard ignores Escape entirely.
  removeOverlayDismiss = onDismissOverlays(() => {
    wizardOpen.value = false;
    sharing.value = null;
  });

  await refresh();
});

onUnmounted(() => {
  removeOverlayDismiss?.();
  removeOverlayDismiss = null;
});

watch(timeRange, (range) => alertsStore.fetchEvents({ time_range: range }));

function openCreate(): void {
  editing.value = null;
  wizardOpen.value = true;
}

function openEdit(alert: Alert): void {
  editing.value = alert;
  wizardOpen.value = true;
}

async function removeAlert(alert: Alert): Promise<void> {
  if (!window.confirm(`Delete the alert "${alert.name}"? Its firing history goes with it.`)) return;
  await alertsStore.deleteAlert(alert.id);
}

async function acknowledge(event: AlertEvent): Promise<void> {
  await alertsStore.acknowledgeEvent(event.id);
  // The card badge reads from the alert's unacknowledged count, so the list has to
  // come back too: otherwise the row updates and the badge above still says Firing.
  await alertsStore.fetchAlerts();
}
</script>

<template>
  <div class="space-y-6 p-4 sm:p-6">
    <header class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div class="min-w-0">
        <h1 class="text-lg font-semibold tracking-tight">
          Alerts
        </h1>
        <p class="mt-0.5 text-sm text-muted-foreground">
          Threshold rules over a time window on errors, duration, LLM spend, and run count.
        </p>
      </div>
      <Button
        class="w-full shrink-0 sm:w-auto"
        @click="openCreate"
      >
        <Plus class="mr-1.5 h-4 w-4" />
        New alert
      </Button>
    </header>

    <p
      v-if="alertsStore.error"
      class="text-sm text-destructive"
    >
      {{ alertsStore.error }}
    </p>

    <AlertList
      :alerts="alertsStore.alerts"
      :loading="alertsStore.loading"
      @edit="openEdit"
      @remove="removeAlert"
      @share="sharing = $event"
      @toggle="alertsStore.toggleEnabled($event)"
    />

    <AlertEventsPanel
      :events="alertsStore.events"
      :loading="alertsStore.eventsLoading"
      :time-range="timeRange"
      @acknowledge="acknowledge"
      @update:time-range="timeRange = $event"
    />

    <AlertWizardDialog
      :open="wizardOpen"
      :workflows="workflowOptions"
      :editing="editing"
      @close="wizardOpen = false"
      @saved="refresh"
    />

    <AlertShareDialog
      :open="sharing !== null"
      :alert="sharing"
      @close="sharing = null"
    />
  </div>
</template>
