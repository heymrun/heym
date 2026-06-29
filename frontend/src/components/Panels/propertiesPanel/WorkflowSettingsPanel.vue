<script setup lang="ts">
import { AlertTriangle, ChevronDown, Clock, RotateCcw, Settings, Sparkles } from "lucide-vue-next";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  autoRecoverRuns,
  onToggleAutoRecover,
  otherWorkflows,
  errorWorkflowId,
  onChangeErrorWorkflow,
  minutesSavedPerRun,
  onChangeMinutesSaved,
  workflowTimeoutSeconds,
  onChangeWorkflowTimeout,
  showRunAnalyzer,
  openAnalyzer,
  selectedNode,
} = usePropertiesPanelContext();
</script>

<template>
  <div
    v-if="!selectedNode"
    class="flex-1 flex flex-col overflow-y-auto"
  >
    <div class="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
      <Settings class="w-10 h-10 mx-auto mb-3 opacity-50" />
      <p class="text-sm">
        Select a node to view its properties
      </p>
    </div>

    <div
      v-if="workflowStore.currentWorkflow"
      class="px-4 pb-6"
    >
      <div class="pb-4">
        <div class="flex items-center gap-2 mb-2">
          <AlertTriangle class="w-4 h-4 text-muted-foreground shrink-0" />
          <span class="text-sm font-medium">On error, run workflow</span>
        </div>
        <div class="relative">
          <select
            class="w-full appearance-none text-sm rounded-md border border-border bg-background pl-2 pr-9 py-1.5 disabled:opacity-50"
            :value="errorWorkflowId"
            :disabled="!isWorkflowOwner"
            @change="onChangeErrorWorkflow(($event.target as HTMLSelectElement).value)"
          >
            <option value="">
              None
            </option>
            <option
              v-for="w in otherWorkflows"
              :key="w.id"
              :value="w.id"
            >
              {{ w.name }}
            </option>
          </select>
          <ChevronDown
            class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground"
          />
        </div>
        <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
          Runs the selected workflow if this one fails — unless the canvas
          already has an Error Handler node. Not triggered on manual test
          runs.
        </p>
      </div>

      <div class="border-t border-border/40 pt-4 pb-4">
        <div class="flex items-center gap-2 mb-2">
          <Clock class="w-4 h-4 text-muted-foreground shrink-0" />
          <span class="text-sm font-medium">Time saved per run (min)</span>
        </div>
        <input
          type="number"
          min="0"
          step="1"
          class="w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="minutesSavedPerRun ?? ''"
          :disabled="!isWorkflowOwner"
          placeholder="e.g. 15"
          @change="onChangeMinutesSaved(($event.target as HTMLInputElement).value)"
        >
        <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
          Estimated minutes this automation saves per successful run.
          Surfaced as total Time Saved in Analytics.
        </p>
      </div>

      <div class="border-t border-border/40 pt-4 pb-4">
        <div class="flex items-center gap-2 mb-2">
          <Clock class="w-4 h-4 text-muted-foreground shrink-0" />
          <span class="text-sm font-medium">Workflow timeout (seconds)</span>
        </div>
        <input
          type="number"
          min="0"
          step="1"
          class="w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
          :value="workflowTimeoutSeconds ?? ''"
          :disabled="!isWorkflowOwner"
          placeholder="0 = no timeout"
          @change="onChangeWorkflowTimeout(($event.target as HTMLInputElement).value)"
        >
        <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
          Fail the run if it exceeds this many seconds. 0 disables the
          timeout. Applies to manual, API, and triggered runs.
        </p>
      </div>

      <div class="border-t border-border/40 pt-4">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 min-w-0">
            <RotateCcw class="w-4 h-4 text-muted-foreground shrink-0" />
            <span class="text-sm font-medium">Auto-recover runs</span>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="autoRecoverRuns"
            :disabled="!isWorkflowOwner"
            class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            :class="autoRecoverRuns ? 'bg-primary' : 'bg-muted-foreground/30'"
            @click="onToggleAutoRecover(!autoRecoverRuns)"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              :class="autoRecoverRuns ? 'translate-x-4' : 'translate-x-0.5'"
            />
          </button>
        </div>
        <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
          If the server restarts mid-run, re-runs it from scratch with the
          same inputs. Off = mark interrupted runs as
          <span class="font-medium">skipped</span>.
        </p>
      </div>

      <div
        v-if="showRunAnalyzer"
        class="border-t border-border/40 pt-4"
      >
        <button
          type="button"
          class="w-full inline-flex items-center justify-center gap-2 text-sm font-medium rounded-md px-3 py-2 bg-primary text-primary-foreground hover:opacity-90"
          @click="openAnalyzer"
        >
          <Sparkles class="w-4 h-4" />
          Run Analyzer
        </button>
        <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
          This workflow has no analysis yet. Open the analyzer to generate
          a report.
        </p>
      </div>
    </div>
  </div>
</template>
