<script setup lang="ts">
import AgentSuiteMetricTile from "@/components/Evals/AgentSuite/AgentSuiteMetricTile.vue";
import AgentSuiteRunsTable from "@/components/Evals/AgentSuite/AgentSuiteRunsTable.vue";
import {
  TOOL_KIND_LABELS,
  formatCount,
  formatMs,
  formatUsd,
} from "@/components/Evals/AgentSuite/agentSuiteFormat";
import type { AgentMetrics } from "@/types/evals";

interface Props {
  metrics: AgentMetrics | null;
  loading: boolean;
  error: string | null;
}

defineProps<Props>();
</script>

<template>
  <div class="space-y-5">
    <p
      v-if="loading"
      class="text-sm text-muted-foreground"
    >
      Reading the agent's latest runs...
    </p>
    <p
      v-else-if="error"
      class="text-sm text-destructive"
    >
      {{ error }}
    </p>
    <template v-else-if="metrics">
      <p class="text-sm text-muted-foreground">
        From the last {{ metrics.runs.length }} runs of
        <span class="font-medium text-foreground">{{ metrics.node_label }}</span>.
        <template v-if="metrics.baseline.error_count > 0">
          {{ metrics.baseline.error_count }} ended in an error and are left out of the numbers.
        </template>
      </p>

      <div
        v-if="metrics.runs.length === 0"
        class="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground"
      >
        This agent has no runs yet. Run the workflow, then come back to set its baseline.
      </div>

      <template v-else>
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <AgentSuiteMetricTile
            label="Latency p95"
            :value="formatMs(metrics.baseline.latency_p95_ms)"
            :sub="`p50 ${formatMs(metrics.baseline.latency_p50_ms)}`"
            test-id="agent-suite-baseline-latency"
          />
          <AgentSuiteMetricTile
            label="Cost per run"
            :value="formatUsd(metrics.baseline.cost_avg_usd)"
            :sub="metrics.baseline.unpriced_models.length > 0
              ? `Unpriced: ${metrics.baseline.unpriced_models.join(', ')}`
              : `p95 ${formatUsd(metrics.baseline.cost_p95_usd)}`"
          />
          <AgentSuiteMetricTile
            label="Tokens per run"
            :value="formatCount(metrics.baseline.tokens_avg)"
            :sub="`p95 ${formatCount(metrics.baseline.tokens_p95)}`"
          />
          <AgentSuiteMetricTile
            label="Tool calls per run"
            :value="formatCount(metrics.baseline.tool_calls_avg, 1)"
            :sub="`max ${formatCount(metrics.baseline.tool_calls_max)}`"
          />
        </div>

        <div>
          <h3 class="mb-2 text-sm font-medium text-foreground">
            Tools
          </h3>
          <div class="overflow-x-auto rounded-xl border border-border/60">
            <table class="w-full min-w-[520px] text-sm">
              <thead class="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th class="px-3 py-2 text-left font-medium">
                    Tool
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Runs that called it
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Calls
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Failed
                  </th>
                  <th class="px-3 py-2 text-right font-medium">
                    Avg time
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="tool in metrics.tools"
                  :key="`${tool.kind}:${tool.name}`"
                  class="border-t border-border/40"
                >
                  <td class="px-3 py-2">
                    <span class="mr-2 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{{ TOOL_KIND_LABELS[tool.kind] }}</span>
                    <span class="font-mono text-xs text-foreground">{{ tool.label }}</span>
                    <span
                      v-if="tool.server"
                      class="ml-1 text-xs text-muted-foreground"
                    >({{ tool.server }})</span>
                    <span
                      v-if="tool.configured && tool.call_count === 0"
                      class="ml-2 text-xs text-muted-foreground"
                    >not called yet</span>
                  </td>
                  <td class="px-3 py-2 text-right tabular-nums">
                    {{ tool.runs_called }}/{{ metrics.runs.length }}
                  </td>
                  <td class="px-3 py-2 text-right tabular-nums">
                    {{ tool.call_count }}
                  </td>
                  <td
                    class="px-3 py-2 text-right tabular-nums"
                    :class="tool.error_count > 0 ? 'text-destructive' : ''"
                  >
                    {{ tool.error_count }}
                  </td>
                  <td class="px-3 py-2 text-right tabular-nums">
                    {{ formatMs(tool.avg_ms) }}
                  </td>
                </tr>
                <tr v-if="metrics.tools.length === 0">
                  <td
                    colspan="5"
                    class="px-3 py-4 text-center text-xs text-muted-foreground"
                  >
                    No tool calls in these runs.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 class="mb-2 text-sm font-medium text-foreground">
            Runs
          </h3>
          <AgentSuiteRunsTable :runs="metrics.runs" />
        </div>
      </template>
    </template>
  </div>
</template>
