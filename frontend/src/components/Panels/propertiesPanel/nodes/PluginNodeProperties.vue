<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { isAxiosError } from "axios";

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
const loadingPlugins = ref(true);
const pluginsDisabled = ref(false);
const pluginLoadError = ref<string | null>(null);

onMounted(async () => {
  loadingPlugins.value = true;
  pluginsDisabled.value = false;
  pluginLoadError.value = null;
  try {
    plugins.value = await listPlugins();
  } catch (err) {
    plugins.value = [];
    if (isAxiosError<{ detail?: string }>(err) && err.response?.status === 404) {
      pluginsDisabled.value = true;
      pluginLoadError.value =
        err.response.data?.detail ?? "Plugins are disabled on this instance.";
    } else {
      pluginLoadError.value = pluginErrorMessage(err);
    }
  } finally {
    loadingPlugins.value = false;
  }
});

const pluginId = computed<string>(() => selectedNode.value?.data.pluginId ?? "");
const pluginNodeKey = computed<string>(() => selectedNode.value?.data.pluginNodeKey ?? "");

const pkg = computed<PluginSummary | undefined>(() =>
  plugins.value.find((plugin) => plugin.id === pluginId.value),
);

const fallbackNodeKind = computed<PluginNodeSummary["kind"]>(() =>
  selectedNode.value?.type === "pluginTrigger" ? "trigger" : "action",
);

const nodeDef = computed<PluginNodeSummary | undefined>(() => {
  const nodes = pkg.value?.nodes ?? [];
  const key = pluginNodeKey.value;
  return (
    (key ? nodes.find((node) => node.key === key) : undefined) ??
    nodes.find((node) => node.kind === fallbackNodeKind.value)
  );
});

const statusMessage = computed<string | null>(() => {
  if (!selectedNode.value) return null;
  if (loadingPlugins.value) return "Loading plugin definition...";
  if (pluginsDisabled.value) return pluginLoadError.value;
  if (pluginLoadError.value) return pluginLoadError.value;
  if (!pluginId.value) return "This node is not bound to a plugin package.";
  if (plugins.value.length === 0) return "No plugins are installed on this instance.";
  if (!pkg.value) return `Plugin "${pluginId.value}" is not installed on this instance.`;
  if (!pkg.value.enabled) return `Plugin "${pkg.value.name}" is installed but disabled.`;
  if (!nodeDef.value) {
    return `Plugin "${pkg.value.name}" does not expose any ${fallbackNodeKind.value} nodes.`;
  }
  return null;
});

const fields = computed<PluginFieldDef[]>(() => (statusMessage.value ? [] : nodeDef.value?.fields ?? []));

function pluginErrorMessage(err: unknown): string {
  if (isAxiosError<{ detail?: string }>(err)) {
    const detail = err.response?.data?.detail;
    if (detail) return `Unable to load plugins: ${detail}`;
    if (err.response?.status) return `Unable to load plugins (HTTP ${err.response.status}).`;
  }
  return err instanceof Error ? `Unable to load plugins: ${err.message}` : "Unable to load plugins.";
}

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
      v-if="statusMessage"
      data-testid="plugin-node-status"
      :class="[
        'text-xs',
        pluginLoadError && !pluginsDisabled ? 'text-destructive' : 'text-muted-foreground',
      ]"
    >
      {{ statusMessage }}
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
