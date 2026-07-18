<script setup lang="ts">
import { onMounted, ref } from "vue";
import { AlertTriangle, ChevronDown } from "lucide-vue-next";

import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import {
  OPENCODE_MODEL_FALLBACK,
  OPENCODE_VARIANT_OPTIONS,
  type OpenCodeModel,
} from "@/lib/opencodeCatalog";
import { opencodeApi } from "@/services/api";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  opencodeCredentialOptions,
  opencodeGithubCredentialOptions,
  codexPublishModeOptions,
  codexPublishModeDescriptions,
  opencodeRepositoryUrlExpressionInputRef,
  opencodeBaseBranchExpressionInputRef,
  opencodeTaskPromptExpressionInputRef,
  opencodeBranchNameExpressionInputRef,
  opencodeSetupCommandExpressionInputRef,
  opencodeExpressionNavBindings,
  handleOpenCodeExpressionFieldNavigate,
  onOpenCodeRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();

const models = ref<OpenCodeModel[]>([...OPENCODE_MODEL_FALLBACK]);
const usingFallback = ref(false);

onMounted(async () => {
  try {
    const { models: fetched, source } = await opencodeApi.listModels();
    if (fetched.length > 0) {
      models.value = fetched;
      usingFallback.value = source === "fallback";
    } else {
      usingFallback.value = true;
    }
  } catch {
    // Keep the hardcoded fallback list when the live fetch fails.
    models.value = [...OPENCODE_MODEL_FALLBACK];
    usingFallback.value = true;
  }
});
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>OpenCode Go Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="opencodeCredentialOptions"
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
        :options="opencodeGithubCredentialOptions"
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
        ref="opencodeRepositoryUrlExpressionInputRef"
        :model-value="selectedNode.data.repositoryUrl || ''"
        placeholder="https://github.com/org/repo"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="repositoryUrl"
        v-bind="opencodeExpressionNavBindings('repositoryUrl')"
        @navigate="handleOpenCodeExpressionFieldNavigate"
        @register-field-index="onOpenCodeRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('repositoryUrl', $event)"
      />
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-2">
        <Label>Base Branch</Label>
        <ExpressionInput
          ref="opencodeBaseBranchExpressionInputRef"
          :model-value="selectedNode.data.baseBranch || 'main'"
          placeholder="main"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="baseBranch"
          v-bind="opencodeExpressionNavBindings('baseBranch')"
          @navigate="handleOpenCodeExpressionFieldNavigate"
          @register-field-index="onOpenCodeRegisterExpressionFieldIndex"
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
      <div class="opencode-model-field relative">
        <Input
          :model-value="selectedNode.data.opencodeModel || ''"
          list="opencode-model-options"
          placeholder="opencode/kimi-k3"
          class="pr-10"
          @update:model-value="updateNodeData('opencodeModel', $event)"
        />
        <ChevronDown
          class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <datalist id="opencode-model-options">
          <option
            v-for="m in models"
            :key="m.id"
            :value="m.id"
          >
            {{ m.name }}
          </option>
        </datalist>
      </div>
      <p class="text-xs text-muted-foreground">
        Leave empty for the runner default (<code class="text-xs">opencode/kimi-k3</code>). Pick a
        live OpenCode Go model or type any <code class="text-xs">opencode/&lt;model&gt;</code> id.
        <span v-if="usingFallback">Showing a built-in fallback list (live models unavailable).</span>
      </p>
    </div>

    <div class="space-y-2">
      <Label>Reasoning Variant</Label>
      <Select
        :model-value="selectedNode.data.opencodeVariant || ''"
        :options="[...OPENCODE_VARIANT_OPTIONS]"
        @update:model-value="updateNodeData('opencodeVariant', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Optional. Maps to <code class="text-xs">opencode run --variant</code> for models that support
        reasoning effort.
      </p>
    </div>

    <div class="space-y-2">
      <Label>Task Prompt <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="opencodeTaskPromptExpressionInputRef"
        :model-value="selectedNode.data.taskPrompt || ''"
        placeholder="Fix the failing tests and summarize the change."
        :rows="6"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="taskPrompt"
        v-bind="opencodeExpressionNavBindings('taskPrompt')"
        @navigate="handleOpenCodeExpressionFieldNavigate"
        @register-field-index="onOpenCodeRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('taskPrompt', $event)"
      />
    </div>

    <div class="space-y-2">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-2">
          <Label>Branch Name</Label>
          <ExpressionInput
            ref="opencodeBranchNameExpressionInputRef"
            :model-value="selectedNode.data.branchName || 'opencode/$executionId'"
            placeholder="opencode/$executionId"
            single-line
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            field-key="branchName"
            v-bind="opencodeExpressionNavBindings('branchName')"
            @navigate="handleOpenCodeExpressionFieldNavigate"
            @register-field-index="onOpenCodeRegisterExpressionFieldIndex"
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
        ref="opencodeSetupCommandExpressionInputRef"
        :model-value="selectedNode.data.setupCommand || ''"
        placeholder="npm install && npm test"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="setupCommand"
        v-bind="opencodeExpressionNavBindings('setupCommand')"
        @navigate="handleOpenCodeExpressionFieldNavigate"
        @register-field-index="onOpenCodeRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('setupCommand', $event)"
      />
    </div>
  </template>
</template>

<style scoped>
/* Keep the native datalist picker clickable (opacity 0) so our own always-visible chevron
   is the only arrow shown, across browsers. */
.opencode-model-field :deep(input[list])::-webkit-calendar-picker-indicator {
  opacity: 0;
  cursor: pointer;
}
</style>
