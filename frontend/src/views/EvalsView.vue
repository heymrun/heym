<script setup lang="ts">
import AppHeader from "@/components/Layout/AppHeader.vue";
import DashboardNav from "@/components/Layout/DashboardNav.vue";
import WorkspaceShell from "@/components/Layout/WorkspaceShell.vue";
import ExecutionHistoryAllDialog from "@/components/Panels/ExecutionHistoryAllDialog.vue";
import EvalsLeftPanel from "@/components/Evals/EvalsLeftPanel.vue";
import EvalsResultsPanel from "@/components/Evals/EvalsResultsPanel.vue";
import EvalsTestCasesPanel from "@/components/Evals/EvalsTestCasesPanel.vue";
import ResizablePanels from "@/components/Evals/ResizablePanels.vue";
import { resolveShowcaseContext } from "@/features/showcase/showcaseResolver";
import WorkflowCommandPalette from "@/components/Dialogs/WorkflowCommandPalette.vue";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import { History, Plus, Trash2, Pencil } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { getDocPath } from "@/docs/manifest";
import { joinOriginAndPath } from "@/lib/appUrl";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import { evalsApi, workflowApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import type { WorkflowListItem } from "@/types/workflow";
import type {
  EvalRun,
  EvalRunListItem,
  EvalSuite,
  EvalSuiteListItem,
  ReasoningEffort,
} from "@/types/evals";

const suites = ref<EvalSuiteListItem[]>([]);
const runs = ref<EvalRunListItem[]>([]);
const selectedSuiteId = ref<string | null>(null);
const suiteDetail = ref<EvalSuite | null>(null);
const loading = ref(true);
const selectedCredentialId = ref<string | null>(null);
const currentRun = ref<EvalRun | null>(null);
const historyOpen = ref(false);
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const { addRecent } = useRecentWorkflows();

const workflows = ref<WorkflowListItem[]>([]);
const showCommandPalette = ref(false);
const showcaseContext = computed(() => {
  return resolveShowcaseContext({ routePath: route.path });
});

const selectedSuite = computed(() => suiteDetail.value);

function isTypingTarget(target: EventTarget | null): boolean {
  if (!target) return false;
  const element = target as HTMLElement;
  return (
    element.tagName === "INPUT" ||
    element.tagName === "TEXTAREA" ||
    element.isContentEditable ||
    element.closest("input, textarea, [contenteditable]") !== null
  );
}

function handleKeyDown(event: KeyboardEvent): void {
  const isTyping = isTypingTarget(event.target);
  const isMeta = event.metaKey || event.ctrlKey;

  if (isMeta && event.key === "k" && !isTyping) {
    event.preventDefault();
    showCommandPalette.value = true;
    pushOverlayState();
  }
}

function openWorkflowFromPalette(workflowId: string, event?: MouseEvent): void {
  showCommandPalette.value = false;
  const workflow = workflows.value.find((w) => w.id === workflowId);
  if (workflow) {
    addRecent(workflowId, workflow.name);
  }
  if (event && (event.ctrlKey || event.metaKey)) {
    const resolved = router.resolve({ name: "editor", params: { id: workflowId } });
    window.open(resolved.href, "_blank");
  } else {
    router.push({ name: "editor", params: { id: workflowId } });
  }
}

function handleTabSelectFromPalette(tabId: string, event?: MouseEvent): void {
  showCommandPalette.value = false;
  const openInNewTab = event && (event.ctrlKey || event.metaKey);
  if (tabId === "evals") {
    if (openInNewTab) {
      window.open(joinOriginAndPath(window.location.origin, "/evals"), "_blank", "noopener,noreferrer");
    }
    return;
  }
  if (openInNewTab) {
    const path = tabId === "workflows" ? "/" : `/?tab=${tabId}`;
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else if (tabId === "workflows") {
    router.push("/");
  } else {
    router.push({ path: "/", query: { tab: tabId } });
  }
}

function onDocSelectFromPalette(categoryId: string, slug: string, event?: MouseEvent): void {
  showCommandPalette.value = false;
  const path = getDocPath(categoryId, slug);
  if (event && (event.ctrlKey || event.metaKey)) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else {
    router.push(path);
  }
}

const initialTemperature = computed(() => {
  const t = route.query.temperature;
  if (typeof t !== "string") return undefined;
  const parsed = parseFloat(t);
  return Number.isNaN(parsed) ? undefined : parsed;
});

const initialReasoningEffort = computed((): ReasoningEffort | undefined => {
  const r = route.query.reasoning_effort;
  if (typeof r !== "string") return undefined;
  if (["low", "medium", "high"].includes(r)) return r as ReasoningEffort;
  return undefined;
});

async function loadSuites(): Promise<void> {
  loading.value = true;
  try {
    suites.value = await evalsApi.listSuites();
    const querySuiteId = route.query.suite as string | undefined;
    if (querySuiteId && suites.value.some((s) => s.id === querySuiteId)) {
      selectedSuiteId.value = querySuiteId;
    } else if (suites.value.length > 0 && !selectedSuiteId.value) {
      selectedSuiteId.value = suites.value[0].id;
    }
  } finally {
    loading.value = false;
  }
}

async function loadSuiteDetail(): Promise<void> {
  if (!selectedSuiteId.value) {
    suiteDetail.value = null;
    return;
  }
  try {
    suiteDetail.value = await evalsApi.getSuite(selectedSuiteId.value);
  } catch {
    suiteDetail.value = null;
  }
}

watch(selectedSuiteId, loadSuiteDetail, { immediate: true });

async function loadRuns(): Promise<void> {
  if (!selectedSuiteId.value) {
    runs.value = [];
    return;
  }
  try {
    runs.value = await evalsApi.listRuns(selectedSuiteId.value);
  } catch {
    runs.value = [];
  }
}

watch(selectedSuiteId, loadRuns, { immediate: true });

async function createSuite(): Promise<void> {
  try {
    const suite = await evalsApi.createSuite({
      name: "New Eval Suite",
      description: "",
      system_prompt: "",
      scoring_method: "exact_match",
    });
    suites.value = [
      ...suites.value,
      {
        id: suite.id,
        name: suite.name,
        description: suite.description,
        created_at: suite.created_at,
      },
    ];
    selectedSuiteId.value = suite.id;
    suiteDetail.value = suite;
  } catch (e) {
    console.error("Failed to create suite:", e);
  }
}

async function deleteSuite(): Promise<void> {
  if (!selectedSuiteId.value) return;
  if (!confirm("Are you sure you want to delete this eval suite? This cannot be undone.")) return;

  try {
    await evalsApi.deleteSuite(selectedSuiteId.value);
    const idx = suites.value.findIndex((s) => s.id === selectedSuiteId.value);
    suites.value = suites.value.filter((s) => s.id !== selectedSuiteId.value);
    selectedSuiteId.value = null;
    suiteDetail.value = null;
    if (suites.value.length > 0) {
      const nextIdx = Math.min(idx, suites.value.length - 1);
      selectedSuiteId.value = suites.value[nextIdx >= 0 ? nextIdx : 0].id;
    }
  } catch (e) {
    console.error("Failed to delete suite:", e);
  }
}

function onSuiteUpdated(updated: EvalSuite): void {
  suiteDetail.value = updated;
  const idx = suites.value.findIndex((s) => s.id === updated.id);
  if (idx >= 0) {
    suites.value = [
      ...suites.value.slice(0, idx),
      {
        ...suites.value[idx],
        name: updated.name,
        description: updated.description,
      },
      ...suites.value.slice(idx + 1),
    ];
  }
}

function onCredentialChanged(id: string): void {
  selectedCredentialId.value = id;
}

function onRunCompleted(run: EvalRun): void {
  currentRun.value = run;
  void loadRuns();
}

function onRunSelected(run: EvalRun | null): void {
  currentRun.value = run;
}

const showHistoryInPanel = ref(false);

const showEditButton = computed(
  () =>
    !!currentRun.value &&
    (currentRun.value.status === "completed" || currentRun.value.status === "failed"),
);

const resultsPanelKey = ref(0);

function switchToEditor(): void {
  historyOpen.value = false;
  showHistoryInPanel.value = false;
  currentRun.value = null;
  resultsPanelKey.value++;
}

async function loadWorkflows(): Promise<void> {
  try {
    workflows.value = await workflowApi.list();
  } catch {
    workflows.value = [];
  }
}

onMounted(async () => {
  await authStore.fetchUser();
  await Promise.all([loadSuites(), loadWorkflows()]);
  window.addEventListener("keydown", handleKeyDown);
  const unsub = onDismissOverlays(() => {
    historyOpen.value = false;
    showHistoryInPanel.value = false;
    showCommandPalette.value = false;
  });
  onUnmounted(() => unsub());
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeyDown);
});
</script>

<template>
  <WorkspaceShell :showcase-context="showcaseContext">
    <div class="h-screen flex flex-col bg-background overflow-hidden">
      <AppHeader :on-open-command-palette="() => { showCommandPalette = true; pushOverlayState(); }">
        <template #actions>
          <Button
            variant="ghost"
            size="sm"
            class="gap-2 min-h-[44px] min-w-[44px] sm:min-w-auto text-foreground"
            @click="historyOpen = true; pushOverlayState()"
          >
            <History class="w-4 h-4" />
            <span class="hidden sm:inline">History</span>
          </Button>
        </template>
      </AppHeader>
      <main class="dashboard-main flex-1 flex flex-col min-h-0 overflow-hidden px-3 sm:px-4 py-4 sm:py-6 md:py-8">
        <div class="absolute top-0 left-0 right-0 h-[500px] pointer-events-none overflow-hidden">
          <div class="absolute inset-0 bg-gradient-to-b from-primary/[0.03] via-transparent to-transparent" />
          <div class="absolute inset-0 bg-dots-pattern opacity-30" />
        </div>
        <div class="w-full max-w-7xl mx-auto relative flex-1 flex flex-col min-h-0">
          <DashboardNav />
          <div
            v-if="suites.length > 0"
            class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4"
          >
            <div class="flex items-center gap-2 min-w-[12rem]">
              <Select
                :model-value="selectedSuiteId ?? undefined"
                :options="suites.map((s) => ({ value: s.id, label: s.name }))"
                placeholder="Select suite"
                class="min-w-[12rem]"
                @update:model-value="(v) => (selectedSuiteId = v ?? null)"
              />
              <Button
                v-if="selectedSuiteId"
                variant="ghost"
                size="icon"
                class="min-h-[44px] min-w-[44px] text-muted-foreground hover:text-destructive shrink-0"
                title="Delete suite"
                @click="deleteSuite"
              >
                <Trash2 class="w-4 h-4" />
              </Button>
            </div>
            <div class="flex gap-2">
              <Button
                v-if="showEditButton"
                variant="outline"
                class="gap-2 min-h-[44px] shrink-0"
                @click="switchToEditor"
              >
                <Pencil class="w-4 h-4" />
                Edit
              </Button>
              <Button
                variant="gradient"
                class="gap-2 min-h-[44px] shrink-0"
                @click="createSuite"
              >
                <Plus class="w-4 h-4" />
                New Suite
              </Button>
            </div>
          </div>
          <div
            v-if="loading"
            class="flex-1 flex items-center justify-center text-muted-foreground min-h-[200px]"
          >
            Loading...
          </div>
          <ResizablePanels
            v-else-if="selectedSuite"
            class="flex-1 min-h-0 overflow-hidden"
          >
            <template #left>
              <EvalsLeftPanel
                :suite="selectedSuite"
                :current-run="currentRun"
                :is-run-in-progress="currentRun?.status === 'running'"
                :show-edit-button="showEditButton"
                :initial-temperature="initialTemperature"
                :initial-reasoning-effort="initialReasoningEffort"
                @suite-updated="onSuiteUpdated"
                @run-completed="onRunCompleted"
                @credential-changed="onCredentialChanged"
              />
            </template>
            <template #center>
              <EvalsTestCasesPanel
                :suite="selectedSuite"
                :current-run="currentRun"
                :credential-id="selectedCredentialId"
                :runs="runs"
                @suite-updated="onSuiteUpdated"
                @run-selected="onRunSelected"
                @open-history="showHistoryInPanel = true"
              />
            </template>
            <template #right>
              <EvalsResultsPanel
                :key="resultsPanelKey"
                :suite="selectedSuite"
                :current-run="currentRun"
                :runs="runs"
                :force-show-history="showHistoryInPanel"
                @run-selected="onRunSelected"
                @history-open="showHistoryInPanel = $event"
                @runs-refreshed="loadRuns"
              />
            </template>
          </ResizablePanels>
          <div
            v-else
            class="flex-1 flex flex-col items-center justify-center gap-4 text-muted-foreground min-h-[200px]"
          >
            <p class="text-base">
              Create a suite to get started
            </p>
            <Button
              variant="default"
              size="lg"
              class="gap-2"
              @click="createSuite"
            >
              <Plus class="w-4 h-4" />
              Create your first suite
            </Button>
          </div>
        </div>
      </main>

      <ExecutionHistoryAllDialog
        :open="historyOpen"
        @close="historyOpen = false"
      />

      <WorkflowCommandPalette
        :open="showCommandPalette"
        :workflows="workflows"
        context="dashboard"
        active-tab="evals"
        @select="openWorkflowFromPalette"
        @tab-select="handleTabSelectFromPalette"
        @doc-select="onDocSelectFromPalette"
        @close="showCommandPalette = false"
      />
    </div>
  </WorkspaceShell>
</template>

<style scoped>
.dashboard-main {
  background: hsl(var(--background));
  min-height: calc(100vh - 4rem);
  position: relative;
}
</style>
