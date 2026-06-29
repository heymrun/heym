<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { PluginFieldDef, PluginNodeSummary, PluginSummary } from "@/types/workflow";

import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { listPlugins } from "@/services/plugins";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
} = usePropertiesPanelContext();

const plugins = ref<PluginSummary[]>([]);

onMounted(async () => {
  try {
    plugins.value = await listPlugins();
  } catch {
    plugins.value = [];
  }
});

const pkg = computed<PluginSummary | undefined>(() =>
  plugins.value.find((plugin) => plugin.id === selectedNode.value?.data.pluginId),
);

const nodeDef = computed<PluginNodeSummary | undefined>(() => {
  const nodes = pkg.value?.nodes ?? [];
  const key = selectedNode.value?.data.pluginNodeKey;
  return (key ? nodes.find((node) => node.key === key) : undefined) ?? nodes[0];
});

const fields = computed<PluginFieldDef[]>(() => nodeDef.value?.fields ?? []);

function configValue(key: string): unknown {
  const config = selectedNode.value?.data.config;
  return config && typeof config === "object"
    ? (config as Record<string, unknown>)[key]
    : undefined;
}

function setConfigValue(key: string, value: unknown): void {
  const current = selectedNode.value?.data.config;
  const next =
    current && typeof current === "object" ? { ...(current as Record<string, unknown>) } : {};
  next[key] = value;
  updateNodeData("config", next);
}
</script>

<template>
  <template v-if="selectedNode">
    <p
      v-if="!nodeDef"
      class="text-xs text-muted-foreground"
    >
      Plugin not found or disabled on this instance.
    </p>
    <div
      v-for="field in fields"
      :key="field.key"
      class="space-y-2"
    >
      <Label>{{ field.label }}<span
        v-if="field.required"
        class="text-destructive"
      > *</span></Label>

      <Input
        v-if="field.secret"
        type="password"
        :model-value="(configValue(field.key) as string) || ''"
        @update:model-value="setConfigValue(field.key, $event)"
      />

      <Input
        v-else-if="field.type === 'number'"
        type="number"
        :model-value="(configValue(field.key) as number | undefined) ?? ''"
        @update:model-value="setConfigValue(field.key, $event === '' ? null : Number($event))"
      />

      <label
        v-else-if="field.type === 'boolean'"
        class="flex items-center gap-2 text-sm"
      >
        <input
          type="checkbox"
          :checked="Boolean(configValue(field.key))"
          @change="setConfigValue(field.key, ($event.target as HTMLInputElement).checked)"
        >
        Enabled
      </label>

      <select
        v-else-if="field.type === 'select'"
        class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        :value="(configValue(field.key) as string) || ''"
        @change="setConfigValue(field.key, ($event.target as HTMLSelectElement).value)"
      >
        <option
          v-for="opt in field.options ?? []"
          :key="opt.value"
          :value="opt.value"
        >
          {{ opt.label }}
        </option>
      </select>

      <ExpressionInput
        v-else
        :model-value="(configValue(field.key) as string) || ''"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        :dialog-key-label="field.label"
        :field-key="field.key"
        @update:model-value="setConfigValue(field.key, $event)"
      />
    </div>
  </template>
</template>
