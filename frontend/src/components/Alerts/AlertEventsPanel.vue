<script setup lang="ts">
import { computed } from "vue";
import { Check, History } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import { costMetricFromContext, formatAlertValue } from "@/lib/alertMetricFormat";
import { ALERT_TYPE_LABELS, type AlertEvent, type AlertEventTimeRange } from "@/types/alerts";

interface Props {
  events: AlertEvent[];
  loading: boolean;
  timeRange: AlertEventTimeRange;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  acknowledge: [event: AlertEvent];
  "update:timeRange": [value: AlertEventTimeRange];
}>();

const TIME_RANGES = [
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "all", label: "All time" },
];

const NOTIFY_CLASSES: Record<string, string> = {
  succeeded: "text-emerald-700 dark:text-emerald-400",
  failed: "text-red-700 dark:text-red-400",
};

const rangeModel = computed({
  get: (): string => props.timeRange,
  set: (value: string | undefined): void =>
    emit("update:timeRange", (value ?? "7d") as AlertEventTimeRange),
});

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

function windowLabel(event: AlertEvent): string {
  const minutes = Math.round(
    (new Date(event.window_end).getTime() - new Date(event.window_start).getTime()) / 60000,
  );
  return `${minutes}m window`;
}

/** Raw floats, e.g. 6184.591054916382, need the alert type's unit to be readable. */
function metricLabel(event: AlertEvent, value: number): string {
  return formatAlertValue(value, event.alert_type, costMetricFromContext(event.context));
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="flex items-center gap-2 text-sm font-semibold">
        <History class="h-4 w-4 text-muted-foreground" />
        Firing history
      </h2>
      <Select
        v-model="rangeModel"
        :options="TIME_RANGES"
        class="w-full sm:w-44"
      />
    </div>

    <p
      v-if="loading"
      class="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground"
    >
      Loading history...
    </p>

    <p
      v-else-if="events.length === 0"
      class="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground"
    >
      Nothing has fired in this period.
    </p>

    <ul
      v-else
      class="space-y-2"
    >
      <li
        v-for="event in events"
        :key="event.id"
        class="rounded-xl border border-border bg-card p-4 text-sm transition-colors duration-200 hover:border-border/80"
      >
        <!-- Stacks below sm so the acknowledge control keeps its own row instead
             of squeezing the observed/threshold line. -->
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span class="min-w-0 truncate font-medium">{{ event.alert_name }}</span>
              <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                {{ ALERT_TYPE_LABELS[event.alert_type] }}
              </span>
            </div>

            <div class="mt-1.5 text-muted-foreground">
              Observed
              <span class="font-semibold tabular-nums text-foreground">
                {{ metricLabel(event, event.observed_value) }}
              </span>
              against a threshold of
              <span class="font-semibold tabular-nums text-foreground">
                {{ metricLabel(event, event.threshold_value) }}
              </span>
              <span class="whitespace-nowrap">({{ windowLabel(event) }})</span>
            </div>

            <div class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span class="tabular-nums">{{ formatTime(event.triggered_at) }}</span>
              <span
                v-if="event.notify_status"
                class="flex items-center gap-1"
              >
                <span aria-hidden="true">·</span>
                notify:
                <span :class="NOTIFY_CLASSES[event.notify_status] ?? ''">
                  {{ event.notify_status }}
                </span>
              </span>
            </div>
          </div>

          <div class="shrink-0">
            <Button
              v-if="!event.acknowledged_at"
              variant="outline"
              size="sm"
              aria-label="Acknowledge"
              title="Acknowledge this firing"
              @click="emit('acknowledge', event)"
            >
              <Check class="mr-1.5 h-3.5 w-3.5" />
              Acknowledge
            </Button>
            <!-- Acknowledging has to leave a mark, otherwise pressing the button
                 looks like nothing happened. -->
            <span
              v-else
              class="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-700 dark:text-emerald-400"
              :title="`Acknowledged ${formatTime(event.acknowledged_at)}`"
            >
              <Check class="h-3 w-3" />
              Acknowledged
            </span>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
