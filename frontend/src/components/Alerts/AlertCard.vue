<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { ExternalLink, Pause, Pencil, Play, Share2, Trash2 } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import { costMetricFromConfig, formatAlertValue } from "@/lib/alertMetricFormat";
import { joinOriginAndPath } from "@/lib/appUrl";
import { isPaletteOpenInNewTab } from "@/lib/paletteNavigate";
import { cn } from "@/lib/utils";
import { ALERT_TYPE_LABELS, type Alert } from "@/types/alerts";

interface Props {
  alert: Alert;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  edit: [alert: Alert];
  remove: [alert: Alert];
  share: [alert: Alert];
  toggle: [alert: Alert];
}>();

const router = useRouter();

const scopeLabel = computed((): string =>
  props.alert.scope === "system" ? "All workflows" : (props.alert.workflow_name ?? "Workflow"),
);

/**
 * A triggered alert whose firings have all been acknowledged reads as
 * "Acknowledged", not "Firing": the condition still holds, but you have seen it.
 * It returns to OK on its own when the metric drops back under the threshold.
 */
const isAcknowledged = computed(
  (): boolean => props.alert.state === "triggered" && props.alert.unacknowledged_count === 0,
);

const stateLabel = computed((): string => {
  if (!props.alert.enabled) return "Paused";
  if (props.alert.state !== "triggered") return "OK";
  return isAcknowledged.value ? "Acknowledged" : "Firing";
});

/**
 * --destructive is the same 60% lightness in both themes, so a /10 tint left the
 * badge washed out on light and muddy on dark. These pick a readable text weight
 * per theme.
 */
const stateClass = computed((): string => {
  if (!props.alert.enabled) return "bg-muted text-muted-foreground";
  if (props.alert.state !== "triggered") {
    return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
  }
  return isAcknowledged.value
    ? "bg-amber-500/15 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300"
    : "bg-red-500/15 text-red-700 dark:bg-red-500/25 dark:text-red-300";
});

/** Raw floats from the evaluator, e.g. 6186.190128326416, are not readable. */
const observedLabel = computed((): string =>
  formatAlertValue(
    props.alert.last_observed_value,
    props.alert.alert_type,
    costMetricFromConfig(props.alert.config),
  ),
);

function openNotifyWorkflow(event: MouseEvent): void {
  if (!props.alert.notify_workflow_id) return;
  const path = `/workflows/${props.alert.notify_workflow_id}`;
  // Same Ctrl/Cmd convention as the command palette: modified click opens a tab.
  if (isPaletteOpenInNewTab(event)) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
    return;
  }
  router.push(path);
}
</script>

<template>
  <div
    :class="
      cn(
        'group rounded-xl border bg-card p-4 transition-colors duration-200 sm:p-5',
        alert.enabled && alert.state === 'triggered' && !isAcknowledged
          ? 'border-red-500/40'
          : 'border-border hover:border-border/80',
        !alert.enabled && 'opacity-75',
      )
    "
  >
    <!-- Stacks below sm so the actions get a full row instead of being crushed
         against a truncated title. -->
    <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 class="min-w-0 truncate text-base font-semibold tracking-tight">
            {{ alert.name }}
          </h3>
          <span
            :class="
              cn('shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium', stateClass)
            "
          >
            {{ stateLabel }}
          </span>
        </div>

        <p class="mt-1 truncate text-xs text-muted-foreground">
          {{ ALERT_TYPE_LABELS[alert.alert_type] }} · {{ scopeLabel }}
        </p>

        <p class="mt-2 text-sm font-medium tabular-nums">
          {{ alert.condition_summary }}
        </p>

        <p
          v-if="alert.last_observed_value !== null"
          class="mt-1 text-xs text-muted-foreground"
        >
          Currently at <span class="font-medium tabular-nums text-foreground">{{ observedLabel }}</span>
        </p>
      </div>

      <!-- Wraps rather than overflowing; full width on mobile, hugging right above it. -->
      <div class="flex flex-wrap items-center gap-1.5 sm:shrink-0 sm:justify-end">
        <Button
          v-if="alert.notify_workflow_id"
          variant="outline"
          size="sm"
          :title="`Open ${alert.notify_workflow_name ?? 'the workflow this alert runs'} (Ctrl or Cmd click for a new tab)`"
          @click="openNotifyWorkflow"
        >
          <ExternalLink class="h-3.5 w-3.5 sm:mr-1.5" />
          <span class="hidden sm:inline">Go to workflow</span>
          <span class="sr-only sm:hidden">Go to workflow</span>
        </Button>

        <template v-if="alert.is_owner">
          <Button
            variant="outline"
            size="sm"
            :title="alert.enabled ? 'Pause this alert' : 'Resume this alert'"
            @click="emit('toggle', alert)"
          >
            <component
              :is="alert.enabled ? Pause : Play"
              class="h-3.5 w-3.5 sm:mr-1.5"
            />
            <span class="hidden sm:inline">{{ alert.enabled ? "Pause" : "Resume" }}</span>
            <span class="sr-only sm:hidden">{{ alert.enabled ? "Pause" : "Resume" }}</span>
          </Button>

          <div class="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              aria-label="Share alert"
              title="Share alert"
              @click="emit('share', alert)"
            >
              <Share2 class="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Edit alert"
              title="Edit alert"
              @click="emit('edit', alert)"
            >
              <Pencil class="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Delete alert"
              title="Delete alert"
              class="text-muted-foreground hover:text-destructive"
              @click="emit('remove', alert)"
            >
              <Trash2 class="h-4 w-4" />
            </Button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
