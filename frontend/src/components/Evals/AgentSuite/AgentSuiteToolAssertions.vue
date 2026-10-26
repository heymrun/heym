<script setup lang="ts">
import { Plus, X } from "lucide-vue-next";
import { computed, ref } from "vue";

import { TOOL_KIND_LABELS, toolKey } from "@/components/Evals/AgentSuite/agentSuiteFormat";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import type { AgentToolUsage, ToolAssertion, ToolExpect, ToolKind } from "@/types/evals";

type ToolChoice = ToolExpect | "any";

interface ToolRow {
  key: string;
  kind: ToolKind;
  name: string;
  label: string;
  server: string | null;
  usage: AgentToolUsage | null;
}

interface Props {
  tools: AgentToolUsage[];
  runCount: number;
  assertions: ToolAssertion[];
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "update:assertions", value: ToolAssertion[]): void;
}>();

const CHOICES: { value: ToolChoice; label: string }[] = [
  { value: "called", label: "Must call" },
  { value: "not_called", label: "Must not call" },
  { value: "any", label: "Either" },
];

// Sub-workflows are always listed from the agent's settings, so they are not added by hand.
const ADDABLE_KINDS: ToolKind[] = ["tool", "mcp", "sub_agent", "skill"];

const customKind = ref<ToolKind>("tool");
const customName = ref("");

const rows = computed((): ToolRow[] => {
  const list: ToolRow[] = props.tools.map((tool) => ({
    key: toolKey(tool.kind, tool.name),
    kind: tool.kind,
    name: tool.name,
    label: tool.label,
    server: tool.server,
    usage: tool,
  }));
  const known = new Set(list.map((row) => row.key));
  for (const assertion of props.assertions) {
    const key = toolKey(assertion.kind, assertion.name);
    if (known.has(key)) continue;
    list.push({
      key,
      kind: assertion.kind,
      name: assertion.name,
      label: assertion.label || assertion.name,
      server: null,
      usage: null,
    });
  }
  return list;
});

function choiceFor(row: ToolRow): ToolChoice {
  const found = props.assertions.find(
    (assertion) => toolKey(assertion.kind, assertion.name) === row.key,
  );
  return found?.expect ?? "any";
}

function without(row: ToolRow): ToolAssertion[] {
  return props.assertions.filter((assertion) => toolKey(assertion.kind, assertion.name) !== row.key);
}

function setChoice(row: ToolRow, choice: ToolChoice): void {
  const rest = without(row);
  emit(
    "update:assertions",
    choice === "any"
      ? rest
      : [...rest, { kind: row.kind, name: row.name, label: row.label, expect: choice }],
  );
}

function removeRow(row: ToolRow): void {
  emit("update:assertions", without(row));
}

function addCustomTool(): void {
  const name = customName.value.trim();
  if (!name) return;
  const row: ToolRow = {
    key: toolKey(customKind.value, name),
    kind: customKind.value,
    name,
    label: name,
    server: null,
    usage: null,
  };
  setChoice(row, "called");
  customName.value = "";
}

function usageText(row: ToolRow): string {
  if (!row.usage) return "Added by hand, not seen in recent runs";
  return `Called in ${row.usage.runs_called}/${props.runCount} runs`;
}
</script>

<template>
  <section>
    <h3 class="text-sm font-medium text-foreground">
      Tool-call assertions
    </h3>
    <p class="mb-3 mt-1 text-xs text-muted-foreground">
      Covers Python and node tools, MCP tools, sub-agents, sub-workflows and skills. A run fails
      when it skips one it must call or calls one it must not.
    </p>
    <div class="divide-y divide-border/40 rounded-xl border border-border/60">
      <div
        v-for="row in rows"
        :key="row.key"
        class="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5"
        data-testid="agent-suite-tool-row"
      >
        <div class="flex min-w-0 items-center gap-2">
          <span class="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
            {{ TOOL_KIND_LABELS[row.kind] }}
          </span>
          <div class="min-w-0">
            <p class="truncate font-mono text-xs text-foreground">
              {{ row.label }}<span
                v-if="row.server"
                class="ml-1 font-sans text-muted-foreground"
              >({{ row.server }})</span>
            </p>
            <p class="text-xs text-muted-foreground">
              {{ usageText(row) }}
            </p>
          </div>
        </div>
        <div class="flex items-center gap-1">
          <div class="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
            <button
              v-for="choice in CHOICES"
              :key="choice.value"
              type="button"
              class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
              :class="choiceFor(row) === choice.value
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'"
              :aria-pressed="choiceFor(row) === choice.value"
              @click="setChoice(row, choice.value)"
            >
              {{ choice.label }}
            </button>
          </div>
          <button
            v-if="!row.usage"
            type="button"
            class="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
            :aria-label="`Remove ${row.label}`"
            title="Remove"
            data-testid="agent-suite-tool-remove"
            @click="removeRow(row)"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
      </div>
      <p
        v-if="rows.length === 0"
        class="px-3 py-4 text-center text-xs text-muted-foreground"
      >
        No tools seen yet. Add one by name below.
      </p>
    </div>
    <form
      class="mt-2 flex flex-wrap gap-2"
      @submit.prevent="addCustomTool"
    >
      <Select
        v-model="customKind"
        :options="ADDABLE_KINDS.map((kind) => ({ value: kind, label: TOOL_KIND_LABELS[kind] }))"
        class="w-36"
      />
      <Input
        v-model="customName"
        placeholder="Name, e.g. an MCP tool or a sub-agent label"
        class="max-w-xs"
        data-testid="agent-suite-custom-tool"
      />
      <Button
        type="submit"
        variant="outline"
        class="gap-1.5"
        :disabled="!customName.trim()"
      >
        <Plus class="h-4 w-4" />
        Add
      </Button>
    </form>
  </section>
</template>
