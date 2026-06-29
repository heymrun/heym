<script setup lang="ts">
import NodeErrorHandlingSection from "./NodeErrorHandlingSection.vue";
import NodeLastOutputSection from "./NodeLastOutputSection.vue";
import PinnedDataSection from "./PinnedDataSection.vue";
import SelectedNodeHeader from "./SelectedNodeHeader.vue";
import SelectedNodeLabelField from "./SelectedNodeLabelField.vue";
import NodePropertiesForm from "@/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const { selectedNode } = usePropertiesPanelContext();
</script>

<template>
  <div
    v-if="selectedNode"
    class="flex flex-col h-full overflow-hidden overflow-x-hidden"
  >
    <SelectedNodeHeader />

    <div class="flex-1 overflow-auto overflow-x-hidden p-4 space-y-4">
      <SelectedNodeLabelField />
      <NodePropertiesForm />
      <NodeErrorHandlingSection />
      <PinnedDataSection />
      <NodeLastOutputSection />
    </div>
  </div>
</template>
