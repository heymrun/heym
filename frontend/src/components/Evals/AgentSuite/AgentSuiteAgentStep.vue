<script setup lang="ts">
import { Bot } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import ReadonlyCanvasSurface from "@/components/Canvas/ReadonlyCanvasSurface.vue";
import AgentSuiteAgentDetails from "@/components/Evals/AgentSuite/AgentSuiteAgentDetails.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { evalsApi, workflowApi } from "@/services/api";
import type { AgentCandidate } from "@/types/evals";
import type { Workflow } from "@/types/workflow";

interface Props {
  workflowId: string;
  nodeId: string;
  /** A saved suite keeps its agent; only a new suite picks one. */
  readonly?: boolean;
  workflowName?: string;
  nodeLabel?: string;
}

const props = withDefaults(defineProps<Props>(), {
  readonly: false,
  workflowName: "",
  nodeLabel: "",
});

const emit = defineEmits<{
  (e: "update:workflowId", value: string): void;
  (e: "update:nodeId", value: string): void;
  (e: "agent-label", value: string): void;
}>();

const NO_RUNS = "No runs yet";

const candidates = ref<AgentCandidate[]>([]);
const loading = ref(false);
// The picked workflow, for the canvas overview and the agent's settings.
const workflow = ref<Workflow | null>(null);

watch(
  () => props.workflowId,
  async (id) => {
    workflow.value = null;
    if (!id || props.readonly) return;
    try {
      workflow.value = await workflowApi.get(id);
    } catch {
      workflow.value = null;
    }
  },
  { immediate: true },
);

// Workflows keep the order the API gives: most recently run first.
const workflowOptions = computed(() => {
  const byWorkflow = new Map<string, { label: string; runs: number }>();
  for (const candidate of candidates.value) {
    const entry = byWorkflow.get(candidate.workflow_id) ?? {
      label: candidate.workflow_name,
      runs: 0,
    };
    entry.runs += candidate.run_count;
    byWorkflow.set(candidate.workflow_id, entry);
  }
  return [...byWorkflow.entries()].map(([id, entry]) => ({
    value: id,
    label: entry.label,
    hint: entry.runs === 0 ? NO_RUNS : undefined,
    disabled: entry.runs === 0,
  }));
});

const agentOptions = computed(() =>
  candidates.value
    .filter((candidate) => candidate.workflow_id === props.workflowId)
    .map((candidate) => ({
      value: candidate.node_id,
      label: candidate.node_label,
      hint: candidate.run_count === 0 ? NO_RUNS : `${candidate.run_count} runs`,
      disabled: candidate.run_count === 0,
    })),
);

function selectWorkflow(value: string | undefined): void {
  emit("update:workflowId", value ?? "");
  const runnable = candidates.value.filter(
    (candidate) => candidate.workflow_id === value && candidate.run_count > 0,
  );
  if (runnable.length === 1) {
    selectNode(runnable[0].node_id, value);
  } else {
    emit("update:nodeId", "");
  }
}

function selectNode(value: string | undefined, workflowId = props.workflowId): void {
  emit("update:nodeId", value ?? "");
  const candidate = candidates.value.find(
    (item) => item.workflow_id === workflowId && item.node_id === value,
  );
  if (candidate) emit("agent-label", candidate.node_label);
}

onMounted(async () => {
  if (props.readonly) return;
  loading.value = true;
  try {
    candidates.value = await evalsApi.listAgents();
  } catch {
    candidates.value = [];
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="grid gap-6 lg:grid-cols-[minmax(0,36rem)_minmax(0,1fr)]">
    <div class="space-y-5">
      <p class="text-sm text-muted-foreground">
        Pick the agent to check. The suite reads its runs from Traces, and once saved it can run the
        workflow for you.
      </p>
      <template v-if="readonly">
        <div class="flex items-center gap-3 rounded-xl border border-border/60 bg-card px-4 py-3">
          <Bot class="h-5 w-5 shrink-0 text-primary" />
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-foreground">
              {{ nodeLabel }}
            </p>
            <p class="truncate text-xs text-muted-foreground">
              {{ workflowName }}
            </p>
          </div>
        </div>
      </template>
      <p
        v-else-if="!loading && candidates.length === 0"
        class="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground"
      >
        None of your workflows has an agent node yet. Add an Agent node, run the workflow, then come
        back.
      </p>
      <template v-else>
        <div>
          <Label class="mb-2 block text-xs font-medium text-muted-foreground">
            Workflow
          </Label>
          <SearchableSelect
            :model-value="workflowId || undefined"
            :options="workflowOptions"
            :disabled="loading"
            :placeholder="loading ? 'Loading workflows...' : 'Select workflow'"
            search-placeholder="Search workflows..."
            data-testid="agent-suite-workflow"
            @update:model-value="selectWorkflow"
          />
          <p class="mt-2 text-xs text-muted-foreground">
            Only workflows with an agent node are listed. One whose agents have not run yet cannot be
            picked.
          </p>
        </div>
        <div v-if="workflowId">
          <Label class="mb-2 block text-xs font-medium text-muted-foreground">
            Agent
          </Label>
          <SearchableSelect
            :model-value="nodeId || undefined"
            :options="agentOptions"
            placeholder="Select agent"
            search-placeholder="Search agents..."
            data-testid="agent-suite-agent"
            @update:model-value="(value) => selectNode(value)"
          />
        </div>
        <div
          v-if="workflow"
          class="h-[270px] overflow-hidden rounded-xl border border-border/60"
          data-testid="agent-suite-canvas"
        >
          <ReadonlyCanvasSurface
            :nodes="workflow.nodes"
            :edges="workflow.edges"
            :flow-key="workflow.id"
            :selected-node-id="nodeId || null"
            :interactive="false"
            :show-controls="false"
            :show-mini-map="false"
            :framed="false"
          />
        </div>
      </template>
    </div>
    <AgentSuiteAgentDetails
      v-if="!readonly && workflow && nodeId"
      :workflow="workflow"
      :node-id="nodeId"
    />
  </div>
</template>
