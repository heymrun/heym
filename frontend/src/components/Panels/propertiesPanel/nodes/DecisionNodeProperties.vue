<script setup lang="ts">
import { computed, ref } from "vue";
import type { DecisionQuestion } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import DecisionAIQuestionsDialog from "@/components/Decision/DecisionAIQuestionsDialog.vue";
import DecisionQuestionsEditor from "./DecisionQuestionsEditor.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
  decisionCredentialOptions,
  decisionExpressionFieldCount,
  decisionExpressionFieldIndex,
  setDecisionExpressionInputRef,
  handleDecisionExpressionFieldNavigate,
  onDecisionRegisterExpressionFieldIndex,
} = usePropertiesPanelContext();

const aiDialogOpen = ref(false);

const questions = computed((): DecisionQuestion[] => selectedNode.value?.data.questions ?? []);
const customBodyEnabled = computed((): boolean => !!selectedNode.value?.data.customBodyEnabled);

function applyGenerated(payload: { state: string | null; questions: DecisionQuestion[] }): void {
  if (payload.state) {
    updateNodeData("state", payload.state);
  }
  updateNodeData("questions", [...questions.value, ...payload.questions]);
  aiDialogOpen.value = false;
}

/** The request body the form describes, in the shape the provider expects. */
function buildSeedBody(): string {
  const wireQuestions: Record<string, unknown> = {};
  for (const question of questions.value) {
    const id = (question.id ?? "").trim();
    if (!id) continue;
    const entry: Record<string, unknown> = {
      type: question.type,
      instructions: question.instructions ?? "",
    };
    if (question.type === "noul") {
      const criteria: Record<string, string> = {};
      if (question.criteriaTrue) criteria.true = question.criteriaTrue;
      if (question.criteriaFalse) criteria.false = question.criteriaFalse;
      if (Object.keys(criteria).length > 0) entry.criteria = criteria;
    } else if (question.type === "choice") {
      entry.criteria = Object.fromEntries(
        (question.options ?? []).map((option) => [option.key, option.description || null]),
      );
    } else {
      entry.criteria = question.levels ?? [];
    }
    wireQuestions[id] = entry;
  }
  return JSON.stringify(
    {
      model: selectedNode.value?.data.model || "jev-latest",
      state: selectedNode.value?.data.state || "$input.text",
      questions: wireQuestions,
    },
    null,
    2,
  );
}

/**
 * True when the stored body no longer matches the form. The body is hand-editable, so
 * it is never overwritten silently; the panel offers a rebuild instead.
 */
const customBodyOutOfSync = computed((): boolean => {
  if (!customBodyEnabled.value) return false;
  const current = (selectedNode.value?.data.customBody ?? "").trim();
  if (!current) return false;
  try {
    return JSON.stringify(JSON.parse(current)) !== JSON.stringify(JSON.parse(buildSeedBody()));
  } catch {
    // Unparseable means hand-edited (or broken); either way, do not claim it is stale.
    return false;
  }
});

function rebuildCustomBody(): void {
  updateNodeData("customBody", buildSeedBody());
}

function toggleCustomBody(enabled: boolean): void {
  updateNodeData("customBodyEnabled", enabled);
  if (enabled && !(selectedNode.value?.data.customBody ?? "").trim()) {
    updateNodeData("customBody", buildSeedBody());
  }
}

</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="decisionCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p class="text-xs text-muted-foreground">
        A Decision Model credential. These models answer typed questions with
        probabilities; they do not generate text.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Model</Label>
      <Input
        :model-value="selectedNode.data.model || ''"
        placeholder="jev-latest"
        @update:model-value="updateNodeData('model', $event)"
      />
    </div>

    <template v-if="!customBodyEnabled">
      <div class="space-y-2">
        <Label>State</Label>
        <ExpressionInput
          :ref="(el: unknown) => setDecisionExpressionInputRef('state', el)"
          :model-value="selectedNode.data.state || ''"
          placeholder="$input.text"
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="State"
          field-key="state"
          expandable
          :navigation-enabled="decisionExpressionFieldCount > 1"
          :navigation-index="decisionExpressionFieldIndex('state')"
          :navigation-total="decisionExpressionFieldCount"
          @navigate="handleDecisionExpressionFieldNavigate"
          @register-field-index="onDecisionRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('state', $event)"
        />
        <p class="text-xs text-muted-foreground">
          What the model should read. A field holding one expression keeps its type, so
          <code>$input</code> sends the object rather than its text.
        </p>
      </div>

      <DecisionQuestionsEditor @generate="aiDialogOpen = true" />
    </template>

    <div class="space-y-2 pt-2 border-t">
      <div class="flex items-center gap-2">
        <input
          id="decision-custom-body"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="customBodyEnabled"
          @change="toggleCustomBody(($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="decision-custom-body"
          class="text-sm font-normal"
        >
          Custom request body
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        Send a hand-written JSON body instead of the form above, for an endpoint whose
        contract differs from this one.
      </p>
    </div>

    <div
      v-if="customBodyEnabled"
      class="space-y-2"
    >
      <ExpressionInput
        :ref="(el: unknown) => setDecisionExpressionInputRef('customBody', el)"
        :model-value="selectedNode.data.customBody || ''"
        placeholder="{ &quot;model&quot;: &quot;jev-latest&quot;, &quot;state&quot;: &quot;$input.text&quot;, &quot;questions&quot;: {} }"
        :rows="12"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Request Body"
        field-key="customBody"
        expandable
        :navigation-enabled="false"
        :navigation-index="0"
        :navigation-total="decisionExpressionFieldCount"
        @navigate="handleDecisionExpressionFieldNavigate"
        @register-field-index="onDecisionRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('customBody', $event)"
      />
      <div
        v-if="customBodyOutOfSync"
        class="flex items-start justify-between gap-2 rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1.5"
      >
        <p class="min-w-0 text-xs text-amber-600">
          This body no longer matches the questions above. It is sent as written, so it
          will not pick up your edits until you rebuild it.
        </p>
        <Button
          variant="outline"
          size="sm"
          class="shrink-0"
          @click="rebuildCustomBody"
        >
          Rebuild
        </Button>
      </div>
      <p class="text-xs text-muted-foreground">
        Sent exactly as written. The State field and the question rows are ignored while
        this is on.
      </p>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>Request Timeout (seconds)</Label>
      <Input
        type="number"
        :model-value="String(selectedNode.data.requestTimeoutSeconds ?? 60)"
        min="1"
        max="3600"
        placeholder="60"
        @update:model-value="updateNodeData('requestTimeoutSeconds', parseInt(String($event), 10) || 60)"
      />
      <p class="text-xs text-muted-foreground">
        Max seconds to wait for the decision before timing out
      </p>
    </div>

    <DecisionAIQuestionsDialog
      v-if="aiDialogOpen"
      :existing-question-ids="questions.map((q) => q.id)"
      :state-sample="selectedNode.data.state || ''"
      @applied="applyGenerated"
      @close="aiDialogOpen = false"
    />
  </template>
</template>
