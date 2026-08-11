<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, Loader2 } from "lucide-vue-next";

import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useAlertsStore } from "@/stores/alerts";
import {
  ALERT_TYPE_LABELS,
  type AlertConfig,
  type AlertPreview,
  type AlertScope,
  type AlertType,
  type NotifyWorkflowMode,
  type RenotifyMode,
} from "@/types/alerts";

interface Props {
  name: string;
  description: string | null;
  alertType: AlertType;
  scope: AlertScope;
  workflowId: string | null;
  workflowName: string | null;
  config: AlertConfig;
  renotifyMode: RenotifyMode;
  cooldownMinutes: number | null;
  notifyWorkflowName: string | null;
  notifyMode: NotifyWorkflowMode;
  aiFilledFields: string[];
}

const props = defineProps<Props>();
const emit = defineEmits<{
  "update:name": [value: string];
  "update:description": [value: string | null];
}>();

const alertsStore = useAlertsStore();

const LOOKBACK_OPTIONS = [
  { value: "24", label: "Last 24 hours" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last 7 days" },
];

const lookbackHours = ref("24");
const preview = ref<AlertPreview | null>(null);
const previewLoading = ref(false);
const previewError = ref<string | null>(null);

const nameModel = computed({
  get: (): string => props.name,
  set: (value: string): void => emit("update:name", value),
});

const descriptionModel = computed({
  get: (): string => props.description ?? "",
  set: (value: string): void => emit("update:description", value || null),
});

const scopeLabel = computed((): string =>
  props.scope === "system" ? "All my workflows" : (props.workflowName ?? "One workflow"),
);

const renotifyLabel = computed((): string =>
  props.renotifyMode === "on_recovery"
    ? "Notify once, until it recovers"
    : `Repeat every ${props.cooldownMinutes ?? 60} minutes`,
);

/** A threshold that would have fired constantly is almost certainly set too low. */
const thresholdLooksNoisy = computed((): boolean => {
  const result = preview.value;
  if (!result) return false;
  return result.backtest_fire_count >= 10;
});

function isAiFilled(field: string): boolean {
  return props.aiFilledFields.includes(field);
}

async function runBacktest(): Promise<void> {
  previewLoading.value = true;
  previewError.value = null;
  try {
    preview.value = await alertsStore.previewCondition({
      alert_type: props.alertType,
      scope: props.scope,
      workflow_id: props.workflowId,
      config: props.config,
      lookback_hours: Number(lookbackHours.value),
    });
  } catch (err: unknown) {
    previewError.value = err instanceof Error ? err.message : "Could not run the backtest";
  } finally {
    previewLoading.value = false;
  }
}

onMounted(runBacktest);
watch(lookbackHours, runBacktest);
</script>

<template>
  <div class="space-y-6">
    <div class="space-y-2">
      <Label for="alert-name">Name</Label>
      <Input
        id="alert-name"
        v-model="nameModel"
        :class="isAiFilled('name') ? 'border-primary/60' : undefined"
        placeholder="Invoice sync failures"
      />
      <p
        v-if="isAiFilled('name')"
        class="text-xs text-primary"
      >
        Filled by AI
      </p>
    </div>

    <div class="space-y-2">
      <Label for="alert-description">Description (optional)</Label>
      <Textarea
        id="alert-description"
        v-model="descriptionModel"
        :rows="2"
      />
    </div>

    <div class="rounded-lg border border-border p-4 text-sm">
      <dl class="grid gap-2 sm:grid-cols-2">
        <div>
          <dt class="text-xs text-muted-foreground">
            Type
          </dt>
          <dd>{{ ALERT_TYPE_LABELS[alertType] }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">
            Watching
          </dt>
          <dd>{{ scopeLabel }}</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">
            Window
          </dt>
          <dd>{{ config.window_minutes }} minutes</dd>
        </div>
        <div>
          <dt class="text-xs text-muted-foreground">
            Repeat
          </dt>
          <dd>{{ renotifyLabel }}</dd>
        </div>
        <div
          v-if="notifyWorkflowName || notifyMode === 'create'"
          class="sm:col-span-2"
        >
          <dt class="text-xs text-muted-foreground">
            Runs on fire
          </dt>
          <dd v-if="notifyMode === 'create'">
            A new workflow, "{{ name || "this alert" }} notification", created when you save
          </dd>
          <dd v-else>
            {{ notifyWorkflowName }}
          </dd>
        </div>
      </dl>
    </div>

    <div class="space-y-3">
      <div class="flex items-center justify-between gap-3">
        <Label>Backtest</Label>
        <Select
          v-model="lookbackHours"
          :options="LOOKBACK_OPTIONS"
          class="w-44"
        />
      </div>

      <div class="rounded-lg border border-border p-4 text-sm">
        <div
          v-if="previewLoading"
          class="flex items-center gap-2 text-muted-foreground"
        >
          <Loader2 class="h-4 w-4 animate-spin" />
          Checking what this would have done...
        </div>

        <p
          v-else-if="previewError"
          class="text-destructive"
        >
          {{ previewError }}
        </p>

        <div
          v-else-if="preview"
          class="space-y-2"
        >
          <p>
            This condition would have fired
            <strong>{{ preview.backtest_fire_count }}</strong>
            {{ preview.backtest_fire_count === 1 ? "time" : "times" }}
            over the selected period.
          </p>
          <p class="text-muted-foreground">
            Highest observed value: <strong>{{ preview.backtest_max_observed }}</strong> against a
            threshold of <strong>{{ preview.threshold_value }}</strong>.
            <span v-if="preview.would_fire_now"> It would be firing right now.</span>
          </p>

          <div
            v-if="thresholdLooksNoisy"
            class="flex gap-2 rounded-md bg-amber-500/10 p-3 text-amber-700 dark:text-amber-400"
          >
            <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              That is a lot of firings. Consider raising the threshold or widening the window before
              saving, otherwise this alert will be noise.
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
