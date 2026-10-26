<script setup lang="ts">
import { RefreshCw } from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import AgentSuiteMetricTile from "@/components/Evals/AgentSuite/AgentSuiteMetricTile.vue";
import AgentSuiteRunsTable from "@/components/Evals/AgentSuite/AgentSuiteRunsTable.vue";
import {
  RUN_LIMIT_OPTIONS,
  apiErrorText,
  formatCount,
  formatMs,
  formatUsd,
} from "@/components/Evals/AgentSuite/agentSuiteFormat";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import { evalsApi } from "@/services/api";
import type { AgentDeltaMetric, AgentMetricDelta, AgentSuiteReport } from "@/types/evals";

interface Props {
  suiteId: string;
  /** Bumped by the parent after the checks change, to score the runs again. */
  reloadKey?: number;
  /** The latest finished press of Run; its runs are scored by default. */
  runId?: string | null;
}

const props = withDefaults(defineProps<Props>(), { reloadKey: 0, runId: null });

const SUITE_SCOPE = "suite";
const DEFAULT_SCOPE = String(RUN_LIMIT_OPTIONS[0]);

const report = ref<AgentSuiteReport | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const scope = ref(props.runId ? SUITE_SCOPE : DEFAULT_SCOPE);

const scopeOptions = computed(() => [
  ...(props.runId ? [{ value: SUITE_SCOPE, label: "Latest suite run" }] : []),
  ...RUN_LIMIT_OPTIONS.map((value) => ({ value: String(value), label: `Last ${value} runs` })),
]);

const TILES: { metric: AgentDeltaMetric; label: string; format: (v: number | null) => string }[] = [
  { metric: "latency_p95_ms", label: "Latency p95", format: formatMs },
  { metric: "cost_avg_usd", label: "Cost per run", format: formatUsd },
  { metric: "tokens_avg", label: "Tokens per run", format: (v) => formatCount(v) },
  { metric: "tool_calls_avg", label: "Tool calls per run", format: (v) => formatCount(v, 1) },
];

const deltaByMetric = computed(
  () => new Map<string, AgentMetricDelta>((report.value?.deltas ?? []).map((d) => [d.metric, d])),
);

function checkTotal(passed: number, failed: number): number {
  return passed + failed;
}

async function loadReport(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const fromRun = scope.value === SUITE_SCOPE && props.runId;
    report.value = await evalsApi.getAgentSuiteReport(
      props.suiteId,
      fromRun ? undefined : Number(scope.value),
      fromRun ? props.runId : null,
    );
  } catch (e: unknown) {
    error.value = apiErrorText(e, "Could not load the report.");
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.runId,
  (runId) => {
    if (runId) scope.value = SUITE_SCOPE;
    else if (scope.value === SUITE_SCOPE) scope.value = DEFAULT_SCOPE;
  },
);

watch([() => props.suiteId, () => props.reloadKey, () => props.runId, scope], loadReport, {
  immediate: true,
});
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div
        v-if="report"
        class="flex items-baseline gap-3"
      >
        <span
          class="text-3xl font-semibold tabular-nums text-foreground"
          data-testid="agent-suite-pass-rate"
        >
          {{ report.pass_rate === null ? "—" : `${report.pass_rate}%` }}
        </span>
        <span class="text-sm text-muted-foreground">
          {{ report.passed_count }} of {{ report.run_count }} runs passed
        </span>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Select
          v-model="scope"
          :options="scopeOptions"
          class="w-44"
          data-testid="agent-suite-report-scope"
        />
        <Button
          variant="outline"
          size="icon"
          title="Refresh"
          :loading="loading"
          @click="loadReport"
        >
          <RefreshCw class="h-4 w-4" />
        </Button>
      </div>
    </div>

    <p
      v-if="error"
      class="text-sm text-destructive"
    >
      {{ error }}
    </p>

    <template v-if="report">
      <div
        v-if="report.run_count === 0"
        class="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground"
      >
        <template v-if="scope === SUITE_SCOPE">
          None of these runs reached the agent.
        </template>
        <template v-else>
          No runs to score yet. Run the workflow above, or wait for the agent's next run.
        </template>
      </div>
      <template v-else>
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <AgentSuiteMetricTile
            v-for="tile in TILES"
            :key="tile.metric"
            :label="tile.label"
            :value="tile.format(deltaByMetric.get(tile.metric)?.current ?? null)"
            :sub="`Baseline ${tile.format(deltaByMetric.get(tile.metric)?.baseline ?? null)}`"
            :delta-pct="deltaByMetric.get(tile.metric)?.delta_pct ?? null"
          />
        </div>

        <div>
          <h3 class="mb-2 text-sm font-medium text-foreground">
            Checks
          </h3>
          <div class="divide-y divide-border/40 rounded-xl border border-border/60">
            <div
              v-for="check in report.checks"
              :key="check.key"
              class="flex items-center gap-3 px-3 py-2.5"
              data-testid="agent-suite-check-row"
            >
              <span class="min-w-0 flex-1 truncate text-sm text-foreground">{{ check.label }}</span>
              <div class="hidden h-1.5 w-32 overflow-hidden rounded-full bg-muted sm:block">
                <div
                  class="h-full rounded-full"
                  :class="check.failed > 0 ? 'bg-destructive' : 'bg-emerald-500'"
                  :style="{
                    width: `${checkTotal(check.passed, check.failed) === 0 ? 0 : (check.passed / checkTotal(check.passed, check.failed)) * 100}%`,
                  }"
                />
              </div>
              <span class="w-20 text-right text-xs tabular-nums text-muted-foreground">
                {{ check.passed }}/{{ checkTotal(check.passed, check.failed) }} passed
              </span>
              <span
                v-if="check.skipped > 0"
                class="text-xs text-muted-foreground"
              >
                {{ check.skipped }} skipped
              </span>
            </div>
          </div>
        </div>

        <div>
          <h3 class="mb-2 text-sm font-medium text-foreground">
            Runs
          </h3>
          <AgentSuiteRunsTable :runs="report.runs" />
        </div>
      </template>
    </template>
  </div>
</template>
