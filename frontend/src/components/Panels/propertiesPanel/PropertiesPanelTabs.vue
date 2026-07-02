<script setup lang="ts">
import { Settings, Zap } from "lucide-vue-next";
import { cn } from "@/lib/utils";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  activeTab,
  isRunbookPlaying,
  revealRunTabForRunbook,
} = usePropertiesPanelContext();
</script>

<template>
  <div class="flex border-b border-border/30 p-1 gap-1 bg-muted/20">
    <button
      :class="cn(
        'flex-1 px-3 py-2 min-h-[44px] text-sm font-medium transition-all flex items-center justify-center gap-2 rounded-lg',
        activeTab === 'properties'
          ? 'text-primary bg-primary/10 shadow-sm dark:bg-primary/20 dark:text-primary-foreground'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
      )"
      @click="activeTab = 'properties'"
    >
      <Settings class="w-4 h-4" />
      <span class="hidden md:inline">Properties</span>
    </button>
    <button
      data-runbook-run
      :class="cn(
        'flex-1 px-3 py-2 min-h-[44px] text-sm font-medium transition-all flex items-center justify-center gap-2 rounded-lg',
        activeTab === 'config'
          ? 'text-primary bg-primary/10 shadow-sm dark:bg-primary/20 dark:text-primary-foreground'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
        isRunbookPlaying && 'runbook-pulse'
      )"
      @click="activeTab = 'config'"
      @focus="revealRunTabForRunbook"
      @mouseenter="revealRunTabForRunbook"
    >
      <Zap class="w-4 h-4" />
      <span class="hidden md:inline">Run</span>
    </button>
  </div>
</template>
