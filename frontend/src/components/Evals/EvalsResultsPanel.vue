<script setup lang="ts">
import { computed, ref, nextTick, watch } from "vue";

import Button from "@/components/ui/Button.vue";
import { evalsApi } from "@/services/api";
import { useThemeStore } from "@/stores/theme";
import type { EvalRun, EvalRunListItem, EvalSuite } from "@/types/evals";
import { History, Download, Trash2 } from "lucide-vue-next";

interface Props {
  suite: EvalSuite;
  currentRun: EvalRun | null;
  runs?: EvalRunListItem[];
  forceShowHistory?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  runs: () => [],
  forceShowHistory: false,
});

const emit = defineEmits<{
  (e: "run-selected", run: EvalRun | null): void;
  (e: "history-open", open: boolean): void;
  (e: "runs-refreshed"): void;
}>();

const themeStore = useThemeStore();
const showHistory = ref(false);
const historySectionRef = ref<HTMLElement | null>(null);
const contentTopRef = ref<HTMLElement | null>(null);

watch(
  () => props.forceShowHistory,
  (v) => {
    if (v) {
      showHistory.value = true;
      void nextTick(() => {
        contentTopRef.value?.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      });
    }
  },
  { immediate: true },
);

const isDark = computed(() => themeStore.isDark);

function scoreToPct(score: string): number {
  if (score === "pass") return 100;
  if (score === "fail") return 0;
  if (score === "partial") return 50;
  const n = parseInt(score, 10);
  return Number.isNaN(n) ? 0 : Math.max(0, Math.min(100, n));
}

const modelSummaries = computed(() => {
  const run = props.currentRun;
  if (!run || !run.results) return [];
  const byModel = new Map<
    string,
    { scores: number[]; total: number; latency: number[]; tokens: number }
  >();
  for (const r of run.results) {
    let s = byModel.get(r.model_id);
    if (!s) {
      s = { scores: [], total: 0, latency: [], tokens: 0 };
      byModel.set(r.model_id, s);
    }
    s.total++;
    s.scores.push(scoreToPct(r.score));
    if (r.latency_ms != null) s.latency.push(r.latency_ms);
    if (r.tokens_used != null) s.tokens += r.tokens_used;
  }
  return Array.from(byModel.entries()).map(([model, s]) => {
    const avgAccuracy =
      s.scores.length > 0
        ? s.scores.reduce((a, b) => a + b, 0) / s.scores.length
        : 0;
    const passCount = s.scores.filter((p) => p >= 50).length;
    return {
      model,
      avgAccuracy,
      passCount,
      total: s.total,
      avgLatency:
        s.latency.length > 0
          ? s.latency.reduce((a, b) => a + b, 0) / s.latency.length
          : null,
      tokens: s.tokens,
    };
  });
});

const accuracyChartOptions = computed(() => ({
  chart: { type: "bar" as const },
  plotOptions: {
    bar: { horizontal: true, barHeight: "60%" },
  },
  xaxis: {
    categories: modelSummaries.value.map((s) => s.model),
    max: 100,
  },
  dataLabels: { enabled: false },
  colors: ["hsl(var(--primary))"],
  theme: {
    mode: isDark.value ? "dark" : "light",
  },
  tooltip: {
    theme: isDark.value ? "dark" : "light",
  },
}));

const passRateSeries = computed(() => [
  {
    name: "Accuracy %",
    data: modelSummaries.value.map((s) => Math.round(s.avgAccuracy)),
  },
]);

const latencyChartOptions = computed(() => ({
  chart: { type: "bar" as const },
  plotOptions: {
    bar: { horizontal: true, barHeight: "60%" },
  },
  xaxis: {
    categories: modelSummaries.value.map((s) => s.model),
  },
  dataLabels: { enabled: false },
  colors: ["hsl(var(--accent-orange))"],
  theme: {
    mode: isDark.value ? "dark" : "light",
  },
  tooltip: {
    theme: isDark.value ? "dark" : "light",
  },
}));

const latencySeries = computed(() => [
  {
    name: "Avg Latency (ms)",
    data: modelSummaries.value.map((s) =>
      s.avgLatency != null ? Math.round(s.avgLatency) : 0,
    ),
  },
]);

function toggleHistory(): void {
  showHistory.value = !showHistory.value;
  if (showHistory.value) {
    void nextTick(() => {
      historySectionRef.value?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    });
  }
  emit("history-open", showHistory.value);
}

async function selectRun(run: EvalRunListItem): Promise<void> {
  try {
    const full = await evalsApi.getRun(run.id);
    emit("run-selected", full);
  } catch {
    emit("run-selected", null);
  }
}

async function exportResults(): Promise<void> {
  const run = props.currentRun;
  if (!run) return;
  const blob = new Blob([JSON.stringify(run, null, 2)], {
    type: "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `eval-run-${run.id}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function deleteRun(run: EvalRunListItem): Promise<void> {
  try {
    await evalsApi.deleteRun(run.id);
    if (props.currentRun?.id === run.id) {
      emit("run-selected", null);
    }
    emit("runs-refreshed");
  } catch (e) {
    console.error("Delete run failed:", e);
  }
}

async function clearAllRuns(): Promise<void> {
  if (!props.suite.id || !confirm("Clear all run history for this suite?")) return;
  try {
    await evalsApi.clearAllRuns(props.suite.id);
    emit("run-selected", null);
    emit("runs-refreshed");
  } catch (e) {
    console.error("Clear all runs failed:", e);
  }
}

function formatScoringMethod(method: string): string {
  const labels: Record<string, string> = {
    exact_match: "Exact Match",
    contains: "Contains",
    llm_judge: "LLM-as-Judge",
  };
  return labels[method] ?? method;
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <div class="p-4 border-b border-border/40 shrink-0 flex items-center justify-between">
      <h3 class="text-sm font-semibold">
        Results
      </h3>
      <div class="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          @click="toggleHistory"
        >
          <History class="w-4 h-4" />
          History
        </Button>
        <Button
          v-if="currentRun"
          variant="outline"
          size="sm"
          @click="exportResults"
        >
          <Download class="w-4 h-4" />
          Export
        </Button>
      </div>
    </div>
    <div class="flex-1 overflow-auto p-4 space-y-4">
      <div
        ref="contentTopRef"
      />
      <div
        v-if="!currentRun"
        class="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm"
      >
        Run evals to see results here
      </div>
      <template v-else>
        <div class="grid gap-3">
          <div
            v-for="s in modelSummaries"
            :key="s.model"
            class="rounded-xl border border-border/60 bg-card p-4"
          >
            <div class="font-medium text-sm">
              {{ s.model }}
            </div>
            <div class="mt-2 flex gap-4 text-xs text-muted-foreground">
              <span>Accuracy: {{ Math.round(s.avgAccuracy) }}% ({{ s.passCount }}/{{ s.total }} ≥50%)</span>
              <span v-if="s.avgLatency != null">Avg latency: {{ Math.round(s.avgLatency) }}ms</span>
              <span v-if="s.tokens > 0">Tokens: {{ s.tokens }}</span>
            </div>
          </div>
        </div>
        <div
          v-if="modelSummaries.length > 0"
          class="space-y-4"
        >
          <div>
            <h4 class="text-xs font-medium text-muted-foreground mb-2">
              Accuracy %
            </h4>
            <apexchart
              type="bar"
              height="180"
              :options="accuracyChartOptions"
              :series="passRateSeries"
            />
          </div>
          <div>
            <h4 class="text-xs font-medium text-muted-foreground mb-2">
              Latency (ms)
            </h4>
            <apexchart
              type="bar"
              height="180"
              :options="latencyChartOptions"
              :series="latencySeries"
            />
          </div>
        </div>
      </template>

      <div
        v-if="showHistory"
        ref="historySectionRef"
        class="border-t border-border/40 pt-4 mt-4"
      >
        <div class="flex items-center justify-between mb-2">
          <h4 class="text-xs font-medium text-muted-foreground">
            Run History
          </h4>
          <Button
            v-if="runs.length > 0"
            variant="ghost"
            size="sm"
            class="text-xs text-destructive hover:text-destructive"
            @click="clearAllRuns"
          >
            Clear all
          </Button>
        </div>
        <ul class="space-y-2">
          <li
            v-for="r in runs"
            :key="r.id"
            class="flex items-center justify-between gap-2 rounded-lg border border-border/60 px-3 py-2 hover:bg-muted/30 cursor-pointer group"
            :class="{ 'ring-1 ring-primary/40': currentRun?.id === r.id }"
            @click="selectRun(r)"
          >
            <div class="min-w-0 flex-1">
              <div class="text-sm font-medium truncate">
                {{ r.name }}
              </div>
              <div class="text-xs text-muted-foreground">
                {{ r.models.join(", ") }} · {{ r.pass_count }}/{{ r.total_count }} (≥50%)
                <span
                  v-if="r.scoring_method"
                  class="ml-1"
                >· {{ formatScoringMethod(r.scoring_method) }}</span>
              </div>
            </div>
            <div class="flex gap-1 opacity-0 group-hover:opacity-100">
              <button
                type="button"
                class="p-1 rounded hover:bg-muted text-muted-foreground"
                title="Delete"
                @click.stop="deleteRun(r)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
