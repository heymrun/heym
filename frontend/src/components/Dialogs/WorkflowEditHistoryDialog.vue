<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Edit,
  Eye,
  GitBranch,
  Loader2,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-vue-next";
import axios from "axios";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { cn } from "@/lib/utils";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";
import WorkflowVersionPreviewDialog from "@/components/Dialogs/WorkflowVersionPreviewDialog.vue";
import type {
  NodeChange,
  WorkflowVersion,
  WorkflowVersionDiff,
} from "@/types/workflow";

interface Props {
  open: boolean;
  workflowId: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "reverted"): void;
}>();

const workflowStore = useWorkflowStore();
const versions = ref<WorkflowVersion[]>([]);
const versionsWithChanges = ref<WorkflowVersion[]>([]);
const loading = ref(false);
const selectedVersionId = ref<string | null>(null);
const diff = ref<WorkflowVersionDiff | null>(null);
const loadingDiff = ref(false);
const expandedChanges = ref<Set<string>>(new Set());
const reverting = ref(false);
const clearing = ref(false);
const error = ref("");
const previewOpen = ref(false);
const previewVersion = ref<WorkflowVersion | null>(null);
const previewSelectedNode = ref<Record<string, unknown> | null>(null);

function openPreview(version: WorkflowVersion): void {
  previewVersion.value = version;
  previewSelectedNode.value = null;
  previewOpen.value = true;
}

function handleDialogEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape" || !props.open) return;
  event.stopImmediatePropagation();
  event.preventDefault();
  if (previewOpen.value && previewSelectedNode.value) {
    previewSelectedNode.value = null;
  } else if (previewOpen.value) {
    previewOpen.value = false;
    previewSelectedNode.value = null;
  } else {
    emit("close");
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      document.body.dataset.heymOverlayEscapeTrap = "true";
    } else {
      delete document.body.dataset.heymOverlayEscapeTrap;
      previewOpen.value = false;
      previewSelectedNode.value = null;
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  delete document.body.dataset.heymOverlayEscapeTrap;
});
const checkingChanges = ref(false);

const allVersions = computed(() => {
  const current = workflowStore.currentWorkflow;
  if (!current) return versionsWithChanges.value;

  const currentVersion: WorkflowVersion = {
    id: "current",
    workflow_id: current.id,
    version_number: (versionsWithChanges.value[0]?.version_number || 0) + 1,
    name: current.name,
    description: current.description,
    nodes: current.nodes,
    edges: current.edges,
    auth_type: current.auth_type,
    auth_header_key: current.auth_header_key,
    auth_header_value: current.auth_header_value,
    webhook_body_mode: current.webhook_body_mode,
    cache_ttl_seconds: current.cache_ttl_seconds,
    rate_limit_requests: current.rate_limit_requests,
    rate_limit_window_seconds: current.rate_limit_window_seconds,
    created_by_id: current.owner_id,
    created_at: current.updated_at,
  };

  return [currentVersion, ...versionsWithChanges.value];
});

function _areVersionsIdentical(v1: WorkflowVersion, v2: WorkflowVersion): boolean {
  return (
    JSON.stringify(v1.nodes) === JSON.stringify(v2.nodes) &&
    JSON.stringify(v1.edges) === JSON.stringify(v2.edges) &&
    v1.auth_type === v2.auth_type &&
    v1.auth_header_key === v2.auth_header_key &&
    v1.auth_header_value === v2.auth_header_value &&
    v1.webhook_body_mode === v2.webhook_body_mode &&
    v1.cache_ttl_seconds === v2.cache_ttl_seconds &&
    v1.rate_limit_requests === v2.rate_limit_requests &&
    v1.rate_limit_window_seconds === v2.rate_limit_window_seconds
  );
}

const selectedVersion = computed<WorkflowVersion | null>(() => {
  if (!selectedVersionId.value) return allVersions.value[0] || null;
  if (selectedVersionId.value === "current") return allVersions.value[0] || null;
  return allVersions.value.find((v) => v.id === selectedVersionId.value) || null;
});

const isCurrentVersion = computed(() => selectedVersionId.value === "current");

watch(
  () => props.open,
  async (open) => {
    if (open) {
      await loadVersions();
      selectedVersionId.value = "current";
      await loadDiff("current");
    } else {
      versions.value = [];
      versionsWithChanges.value = [];
      selectedVersionId.value = null;
      diff.value = null;
      error.value = "";
      expandedChanges.value = new Set();
    }
  }
);

watch(selectedVersionId, async (versionId) => {
  if (versionId) {
    await loadDiff(versionId);
  }
});

async function loadVersions(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    versions.value = await workflowApi.getVersions(props.workflowId);

    checkingChanges.value = true;
    const filteredVersions: WorkflowVersion[] = [];

    for (let i = 0; i < versions.value.length; i++) {
      const version = versions.value[i];

      if (i > 0) {
        const prevVersion = versions.value[i - 1];
        if (_areVersionsIdentical(version, prevVersion)) {
          continue;
        }
      }

      try {
        const versionDiff = await workflowApi.getVersionDiff(props.workflowId, version.id);
        const hasChanges =
          versionDiff.node_changes.length > 0 ||
          versionDiff.edge_changes.length > 0 ||
          versionDiff.config_changes.length > 0;

        if (!hasChanges) {
          continue;
        }

        filteredVersions.push(version);
      } catch {
        continue;
      }
    }

    versionsWithChanges.value = filteredVersions;
  } catch (err: unknown) {
    if (axios.isAxiosError(err)) {
      error.value = err.response?.data?.detail || "Failed to load versions";
    } else {
      error.value = "Failed to load versions";
    }
    versionsWithChanges.value = versions.value;
  } finally {
    loading.value = false;
    checkingChanges.value = false;
  }
}

async function loadDiff(versionId: string): Promise<void> {
  loadingDiff.value = true;
  try {
    if (versionId === "current") {
      diff.value = null;
    } else {
      diff.value = await workflowApi.getVersionDiff(props.workflowId, versionId);
    }
  } catch (err: unknown) {
    if (axios.isAxiosError(err)) {
      error.value = err.response?.data?.detail || "Failed to load diff";
    } else {
      error.value = "Failed to load diff";
    }
  } finally {
    loadingDiff.value = false;
  }
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString();
}

function selectVersion(versionId: string): void {
  selectedVersionId.value = versionId;
  expandedChanges.value = new Set();
}

function toggleChange(changeId: string): void {
  const newSet = new Set(expandedChanges.value);
  if (newSet.has(changeId)) {
    newSet.delete(changeId);
  } else {
    newSet.add(changeId);
  }
  expandedChanges.value = newSet;
  if (newSet.has(changeId)) {
    nextTick(() => {
      const el = document.querySelector(`[data-change-id="${changeId}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }
}

function isChangeExpanded(changeId: string): boolean {
  return expandedChanges.value.has(changeId);
}

function hasNodeChanges(nodeChange: NodeChange): boolean {
  return filterChanges(nodeChange.changes).length > 0;
}

function getChangeColor(changeType: string): string {
  switch (changeType) {
    case "added":
      return "text-emerald-500 bg-emerald-500/10 border-emerald-500/20";
    case "removed":
      return "text-red-500 bg-red-500/10 border-red-500/20";
    case "modified":
      return "text-blue-500 bg-blue-500/10 border-blue-500/20";
    default:
      return "text-muted-foreground bg-muted border-border";
  }
}

function getChangeIcon(changeType: string): typeof Plus {
  switch (changeType) {
    case "added":
      return Plus;
    case "removed":
      return Minus;
    case "modified":
      return Edit;
    default:
      return AlertCircle;
  }
}

function getChangedTextSnippet(oldValue: unknown, newValue: unknown, maxLength: number = 200): { old: string; new: string } {
  const oldStr = typeof oldValue === 'object' ? JSON.stringify(oldValue) : String(oldValue);
  const newStr = typeof newValue === 'object' ? JSON.stringify(newValue) : String(newValue);

  if (oldStr === newStr) {
    return {
      old: oldStr.length > maxLength ? oldStr.substring(0, maxLength) + '...' : oldStr,
      new: newStr.length > maxLength ? newStr.substring(0, maxLength) + '...' : newStr,
    };
  }

  let diffStart = 0;

  while (diffStart < oldStr.length && diffStart < newStr.length && oldStr[diffStart] === newStr[diffStart]) {
    diffStart++;
  }

  let oldEnd = oldStr.length;
  let newEnd = newStr.length;
  while (oldEnd > diffStart && newEnd > diffStart && oldStr[oldEnd - 1] === newStr[newEnd - 1]) {
    oldEnd--;
    newEnd--;
  }

  const contextBefore = 30;
  const contextAfter = 30;

  const start = Math.max(0, diffStart - contextBefore);
  const oldSnippet = oldStr.substring(start, Math.min(oldEnd + contextAfter, oldStr.length));
  const newSnippet = newStr.substring(start, Math.min(newEnd + contextAfter, newStr.length));

  const oldDisplay = start > 0 ? '...' + oldSnippet : oldSnippet;
  const newDisplay = start > 0 ? '...' + newSnippet : newSnippet;

  const oldFinal = oldDisplay.length > maxLength ? oldDisplay.substring(0, maxLength) + '...' : oldDisplay;
  const newFinal = newDisplay.length > maxLength ? newDisplay.substring(0, maxLength) + '...' : newDisplay;

  return { old: oldFinal, new: newFinal };
}

function normalizeDiffValue(field: string, value: unknown): unknown {
  if (field === "webhook_body_mode" && value === "legacy") {
    return "defined";
  }

  return value;
}

function filterChanges(changes: Array<{ field: string; old_value: unknown; new_value: unknown }>): Array<{ field: string; old_value: unknown; new_value: unknown }> {
  return changes.filter(change => change.field !== 'data.status');
}

async function revertToVersion(): Promise<void> {
  if (!selectedVersion.value || isCurrentVersion.value) return;
  if (!confirm(`Are you sure you want to revert to version ${selectedVersion.value.version_number}? This will replace the current workflow with this version.`)) {
    return;
  }

  reverting.value = true;
  error.value = "";
  try {
    await workflowApi.revertToVersion(props.workflowId, selectedVersion.value.id);
    await workflowStore.loadWorkflow(props.workflowId);
    await loadVersions();
    selectedVersionId.value = "current";
    await loadDiff("current");
    emit("reverted");
    window.location.reload();
  } catch (err: unknown) {
    if (axios.isAxiosError(err)) {
      error.value = err.response?.data?.detail || "Failed to revert workflow";
    } else {
      error.value = "Failed to revert workflow";
    }
  } finally {
    reverting.value = false;
  }
}

async function refreshVersionHistory(): Promise<void> {
  await loadVersions();
  selectedVersionId.value = "current";
  await loadDiff("current");
}

async function clearVersionHistory(): Promise<void> {
  if (!confirm("Are you sure you want to clear all version history? This action cannot be undone.")) {
    return;
  }

  clearing.value = true;
  error.value = "";
  try {
    await workflowApi.clearVersions(props.workflowId);
    await loadVersions();
    selectedVersionId.value = "current";
    await loadDiff("current");
  } catch (err: unknown) {
    if (axios.isAxiosError(err)) {
      error.value = err.response?.data?.detail || "Failed to clear version history";
    } else {
      error.value = "Failed to clear version history";
    }
  } finally {
    clearing.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    title="Edit History"
    size="4xl"
    :close-on-escape="false"
    @escape="handleDialogEscape"
    @close="emit('close')"
  >
    <template #header-actions>
      <Button
        variant="ghost"
        size="icon"
        :disabled="loading"
        @click="refreshVersionHistory"
      >
        <RefreshCw
          class="w-4 h-4"
          :class="{ 'animate-spin': loading }"
        />
      </Button>
      <Button
        v-if="versionsWithChanges.length > 0"
        variant="ghost"
        size="icon"
        class="text-destructive hover:text-destructive"
        :loading="clearing"
        :disabled="clearing"
        @click="clearVersionHistory"
      >
        <Trash2 class="w-4 h-4" />
      </Button>
    </template>
    <div class="space-y-6">
      <div
        v-if="error"
        class="flex items-center gap-2 p-3 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm"
      >
        <AlertCircle class="w-4 h-4 shrink-0" />
        <span>{{ error }}</span>
      </div>

      <div
        v-if="loading"
        class="flex items-center justify-center py-12"
      >
        <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
      </div>

      <div
        v-else-if="checkingChanges"
        class="flex items-center justify-center py-12"
      >
        <Loader2 class="w-5 h-5 animate-spin text-muted-foreground mr-2" />
        <span class="text-sm text-muted-foreground">Checking for changes...</span>
      </div>

      <div
        v-else-if="versions.length === 0"
        class="text-center py-12 text-muted-foreground"
      >
        <GitBranch class="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p class="text-sm">
          No edit history yet
        </p>
        <p class="text-xs mt-1">
          Versions will be created when you save changes to your workflow
        </p>
      </div>

      <div
        v-else
        class="grid grid-cols-1 lg:grid-cols-2 gap-6"
      >
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">
              Versions
            </h3>
            <span class="text-xs text-muted-foreground">{{ allVersions.length }} version(s)</span>
          </div>

          <div class="space-y-2 max-h-[600px] overflow-y-auto pr-2">
            <button
              v-for="version in allVersions"
              :key="version.id"
              class="w-full text-left p-4 rounded-lg border transition-all duration-200 hover:border-primary/40 hover:bg-primary/5"
              :class="cn(
                selectedVersion?.id === version.id && 'border-primary/60 bg-primary/10 shadow-sm',
                version.id === 'current' && 'border-emerald-500/30 bg-emerald-500/5'
              )"
              @click="selectVersion(version.id)"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1">
                    <GitBranch class="w-4 h-4 text-muted-foreground shrink-0" />
                    <span class="text-sm font-semibold">
                      {{ version.id === 'current' ? 'Current' : `Version ${version.version_number}` }}
                    </span>
                    <span
                      v-if="version.id === 'current'"
                      class="text-xs px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 font-medium"
                    >
                      Latest
                    </span>
                  </div>
                  <div class="flex items-center gap-2 text-xs text-muted-foreground mb-2">
                    <Clock class="w-3 h-3" />
                    <span>{{ formatTime(version.created_at) }}</span>
                  </div>
                  <p
                    v-if="version.name"
                    class="text-xs text-muted-foreground truncate"
                  >
                    {{ version.name }}
                  </p>
                </div>
                <div
                  v-if="selectedVersion?.id === version.id"
                  class="w-2 h-2 rounded-full bg-primary shrink-0 mt-1"
                />
              </div>
            </button>
          </div>
        </div>

        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">
              Changes
            </h3>
            <div
              v-if="selectedVersion && !isCurrentVersion"
              class="flex items-center gap-2"
            >
              <Button
                variant="outline"
                size="sm"
                class="gap-2"
                @click="openPreview(selectedVersion!)"
              >
                <Eye class="w-4 h-4" />
                Preview
              </Button>
              <Button
                variant="outline"
                size="sm"
                class="gap-2"
                :loading="reverting"
                :disabled="reverting"
                @click="revertToVersion"
              >
                <RotateCcw class="w-4 h-4" />
                Revert
              </Button>
            </div>
          </div>

          <div
            v-if="loadingDiff"
            class="flex items-center justify-center py-12"
          >
            <Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
          </div>

          <div
            v-else-if="!diff || isCurrentVersion"
            class="text-center py-12 text-muted-foreground text-sm"
          >
            <p v-if="isCurrentVersion">
              This is the current version
            </p>
            <p v-else>
              Select a version to view changes
            </p>
          </div>

          <div
            v-else
            class="space-y-3 max-h-[600px] overflow-y-auto pr-2"
          >
            <div
              v-if="diff.node_changes.length > 0"
              class="space-y-2"
            >
              <h4 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Nodes ({{ diff.node_changes.length }})
              </h4>
              <div
                v-for="nodeChange in diff.node_changes"
                :key="`node-${nodeChange.node_id}`"
                :data-change-id="`node-${nodeChange.node_id}`"
                class="border rounded-lg overflow-hidden"
              >
                <button
                  class="w-full flex items-center gap-3 p-3 text-left transition-colors"
                  :class="hasNodeChanges(nodeChange) ? 'hover:bg-muted/30 cursor-pointer' : 'cursor-default'"
                  :disabled="!hasNodeChanges(nodeChange)"
                  @click="hasNodeChanges(nodeChange) && toggleChange(`node-${nodeChange.node_id}`)"
                >
                  <component
                    :is="isChangeExpanded(`node-${nodeChange.node_id}`) ? ChevronDown : ChevronRight"
                    v-if="hasNodeChanges(nodeChange)"
                    class="w-4 h-4 text-muted-foreground shrink-0"
                  />
                  <div
                    v-else
                    class="w-4 h-4 shrink-0"
                  />
                  <component
                    :is="getChangeIcon(nodeChange.change_type)"
                    class="w-4 h-4 shrink-0"
                    :class="getChangeColor(nodeChange.change_type).split(' ')[0]"
                  />
                  <span class="text-sm font-medium flex-1">
                    {{ nodeChange.new_node?.data?.label || nodeChange.old_node?.data?.label || nodeChange.node_id }}
                  </span>
                  <span
                    class="text-xs px-2 py-0.5 rounded-full font-medium"
                    :class="getChangeColor(nodeChange.change_type)"
                  >
                    {{ nodeChange.change_type }}
                  </span>
                </button>

                <div
                  v-if="isChangeExpanded(`node-${nodeChange.node_id}`) && hasNodeChanges(nodeChange)"
                  class="border-t bg-muted/10 p-3 space-y-2"
                >
                  <div
                    v-if="filterChanges(nodeChange.changes).length > 0"
                    class="space-y-1"
                  >
                    <div class="text-xs font-medium text-muted-foreground mb-1">
                      Changed Fields:
                    </div>
                    <div
                      v-for="change in filterChanges(nodeChange.changes)"
                      :key="change.field"
                      class="text-xs bg-muted/30 p-2 rounded space-y-1"
                    >
                      <div class="font-bold text-foreground">
                        {{ change.field }}
                      </div>
                      <div class="flex items-start gap-2">
                        <div class="flex-1">
                          <div class="text-red-500/80 text-[10px] line-through font-bold break-words">
                            {{ getChangedTextSnippet(change.old_value, change.new_value, 200).old }}
                          </div>
                          <div class="text-emerald-500/80 text-[10px] font-bold break-words">
                            {{ getChangedTextSnippet(change.old_value, change.new_value, 200).new }}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div
              v-if="diff.edge_changes.length > 0"
              class="space-y-2"
            >
              <h4 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Edges ({{ diff.edge_changes.length }})
              </h4>
              <div
                v-for="(edgeChange, index) in diff.edge_changes"
                :key="`edge-${index}`"
                class="border rounded-lg p-3"
              >
                <div class="flex items-center gap-3">
                  <component
                    :is="getChangeIcon(edgeChange.change_type)"
                    class="w-4 h-4 shrink-0"
                    :class="getChangeColor(edgeChange.change_type).split(' ')[0]"
                  />
                  <div class="flex-1 text-sm">
                    <span class="font-medium">{{ edgeChange.change_type }}</span>
                    <span
                      v-if="edgeChange.old_edge || edgeChange.new_edge"
                      class="text-muted-foreground ml-2"
                    >
                      {{ edgeChange.old_edge?.source || edgeChange.new_edge?.source }} →
                      {{ edgeChange.old_edge?.target || edgeChange.new_edge?.target }}
                    </span>
                  </div>
                  <span
                    class="text-xs px-2 py-0.5 rounded-full font-medium"
                    :class="getChangeColor(edgeChange.change_type)"
                  >
                    {{ edgeChange.change_type }}
                  </span>
                </div>
              </div>
            </div>

            <div
              v-if="diff.config_changes.length > 0"
              class="space-y-2"
            >
              <h4 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Configuration ({{ diff.config_changes.length }})
              </h4>
              <div
                v-for="configChange in diff.config_changes"
                :key="configChange.field"
                class="border rounded-lg p-3"
              >
                <div class="flex items-center gap-3 mb-2">
                  <Edit class="w-4 h-4 text-blue-500 shrink-0" />
                  <span class="text-sm font-bold">{{ configChange.field }}</span>
                </div>
                <div class="text-xs space-y-1 ml-7">
                  <div class="text-red-500/80 line-through font-bold break-words">
                    {{ getChangedTextSnippet(normalizeDiffValue(configChange.field, configChange.old_value), normalizeDiffValue(configChange.field, configChange.new_value), 200).old }}
                  </div>
                  <div class="text-emerald-500/80 font-bold break-words">
                    {{ getChangedTextSnippet(normalizeDiffValue(configChange.field, configChange.old_value), normalizeDiffValue(configChange.field, configChange.new_value), 200).new }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Dialog>

  <WorkflowVersionPreviewDialog
    :open="previewOpen"
    :version="previewVersion"
    :selected-node="previewSelectedNode"
    @close="previewOpen = false; previewSelectedNode = null"
    @update:selected-node="previewSelectedNode = $event"
  />
</template>
