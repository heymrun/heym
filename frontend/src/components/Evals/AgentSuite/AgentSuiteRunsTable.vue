<script setup lang="ts">
import { CheckCircle2, ExternalLink, XCircle } from "lucide-vue-next";

import {
  TOOL_KIND_LABELS,
  formatCount,
  formatMs,
  formatRunTime,
  formatUsd,
  toolKey,
  traceLink,
} from "@/components/Evals/AgentSuite/agentSuiteFormat";
import type { AgentRun, AgentRunEvaluation } from "@/types/evals";

interface Props {
  runs: (AgentRun | AgentRunEvaluation)[];
}

defineProps<Props>();

function isEvaluated(run: AgentRun | AgentRunEvaluation): run is AgentRunEvaluation {
  return "passed" in run;
}

function failedChecks(run: AgentRun | AgentRunEvaluation): string[] {
  if (!isEvaluated(run)) return run.error ? [run.error] : [];
  return run.checks
    .filter((check) => check.status === "fail")
    .map((check) => (check.detail ? `${check.label} (${check.detail})` : check.label));
}

interface ToolChip {
  key: string;
  text: string;
  count: number;
  failed: boolean;
}

function uniqueTools(run: AgentRun): ToolChip[] {
  const byKey = new Map<string, ToolChip>();
  for (const call of run.tool_calls) {
    const key = toolKey(call.kind, call.name);
    const prefix = call.kind === "tool" ? "" : `${TOOL_KIND_LABELS[call.kind]} · `;
    const entry = byKey.get(key) ?? { key, text: `${prefix}${call.label}`, count: 0, failed: false };
    entry.count += 1;
    entry.failed = entry.failed || call.status !== "success";
    byKey.set(key, entry);
  }
  return [...byKey.values()];
}
</script>

<template>
  <div class="overflow-x-auto rounded-xl border border-border/60">
    <table class="w-full min-w-[720px] text-sm">
      <thead class="bg-muted/40 text-xs text-muted-foreground">
        <tr>
          <th class="px-3 py-2 text-left font-medium">
            Run
          </th>
          <th class="px-3 py-2 text-right font-medium">
            Latency
          </th>
          <th class="px-3 py-2 text-right font-medium">
            Cost
          </th>
          <th class="px-3 py-2 text-right font-medium">
            Tokens
          </th>
          <th class="px-3 py-2 text-left font-medium">
            Tool calls
          </th>
          <th class="w-10 px-3 py-2" />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="run in runs"
          :key="run.trace_id"
          class="border-t border-border/40 align-top"
          data-testid="agent-suite-run-row"
        >
          <td class="px-3 py-2">
            <div class="flex items-center gap-2">
              <template v-if="isEvaluated(run)">
                <CheckCircle2
                  v-if="run.passed"
                  class="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
                />
                <XCircle
                  v-else
                  class="h-4 w-4 shrink-0 text-destructive"
                />
              </template>
              <span class="whitespace-nowrap text-foreground">{{ formatRunTime(run.created_at) }}</span>
            </div>
            <p class="mt-0.5 truncate text-xs text-muted-foreground">
              {{ run.model ?? "—" }}
            </p>
            <p
              v-for="reason in failedChecks(run)"
              :key="reason"
              class="mt-1 max-w-[18rem] break-words text-xs text-destructive"
            >
              {{ reason }}
            </p>
          </td>
          <td class="px-3 py-2 text-right tabular-nums">
            {{ formatMs(run.latency_ms) }}
            <p class="text-xs text-muted-foreground">
              {{ formatMs(run.model_ms) }} model · {{ formatMs(run.tool_ms) }} tools
            </p>
          </td>
          <td class="px-3 py-2 text-right tabular-nums">
            {{ run.cost_usd === null ? "Unpriced" : formatUsd(run.cost_usd) }}
          </td>
          <td class="px-3 py-2 text-right tabular-nums">
            {{ formatCount(run.total_tokens) }}
          </td>
          <td class="px-3 py-2">
            <span class="mr-2 font-medium tabular-nums">{{ run.tool_count }}</span>
            <span
              v-for="tool in uniqueTools(run)"
              :key="tool.key"
              class="mb-1 mr-1 inline-flex items-center rounded-md px-1.5 py-0.5 text-xs"
              :class="tool.failed ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground'"
            >
              {{ tool.text }}<template v-if="tool.count > 1"> ×{{ tool.count }}</template>
            </span>
          </td>
          <td class="px-3 py-2">
            <RouterLink
              :to="traceLink(run.trace_id)"
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
              title="Open trace"
            >
              <ExternalLink class="h-3.5 w-3.5" />
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
