<script setup lang="ts">
import { Bot } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";

import { credentialsApi } from "@/services/api";
import type { NodeData, Workflow } from "@/types/workflow";

interface Props {
  workflow: Workflow;
  nodeId: string;
}

const props = defineProps<Props>();

interface Chip {
  kind: string;
  label: string;
}

const credentialNames = ref<Record<string, string>>({});

const node = computed(() => props.workflow.nodes.find((item) => item.id === props.nodeId) ?? null);
const data = computed((): NodeData | null => node.value?.data ?? null);

const modelText = computed((): string => {
  const d = data.value;
  if (!d) return "";
  const credential = d.credentialId ? credentialNames.value[d.credentialId] : undefined;
  return [credential, d.model].filter(Boolean).join(" · ") || "Not set";
});

const tuningText = computed((): string => {
  const d = data.value;
  if (!d) return "";
  const parts = [];
  if (d.reasoningEffort) parts.push(`Reasoning ${d.reasoningEffort}`);
  if (typeof d.temperature === "number") parts.push(`Temperature ${d.temperature}`);
  if (d.fallbackModel) parts.push(`Fallback ${d.fallbackModel}`);
  return parts.join(" · ");
});

const chips = computed((): Chip[] => {
  const d = data.value;
  if (!d) return [];
  const list: Chip[] = [];
  for (const tool of d.tools ?? []) list.push({ kind: "Tool", label: tool.name });
  for (const connection of d.mcpConnections ?? []) {
    list.push({ kind: "MCP", label: connection.label || connection.transport });
  }
  for (const skill of d.skills ?? []) list.push({ kind: "Skill", label: skill.name });
  if (d.isOrchestrator) {
    for (const label of d.subAgentLabels ?? []) list.push({ kind: "Sub-agent", label });
  }
  for (const id of d.subWorkflowIds ?? []) {
    list.push({ kind: "Sub-workflow", label: d.subWorkflowNames?.[id] ?? id.slice(0, 8) });
  }
  return list;
});

const settings = computed((): { label: string; value: string }[] => {
  const d = data.value;
  if (!d) return [];
  const onOff = (value: unknown): string => (value ? "On" : "Off");
  return [
    { label: "Max tool iterations", value: String(d.maxToolIterations ?? 30) },
    { label: "Tool timeout", value: `${d.toolTimeoutSeconds ?? 30} s` },
    { label: "Request timeout", value: `${d.requestTimeoutSeconds ?? 60} s` },
    { label: "Human review", value: onOff(d.hitlEnabled) },
    {
      label: "Guardrails",
      value: d.guardrailsEnabled ? `On · ${d.guardrailsSeverity ?? "medium"}` : "Off",
    },
    { label: "JSON output", value: onOff(d.jsonOutputEnabled) },
    { label: "Image input", value: onOff(d.imageInputEnabled) },
    { label: "Persistent memory", value: onOff(d.persistentMemoryEnabled) },
  ];
});

onMounted(async () => {
  try {
    const credentials = await credentialsApi.listLLM();
    credentialNames.value = Object.fromEntries(credentials.map((c) => [c.id, c.name]));
  } catch {
    credentialNames.value = {};
  }
});
</script>

<template>
  <aside
    class="self-start rounded-xl border border-border/60 bg-card p-4"
    data-testid="agent-suite-agent-details"
  >
    <template v-if="data">
      <div class="flex items-center gap-3">
        <Bot class="h-5 w-5 shrink-0 text-primary dark:text-brand-primary-soft" />
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-foreground">
            {{ data.label || nodeId }}
          </p>
          <p class="truncate text-xs text-muted-foreground">
            {{ workflow.name }}
          </p>
        </div>
      </div>

      <dl class="mt-4 space-y-3 text-sm">
        <div>
          <dt class="text-xs text-muted-foreground">
            Model
          </dt>
          <dd class="text-foreground">
            {{ modelText }}
          </dd>
          <dd
            v-if="tuningText"
            class="text-xs text-muted-foreground"
          >
            {{ tuningText }}
          </dd>
        </div>
        <div v-if="data.systemInstruction">
          <dt class="text-xs text-muted-foreground">
            System instructions
          </dt>
          <dd class="line-clamp-6 whitespace-pre-wrap text-foreground">
            {{ data.systemInstruction }}
          </dd>
        </div>
        <div v-if="data.userMessage">
          <dt class="text-xs text-muted-foreground">
            User message
          </dt>
          <dd class="line-clamp-3 whitespace-pre-wrap font-mono text-xs text-foreground">
            {{ data.userMessage }}
          </dd>
        </div>
        <div>
          <dt class="mb-1 text-xs text-muted-foreground">
            Tools
          </dt>
          <dd
            v-if="chips.length > 0"
            class="flex flex-wrap gap-1.5"
          >
            <span
              v-for="chip in chips"
              :key="`${chip.kind}:${chip.label}`"
              class="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground"
            >
              <span class="text-muted-foreground">{{ chip.kind }}</span>
              {{ chip.label }}
            </span>
          </dd>
          <dd
            v-else
            class="text-xs text-muted-foreground"
          >
            No tools attached.
          </dd>
        </div>
      </dl>

      <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border/40 pt-3 text-xs">
        <div
          v-for="item in settings"
          :key="item.label"
          class="flex justify-between gap-2"
        >
          <dt class="text-muted-foreground">
            {{ item.label }}
          </dt>
          <dd class="text-right text-foreground">
            {{ item.value }}
          </dd>
        </div>
      </dl>
    </template>
    <p
      v-else
      class="text-sm text-muted-foreground"
    >
      Could not load this agent.
    </p>
  </aside>
</template>
