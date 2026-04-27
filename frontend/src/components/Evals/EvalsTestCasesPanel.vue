<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { credentialsApi, evalsApi } from "@/services/api";
import { useThemeStore } from "@/stores/theme";
import type { LLMModel } from "@/types/credential";
import type { EvalRun, EvalRunListItem, EvalRunResult, EvalSuite } from "@/types/evals";
import { Plus, Loader2, Trash2 } from "lucide-vue-next";

interface Props {
  suite: EvalSuite;
  currentRun?: EvalRun | null;
  credentialId?: string | null;
  runs?: EvalRunListItem[];
}

const props = withDefaults(defineProps<Props>(), {
  currentRun: undefined,
  credentialId: undefined,
  runs: () => [],
});

const themeStore = useThemeStore();
const isDark = computed(() => themeStore.isDark);

const emit = defineEmits<{
  (e: "suite-updated", suite: EvalSuite): void;
  (e: "run-selected", run: EvalRun | null): void;
  (e: "open-history"): void;
}>();

const isGenerating = ref(false);
const savingTestCaseId = ref<string | null>(null);
const generateDialogOpen = ref(false);
const generateModels = ref<LLMModel[]>([]);
const selectedGenerateModelId = ref<string>("");

watch(
  () => props.credentialId,
  async (id) => {
    if (!id) {
      generateModels.value = [];
      selectedGenerateModelId.value = "";
      return;
    }
    try {
      generateModels.value = await credentialsApi.getModels(id);
      selectedGenerateModelId.value =
        generateModels.value.length > 0 ? generateModels.value[0].id : "";
    } catch {
      generateModels.value = [];
      selectedGenerateModelId.value = "";
    }
  },
  { immediate: true },
);

const isViewingHistory = computed(
  () =>
    !!props.currentRun &&
    (props.currentRun.status === "completed" || props.currentRun.status === "failed"),
);

const isRunInProgress = computed(
  () => props.currentRun?.status === "running",
);

const testCases = computed(() => {
  if (isViewingHistory.value && props.currentRun) {
    const results = props.currentRun.results ?? [];
    if (results.length > 0) {
      const seen = new Set<string>();
      const items: { id: string; input: string; expected_output: string; order_index: number }[] = [];
      let order = 0;
      for (const r of results) {
        const slotId = r.test_case_id ?? r.id;
        if (!seen.has(slotId)) {
          seen.add(slotId);
          items.push({
            id: slotId,
            input: r.input_snapshot ?? "",
            expected_output: r.expected_output_snapshot ?? "",
            order_index: order++,
          });
        }
      }
      return items;
    }
  }
  const cases = props.suite.test_cases ?? [];
  return [...cases].sort((a, b) => a.order_index - b.order_index);
});

const testCasesKey = computed(
  () =>
    `${props.currentRun?.id ?? "editor"}-${testCases.value.map((t) => t.id).join(",")}`,
);

const lastRunDate = computed((): string | null => {
  if (props.runs.length === 0) return null;
  const sorted = [...props.runs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  const latest = sorted[0];
  return latest ? new Date(latest.created_at).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }) : null;
});

const historyChartSeries = computed(() => [
  {
    name: "Accuracy %",
    data: sortedRuns.value.map((r) =>
      r.total_count > 0 ? Math.round((r.pass_count / r.total_count) * 100) : 0,
    ),
  },
]);

function shortRunLabel(name: string): string {
  const match = name.match(/^(.+?)\s*[—–-]\s/);
  return match ? match[1].trim() : name;
}

function formatRunDateFull(createdAt: string): string {
  return new Date(createdAt).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const sortedRuns = computed(() =>
  [...props.runs].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  ),
);

const overallAvg = computed((): number => {
  const list = sortedRuns.value;
  if (list.length === 0) return 0;
  const sum = list.reduce(
    (acc, r) =>
      acc + (r.total_count > 0 ? (r.pass_count / r.total_count) * 100 : 0),
    0,
  );
  return Math.round(sum / list.length);
});

const historyChartCategories = computed(() =>
  sortedRuns.value.map((r) => shortRunLabel(r.name)),
);

async function onChartPointClick(dataPointIndex: number): Promise<void> {
  const run = sortedRuns.value[dataPointIndex];
  if (!run) return;
  emit("open-history");
  try {
    const full = await evalsApi.getRun(run.id);
    emit("run-selected", full);
  } catch {
    emit("run-selected", null);
  }
}

const selectedRunIndex = computed((): number => {
  if (!props.currentRun?.id) return -1;
  return sortedRuns.value.findIndex((r) => r.id === props.currentRun!.id);
});

const chartWrapperRef = ref<HTMLElement | null>(null);

onMounted(() => {
  const unsub = onDismissOverlays(() => {
    generateDialogOpen.value = false;
  });
  onUnmounted(() => unsub());
});

const historyChartOptions = computed(() => {
  const discrete: { seriesIndex: number; dataPointIndex: number; fillColor: string; strokeColor: string; size: number }[] = [];
  if (selectedRunIndex.value >= 0) {
    discrete.push({
      seriesIndex: 0,
      dataPointIndex: selectedRunIndex.value,
      fillColor: "hsl(var(--accent-orange))",
      strokeColor: "hsl(var(--accent-orange))",
      size: 6,
    });
  }
  return {
  chart: {
    type: "line" as const,
    toolbar: { show: false },
    zoom: { enabled: false },
    animations: { enabled: true },
    dynamicAnimation: { enabled: false },
    events: {
      mounted: () => {},
      dataPointSelection: (
        _event: unknown,
        _chartContext: unknown,
        config: { dataPointIndex?: number },
      ) => {
        const idx = config.dataPointIndex;
        if (typeof idx === "number") {
          void onChartPointClick(idx);
        }
      },
    },
  },
  stroke: { curve: "smooth" as const, width: 2 },
  markers: {
    size: 6,
    hover: { size: 8 },
    discrete,
  },
  xaxis: {
    categories: historyChartCategories.value,
    tooltip: { enabled: false },
  },
  yaxis: {
    min: 0,
    max: 100,
    labels: {
      formatter: (val: number) => `${Math.round(val)}%`,
    },
  },
  colors: ["hsl(var(--primary))"],
  theme: {
    mode: isDark.value ? "dark" : "light",
  },
  tooltip: {
    intersect: true,
    shared: false,
    fixed: { enabled: true, position: "topRight" },
    theme: isDark.value ? "dark" : "light",
    custom: ({
      dataPointIndex,
      series,
      seriesIndex,
    }: {
      dataPointIndex: number;
      series: number[][];
      seriesIndex: number;
    }) => {
      const run = sortedRuns.value[dataPointIndex];
      const label = run
        ? `${shortRunLabel(run.name)} · ${formatRunDateFull(run.created_at)}`
        : "";
      const val = series[seriesIndex]?.[dataPointIndex] ?? 0;
      return `<div class="apexcharts-tooltip-box apexcharts-tooltip-candlestick">
        <div>${label}</div>
        <div><strong>${val}%</strong></div>
      </div>`;
    },
  },
};
});

const modelsFromRun = computed(() => props.currentRun?.models ?? []);

function getSnapshotForTestCase(tcId: string): { input: string; expected: string } | null {
  const results = props.currentRun?.results ?? [];
  const first = results.find(
    (r) => r.test_case_id === tcId || r.id === tcId,
  );
  if (!first) return null;
  return {
    input: first.input_snapshot ?? "",
    expected: first.expected_output_snapshot ?? "",
  };
}

function getDisplayInput(tc: { id: string; input: string }): string {
  if (isViewingHistory.value) {
    const snap = getSnapshotForTestCase(tc.id);
    return snap ? snap.input : tc.input;
  }
  return tc.input;
}

function getDisplayExpected(tc: { id: string; expected_output: string }): string {
  if (isViewingHistory.value) {
    const snap = getSnapshotForTestCase(tc.id);
    return snap ? snap.expected : tc.expected_output;
  }
  return tc.expected_output;
}

const contentColumnCount = computed(
  () => 2 + modelsFromRun.value.length,
);
const contentColumnWidth = computed(
  () => `${100 / contentColumnCount.value}%`,
);

function getResultForCell(tcId: string, modelId: string): EvalRunResult | null {
  const results = props.currentRun?.results ?? [];
  const matching = results.filter(
    (r) =>
      (r.test_case_id === tcId || r.id === tcId) && r.model_id === modelId,
  );
  if (matching.length === 0) return null;
  return matching[0];
}

function scoreToPct(score: string): number {
  if (score === "pass") return 100;
  if (score === "fail") return 0;
  if (score === "partial") return 50;
  const n = parseInt(score, 10);
  return Number.isNaN(n) ? 0 : Math.max(0, Math.min(100, n));
}

function getAggregateForCell(tcId: string, modelId: string): string | null {
  const results = props.currentRun?.results ?? [];
  const matching = results.filter(
    (r) =>
      (r.test_case_id === tcId || r.id === tcId) && r.model_id === modelId,
  );
  if (matching.length <= 1) return null;
  const avg = matching.reduce((s, r) => s + scoreToPct(r.score), 0) / matching.length;
  return `${Math.round(avg)}%`;
}

function getScoreClassForCell(tcId: string, modelId: string): string {
  const results = props.currentRun?.results ?? [];
  const matching = results.filter(
    (r) =>
      (r.test_case_id === tcId || r.id === tcId) && r.model_id === modelId,
  );
  if (matching.length === 0) return "bg-muted/20 border-transparent";
  const hasError = matching.some((r) => r.error);
  if (hasError) return "bg-red-500/15 border-red-500/30";
  const avg = matching.reduce((s, r) => s + scoreToPct(r.score), 0) / matching.length;
  if (avg >= 80) return "bg-green-500/15 border-green-500/30";
  if (avg >= 50) return "bg-yellow-500/15 border-yellow-500/30";
  return "bg-red-500/15 border-red-500/30";
}


function formatScore(score: string): string {
  const pct = scoreToPct(score);
  return `${pct}%`;
}

function renderMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr",
      "table", "thead", "tbody", "tr", "th", "td",
    ],
    ALLOWED_ATTR: ["href", "target", "rel"],
  });
}

async function addRow(): Promise<void> {
  try {
    await evalsApi.addTestCase(props.suite.id, {
      input: "",
      expected_output: "",
      input_mode: "text",
      expected_mode: "text",
    });
    const updated = await evalsApi.getSuite(props.suite.id);
    emit("suite-updated", updated);
  } catch (e) {
    console.error("Add test case failed:", e);
  }
}

async function deleteTestCase(tc: { id: string }): Promise<void> {
  try {
    await evalsApi.deleteTestCase(props.suite.id, tc.id);
    const updated = await evalsApi.getSuite(props.suite.id);
    emit("suite-updated", updated);
  } catch (e) {
    console.error("Delete failed:", e);
  }
}

let saveTcTimeout: Record<string, ReturnType<typeof setTimeout>> = {};

function debouncedSaveTc(
  tcId: string,
  field: "input" | "expected_output",
  value: string,
): void {
  if (saveTcTimeout[tcId]) clearTimeout(saveTcTimeout[tcId]);
  saveTcTimeout[tcId] = setTimeout(async () => {
    delete saveTcTimeout[tcId];
    savingTestCaseId.value = tcId;
    try {
      await evalsApi.updateTestCase(props.suite.id, tcId, { [field]: value });
      const updated = await evalsApi.getSuite(props.suite.id);
      emit("suite-updated", updated);
    } catch (e) {
      console.error("Save failed:", e);
    } finally {
      savingTestCaseId.value = null;
    }
  }, 1000);
}

function openGenerateDialog(): void {
  generateDialogOpen.value = true;
  pushOverlayState();
  selectedGenerateModelId.value =
    generateModels.value.length > 0 ? generateModels.value[0].id : "";
}

async function runGenerateTestData(): Promise<void> {
  if (
    !props.suite.id ||
    !props.credentialId ||
    !selectedGenerateModelId.value
  )
    return;
  const model = generateModels.value.find(
    (m) => m.id === selectedGenerateModelId.value,
  );
  if (!model) return;
  isGenerating.value = true;
  try {
    await evalsApi.generateTestData(props.suite.id, {
      credential_id: props.credentialId,
      model: model.id,
      count: 5,
    });
    const updated = await evalsApi.getSuite(props.suite.id);
    emit("suite-updated", updated);
    generateDialogOpen.value = false;
  } catch (e) {
    console.error("Generate failed:", e);
  } finally {
    isGenerating.value = false;
  }
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <div class="p-4 shrink-0 flex items-center justify-between gap-2">
      <h3 class="text-sm font-semibold">
        Performance
        <span
          v-if="runs.length > 0"
          class="font-normal text-muted-foreground ml-1"
        >
          · Overall: {{ overallAvg }}%
        </span>
      </h3>
      <div
        v-if="!isViewingHistory"
        class="flex gap-2"
      >
        <Button
          variant="outline"
          size="sm"
          :disabled="isRunInProgress || isGenerating || !credentialId || !(props.suite.system_prompt?.trim())"
          @click="openGenerateDialog"
        >
          <Loader2
            v-if="isGenerating"
            class="w-4 h-4 animate-spin"
          />
          Generate Test Data
        </Button>
        <Button
          size="sm"
          :disabled="isRunInProgress"
          @click="addRow"
        >
          <Plus class="w-4 h-4" />
          Add Row
        </Button>
      </div>
    </div>
    <!-- Chart outside overflow-auto so tooltip can escape (log evidence: flex-1 overflow-auto clips) -->
    <div
      v-if="runs.length > 0"
      ref="chartWrapperRef"
      class="shrink-0 overflow-visible px-4 -mt-2 pb-1 space-y-1"
    >
      <div class="text-xs font-medium text-muted-foreground -mt-1">
        Last run: {{ lastRunDate }}
      </div>
      <apexchart
        type="line"
        height="180"
        :options="historyChartOptions"
        :series="historyChartSeries"
      />
    </div>
    <div class="flex-1 overflow-auto min-h-0">
      <div
        :key="testCasesKey"
      >
        <h4 class="px-4 pt-1 pb-2 text-sm font-semibold">
          Test Cases
        </h4>
        <table class="w-full border-collapse text-sm table-fixed">
          <colgroup>
            <col class="w-10">
            <col :style="{ width: contentColumnWidth }">
            <col :style="{ width: contentColumnWidth }">
            <col
              v-for="m in modelsFromRun"
              :key="m"
              :style="{ width: contentColumnWidth }"
            >
            <col class="w-10">
          </colgroup>
          <thead class="sticky top-0 bg-background/95 z-10">
            <tr class="border-b border-border/60">
              <th class="w-10 px-2 py-2 text-left font-medium text-muted-foreground">
                #
              </th>
              <th class="px-2 py-2 text-left font-medium text-muted-foreground">
                Input
              </th>
              <th class="px-2 py-2 text-left font-medium text-muted-foreground">
                Expected Output
              </th>
              <th
                v-for="m in modelsFromRun"
                :key="m"
                class="px-2 py-2 text-left font-medium text-muted-foreground"
              >
                {{ m }}
              </th>
              <th class="w-10 px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(tc, idx) in testCases"
              :key="`${currentRun?.id ?? 'editor'}-${tc.id}`"
              class="border-b border-border/40 hover:bg-muted/30 group"
            >
              <td class="px-2 py-2 text-muted-foreground">
                {{ idx + 1 }}
              </td>
              <td class="px-2 py-2 align-top">
                <div
                  v-if="isViewingHistory"
                  class="min-h-[60px] max-h-[60px] rounded-lg border border-border/40 bg-muted/20 px-2 py-1.5 text-xs font-mono whitespace-pre-wrap break-words text-foreground/90 overflow-y-auto"
                >
                  {{ getDisplayInput(tc) || "—" }}
                </div>
                <textarea
                  v-else
                  :value="tc.input"
                  class="w-full min-h-[60px] max-h-[60px] rounded-lg border border-border/60 bg-background px-2 py-1.5 text-xs font-mono resize-none overflow-y-auto focus:outline-none focus:ring-1 focus:ring-primary/40"
                  placeholder="Input..."
                  @input="(e) => debouncedSaveTc(tc.id, 'input', (e.target as HTMLTextAreaElement).value)"
                />
              </td>
              <td class="px-2 py-2 align-top">
                <div
                  v-if="isViewingHistory"
                  class="min-h-[60px] max-h-[60px] rounded-lg border border-border/40 bg-muted/20 px-2 py-1.5 text-xs font-mono whitespace-pre-wrap break-words text-foreground/90 overflow-y-auto"
                >
                  {{ getDisplayExpected(tc) || "—" }}
                </div>
                <textarea
                  v-else
                  :value="tc.expected_output"
                  class="w-full min-h-[60px] max-h-[60px] rounded-lg border border-border/60 bg-background px-2 py-1.5 text-xs font-mono resize-none overflow-y-auto focus:outline-none focus:ring-1 focus:ring-primary/40"
                  placeholder="Expected..."
                  @input="(e) => debouncedSaveTc(tc.id, 'expected_output', (e.target as HTMLTextAreaElement).value)"
                />
              </td>
              <td
                v-for="m in modelsFromRun"
                :key="m"
                class="px-2 py-2 align-top"
              >
                <div
                  v-if="currentRun?.status === 'running' && !getResultForCell(tc.id, m)"
                  class="min-h-[60px] h-[60px] flex items-center justify-center"
                >
                  <Loader2 class="w-4 h-4 animate-spin text-muted-foreground" />
                </div>
                <div
                  v-else
                  :class="[
                    'min-h-[60px] max-h-[60px] rounded-lg border px-2 py-1.5 text-xs relative group/cell overflow-hidden flex flex-col',
                    getResultForCell(tc.id, m)
                      ? getScoreClassForCell(tc.id, m)
                      : 'bg-muted/20 border-transparent'
                  ]"
                >
                  <template v-if="getResultForCell(tc.id, m)">
                    <span class="shrink-0">
                      <template v-if="getResultForCell(tc.id, m)!.error">
                        Error
                      </template>
                      <template v-else>
                        {{ getAggregateForCell(tc.id, m) ?? formatScore(getResultForCell(tc.id, m)!.score) }}
                      </template>
                    </span>
                    <span
                      v-if="getResultForCell(tc.id, m)!.error"
                      class="block mt-1 min-h-0 flex-1 overflow-y-auto text-destructive/90 text-[11px] whitespace-pre-wrap break-words"
                    >
                      {{ getResultForCell(tc.id, m)!.error }}
                    </span>
                    <span
                      v-else-if="getResultForCell(tc.id, m)!.actual_output"
                      class="block mt-1 min-h-0 flex-1 overflow-y-auto text-muted-foreground whitespace-pre-wrap break-words"
                    >
                      {{ getResultForCell(tc.id, m)!.actual_output }}
                    </span>
                    <!-- eslint-disable vue/no-v-html -->
                    <div
                      v-if="getResultForCell(tc.id, m)!.actual_output || getResultForCell(tc.id, m)!.explanation || getResultForCell(tc.id, m)!.error"
                      class="fixed left-1/2 top-1/2 z-[9999] hidden group-hover/cell:block -translate-x-1/2 -translate-y-1/2 w-[min(90vw,900px)] max-h-[85vh] overflow-auto rounded-xl border border-border bg-popover px-6 py-6 text-sm shadow-2xl space-y-4"
                    >
                      <div
                        v-if="getResultForCell(tc.id, m)!.error"
                        class="rounded-lg bg-destructive/10 border border-destructive/30 px-3 py-2 text-xs text-destructive"
                      >
                        <span class="font-medium">Error: </span>
                        {{ getResultForCell(tc.id, m)!.error }}
                      </div>
                      <div
                        v-if="getResultForCell(tc.id, m)!.explanation"
                        class="rounded-lg bg-muted/50 px-3 py-2 text-xs"
                      >
                        <span class="font-medium text-muted-foreground">Evaluation: </span>
                        {{ getResultForCell(tc.id, m)!.explanation }}
                      </div>
                      <div
                        v-if="getResultForCell(tc.id, m)!.actual_output"
                        class="prose prose-sm dark:prose-invert max-w-none prose-p:my-4 prose-ul:my-4 prose-ol:my-4 prose-li:my-2 prose-pre:my-4 prose-code:px-1.5 prose-code:py-0.5 prose-h1:mt-6 prose-h1:mb-4 prose-h2:mt-6 prose-h2:mb-4 prose-h3:mt-5 prose-h3:mb-3 prose-h4:mt-4 prose-h4:mb-2"
                        v-html="renderMarkdown(getResultForCell(tc.id, m)!.actual_output)"
                      />
                    </div>
                  <!-- eslint-enable vue/no-v-html -->
                  </template>
                </div>
              </td>
              <td class="px-2 py-2">
                <button
                  v-if="!isViewingHistory"
                  type="button"
                  class="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/20 text-destructive transition-opacity"
                  @click="deleteTestCase(tc)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div
          v-if="testCases.length === 0"
          class="p-8 text-center text-muted-foreground text-sm"
        >
          No test cases. Add a row or generate test data.
        </div>
      </div>
    </div>

    <Dialog
      :open="generateDialogOpen"
      title="Generate Test Data"
      size="lg"
      @close="generateDialogOpen = false"
    >
      <div class="space-y-4">
        <div>
          <Label class="text-xs font-medium text-muted-foreground mb-2 block">
            Model
          </Label>
          <Select
            v-model="selectedGenerateModelId"
            :options="generateModels.map((m) => ({ value: m.id, label: m.name }))"
            placeholder="Select model"
          />
        </div>
        <div class="flex gap-2 justify-end">
          <Button
            variant="outline"
            @click="generateDialogOpen = false"
          >
            Cancel
          </Button>
          <Button
            :loading="isGenerating"
            :disabled="!selectedGenerateModelId"
            @click="runGenerateTestData"
          >
            Generate
          </Button>
        </div>
      </div>
    </Dialog>
  </div>
</template>