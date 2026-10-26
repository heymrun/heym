<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AgentSuiteAgentStep from "@/components/Evals/AgentSuite/AgentSuiteAgentStep.vue";
import AgentSuiteBaselineStep from "@/components/Evals/AgentSuite/AgentSuiteBaselineStep.vue";
import AgentSuiteChecksStep from "@/components/Evals/AgentSuite/AgentSuiteChecksStep.vue";
import AgentSuiteFooter from "@/components/Evals/AgentSuite/AgentSuiteFooter.vue";
import AgentSuiteHeader, {
  type AgentSuiteView,
} from "@/components/Evals/AgentSuite/AgentSuiteHeader.vue";
import AgentSuiteResultsStep from "@/components/Evals/AgentSuite/AgentSuiteResultsStep.vue";
import AgentSuiteRunPanel from "@/components/Evals/AgentSuite/AgentSuiteRunPanel.vue";
import AgentSuiteStepper, {
  type AgentSuiteStep as Step,
} from "@/components/Evals/AgentSuite/AgentSuiteStepper.vue";
import {
  EMPTY_THRESHOLDS,
  apiErrorText as errorText,
} from "@/components/Evals/AgentSuite/agentSuiteFormat";
import { useStepQuery } from "@/components/Evals/AgentSuite/useStepQuery";
import { evalsApi } from "@/services/api";
import type {
  AgentMetrics,
  AgentSuite,
  AgentSuiteRun,
  AgentThresholds,
  ToolAssertion,
} from "@/types/evals";

interface Props {
  /** Null while a new suite is being set up; nothing is saved until step 3. */
  suiteId: string | null;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "created", suite: AgentSuite): void;
  (e: "updated", suite: AgentSuite): void;
  (e: "cancel"): void;
}>();

const suite = ref<AgentSuite | null>(null);
const step = ref<Step>(1);
const name = ref("");
const nameTouched = ref(false);
const workflowId = ref("");
const nodeId = ref("");
const metrics = ref<AgentMetrics | null>(null);
const metricsLoading = ref(false);
const metricsError = ref<string | null>(null);
const assertions = ref<ToolAssertion[]>([]);
const thresholds = ref<AgentThresholds>({ ...EMPTY_THRESHOLDS });
const saving = ref(false);
const refreshing = ref(false);
const saveError = ref<string | null>(null);
const reportKey = ref(0);
const finishedRunId = ref<string | null>(null);

const isNew = computed((): boolean => props.suiteId === null);

// A saved suite has no stepper: it opens on results and switches views from the header.
const VIEW_STEPS: Record<AgentSuiteView, Step> = { results: 4, baseline: 2, checks: 3 };
const view = computed((): AgentSuiteView | null => {
  if (isNew.value) return null;
  return step.value === 2 ? "baseline" : step.value === 3 ? "checks" : "results";
});

function onRunChanged(run: AgentSuiteRun | null): void {
  if (run && run.status !== "running") finishedRunId.value = run.id;
}

function reset(): void {
  suite.value = null;
  step.value = 1;
  name.value = "";
  nameTouched.value = false;
  workflowId.value = "";
  nodeId.value = "";
  metrics.value = null;
  assertions.value = [];
  thresholds.value = { ...EMPTY_THRESHOLDS };
  saveError.value = null;
  finishedRunId.value = null;
}

async function loadSuite(id: string): Promise<void> {
  try {
    const loaded = await evalsApi.getAgentSuite(id);
    suite.value = loaded;
    name.value = loaded.name;
    workflowId.value = loaded.workflow_id;
    nodeId.value = loaded.node_id;
    assertions.value = loaded.tool_assertions.map((item) => ({ ...item }));
    thresholds.value = { ...loaded.thresholds };
    step.value = 4;
  } catch (e: unknown) {
    saveError.value = errorText(e, "Could not load the suite.");
  }
}

async function loadMetrics(): Promise<void> {
  if (!workflowId.value || !nodeId.value) return;
  metricsLoading.value = true;
  metricsError.value = null;
  try {
    metrics.value = await evalsApi.getAgentMetrics(workflowId.value, nodeId.value);
    if (isNew.value) thresholds.value = { ...metrics.value.suggested_thresholds };
  } catch (e: unknown) {
    metrics.value = null;
    metricsError.value = errorText(e, "Could not read the agent's runs.");
  } finally {
    metricsLoading.value = false;
  }
}

function applyStep(target: Step): void {
  step.value = target >= 2 && !nodeId.value ? 1 : target;
  if ((step.value === 2 || step.value === 3) && !metrics.value && !metricsLoading.value) {
    void loadMetrics();
  }
}

function goTo(target: Step): void {
  if (!isNew.value) return applyStep(target);
  if (target > step.value + 1 || (target >= 2 && !nodeId.value) || target === 4) return;
  pushStep(target);
}

function onAgentLabel(label: string): void {
  if (!nameTouched.value) name.value = `${label} checks`;
}

async function createSuite(): Promise<void> {
  saving.value = true;
  saveError.value = null;
  try {
    const created = await evalsApi.createAgentSuite({
      name: name.value.trim() || "Agent suite",
      workflow_id: workflowId.value,
      node_id: nodeId.value,
      tool_assertions: assertions.value,
      thresholds: thresholds.value,
    });
    suite.value = created;
    step.value = 4;
    emit("created", created);
  } catch (e: unknown) {
    saveError.value = errorText(e, "Could not create the suite.");
  } finally {
    saving.value = false;
  }
}

async function saveChecks(): Promise<void> {
  if (!suite.value) return;
  saving.value = true;
  saveError.value = null;
  try {
    suite.value = await evalsApi.updateAgentSuite(suite.value.id, {
      tool_assertions: assertions.value,
      thresholds: thresholds.value,
    });
    emit("updated", suite.value);
    reportKey.value++;
    step.value = 4;
  } catch (e: unknown) {
    saveError.value = errorText(e, "Could not save the checks.");
  } finally {
    saving.value = false;
  }
}

async function refreshBaseline(): Promise<void> {
  if (!suite.value) return;
  refreshing.value = true;
  try {
    suite.value = await evalsApi.updateAgentSuite(suite.value.id, { refresh_baseline: true });
    reportKey.value++;
  } catch (e: unknown) {
    metricsError.value = errorText(e, "Could not refresh the baseline.");
  } finally {
    refreshing.value = false;
  }
}

let nameTimer: ReturnType<typeof setTimeout> | null = null;

function onNameInput(value: string): void {
  name.value = value;
  nameTouched.value = true;
  if (!suite.value) return;
  if (nameTimer) clearTimeout(nameTimer);
  nameTimer = setTimeout(async () => {
    const trimmed = name.value.trim();
    if (!suite.value || !trimmed || trimmed === suite.value.name) return;
    try {
      suite.value = await evalsApi.updateAgentSuite(suite.value.id, { name: trimmed });
      emit("updated", suite.value);
    } catch (e: unknown) {
      saveError.value = errorText(e, "Could not rename the suite.");
    }
  }, 500);
}

watch(nodeId, () => {
  if (isNew.value) metrics.value = null;
});

watch(
  () => props.suiteId,
  (id) => {
    reset();
    if (id) void loadSuite(id);
  },
  { immediate: true },
);

const { pushStep } = useStepQuery(applyStep, () => isNew.value);
</script>

<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-border/60 bg-card/40">
    <AgentSuiteHeader
      :name="name"
      :workflow-id="workflowId"
      :view="view"
      @update:name="onNameInput"
      @update:view="(next) => goTo(VIEW_STEPS[next])"
    />

    <AgentSuiteStepper
      v-if="isNew"
      :step="step"
      @go="goTo"
    />

    <div class="min-h-0 flex-1 overflow-y-auto p-4">
      <AgentSuiteAgentStep
        v-if="step === 1"
        v-model:workflow-id="workflowId"
        v-model:node-id="nodeId"
        :readonly="!isNew"
        :workflow-name="suite?.workflow_name"
        :node-label="suite?.node_label"
        @agent-label="onAgentLabel"
      />
      <AgentSuiteBaselineStep
        v-else-if="step === 2"
        :metrics="metrics"
        :loading="metricsLoading"
        :error="metricsError"
      />
      <AgentSuiteChecksStep
        v-else-if="step === 3"
        v-model:assertions="assertions"
        v-model:thresholds="thresholds"
        :tools="metrics?.tools ?? []"
        :run-count="metrics?.runs.length ?? 0"
        :suggested="metrics?.suggested_thresholds ?? EMPTY_THRESHOLDS"
        :baseline="metrics?.baseline ?? null"
        :saved-baseline="suite?.baseline ?? null"
        :refreshing="refreshing"
        @refresh-baseline="refreshBaseline"
      />
      <div
        v-else-if="step === 4 && suite"
        class="space-y-5"
      >
        <AgentSuiteRunPanel
          :suite-id="suite.id"
          :workflow-id="suite.workflow_id"
          @run-changed="onRunChanged"
        />
        <AgentSuiteResultsStep
          :suite-id="suite.id"
          :reload-key="reportKey"
          :run-id="finishedRunId"
        />
      </div>
    </div>

    <AgentSuiteFooter
      v-if="isNew ? step < 4 : step === 3"
      :step="step"
      :is-new="isNew"
      :can-continue="!!nodeId"
      :saving="saving"
      :error="saveError"
      @go="goTo"
      @create="createSuite"
      @save="saveChecks"
      @cancel="emit('cancel')"
    />
  </div>
</template>
