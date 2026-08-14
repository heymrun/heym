<script setup lang="ts">
import { BookOpen, Power, Trash2 } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";
import { isTileFillingIcon } from "@/lib/nodeIcons";

const {
  nodeIcons,
  nodeColorMap,
  nodeDocSlugMap,
  selectedNode,
  selectedNodeTypeLabel,
  isNodeActive,
  toggleActive,
  deleteNode,
} = usePropertiesPanelContext();

// Some node colours are picked for their icon tile, where they sit on a tinted
// background. As small text on the panel they fall below a comfortable contrast
// ratio, so those types get a dedicated readability-tuned token.
const HEADER_FOREGROUND_TOKENS: Partial<Record<string, string>> = {
  agent: "--node-agent-header-foreground",
  code: "--node-code-header-foreground",
};

function typeLabelColor(nodeType: string): string {
  const token = HEADER_FOREGROUND_TOKENS[nodeType];
  if (token) {
    return `hsl(var(${token}))`;
  }
  return `hsl(var(--${nodeColorMap[nodeType as keyof typeof nodeColorMap]}) / 0.8)`;
}
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="p-4 border-b flex items-center justify-between shrink-0"
      :style="{
        backgroundColor: `hsl(var(--${nodeColorMap[selectedNode.type]}) / 0.15)`,
      }"
    >
      <div class="flex items-center gap-3 min-w-0">
        <div
          class="flex items-center justify-center w-9 h-9 rounded-lg shrink-0"
          :style="{
            backgroundColor: `hsl(var(--${nodeColorMap[selectedNode.type]}) / 0.2)`,
            color: selectedNode.type === 'agent'
              ? 'hsl(var(--node-agent-header-foreground))'
              : `hsl(var(--${nodeColorMap[selectedNode.type]}))`,
          }"
        >
          <component
            :is="nodeIcons[selectedNode.type]"
            :class="isTileFillingIcon(selectedNode.type) ? 'w-full h-full' : 'w-5 h-5'"
          />
        </div>
        <div class="flex flex-col min-w-0">
          <h2 class="font-semibold text-sm truncate">
            {{ selectedNode.data.label }}
          </h2>
          <div class="flex items-center gap-1.5">
            <span
              class="text-xs text-muted-foreground"
              :style="{ color: typeLabelColor(selectedNode.type) }"
            >{{ selectedNodeTypeLabel
            }}</span>
            <span
              v-if="!isNodeActive"
              class="text-[10px] text-gray-500 bg-gray-800 px-1 py-0.5 rounded"
            >disabled</span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-0.5 shrink-0 -mr-2">
        <Button
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8 text-muted-foreground hover:text-foreground"
          title="View documentation"
          @click.prevent="$router.push(`/docs/nodes/${nodeDocSlugMap[selectedNode.type]}`)"
        >
          <BookOpen class="w-4 h-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
          :class="isNodeActive ? 'text-green-500 hover:text-green-600' : 'text-gray-500 hover:text-gray-400'"
          :title="isNodeActive ? 'Disable node (D)' : 'Enable node (D)'"
          @click="toggleActive"
        >
          <Power class="w-4 h-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="text-destructive h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
          @click="deleteNode"
        >
          <Trash2 class="w-4 h-4" />
        </Button>
      </div>
    </div>
  </template>
</template>
