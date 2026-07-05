<script setup lang="ts">
import { AlertTriangle, ChevronDown } from "lucide-vue-next";

import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  codexRepositoryUrlExpressionInputRef,
  codexBaseBranchExpressionInputRef,
  codexTaskPromptExpressionInputRef,
  codexBranchNameExpressionInputRef,
  codexSetupCommandExpressionInputRef,
  selectedNode,
  codexCredentialOptions,
  codexGithubCredentialOptions,
  codexPublishModeOptions,
  codexPublishModeDescriptions,
  codexExpressionNavBindings,
  handleCodexExpressionFieldNavigate,
  onCodexRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();

// Codex model suggestions (developers.openai.com/codex/models). Editable — any plan-supported
// model can be typed; leave empty to use Codex's default.
const codexModelOptions = [
  "gpt-5.5",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.3-codex-spark",
  "gpt-5.3-codex",
  "gpt-5.2",
];
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Codex Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="codexCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Credential is required.
      </p>
    </div>

    <div class="space-y-2">
      <Label>GitHub Credential</Label>
      <Select
        :model-value="selectedNode.data.githubCredentialId || ''"
        :options="codexGithubCredentialOptions"
        @update:model-value="updateNodeData('githubCredentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.githubCredentialId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        GitHub credential is required.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Repository URL <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="codexRepositoryUrlExpressionInputRef"
        :model-value="selectedNode.data.repositoryUrl || ''"
        placeholder="https://github.com/org/repo"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="repositoryUrl"
        v-bind="codexExpressionNavBindings('repositoryUrl')"
        @navigate="handleCodexExpressionFieldNavigate"
        @register-field-index="onCodexRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('repositoryUrl', $event)"
      />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-2">
        <Label>Base Branch</Label>
        <ExpressionInput
          ref="codexBaseBranchExpressionInputRef"
          :model-value="selectedNode.data.baseBranch || 'main'"
          placeholder="main"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="baseBranch"
          v-bind="codexExpressionNavBindings('baseBranch')"
          @navigate="handleCodexExpressionFieldNavigate"
          @register-field-index="onCodexRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('baseBranch', $event)"
        />
      </div>

      <div class="space-y-2">
        <Label>Timeout</Label>
        <Input
          type="number"
          :model-value="String(selectedNode.data.timeoutSeconds ?? 3600)"
          min="60"
          max="21600"
          step="60"
          @update:model-value="updateNodeData('timeoutSeconds', parseInt($event as string, 10) || 3600)"
        />
      </div>
    </div>

    <div class="space-y-2">
      <Label>Model</Label>
      <div class="codex-model-field relative">
        <Input
          :model-value="selectedNode.data.codexModel || ''"
          list="codex-model-options"
          placeholder="Codex default"
          class="pr-10"
          @update:model-value="updateNodeData('codexModel', $event)"
        />
        <ChevronDown
          class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <datalist id="codex-model-options">
          <option
            v-for="m in codexModelOptions"
            :key="m"
            :value="m"
          />
        </datalist>
      </div>
      <p class="text-xs text-muted-foreground">
        Leave empty for Codex's default. Pick a suggestion or type any model your ChatGPT plan
        supports.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Task Prompt <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="codexTaskPromptExpressionInputRef"
        :model-value="selectedNode.data.taskPrompt || ''"
        placeholder="Fix the failing tests and summarize the change."
        :rows="6"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="taskPrompt"
        v-bind="codexExpressionNavBindings('taskPrompt')"
        @navigate="handleCodexExpressionFieldNavigate"
        @register-field-index="onCodexRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('taskPrompt', $event)"
      />
    </div>

    <div class="space-y-2">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <Label>Branch Name</Label>
          <ExpressionInput
            ref="codexBranchNameExpressionInputRef"
            :model-value="selectedNode.data.branchName || 'codex/$executionId'"
            placeholder="codex/$executionId"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="branchName"
            v-bind="codexExpressionNavBindings('branchName')"
            @navigate="handleCodexExpressionFieldNavigate"
            @register-field-index="onCodexRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('branchName', $event)"
          />
        </div>

        <div class="space-y-2">
          <Label>Publish Mode</Label>
          <Select
            :model-value="selectedNode.data.publishMode || 'diff_only'"
            :options="codexPublishModeOptions"
            @update:model-value="updateNodeData('publishMode', $event)"
          />
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        {{ codexPublishModeDescriptions[selectedNode.data.publishMode || "diff_only"] }}
      </p>
    </div>

    <div class="space-y-2">
      <Label>Setup Command</Label>
      <ExpressionInput
        ref="codexSetupCommandExpressionInputRef"
        :model-value="selectedNode.data.setupCommand || ''"
        placeholder="npm install && npm test"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="setupCommand"
        v-bind="codexExpressionNavBindings('setupCommand')"
        @navigate="handleCodexExpressionFieldNavigate"
        @register-field-index="onCodexRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('setupCommand', $event)"
      />
    </div>
  </template>
</template>

<style scoped>
/* Keep the native datalist picker clickable (opacity 0) so our own always-visible chevron
   is the only arrow shown, across browsers. */
.codex-model-field :deep(input[list])::-webkit-calendar-picker-indicator {
  opacity: 0;
  cursor: pointer;
}
</style>
