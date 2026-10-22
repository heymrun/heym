<script setup lang="ts">
import { computed } from "vue";
import { X } from "lucide-vue-next";

import type { NodeResult, WorkflowNode } from "@/types/workflow";

import PluginIcon from "@/components/Panels/PluginIcon.vue";
import { isTileFillingIcon, nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { cn } from "@/lib/utils";
import { NODE_DEFINITIONS } from "@/types/node";

const props = defineProps<{ node: WorkflowNode; result: NodeResult | null }>();
const emit = defineEmits<{ (event: "clear"): void }>();

const colorVar = computed<string>(() => NODE_DEFINITIONS[props.node.type]?.color ?? "node-action");
const typeLabel = computed<string>(() => NODE_DEFINITIONS[props.node.type]?.label ?? props.node.type);
const isPlugin = computed<boolean>(
  () => (props.node.type === "plugin" || props.node.type === "pluginTrigger") && !!props.node.data.pluginId,
);
const statusLabel = computed<string>(() => {
  const status = props.result?.status ?? "";
  return status ? status.charAt(0).toUpperCase() + status.slice(1) : "";
});
const durationLabel = computed<string>(() => {
  const ms = props.result?.execution_time_ms ?? 0;
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
});
const stateHint = computed<string>(() =>
  props.result
    ? "This node ran. The AI sees its last output and error when it edits the node."
    : "This node has no output in the current run. Run it first if the AI should see its output.",
);
const statusDotClass = computed<string>(() => {
  if (props.result?.status === "error") return "bg-destructive";
  if (props.result?.status === "success") return "bg-success";
  return "bg-muted-foreground";
});
</script>

<template>
  <div
    class="mb-3 shrink-0 rounded-lg border border-border bg-muted/30 p-2.5"
    data-testid="ai-node-focus-card"
    :data-variant="result ? 'card' : 'compact'"
  >
    <div class="flex items-start gap-2.5">
      <div
        v-if="!result"
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        :style="{ backgroundColor: `hsl(var(--${colorVar}) / 0.12)` }"
      >
        <PluginIcon
          v-if="isPlugin"
          :plugin-id="node.data.pluginId!"
          :node-key="node.data.pluginNodeKey"
          size-class="w-4.5 h-4.5"
        />
        <component
          :is="nodeIcons[node.type]"
          v-else
          :class="cn(isTileFillingIcon(node.type) ? 'w-full h-full' : 'w-4.5 h-4.5', nodeIconColorClass[node.type])"
        />
      </div>
      <div class="min-w-0 flex-1">
        <p
          class="text-[11px] leading-4 text-muted-foreground"
          data-testid="ai-node-focus-state"
          :title="stateHint"
        >
          Modifying Node:<span
            v-if="result"
            class="ml-1 text-primary dark:text-brand-primary-soft"
          >(Has Node Output)</span>
        </p>
        <p
          v-if="!result"
          class="truncate text-sm font-medium leading-5"
        >
          {{ node.data.label }}
        </p>
      </div>
      <button
        type="button"
        class="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        title="Close node focus and edit the whole workflow"
        data-testid="ai-node-focus-clear"
        @click="emit('clear')"
      >
        <X class="h-3.5 w-3.5" />
      </button>
    </div>

    <div
      v-if="result"
      class="relative mt-1.5 overflow-hidden rounded-xl border bg-card px-3 pb-2.5 pt-3"
      :style="{ borderColor: `hsl(var(--${colorVar}) / 0.6)` }"
    >
      <div
        class="absolute inset-x-0 top-0 h-[3px]"
        :style="{ backgroundColor: `hsl(var(--${colorVar}))` }"
      />
      <div class="flex items-center gap-3">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
          :style="{ backgroundColor: `hsl(var(--${colorVar}) / 0.12)` }"
        >
          <PluginIcon
            v-if="isPlugin"
            :plugin-id="node.data.pluginId!"
            :node-key="node.data.pluginNodeKey"
            size-class="w-4.5 h-4.5"
          />
          <component
            :is="nodeIcons[node.type]"
            v-else
            :class="cn(isTileFillingIcon(node.type) ? 'w-full h-full' : 'w-4.5 h-4.5', nodeIconColorClass[node.type])"
          />
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold leading-tight">
            {{ node.data.label }}
          </p>
          <p class="text-xs text-muted-foreground">
            {{ typeLabel }}
          </p>
        </div>
        <p
          class="flex shrink-0 items-center gap-1.5 self-end text-[11px] leading-4 text-muted-foreground"
          data-testid="ai-node-focus-status"
        >
          <span :class="['h-1.5 w-1.5 rounded-full', statusDotClass]" />
          <span :class="result.status === 'error' ? 'text-destructive' : ''">{{ statusLabel }}</span>
          <span>·</span>
          <span>{{ durationLabel }}</span>
        </p>
      </div>
      <p
        v-if="result.error"
        class="mt-1 line-clamp-2 break-words font-mono text-[11px] leading-4 text-destructive/90"
        :title="result.error"
      >
        {{ result.error }}
      </p>
    </div>
  </div>
</template>
