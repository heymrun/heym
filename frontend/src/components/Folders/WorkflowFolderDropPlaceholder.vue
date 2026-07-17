<script setup lang="ts">
import { FolderInput, MapPin } from "lucide-vue-next";

interface Props {
  targetId: string;
  targetKind: "Folder" | "Subfolder" | "Root";
  targetLabel: string;
  workflowName: string;
  valid: boolean;
}

defineProps<Props>();
</script>

<template>
  <div
    class="workflow-folder-drop-placeholder flex min-h-[82px] items-center gap-3 rounded-xl border-2 border-dashed px-4 py-3 transition-colors"
    :class="valid
      ? 'border-primary bg-primary/[0.08] text-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.08)]'
      : 'border-border bg-muted/30 text-muted-foreground'"
    :data-testid="`workflow-folder-drop-placeholder-${targetId}`"
    :data-drop-valid="String(valid)"
    role="status"
    aria-live="polite"
  >
    <div
      class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
      :class="valid ? 'bg-primary/15' : 'bg-muted'"
    >
      <FolderInput class="h-5 w-5" />
    </div>
    <div class="min-w-0 flex-1">
      <p class="text-sm font-semibold">
        {{ valid ? `Move to ${targetKind}` : `Already in ${targetKind}` }}
      </p>
      <p class="mt-0.5 truncate text-xs text-muted-foreground">
        {{ workflowName }}
      </p>
    </div>
    <div class="flex max-w-[45%] items-center gap-1 text-right text-xs font-medium">
      <MapPin class="h-3.5 w-3.5 shrink-0" />
      <span class="truncate">{{ targetLabel }}</span>
    </div>
  </div>
</template>

<style scoped>
.workflow-folder-drop-placeholder {
  animation: drop-placeholder-in 0.16s ease-out both;
}

@keyframes drop-placeholder-in {
  from {
    opacity: 0;
    transform: scale(0.985);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
