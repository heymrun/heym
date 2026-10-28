<script setup lang="ts">
import { onClickOutside } from "@vueuse/core";
import { Bot, ChevronDown, FileText, Pencil, Plus, Trash2 } from "lucide-vue-next";
import { computed, ref } from "vue";

import Button from "@/components/ui/Button.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import type { EvalSuiteListItem, EvalSuiteType } from "@/types/evals";

interface Props {
  suites: EvalSuiteListItem[];
  selectedSuiteId: string | null;
  showEditButton?: boolean;
}

const props = withDefaults(defineProps<Props>(), { showEditButton: false });

const emit = defineEmits<{
  (e: "select", id: string | null): void;
  (e: "delete"): void;
  (e: "edit"): void;
  (e: "create", type: EvalSuiteType): void;
}>();

const TYPE_LABELS: Record<EvalSuiteType, string> = {
  prompt: "Prompt",
  agent: "Agent",
};

const menuOpen = ref(false);
const menuRef = ref<HTMLElement | null>(null);
onClickOutside(menuRef, () => {
  menuOpen.value = false;
});

const options = computed(() =>
  props.suites.map((suite) => ({
    value: suite.id,
    label: suite.name,
    hint: TYPE_LABELS[suite.suite_type],
  })),
);

function create(type: EvalSuiteType): void {
  menuOpen.value = false;
  emit("create", type);
}
</script>

<template>
  <div class="flex items-center justify-between gap-2 sm:gap-4">
    <div class="flex min-w-0 flex-1 items-center gap-2 sm:min-w-[12rem] sm:flex-none">
      <div class="min-w-0 flex-1 sm:contents">
        <SearchableSelect
          :model-value="selectedSuiteId ?? undefined"
          :options="options"
          placeholder="Select suite"
          search-placeholder="Search suites..."
          class="sm:min-w-[16rem]"
          data-testid="eval-suite-select"
          @update:model-value="(v) => emit('select', v ?? null)"
        />
      </div>
      <Button
        v-if="selectedSuiteId"
        variant="ghost"
        size="icon"
        class="min-h-[44px] min-w-[44px] shrink-0 text-muted-foreground hover:text-destructive"
        title="Delete suite"
        @click="emit('delete')"
      >
        <Trash2 class="h-4 w-4" />
      </Button>
    </div>
    <div class="flex shrink-0 gap-2">
      <Button
        v-if="showEditButton"
        variant="outline"
        class="min-h-[44px] shrink-0 gap-2 !px-3 sm:!px-5"
        title="Edit"
        @click="emit('edit')"
      >
        <Pencil class="h-4 w-4" />
        <span class="sr-only sm:not-sr-only">Edit</span>
      </Button>
      <div
        ref="menuRef"
        class="relative"
      >
        <Button
          variant="gradient"
          class="min-h-[44px] shrink-0 gap-2 !px-3 sm:!px-5"
          title="New suite"
          data-testid="eval-new-suite"
          @click="menuOpen = !menuOpen"
        >
          <Plus class="h-4 w-4" />
          <span class="sr-only sm:not-sr-only">New Suite</span>
          <ChevronDown class="h-4 w-4" />
        </Button>
        <div
          v-if="menuOpen"
          class="absolute right-0 top-full z-20 mt-1 w-64 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-popover p-1 shadow-lg"
        >
          <button
            type="button"
            class="flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left hover:bg-accent"
            data-testid="eval-new-prompt-suite"
            @click="create('prompt')"
          >
            <FileText class="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <span>
              <span class="block text-sm font-medium text-foreground">Prompt suite</span>
              <span class="block text-xs text-muted-foreground">Test a system prompt across models</span>
            </span>
          </button>
          <button
            type="button"
            class="flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left hover:bg-accent"
            data-testid="eval-new-agent-suite"
            @click="create('agent')"
          >
            <Bot class="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <span>
              <span class="block text-sm font-medium text-foreground">Agent suite</span>
              <span class="block text-xs text-muted-foreground">Check an agent's real runs: tools, latency, cost</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
