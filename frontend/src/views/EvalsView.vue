<script setup lang="ts">
import AppHeader from "@/components/Layout/AppHeader.vue";
import DashboardNav from "@/components/Layout/DashboardNav.vue";
import WorkspaceShell from "@/components/Layout/WorkspaceShell.vue";
import ExecutionHistoryAllDialog from "@/components/Panels/ExecutionHistoryAllDialog.vue";
import AgentSuitePanel from "@/components/Evals/AgentSuite/AgentSuitePanel.vue";
import EvalsLeftPanel from "@/components/Evals/EvalsLeftPanel.vue";
import EvalsResultsPanel from "@/components/Evals/EvalsResultsPanel.vue";
import EvalsSuiteBar from "@/components/Evals/EvalsSuiteBar.vue";
import EvalsTestCasesPanel from "@/components/Evals/EvalsTestCasesPanel.vue";
import ResizablePanels from "@/components/Evals/ResizablePanels.vue";
import ReleaseTourHost from "@/features/release-tour/components/ReleaseTourHost.vue";
import { resolveShowcaseContext } from "@/features/showcase/showcaseResolver";
import WorkflowCommandPalette from "@/components/Dialogs/WorkflowCommandPalette.vue";
import Button from "@/components/ui/Button.vue";
import { Bot, History, Plus } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { getDocPath } from "@/docs/manifest";
import { joinOriginAndPath } from "@/lib/appUrl";
import { isPaletteOpenInNewTab } from "@/lib/paletteNavigate";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import { evalsApi, workflowApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import type { WorkflowListItem } from "@/types/workflow";
import { isReasoningEffort } from "@/types/evals";
import type {
  AgentSuite,
  EvalRun,
  EvalRunListItem,
  EvalSuite,
  EvalSuiteListItem,
  EvalSuiteType,
  ReasoningEffort,
} from "@/types/evals";

const suites = ref<EvalSuiteListItem[]>([]);
const runs = ref<EvalRunListItem[]>([]);
const selectedSuiteId = ref<string | null>(null);
const suiteDetail = ref<EvalSuite | null>(null);
// The selected prompt suite could not be loaded; the view offers a retry.
const detailError = ref(false);
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
const releaseTourEligible = computed(() => !showCommandPalette.value && !historyOpen.value);
const showcaseContext = computed(() => {
  return resolveShowcaseContext({ routePath: route.path });
});

// Only the detail of the suite that is selected now, never one left from an earlier pick.
const selectedSuite = computed(() =>
  suiteDetail.value?.id === selectedSuiteId.value ? suiteDetail.value : null,
);
// A new agent suite is set up in the panel before anything is saved. It lives in the URL
// (`?new=agent`), so the browser's back button walks out of it like any other page.
const agentDraft = computed(() => route.query.new === "agent");

function setDraftQuery(open: boolean, replace = false): void {
  const query = { ...route.query };
  delete query.step;
  if (open) query.new = "agent";
  else delete query.new;
  void (replace ? router.replace({ query }) : router.push({ query }));
}

function suiteTypeOf(id: string | null): EvalSuiteType | null {
  if (!id) return null;
  return suites.value.find((s) => s.id === id)?.suite_type ?? "prompt";
}

const selectedSuiteType = computed(() => suiteTypeOf(selectedSuiteId.value));
const showAgentPanel = computed(() => agentDraft.value || selectedSuiteType.value === "agent");

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

function openWorkflowFromPalette(workflowId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const workflow = workflows.value.find((w) => w.id === workflowId);
  if (workflow) {
    addRecent(workflowId, workflow.name);
  }
  if (isPaletteOpenInNewTab(event)) {
    const resolved = router.resolve({ name: "editor", params: { id: workflowId } });
    window.open(resolved.href, "_blank");
  } else {
    router.push({ name: "editor", params: { id: workflowId } });
  }
}

function handleTabSelectFromPalette(tabId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const openInNewTab = isPaletteOpenInNewTab(event);
  if (tabId === "evals") {
    if (openInNewTab) {
      window.open(joinOriginAndPath(window.location.origin, "/evals"), "_blank", "noopener,noreferrer");
    }
    return;
  }
  if (tabId === "chat") {
    if (openInNewTab) {
      window.open(joinOriginAndPath(window.location.origin, "/chats"), "_blank", "noopener,noreferrer");
    } else {
      router.push("/chats");
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

function onDocSelectFromPalette(categoryId: string, slug: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const path = getDocPath(categoryId, slug);
  if (isPaletteOpenInNewTab(event)) {
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
  if (isReasoningEffort(r)) return r;
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

// Each load is numbered: an answer for an earlier selection arrives after the user moved on
// and must not replace what they picked since.
let detailRequest = 0;
let runsRequest = 0;

async function loadSuiteDetail(): Promise<void> {
  const id = selectedSuiteId.value;
  const request = ++detailRequest;
  detailError.value = false;
  if (!id || selectedSuiteType.value !== "prompt") {
    suiteDetail.value = null;
    return;
  }
  try {
    const detail = await evalsApi.getSuite(id);
    if (request === detailRequest) suiteDetail.value = detail;
  } catch {
    if (request === detailRequest) detailError.value = true;
  }
}

watch(selectedSuiteId, loadSuiteDetail, { immediate: true });

async function loadRuns(): Promise<void> {
  const id = selectedSuiteId.value;
  const request = ++runsRequest;
  if (!id || selectedSuiteType.value !== "prompt") {
    runs.value = [];
    return;
  }
  try {
    const loaded = await evalsApi.listRuns(id);
    if (request === runsRequest) runs.value = loaded;
  } catch {
    if (request === runsRequest) runs.value = [];
  }
}

watch(selectedSuiteId, loadRuns, { immediate: true });

function selectSuite(id: string | null): void {
  if (agentDraft.value) setDraftQuery(false, true);
  selectedSuiteId.value = id;
}

function createSuiteOfType(type: EvalSuiteType): void {
  if (type === "agent") {
    setDraftQuery(true);
    return;
  }
  if (agentDraft.value) setDraftQuery(false, true);
  void createSuite();
}

function onAgentSuiteCreated(suite: AgentSuite): void {
  suites.value = [
    {
      id: suite.id,
      name: suite.name,
      description: null,
      created_at: suite.created_at,
      suite_type: "agent",
    },
    ...suites.value,
  ];
  setDraftQuery(false, true);
  selectedSuiteId.value = suite.id;
}

function cancelAgentDraft(): void {
  setDraftQuery(false, true);
}

function onAgentSuiteUpdated(suite: AgentSuite): void {
  suites.value = suites.value.map((s) => (s.id === suite.id ? { ...s, name: suite.name } : s));
}

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
        suite_type: "prompt",
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
    if (selectedSuiteType.value === "agent") {
      await evalsApi.deleteAgentSuite(selectedSuiteId.value);
    } else {
      await evalsApi.deleteSuite(selectedSuiteId.value);
    }
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
  // A late autosave of the previous suite renames it in the list but leaves the open one alone.
  if (updated.id === selectedSuiteId.value) suiteDetail.value = updated;
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
        <template #before-docs>
          <div
            id="release-tour-launcher-slot"
            class="contents"
          />
        </template>
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
          <EvalsSuiteBar
            v-if="suites.length > 0 && !agentDraft"
            class="mb-4"
            :suites="suites"
            :selected-suite-id="selectedSuiteId"
            :show-edit-button="showEditButton && selectedSuiteType === 'prompt'"
            @select="selectSuite"
            @delete="deleteSuite"
            @edit="switchToEditor"
            @create="createSuiteOfType"
          />
          <div
            v-if="loading"
            class="flex-1 flex items-center justify-center text-muted-foreground min-h-[200px]"
          >
            Loading...
          </div>
          <AgentSuitePanel
            v-else-if="showAgentPanel"
            class="flex-1 min-h-0"
            :suite-id="agentDraft ? null : selectedSuiteId"
            @created="onAgentSuiteCreated"
            @updated="onAgentSuiteUpdated"
            @cancel="cancelAgentDraft"
          />
          <ResizablePanels
            v-else-if="selectedSuite"
            class="flex-1 min-h-0 overflow-hidden"
          >
            <template #left>
              <EvalsLeftPanel
                :suite="selectedSuite"
                :current-run="currentRun"
                :last-run="runs[0] ?? null"
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
            v-else-if="selectedSuiteId && detailError"
            class="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground min-h-[200px]"
          >
            <p class="text-base">
              Could not load this suite.
            </p>
            <Button
              variant="outline"
              @click="loadSuiteDetail"
            >
              Retry
            </Button>
          </div>
          <div
            v-else-if="selectedSuiteId"
            class="flex-1 flex items-center justify-center text-muted-foreground min-h-[200px]"
            data-testid="eval-suite-loading"
          >
            Loading suite...
          </div>
          <div
            v-else
            class="flex-1 flex flex-col items-center justify-center gap-4 text-muted-foreground min-h-[200px]"
          >
            <p class="text-base">
              Create a suite to get started
            </p>
            <div class="flex flex-wrap justify-center gap-2">
              <Button
                variant="default"
                size="lg"
                class="gap-2"
                @click="createSuiteOfType('prompt')"
              >
                <Plus class="w-4 h-4" />
                Prompt suite
              </Button>
              <Button
                variant="outline"
                size="lg"
                class="gap-2"
                data-testid="eval-empty-agent-suite"
                @click="createSuiteOfType('agent')"
              >
                <Bot class="w-4 h-4" />
                Agent suite
              </Button>
            </div>
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

      <ReleaseTourHost :eligible="releaseTourEligible" />
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
