<script setup lang="ts">
import {
  ChevronLeft,
  Compass,
  Download,
  GitBranch,
  Globe,
  LayoutTemplate,
  Moon,
  Share2,
  Sparkles,
  Sun,
  TerminalSquare,
  Trash2,
} from "lucide-vue-next";

interface Props {
  isDashboardWidget: boolean;
  isStandardWorkflow: boolean;
  isDark: boolean;
}

defineProps<Props>();

const emit = defineEmits<{
  (event: "back"): void;
  (event: "clear"): void;
  (event: "edit-history"): void;
  (event: "download"): void;
  (event: "portal"): void;
  (event: "template"): void;
  (event: "curl"): void;
  (event: "guide"): void;
  (event: "theme"): void;
  (event: "share"): void;
  (event: "ai"): void;
}>();
</script>

<template>
  <section class="rounded-xl border border-border/70 bg-card px-4 pb-1 pt-4">
    <p class="pb-2 text-xs font-semibold">
      More actions
    </p>
    <button
      v-if="isDashboardWidget"
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('back')"
    >
      <ChevronLeft class="h-4 w-4" />Back to Dashboard
    </button>
    <button
      v-else
      type="button"
      class="mobile-workflow-menu-row text-destructive"
      @click="emit('clear')"
    >
      <Trash2 class="h-4 w-4" />Clear workflow
    </button>
    <button
      v-if="isStandardWorkflow"
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('share')"
    >
      <Share2 class="h-4 w-4" />Share workflow
    </button>
    <button
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('ai')"
    >
      <Sparkles class="h-4 w-4" />AI Assistant
    </button>
    <button
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('edit-history')"
    >
      <GitBranch class="h-4 w-4" />Edit history
    </button>
    <button
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('download')"
    >
      <Download class="h-4 w-4" />Download workflow
    </button>
    <button
      v-if="isStandardWorkflow"
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('portal')"
    >
      <Globe class="h-4 w-4" />Portal
    </button>
    <button
      v-if="isStandardWorkflow"
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('template')"
    >
      <LayoutTemplate class="h-4 w-4" />Save as template
    </button>
    <button
      v-if="isStandardWorkflow"
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('curl')"
    >
      <TerminalSquare class="h-4 w-4" />cURL
    </button>
    <button
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('guide')"
    >
      <Compass class="h-4 w-4" />Page guide
    </button>
    <button
      type="button"
      class="mobile-workflow-menu-row"
      @click="emit('theme')"
    >
      <Sun
        v-if="isDark"
        class="h-4 w-4"
      />
      <Moon
        v-else
        class="h-4 w-4"
      />
      {{ isDark ? "Switch to light mode" : "Switch to dark mode" }}
    </button>
  </section>
</template>

<style scoped>
.mobile-workflow-menu-row { @apply flex h-11 w-full items-center gap-3 border-b border-border/60 text-left text-sm last:border-b-0; }
</style>
