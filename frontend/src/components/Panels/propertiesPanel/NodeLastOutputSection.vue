<script setup lang="ts">
import { Check, CheckCircle2, ChevronLeft, ChevronRight, Copy, Maximize2, Minimize2, X, XCircle } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import JsonTree from "@/components/ui/JsonTree.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  copied,
  isLastOutputExpanded,
  lastOutputJsonTreeKey,
  lastOutputJsonAutoDepth,
  expandAllLastOutputJson,
  collapseAllLastOutputJson,
  selectedNodeEvaluateDialogLabel,
  nodeOutput,
  selectedNodeLoopItemNavigation,
  navigateToPreviousSelectedNodeLoopItem,
  navigateToNextSelectedNodeLoopItem,
  lastOutputExpandedPanelRef,
  formatOutput,
  displayNodeOutput,
  nodeOutputImageSrcs,
  imageLightboxSrc,
  copyOutput,
} = usePropertiesPanelContext();
</script>

<template>
  <div
    v-if="nodeOutput"
    class="space-y-2 pt-4 border-t rounded-lg border border-border/40 bg-muted/20 p-3"
  >
    <div
      :class="[
        'flex gap-2 min-w-0',
        selectedNodeLoopItemNavigation
          ? 'flex-col items-start'
          : 'items-center justify-between'
      ]"
    >
      <div class="flex items-center gap-2 min-w-0">
        <Label>Last Output</Label>
        <CheckCircle2
          v-if="nodeOutput.status === 'success'"
          class="w-4 h-4 shrink-0 text-green-500"
        />
        <XCircle
          v-else-if="nodeOutput.status === 'error'"
          class="w-4 h-4 shrink-0 text-red-500"
        />
      </div>
      <div
        v-if="!nodeOutput.error"
        :class="[
          'flex min-w-0 flex-wrap items-center gap-1.5',
          selectedNodeLoopItemNavigation ? 'w-full justify-start' : 'shrink-0 justify-end'
        ]"
      >
        <div
          v-if="selectedNodeLoopItemNavigation"
          class="flex items-center gap-0.5 rounded-md border border-border/50 bg-background/70 px-1 py-1"
        >
          <span class="px-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            Loop
          </span>
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7"
            :disabled="!selectedNodeLoopItemNavigation.canNavigatePrev"
            title="Previous loop item"
            @click.stop="navigateToPreviousSelectedNodeLoopItem"
          >
            <ChevronLeft class="w-3.5 h-3.5" />
          </Button>
          <span class="min-w-[3.5rem] text-center text-xs text-muted-foreground">
            {{ selectedNodeLoopItemNavigation.currentDisplayIndex }} /
            {{ selectedNodeLoopItemNavigation.totalDisplayCount }}
          </span>
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7"
            :disabled="!selectedNodeLoopItemNavigation.canNavigateNext"
            title="Next loop item"
            @click.stop="navigateToNextSelectedNodeLoopItem"
          >
            <ChevronRight class="w-3.5 h-3.5" />
          </Button>
        </div>
        <Button
          variant="ghost"
          size="sm"
          class="h-7 px-2 gap-1.5"
          @click="isLastOutputExpanded = !isLastOutputExpanded"
        >
          <Maximize2
            v-if="!isLastOutputExpanded"
            class="w-3.5 h-3.5"
          />
          <Minimize2
            v-else
            class="w-3.5 h-3.5"
          />
          <span class="text-xs">{{ isLastOutputExpanded ? 'Minimize' : 'Expand' }}</span>
        </Button>
        <button
          class="flex items-center gap-1 px-2 py-1 rounded hover:bg-muted transition-colors text-xs shrink-0"
          :title="copied ? 'Copied!' : 'Copy to clipboard'"
          @click="copyOutput"
        >
          <Check
            v-if="copied"
            class="w-3 h-3 text-green-500"
          />
          <Copy
            v-else
            class="w-3 h-3 text-muted-foreground"
          />
          <span
            v-if="copied"
            class="text-green-500"
          >Copied</span>
        </button>
      </div>
    </div>
    <div
      v-if="nodeOutput.error"
      class="p-2 rounded-md bg-red-500/10 text-red-400 text-xs font-mono break-all whitespace-pre-wrap"
    >
      {{ nodeOutput.error }}
    </div>
    <template v-else>
      <div
        v-if="nodeOutputImageSrcs.length > 0 && !isLastOutputExpanded"
        class="space-y-2"
      >
        <div class="flex flex-wrap gap-2">
          <img
            v-for="(src, idx) in nodeOutputImageSrcs"
            :key="idx"
            :src="src"
            :alt="`Screenshot ${idx + 1}`"
            class="w-24 h-24 sm:w-28 sm:h-28 rounded-md border object-cover cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
            @click="imageLightboxSrc = src"
          >
        </div>
        <div
          v-if="(nodeOutput.output as Record<string, unknown>)?.revised_prompt"
          class="p-2 rounded-md bg-muted text-xs"
        >
          <span class="text-muted-foreground">Revised prompt:</span>
          <p class="mt-1">
            {{ (nodeOutput.output as Record<string, unknown>).revised_prompt }}
          </p>
        </div>
      </div>
      <div
        v-else-if="!isLastOutputExpanded"
        class="p-2 rounded-md bg-muted text-xs font-mono overflow-auto max-h-48"
      >
        <pre>{{ JSON.stringify(displayNodeOutput, null, 2) }}</pre>
      </div>
    </template>
    <div class="text-xs text-muted-foreground">
      Execution time: {{ nodeOutput.execution_time_ms.toFixed(2) }}ms
    </div>

    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="isLastOutputExpanded && nodeOutput && !nodeOutput.error"
          class="fixed inset-0 z-50 flex items-center justify-center"
        >
          <div
            class="absolute inset-0 bg-black/50 backdrop-blur-sm"
            @click="isLastOutputExpanded = false"
          />
          <div
            ref="lastOutputExpandedPanelRef"
            class="relative w-[90vw] max-w-full h-[90vh] rounded-lg border border-border bg-card shadow-md flex flex-col overflow-x-hidden outline-none"
            tabindex="-1"
            role="dialog"
            aria-modal="true"
            @keydown.escape.stop.prevent="isLastOutputExpanded = false"
          >
            <div class="flex items-center justify-between gap-2 sm:gap-3 p-3 sm:p-4 border-b">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <CheckCircle2 class="w-4 h-4 text-primary shrink-0" />
                <Label class="text-sm font-medium truncate">
                  Last Output — {{ selectedNodeEvaluateDialogLabel }}
                </Label>
              </div>
              <div class="flex items-center justify-end gap-1 shrink-0 flex-wrap">
                <div
                  v-if="selectedNodeLoopItemNavigation"
                  class="flex items-center gap-0.5 rounded-md border border-border/50 bg-background/70 px-1 py-1"
                >
                  <span class="px-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                    Loop
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                    :disabled="!selectedNodeLoopItemNavigation.canNavigatePrev"
                    title="Previous loop item"
                    @click.stop="navigateToPreviousSelectedNodeLoopItem"
                  >
                    <ChevronLeft class="w-3.5 h-3.5" />
                  </Button>
                  <span class="min-w-[3.75rem] text-center text-xs text-muted-foreground">
                    {{ selectedNodeLoopItemNavigation.currentDisplayIndex }} /
                    {{ selectedNodeLoopItemNavigation.totalDisplayCount }}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                    :disabled="!selectedNodeLoopItemNavigation.canNavigateNext"
                    title="Next loop item"
                    @click.stop="navigateToNextSelectedNodeLoopItem"
                  >
                    <ChevronRight class="w-3.5 h-3.5" />
                  </Button>
                </div>
                <template
                  v-if="displayNodeOutput !== null && typeof displayNodeOutput === 'object'"
                >
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                    @click="expandAllLastOutputJson"
                  >
                    Expand all
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                    @click="collapseAllLastOutputJson"
                  >
                    Collapse all
                  </Button>
                </template>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-11 min-h-[44px] md:h-7 px-2 gap-1.5"
                  @click="copyOutput"
                >
                  <Copy class="w-3.5 h-3.5" />
                  <span class="text-xs">{{ copied ? 'Copied!' : 'Copy' }}</span>
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                  @click="isLastOutputExpanded = false"
                >
                  <X class="w-4 h-4" />
                </Button>
              </div>
            </div>
            <div class="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
              <div
                v-if="nodeOutputImageSrcs.length > 0"
                class="flex flex-wrap gap-2"
              >
                <img
                  v-for="(src, idx) in nodeOutputImageSrcs"
                  :key="`modal-${idx}`"
                  :src="src"
                  :alt="`Screenshot ${idx + 1}`"
                  class="w-24 h-24 sm:w-28 sm:h-28 rounded-md border object-cover cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
                  @click="imageLightboxSrc = src"
                >
              </div>
              <div
                v-if="displayNodeOutput !== null && typeof displayNodeOutput === 'object'"
                class="text-xs font-mono"
              >
                <JsonTree
                  :key="lastOutputJsonTreeKey"
                  :data="displayNodeOutput"
                  :root-expanded="true"
                  :auto-expand-depth="lastOutputJsonAutoDepth"
                />
              </div>
              <pre
                v-else
                class="text-xs font-mono whitespace-pre-wrap break-words text-foreground"
              >{{ formatOutput(displayNodeOutput) }}</pre>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
