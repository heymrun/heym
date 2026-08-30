<script setup lang="ts">
import { computed, watch } from "vue";

import DebugPanel from "@/components/Panels/DebugPanel.vue";
import PropertiesPanelDialogs from "@/components/Panels/propertiesPanel/PropertiesPanelDialogs.vue";
import PropertiesPanelPropertiesTab from "@/components/Panels/propertiesPanel/PropertiesPanelPropertiesTab.vue";
import PropertiesPanelRunTab from "@/components/Panels/propertiesPanel/PropertiesPanelRunTab.vue";
import { providePropertiesPanelContext, usePropertiesPanelController } from "@/components/Panels/propertiesPanel/usePropertiesPanelController";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  tab: "properties" | "config";
}

const props = defineProps<Props>();
const workflowStore = useWorkflowStore();
const propertiesPanelContext = usePropertiesPanelController();
providePropertiesPanelContext(propertiesPanelContext);
const hasExecution = computed(
  () => workflowStore.executionResult !== null || workflowStore.nodeResults.length > 0,
);

watch(
  () => props.tab,
  (tab) => {
    workflowStore.propertiesPanelTab = tab;
  },
  { immediate: true },
);
</script>

<template>
  <div
    class="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-border/70 bg-card"
  >
    <PropertiesPanelPropertiesTab />
    <PropertiesPanelRunTab />
  </div>

  <DebugPanel
    v-if="tab === 'config' && hasExecution"
    embedded
    class="mt-3 overflow-hidden rounded-xl border border-border/70"
  />

  <PropertiesPanelDialogs />
</template>
