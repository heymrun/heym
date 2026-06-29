<script setup lang="ts">
import { CheckCircle2, Copy, Maximize2, Minimize2, Play, X } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import JsonTree from "@/components/ui/JsonTree.vue";
import Label from "@/components/ui/Label.vue";
import RunInputField from "@/components/Panels/RunInputField.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  activeTab,
  runInputValues,
  runInputJson,
  allInputFields,
  isGenericWebhookBodyMode,
  runBodyError,
  genericBodyPlaceholder,
  updateRunInputJson,
  updateInputValue,
  formatRunInputJson,
  copiedOutput,
  isOutputExpanded,
  runOutputJsonTreeKey,
  runOutputJsonAutoDepth,
  runOutputExpandedPanelRef,
  expandAllRunOutputJson,
  collapseAllRunOutputJson,
  isExecuting,
  isRunPanelFileDragActive,
  resetRunPanelFileDrag,
  onRunPanelFileDragEnter,
  onRunPanelFileDragLeave,
  onRunPanelFileDragOver,
  onRunPanelFileDrop,
  isRunbookPlaying,
  hasNodes,
  lastExecutedNode,
  handleExecute,
  formatOutput,
  copyLastNodeOutput,
} = usePropertiesPanelContext();
</script>

<template>
  <div
    v-if="activeTab === 'config'"
    class="flex-1 flex flex-col overflow-hidden overflow-x-hidden min-h-0"
    @dragenter="onRunPanelFileDragEnter"
    @dragleave="onRunPanelFileDragLeave"
    @dragover="onRunPanelFileDragOver"
    @drop="onRunPanelFileDrop"
  >
    <div class="flex-1 flex flex-col overflow-hidden min-h-0">
      <div
        :class="[
          'overflow-y-auto overflow-x-hidden p-3 sm:p-4 space-y-4 min-w-0',
          !lastExecutedNode || isExecuting ? 'flex-1' : 'flex-shrink-0'
        ]"
      >
        <template v-if="isGenericWebhookBodyMode">
          <div class="space-y-2 min-w-0">
            <div class="flex items-center justify-between gap-3">
              <Label>Raw JSON Body</Label>
              <Button
                variant="ghost"
                size="sm"
                :disabled="!!runBodyError"
                @click="formatRunInputJson"
              >
                Format JSON
              </Button>
            </div>
            <Textarea
              :model-value="runInputJson"
              :rows="8"
              :disabled="isExecuting"
              class="min-w-0 w-full font-mono text-sm"
              :placeholder="genericBodyPlaceholder"
              @update:model-value="updateRunInputJson"
            />
            <p class="text-xs text-muted-foreground">
              Generic mode sends the request body exactly as written here. Access nested values through $inputLabel.body.*
            </p>
            <p
              v-if="runBodyError"
              class="text-xs text-red-500"
            >
              {{ runBodyError }}
            </p>
          </div>
        </template>

        <template v-else-if="allInputFields.length > 0">
          <div
            v-for="field in allInputFields"
            :key="field.key"
            class="space-y-2 min-w-0"
          >
            <Label class="truncate">{{ field.key }}</Label>
            <RunInputField
              :field-key="field.key"
              :model-value="runInputValues[field.key] ?? ''"
              :placeholder="field.defaultValue || `Enter ${field.key}...`"
              :disabled="isExecuting"
              :panel-file-drag-active="isRunPanelFileDragActive"
              @update:model-value="updateInputValue(field.key, $event)"
              @file-dropped="resetRunPanelFileDrag"
            />
          </div>
        </template>

        <Button
          class="w-full min-w-0"
          :class="isRunbookPlaying && 'runbook-pulse'"
          :loading="isExecuting"
          :disabled="!hasNodes || !!runBodyError"
          @click="handleExecute"
        >
          <Play class="w-4 h-4 shrink-0" />
          <span class="hidden sm:inline truncate">{{ isExecuting ? 'Executing...' : 'Run Workflow' }}</span>
        </Button>

        <p
          v-if="hasNodes"
          class="hidden sm:block text-xs text-muted-foreground text-center break-words"
        >
          Press <kbd class="px-1.5 py-0.5 rounded bg-muted font-mono">Ctrl+Enter</kbd> to run
        </p>

        <p
          v-if="!hasNodes"
          class="text-xs text-muted-foreground text-center"
        >
          Add nodes to your workflow to run it
        </p>
      </div>

      <div
        v-if="lastExecutedNode && !isExecuting"
        :class="[
          'flex-1 flex flex-col overflow-hidden pt-4 px-4 pb-4 min-h-0',
          allInputFields.length > 0 || isGenericWebhookBodyMode ? 'border-t border-border/30' : ''
        ]"
      >
        <div class="space-y-2">
          <div class="flex items-center gap-2">
            <CheckCircle2 class="w-4 h-4 text-primary" />
            <Label class="text-sm font-medium">Last Executed Node</Label>
          </div>
          <div class="rounded-md bg-muted/50 p-2">
            <p class="text-sm font-medium text-foreground">
              {{ lastExecutedNode.node_label }}
            </p>
            <p class="text-xs text-muted-foreground mt-1">
              Status: <span
                :class="lastExecutedNode.status === 'success' ? 'text-green-500' : lastExecutedNode.status === 'error' ? 'text-red-500' : 'text-yellow-500'"
              >{{
                lastExecutedNode.status }}</span>
            </p>
          </div>
        </div>

        <div class="flex-1 flex flex-col space-y-2 min-h-0">
          <div class="flex items-center justify-between flex-shrink-0">
            <Label class="text-sm font-medium">Output</Label>
            <div class="flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                class="h-7 px-2 gap-1.5"
                @click="isOutputExpanded = !isOutputExpanded"
              >
                <Maximize2
                  v-if="!isOutputExpanded"
                  class="w-3.5 h-3.5"
                />
                <Minimize2
                  v-else
                  class="w-3.5 h-3.5"
                />
                <span class="text-xs">{{ isOutputExpanded ? 'Minimize' : 'Expand' }}</span>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 px-2 gap-1.5"
                @click="copyLastNodeOutput"
              >
                <Copy class="w-3.5 h-3.5" />
                <span class="text-xs">{{ copiedOutput ? 'Copied!' : 'Copy' }}</span>
              </Button>
            </div>
          </div>
          <div
            v-if="!isOutputExpanded"
            class="flex-1 rounded-md border border-border/30 bg-muted/30 p-3 overflow-y-auto min-h-0"
          >
            <pre class="text-xs font-mono whitespace-pre-wrap break-words text-foreground">{{
            formatOutput(lastExecutedNode.output) }}</pre>
          </div>
        </div>

        <Teleport to="body">
          <Transition name="fade">
            <div
              v-if="isOutputExpanded"
              class="fixed inset-0 z-50 flex items-center justify-center"
            >
              <div
                class="absolute inset-0 bg-black/50 backdrop-blur-sm"
                @click="isOutputExpanded = false"
              />
              <div
                ref="runOutputExpandedPanelRef"
                class="relative w-[90vw] max-w-full h-[90vh] rounded-lg border border-border bg-card shadow-md flex flex-col overflow-x-hidden outline-none"
                tabindex="-1"
                role="dialog"
                aria-modal="true"
                @keydown.escape.stop.prevent="isOutputExpanded = false"
              >
                <div class="flex items-center justify-between gap-2 sm:gap-3 p-3 sm:p-4 border-b">
                  <div class="flex items-center gap-2 min-w-0 flex-1">
                    <CheckCircle2 class="w-4 h-4 text-primary shrink-0" />
                    <Label class="text-sm font-medium truncate">
                      Output — {{ lastExecutedNode.node_label }}
                    </Label>
                  </div>
                  <div class="flex items-center justify-end gap-1 shrink-0 flex-wrap">
                    <template
                      v-if="lastExecutedNode.output && typeof lastExecutedNode.output === 'object'"
                    >
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                        @click="expandAllRunOutputJson"
                      >
                        Expand all
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                        @click="collapseAllRunOutputJson"
                      >
                        Collapse all
                      </Button>
                    </template>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-11 min-h-[44px] md:h-7 px-2 gap-1.5"
                      @click="copyLastNodeOutput"
                    >
                      <Copy class="w-3.5 h-3.5" />
                      <span class="text-xs">{{ copiedOutput ? 'Copied!' : 'Copy' }}</span>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                      @click="isOutputExpanded = false"
                    >
                      <X class="w-4 h-4" />
                    </Button>
                  </div>
                </div>
                <div class="flex-1 overflow-y-auto p-4 min-h-0">
                  <div
                    v-if="lastExecutedNode.output && typeof lastExecutedNode.output === 'object'"
                    class="text-xs font-mono"
                  >
                    <JsonTree
                      :key="runOutputJsonTreeKey"
                      :data="lastExecutedNode.output"
                      :root-expanded="true"
                      :auto-expand-depth="runOutputJsonAutoDepth"
                    />
                  </div>
                  <pre
                    v-else
                    class="text-xs font-mono whitespace-pre-wrap break-words text-foreground"
                  >{{
                  formatOutput(lastExecutedNode.output) }}</pre>
                </div>
              </div>
            </div>
          </Transition>
        </Teleport>
      </div>
    </div>
  </div>
</template>
