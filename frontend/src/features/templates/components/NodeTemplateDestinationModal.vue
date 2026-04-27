<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { FilePlus2, Search, Workflow } from "lucide-vue-next";

import { workflowApi } from "@/services/api";
import type { WorkflowListItem } from "@/types/workflow";
import type { NodeTemplate } from "../types/template.types";

interface Props {
  template: NodeTemplate;
}

const { template } = defineProps<Props>();

const emit = defineEmits<{
  choose: [destination: "new" | "existing", workflowId?: string];
  close: [];
}>();

const workflows = ref<WorkflowListItem[]>([]);
const loadingWorkflows = ref(false);
const searchQuery = ref("");

const filteredWorkflows = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  if (!q) return workflows.value;
  return workflows.value.filter((w) => w.name.toLowerCase().includes(q));
});

async function loadWorkflows(): Promise<void> {
  loadingWorkflows.value = true;
  try {
    workflows.value = (await workflowApi.list()).filter((w) => !w.scheduled_for_deletion);
  } catch {
    workflows.value = [];
  } finally {
    loadingWorkflows.value = false;
  }
}

onMounted(() => {
  loadWorkflows();
  const unsub = onDismissOverlays(() => emit("close"));
  onUnmounted(unsub);
});
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      @click.self="emit('close')"
    >
      <div
        class="w-full max-w-sm rounded-2xl border border-border/50 bg-card shadow-2xl flex flex-col"
        style="max-height: 80vh;"
        @click.stop
      >
        <!-- Header -->
        <div class="p-5 pb-3">
          <h3 class="text-base font-semibold text-foreground">
            Add to workflow
          </h3>
          <p class="mt-1 text-sm text-muted-foreground">
            Where should
            <span class="font-medium text-foreground">{{ template.name }}</span>
            be added?
          </p>
        </div>

        <!-- New workflow button -->
        <div class="px-5 pb-3">
          <button
            class="w-full flex items-center gap-3 p-3 rounded-xl border border-primary/40 hover:border-primary/70 hover:bg-primary/5 transition-all text-left"
            type="button"
            @click="emit('choose', 'new')"
          >
            <FilePlus2 class="w-5 h-5 text-primary shrink-0" />
            <div>
              <div class="text-sm font-medium">
                New workflow
              </div>
              <div class="text-xs text-muted-foreground">
                Create a fresh workflow with this node
              </div>
            </div>
          </button>
        </div>

        <!-- Divider -->
        <div class="mx-5 border-t border-border/30 mb-3" />

        <!-- Search -->
        <div class="px-5 mb-2">
          <div class="relative">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
            <input
              v-model="searchQuery"
              class="w-full pl-9 pr-3 py-2 text-sm bg-muted/30 border border-border/40 rounded-lg outline-none focus:border-primary/50 focus:bg-muted/50 placeholder:text-muted-foreground transition-colors"
              placeholder="Search workflows…"
              type="text"
            >
          </div>
        </div>

        <!-- Workflow list (max 7 items visible, rest scrollable) -->
        <div
          class="px-5 pb-5 overflow-y-auto"
          style="max-height: 294px;"
        >
          <div
            v-if="loadingWorkflows"
            class="flex flex-col gap-2"
          >
            <div
              v-for="i in 3"
              :key="i"
              class="h-10 rounded-lg bg-muted/40 animate-pulse"
            />
          </div>
          <div
            v-else-if="filteredWorkflows.length === 0"
            class="py-6 text-center text-sm text-muted-foreground"
          >
            {{ searchQuery ? "No workflows match your search" : "No workflows yet" }}
          </div>
          <div
            v-else
            class="flex flex-col gap-1"
          >
            <button
              v-for="wf in filteredWorkflows"
              :key="wf.id"
              class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors text-left group"
              type="button"
              @click="emit('choose', 'existing', wf.id)"
            >
              <Workflow class="w-4 h-4 text-muted-foreground group-hover:text-primary shrink-0 transition-colors" />
              <span class="text-sm text-foreground truncate">{{ wf.name }}</span>
            </button>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-5 pb-5 pt-1 border-t border-border/30">
          <button
            class="w-full text-sm text-muted-foreground hover:text-foreground text-center transition-colors py-1"
            type="button"
            @click="emit('close')"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
