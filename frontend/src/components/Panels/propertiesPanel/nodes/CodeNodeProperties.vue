<script setup lang="ts">
import { ref } from "vue";
import { Wand2 } from "lucide-vue-next";
import axios from "axios";

import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { codeApi } from "@/services/api";
import { useToast } from "@/composables/useToast";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const CODE_PLACEHOLDER = `def main(params):
    return {"message": f"Hello, {params.name}!"}`;

const {
  workflowStore,
  codeParametersInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
} = usePropertiesPanelContext();

const { showToast } = useToast();
const isFormatting = ref(false);

async function formatCode(): Promise<void> {
  const source = selectedNode.value?.data.codeSource || "";
  if (!source.trim() || isFormatting.value) {
    return;
  }
  isFormatting.value = true;
  try {
    const formatted = await codeApi.format(source);
    if (formatted === source) {
      showToast("Code is already formatted", "info");
      return;
    }
    updateNodeData("codeSource", formatted);
    showToast("Code formatted", "success");
  } catch (error: unknown) {
    const detail = axios.isAxiosError(error)
      ? (error.response?.data as { detail?: string } | undefined)?.detail
      : undefined;
    showToast(detail || "Could not format the code", "error");
  } finally {
    isFormatting.value = false;
  }
}
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="code-source-field"
    >
      <div class="flex items-center justify-between gap-2">
        <Label>Code</Label>
        <Button
          variant="ghost"
          size="sm"
          class="h-7 gap-1 px-2 text-xs"
          :disabled="isFormatting || !(selectedNode.data.codeSource || '').trim()"
          data-testid="code-format-button"
          @click="formatCode"
        >
          <Wand2 class="h-3.5 w-3.5" />
          {{ isFormatting ? "Formatting…" : "Format" }}
        </Button>
      </div>
      <Textarea
        :model-value="selectedNode.data.codeSource || ''"
        :placeholder="CODE_PLACEHOLDER"
        :rows="10"
        wrap="off"
        class="font-mono text-xs leading-relaxed"
        @update:model-value="updateNodeData('codeSource', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Must define
        <code class="font-mono">def main(params):</code>
        and return a JSON-serializable value. Read parameters with dot notation
        (<code class="font-mono">params.name</code>). Anything you
        <code class="font-mono">print</code>
        is captured separately.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="code-parameters-field"
    >
      <Label>Parameters</Label>
      <ExpressionInput
        ref="codeParametersInputRef"
        :model-value="selectedNode.data.codeParameters || ''"
        placeholder="{ &quot;name&quot;: &quot;$trigger.body.name&quot; }"
        :rows="4"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Parameters"
        field-key="codeParameters"
        @update:model-value="updateNodeData('codeParameters', $event)"
      />
      <p class="text-xs text-muted-foreground">
        A JSON object. Expressions are resolved before the code runs.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="code-requirements-field"
    >
      <Label>requirements.txt</Label>
      <Textarea
        :model-value="selectedNode.data.codeRequirements || ''"
        placeholder="requests==2.32.3"
        :rows="4"
        wrap="off"
        class="font-mono text-xs leading-relaxed"
        @update:model-value="updateNodeData('codeRequirements', $event)"
      />
      <p class="text-xs text-muted-foreground">
        One package per line. Leave empty to skip installation and run faster.
        Packages are installed fresh in a throwaway container on every run.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="code-allow-network-field"
    >
      <div class="flex items-center gap-2">
        <input
          id="code-allow-network"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="selectedNode.data.codeAllowNetwork === true"
          @change="updateNodeData('codeAllowNetwork', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="code-allow-network"
          class="text-sm font-medium"
        >
          Allow network during execution
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        Off by default: the code runs with no network at all. Installing
        dependencies always has network. Turn this on only when the code itself
        must reach the internet.
      </p>
    </div>
  </template>
</template>
