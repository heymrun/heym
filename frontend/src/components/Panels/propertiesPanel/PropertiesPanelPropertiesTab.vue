<script setup lang="ts">
import SelectedNodePanel from "./SelectedNodePanel.vue";
import WorkflowSettingsPanel from "./WorkflowSettingsPanel.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const { activeTab, selectedNode } = usePropertiesPanelContext();
</script>

<template>
  <div
    v-if="activeTab === 'properties'"
    class="flex-1 flex flex-col overflow-hidden overflow-x-hidden"
  >
    <WorkflowSettingsPanel v-if="!selectedNode" />
    <SelectedNodePanel v-else />
  </div>
</template>
