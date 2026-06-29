<script setup lang="ts">
import PropertiesPanelDialogs from "@/components/Panels/propertiesPanel/PropertiesPanelDialogs.vue";
import PropertiesPanelPropertiesTab from "@/components/Panels/propertiesPanel/PropertiesPanelPropertiesTab.vue";
import PropertiesPanelRunTab from "@/components/Panels/propertiesPanel/PropertiesPanelRunTab.vue";
import PropertiesPanelTabs from "@/components/Panels/propertiesPanel/PropertiesPanelTabs.vue";
import { providePropertiesPanelContext, usePropertiesPanelController } from "@/components/Panels/propertiesPanel/usePropertiesPanelController";

const propertiesPanelContext = usePropertiesPanelController();
providePropertiesPanelContext(propertiesPanelContext);
</script>

<template>
  <div
    class="properties-panel w-80 sm:w-72 md:w-80 border-l border-border/30 flex flex-col max-w-full overflow-x-hidden"
  >
    <PropertiesPanelTabs />
    <PropertiesPanelPropertiesTab />
    <PropertiesPanelRunTab />
  </div>

  <PropertiesPanelDialogs />
</template>

<style scoped>
.properties-panel {
  background: linear-gradient(180deg,
      hsl(var(--card) / 0.95) 0%,
      hsl(var(--card) / 0.85) 100%);
  backdrop-filter: blur(8px);
  position: relative;
  z-index: 10;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
