<script setup lang="ts">
import { AlertTriangle, Braces, Brain, ShieldAlert } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import type { GuardrailCategory, ReasoningEffort } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  userMessageInputRef,
  llmSystemInstructionInputRef,
  llmImageExpressionInputRef,
  loadingModels,
  loadingGuardrailModels,
  loadingFallbackModels,
  jsonFormatError,
  guardrailCredentialOptions,
  guardrailModelOptions,
  handleGuardrailCredentialChange,
  handleGuardrailModelChange,
  fallbackCredentialOptions,
  fallbackModelOptions,
  handleFallbackCredentialChange,
  handleFallbackModelChange,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  handleLlmExpressionFieldNavigate,
  onLlmRegisterExpressionFieldIndex,
  credentialOptions,
  modelOptions,
  reasoningEffortOptions,
  outputTypeOptions,
  GUARDRAIL_CATEGORIES,
  GUARDRAIL_SEVERITY_OPTIONS,
  toggleGuardrailCategory,
  isImageOutputMode,
  llmExpressionFieldCount,
  selectedModelIsReasoning,
  llmBatchCapabilityMessage,
  llmBatchCapabilityTone,
  llmBatchModeAvailable,
  handleModelChange,
  handleCredentialChange,
  handleLlmOutputTypeChange,
  handleLlmImageInputChange,
  handleLlmBatchModeChange,
  formatJsonSchema,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="credentialOptions"
        @update:model-value="handleCredentialChange($event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-muted-foreground"
      >
        <a
          href="/?tab=credentials"
          class="text-primary hover:underline"
          @click.prevent="$router.push('/?tab=credentials')"
        >Add credentials</a> in Dashboard
      </p>
    </div>

    <div class="space-y-2">
      <Label>Model</Label>
      <Select
        :model-value="selectedNode.data.model || ''"
        :options="modelOptions"
        :disabled="!selectedNode.data.credentialId || loadingModels"
        @update:model-value="handleModelChange($event)"
      />
      <p
        v-if="loadingModels"
        class="text-xs text-muted-foreground"
      >
        Loading models...
      </p>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>Fallback (optional)</Label>
      <p class="text-xs text-muted-foreground">
        If primary credential/model fails, retry with fallback.
      </p>
      <Select
        :model-value="selectedNode.data.fallbackCredentialId || ''"
        :options="fallbackCredentialOptions"
        @update:model-value="handleFallbackCredentialChange($event)"
      />
      <Select
        :model-value="selectedNode.data.fallbackModel || ''"
        :options="fallbackModelOptions"
        :disabled="!selectedNode.data.fallbackCredentialId || loadingFallbackModels"
        @update:model-value="handleFallbackModelChange($event)"
      />
    </div>

    <div class="space-y-2">
      <Label>Output Type</Label>
      <Select
        :model-value="selectedNode.data.outputType || 'text'"
        :options="outputTypeOptions"
        @update:model-value="handleLlmOutputTypeChange($event)"
      />
      <p class="text-xs text-muted-foreground">
        Choose between text generation or image generation
      </p>
    </div>

    <template v-if="isImageOutputMode">
      <div class="space-y-2">
        <Label>Prompt</Label>
        <ExpressionInput
          ref="userMessageInputRef"
          :model-value="selectedNode.data.userMessage || ''"
          placeholder="A beautiful sunset over mountains..."
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          navigation-enabled
          :navigation-index="0"
          :navigation-total="llmExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Prompt"
          field-key="userMessage"
          @update:model-value="updateNodeData('userMessage', $event)"
          @navigate="handleLlmExpressionFieldNavigate"
          @register-field-index="onLlmRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Describe the image you want to generate
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label>Image Input</Label>
        <div class="flex items-center gap-2">
          <input
            id="llm-image-input"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.imageInputEnabled"
            :disabled="!!selectedNode.data.batchModeEnabled"
            @change="handleLlmImageInputChange(($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="llm-image-input"
            class="text-sm font-normal"
          >
            Include image input
          </Label>
        </div>
        <ExpressionInput
          v-if="selectedNode.data.imageInputEnabled"
          ref="llmImageExpressionInputRef"
          :model-value="selectedNode.data.imageInput || ''"
          placeholder="$input.imageUrl"
          :rows="2"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          navigation-enabled
          :navigation-index="1"
          :navigation-total="llmExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Image input"
          field-key="imageInput"
          @update:model-value="updateNodeData('imageInput', $event)"
          @navigate="handleLlmExpressionFieldNavigate"
          @register-field-index="onLlmRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Supports image URLs or base64 data URLs.
        </p>
      </div>
    </template>

    <template v-else>
      <div class="space-y-2 pt-2 border-t">
        <Label>System Instruction</Label>
        <ExpressionInput
          ref="llmSystemInstructionInputRef"
          :model-value="selectedNode.data.systemInstruction || ''"
          placeholder="You are a helpful assistant..."
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          navigation-enabled
          :navigation-index="0"
          :navigation-total="llmExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="System instruction"
          field-key="systemInstruction"
          @update:model-value="updateNodeData('systemInstruction', $event)"
          @navigate="handleLlmExpressionFieldNavigate"
          @register-field-index="onLlmRegisterExpressionFieldIndex"
        />
      </div>

      <div class="space-y-2">
        <Label>User Message</Label>
        <ExpressionInput
          ref="userMessageInputRef"
          :model-value="selectedNode.data.userMessage || ''"
          :placeholder="exampleRef"
          :rows="3"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          navigation-enabled
          :navigation-index="1"
          :navigation-total="llmExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="User message"
          field-key="userMessage"
          @update:model-value="updateNodeData('userMessage', $event)"
          @navigate="handleLlmExpressionFieldNavigate"
          @register-field-index="onLlmRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          <template v-if="selectedNode.data.batchModeEnabled">
            Batch mode expects an array here. Example:
            <span class="font-mono">$input.items.map("item.text")</span>
          </template>
          <template v-else>
            Use $ expressions like {{ exampleRef }}
          </template>
        </p>
      </div>

      <div class="space-y-3 pt-2 border-t">
        <div class="flex items-center gap-2">
          <input
            id="llm-batch-mode"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.batchModeEnabled"
            :disabled="!llmBatchModeAvailable"
            @change="handleLlmBatchModeChange(($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="llm-batch-mode"
            class="text-sm font-normal"
          >
            Use Batch API mode
          </Label>
        </div>
        <p
          v-if="llmBatchCapabilityMessage"
          :class="[
            'text-xs',
            llmBatchCapabilityTone === 'positive'
              ? 'text-success'
              : llmBatchCapabilityTone === 'warning'
                ? 'text-amber-600'
                : 'text-muted-foreground',
          ]"
        >
          {{ llmBatchCapabilityMessage }}
        </p>
        <p
          v-if="selectedNode.data.batchModeEnabled"
          class="text-xs text-muted-foreground"
        >
          User Message must resolve to an array. Batch status updates stream live and
          can trigger the <span class="font-semibold text-node-llm">STATUS</span> output
          branch.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label>Image Input</Label>
        <div class="flex items-center gap-2">
          <input
            id="llm-image-input"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.imageInputEnabled"
            :disabled="!!selectedNode.data.batchModeEnabled"
            @change="handleLlmImageInputChange(($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="llm-image-input"
            class="text-sm font-normal"
          >
            Include image input
          </Label>
        </div>
        <ExpressionInput
          v-if="selectedNode.data.imageInputEnabled"
          ref="llmImageExpressionInputRef"
          :model-value="selectedNode.data.imageInput || ''"
          placeholder="$input.imageUrl"
          :rows="2"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          navigation-enabled
          :navigation-index="2"
          :navigation-total="llmExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Image input"
          field-key="imageInput"
          @update:model-value="updateNodeData('imageInput', $event)"
          @navigate="handleLlmExpressionFieldNavigate"
          @register-field-index="onLlmRegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Supports image URLs or base64 data URLs.
        </p>
      </div>

      <div class="space-y-3 pt-2 border-t">
        <div
          v-if="selectedModelIsReasoning"
          class="space-y-2"
        >
          <div class="flex items-center gap-2">
            <Brain class="w-4 h-4 text-purple-500" />
            <Label class="text-purple-500">Reasoning Model</Label>
          </div>
          <Select
            :model-value="(selectedNode.data.reasoningEffort as ReasoningEffort) || 'medium'"
            :options="reasoningEffortOptions"
            @update:model-value="updateNodeData('reasoningEffort', $event)"
          />
          <p class="text-xs text-muted-foreground">
            Reasoning effort level (replaces temperature)
          </p>
        </div>

        <div
          v-else
          class="space-y-2"
        >
          <Label>Temperature</Label>
          <Input
            type="number"
            :model-value="selectedNode.data.temperature || 0.7"
            min="0"
            max="2"
            step="0.1"
            @update:model-value="updateNodeData('temperature', parseFloat($event as string))"
          />
        </div>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label>Request Timeout (seconds)</Label>
        <Input
          type="number"
          :model-value="String(selectedNode.data.requestTimeoutSeconds ?? 60)"
          min="1"
          max="3600"
          placeholder="60"
          @update:model-value="updateNodeData('requestTimeoutSeconds', parseInt($event, 10) || 60)"
        />
        <p class="text-xs text-muted-foreground">
          Max seconds to wait for the model response before timing out
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label>JSON Output Parser</Label>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input
              id="llm-json-output"
              type="checkbox"
              class="h-4 w-4 rounded border-input bg-background"
              :checked="!!selectedNode.data.jsonOutputEnabled"
              @change="updateNodeData('jsonOutputEnabled', ($event.target as HTMLInputElement).checked)"
            >
            <Label
              for="llm-json-output"
              class="text-sm font-normal"
            >
              Enable JSON output
            </Label>
          </div>
          <Button
            v-if="selectedNode.data.jsonOutputEnabled"
            variant="ghost"
            size="sm"
            :class="['h-11 min-h-[44px] md:h-7 px-2 gap-1.5', jsonFormatError ? 'text-red-500' : '']"
            :title="jsonFormatError ? 'Invalid JSON' : 'Format JSON'"
            @click="formatJsonSchema"
          >
            <Braces class="w-3.5 h-3.5" />
            <span class="text-xs">{{ jsonFormatError ? 'Invalid' : 'Format' }}</span>
          </Button>
        </div>
        <Textarea
          v-if="selectedNode.data.jsonOutputEnabled"
          :model-value="selectedNode.data.jsonOutputSchema || ''"
          placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: { &quot;answer&quot;: { &quot;type&quot;: &quot;string&quot; } }, &quot;required&quot;: [&quot;answer&quot;] }"
          :rows="6"
          class="font-mono text-xs"
          @update:model-value="updateNodeData('jsonOutputSchema', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Provide a JSON schema to shape the response.
        </p>
      </div>
    </template>

    <div class="space-y-4 pt-4 border-t">
      <div class="flex items-center gap-2">
        <input
          id="llm-guardrails-enabled"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.guardrailsEnabled"
          @change="updateNodeData('guardrailsEnabled', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="llm-guardrails-enabled"
          class="text-sm font-normal flex items-center gap-1.5"
        >
          <ShieldAlert class="w-3.5 h-3.5 text-amber-500" />
          Enable Guardrails
        </Label>
      </div>

      <template v-if="selectedNode.data.guardrailsEnabled">
        <div class="space-y-3 pl-6">
          <div
            v-if="!selectedNode.data.guardrailCredentialId || !selectedNode.data.guardrailModel"
            class="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400"
          >
            <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <p class="text-xs">
              Guardrail credential and model are required. The workflow cannot run until both are selected.
            </p>
          </div>
          <div class="space-y-2">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Credential</Label>
            <Select
              :model-value="selectedNode.data.guardrailCredentialId || ''"
              :options="guardrailCredentialOptions"
              @update:model-value="handleGuardrailCredentialChange($event)"
            />
            <p class="text-xs text-muted-foreground">
              Select a credential (e.g. OpenAI) for content safety. Required when guardrails are enabled.
            </p>
          </div>
          <div class="space-y-2">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Model</Label>
            <Select
              :model-value="selectedNode.data.guardrailModel || ''"
              :options="guardrailModelOptions"
              :disabled="loadingGuardrailModels"
              @update:model-value="handleGuardrailModelChange($event)"
            />
          </div>
          <div class="space-y-2">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Blocked Categories</Label>
            <div class="grid grid-cols-1 gap-1.5">
              <div
                v-for="cat in GUARDRAIL_CATEGORIES"
                :key="cat.value"
                class="flex items-center gap-2"
              >
                <input
                  :id="`llm-guardrail-${cat.value}`"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="(selectedNode.data.guardrailsCategories || []).includes(cat.value as GuardrailCategory)"
                  @change="toggleGuardrailCategory(($event.target as HTMLInputElement).checked, cat.value as GuardrailCategory)"
                >
                <Label
                  :for="`llm-guardrail-${cat.value}`"
                  class="text-xs font-normal"
                >
                  {{ cat.label }}
                </Label>
              </div>
            </div>
          </div>

          <div class="space-y-2 pt-1">
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Sensitivity</Label>
            <Select
              :model-value="selectedNode.data.guardrailsSeverity || 'medium'"
              :options="GUARDRAIL_SEVERITY_OPTIONS"
              @update:model-value="updateNodeData('guardrailsSeverity', $event)"
            />
            <p class="text-xs text-muted-foreground">
              <span v-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'low'">
                Low — flag even borderline cases
              </span>
              <span v-else-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'medium'">
                Medium — flag clear violations
              </span>
              <span v-else>
                High — only flag extreme violations
              </span>
            </p>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">
          If the user message matches a blocked category, the node will throw an error instead of running.
        </p>
      </template>
    </div>
  </template>
</template>
