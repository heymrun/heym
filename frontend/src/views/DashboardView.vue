<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import JSZip from "jszip";
import { useRoute, useRouter } from "vue-router";
import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  Download,
  Edit2,
  FileJson,
  FolderPlus,
  History,
  LayoutTemplate,
  Pin,
  Plus,
  RotateCcw,
  Settings,
  Trash2,
  Workflow,
  X,
} from "lucide-vue-next";

import AnalyticsDashboard from "@/components/Analytics/AnalyticsDashboard.vue";
import DashboardChatPanel from "@/components/Dashboard/DashboardChatPanel.vue";
import CredentialsPanel from "@/components/Credentials/CredentialsPanel.vue";
import TemplatesPage from "@/features/templates/components/TemplatesPage.vue";
import GlobalVariablesPanel from "@/components/GlobalVariables/GlobalVariablesPanel.vue";
import DockerLogsViewer from "@/components/LogsTab/DockerLogsViewer.vue";
import FolderTreeItem from "@/components/Folders/FolderTreeItem.vue";
import MCPPanel from "@/components/MCP/MCPPanel.vue";
import TracesPanel from "@/components/Traces/TracesPanel.vue";
import ScheduledView from "@/views/ScheduledView.vue";
import TeamsPanel from "@/components/Teams/TeamsPanel.vue";
import DataTablePanel from "@/components/DataTable/DataTablePanel.vue";
import DrivePanel from "@/components/Drive/DrivePanel.vue";
import VectorStoresPanel from "@/components/VectorStores/VectorStoresPanel.vue";
import AppHeader from "@/components/Layout/AppHeader.vue";
import DashboardNav from "@/components/Layout/DashboardNav.vue";
import WorkspaceShell from "@/components/Layout/WorkspaceShell.vue";
import ExecutionHistoryAllDialog from "@/components/Panels/ExecutionHistoryAllDialog.vue";
import WorkflowActionSheet from "@/components/Dialogs/WorkflowActionSheet.vue";
import WorkflowCommandPalette from "@/components/Dialogs/WorkflowCommandPalette.vue";
import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useLongPress } from "@/composables/useLongPress";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { getDocPath } from "@/docs/manifest";
import { resolveShowcaseContext } from "@/features/showcase/showcaseResolver";
import type { DashboardShowcaseTab } from "@/features/showcase/showcase.types";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import { joinOriginAndPath } from "@/lib/appUrl";
import { nodeIcons } from "@/lib/nodeIcons";
import { cn, formatDate } from "@/lib/utils";
import { credentialsApi, folderApi, templatesApi, workflowApi } from "@/services/api";
import type { NodeTemplate, WorkflowTemplate } from "@/features/templates/types/template.types";
import { useMediaQuery } from "@vueuse/core";
import { useAuthStore } from "@/stores/auth";
import { useFolderStore } from "@/stores/folder";
import { useQuickDrawerStore } from "@/stores/quickDrawer";
import type { CredentialListItem } from "@/types/credential";
import type { FolderTree, NodeData, WorkflowEdge, WorkflowListItem, WorkflowNode } from "@/types/workflow";

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const folderStore = useFolderStore();
const quickDrawerStore = useQuickDrawerStore();
const { pinnedWorkflowIds: quickDrawerPinnedWorkflowIds } = storeToRefs(quickDrawerStore);
let removeOverlayDismiss: (() => void) | null = null;
const { addRecent } = useRecentWorkflows();
const paletteAutoOpenId = ref<string | undefined>(undefined);
const paletteAutoOpenKind = ref<"workflow" | "node" | undefined>(undefined);

const tabParam = route.query.tab as string;

function parseTabParam(raw: string | undefined | null): { tab: string; subPath: string | null } {
  if (!raw) return { tab: "workflows", subPath: null };
  if (raw.startsWith("datatable/")) {
    return { tab: "datatable", subPath: raw.slice("datatable/".length) };
  }
  return { tab: raw, subPath: null };
}

const validTabs = new Set([
  "workflows", "schedules", "credentials", "globalvariables", "vectorstores", "mcp",
  "traces", "analytics", "templates", "teams", "logs", "chat", "drive", "datatable",
]);

const parsedInitial = parseTabParam(tabParam);
type TabKey = "workflows" | "schedules" | "credentials" | "globalvariables" | "vectorstores" | "mcp" | "traces" | "analytics" | "templates" | "teams" | "logs" | "chat" | "drive" | "datatable";
const initialTab: TabKey = validTabs.has(parsedInitial.tab) ? (parsedInitial.tab as TabKey) : "workflows";
const dataTableInitialId = ref<string | null>(parsedInitial.tab === "datatable" ? parsedInitial.subPath : null);
const activeTab = ref<TabKey>(initialTab);

watch(activeTab, (newTab) => {
  const query: Record<string, string> = newTab === "workflows" ? {} : { tab: newTab };
  if (newTab === "traces" && typeof route.query.traceId === "string") {
    query.traceId = route.query.traceId;
  }
  router.replace({ query });

  if (newTab === "workflows") {
    quickDrawerStore.syncPreferencesFromStorage();
  }
});

watch(
  () => route.query.tab,
  (newTabParam) => {
    const parsed = parseTabParam(newTabParam as string);
    const newTab = validTabs.has(parsed.tab) ? parsed.tab : "workflows";
    if (parsed.tab === "datatable") {
      dataTableInitialId.value = parsed.subPath ?? null;
    }
    if (activeTab.value !== newTab) {
      activeTab.value = newTab as typeof activeTab.value;
    }
  },
);

function onDataTableNavigate(id: string | null): void {
  dataTableInitialId.value = null;
  if (id) {
    router.push({ query: { tab: `datatable/${id}` } });
    return;
  }
  router.replace({ query: { tab: "datatable" } });
}

const workflows = ref<WorkflowListItem[]>([]);
const loading = ref(true);
const showCreateDialog = ref(false);
const newWorkflowName = ref("");
const newWorkflowDescription = ref("");
const creating = ref(false);
const showEditDialog = ref(false);
const editingWorkflow = ref<WorkflowListItem | null>(null);
const editWorkflowName = ref("");
const editWorkflowDescription = ref("");
const editing = ref(false);
const historyOpen = ref(false);
const historyWorkflowId = ref<string | undefined>(undefined);
const historyInitialStatus = ref<string | undefined>(undefined);
const copyingId = ref<string | null>(null);
const toastMessage = ref("");
const toastVisible = ref(false);
const toastType = ref<"error" | "success">("error");

const showFolderDialog = ref(false);
const newFolderName = ref("");
const creatingFolder = ref(false);
const parentFolderIdForNew = ref<string | null>(null);

const showRenameFolderDialog = ref(false);
const renamingFolder = ref<FolderTree | null>(null);
const renameFolderName = ref("");
const savingFolderRename = ref(false);

const draggedWorkflowId = ref<string | null>(null);
const dragOverFolderId = ref<string | null>(null);
const dragOverRoot = ref(false);

const contextMenuFolder = ref<FolderTree | null>(null);
const contextMenuPosition = ref({ x: 0, y: 0 });
const showContextMenu = ref(false);

const isDraggingJsonFile = ref(false);
const dragOverTrash = ref(false);

const showCommandPalette = ref(false);

const isMobile = useMediaQuery("(max-width: 767px)");
const showWorkflowActionSheet = ref(false);
const workflowActionWorkflow = ref<WorkflowListItem | null>(null);
const actionSheetConsumedId = ref<string | null>(null);
const showcaseContext = computed(() => {
  return resolveShowcaseContext({
    routePath: route.path,
    dashboardTab: activeTab.value as DashboardShowcaseTab,
  });
});

const longPressTargetWorkflow = ref<WorkflowListItem | null>(null);
const { handlers: longPressHandlers } = useLongPress(() => {
  const w = longPressTargetWorkflow.value;
  if (w) {
    actionSheetConsumedId.value = w.id;
    workflowActionWorkflow.value = w;
    showWorkflowActionSheet.value = true;
    pushOverlayState();
  }
});

const recentTemplates = ref<WorkflowTemplate[]>([]);

async function loadRecentTemplates(): Promise<void> {
  try {
    const all = await templatesApi.list();
    recentTemplates.value = all.workflow_templates.slice(0, 4);
  } catch {
    recentTemplates.value = [];
  }
}

function closeWorkflowActionSheet(): void {
  showWorkflowActionSheet.value = false;
  workflowActionWorkflow.value = null;
  actionSheetConsumedId.value = null;
  longPressTargetWorkflow.value = null;
}

function onWorkflowCardTouchStart(e: TouchEvent, workflow: WorkflowListItem): void {
  longPressTargetWorkflow.value = workflow;
  longPressHandlers.onTouchStart(e);
}

function onWorkflowCardTouchEnd(): void {
  longPressHandlers.onTouchEnd();
  longPressTargetWorkflow.value = null;
}

function onWorkflowCardTouchMove(): void {
  longPressHandlers.onTouchMove();
}

const rootWorkflows = computed(() => {
  const pinnedIds = new Set(quickDrawerPinnedWorkflowIds.value);
  return workflows.value.filter(
    (workflow) =>
      !workflow.folder_id &&
      !workflow.scheduled_for_deletion &&
      !pinnedIds.has(workflow.id),
  );
});

const pinnedDrawerWorkflows = computed(() => {
  if (quickDrawerPinnedWorkflowIds.value.length === 0) {
    return [];
  }

  const workflowMap = new Map(
    workflows.value
      .filter((workflow) => !workflow.scheduled_for_deletion)
      .map((workflow) => [workflow.id, workflow] as const),
  );

  return quickDrawerPinnedWorkflowIds.value
    .map((workflowId) => workflowMap.get(workflowId) ?? null)
    .filter((workflow): workflow is WorkflowListItem => workflow !== null);
});

const scheduledWorkflows = computed(() => {
  return workflows.value.filter((w) => w.scheduled_for_deletion);
});

function showToast(message: string, type: "error" | "success" = "error"): void {
  toastMessage.value = message;
  toastType.value = type;
  toastVisible.value = true;
  setTimeout(() => {
    toastVisible.value = false;
  }, 4000);
}

function closeContextMenu(): void {
  showContextMenu.value = false;
  contextMenuFolder.value = null;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!target) return false;
  const element = target as HTMLElement;
  return (
    element.tagName === "INPUT" ||
    element.tagName === "TEXTAREA" ||
    element.isContentEditable ||
    element.closest("input, textarea, [contenteditable]") !== null
  );
}

function handleKeyDown(event: KeyboardEvent): void {
  const isTyping = isTypingTarget(event.target);
  const isMeta = event.metaKey || event.ctrlKey;

  if (isMeta && event.key === "k" && !isTyping) {
    event.preventDefault();
    showCommandPalette.value = true;
    pushOverlayState();
  }
}

function onQuickDrawerPreferencesStorage(): void {
  quickDrawerStore.syncPreferencesFromStorage();
}

function openWorkflowFromPalette(workflowId: string, event?: MouseEvent): void {
  showCommandPalette.value = false;
  const workflow = workflows.value.find((w) => w.id === workflowId);
  if (workflow) {
    addRecent(workflowId, workflow.name);
  }
  openWorkflow(workflowId, event);
}

function handleTabSelectFromPalette(tabId: string, event?: MouseEvent): void {
  showCommandPalette.value = false;
  const openInNewTab = event && (event.ctrlKey || event.metaKey);
  if (tabId === "evals") {
    if (openInNewTab) {
      window.open(joinOriginAndPath(window.location.origin, "/evals"), "_blank", "noopener,noreferrer");
    } else {
      router.push("/evals");
    }
  } else {
    if (openInNewTab) {
      const path = tabId === "workflows" ? "/" : `/?tab=${tabId}`;
      window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
    } else {
      activeTab.value = tabId as typeof activeTab.value;
    }
  }
}

function onDocSelectFromPalette(categoryId: string, slug: string, event?: MouseEvent): void {
  showCommandPalette.value = false;
  const path = getDocPath(categoryId, slug);
  if (event && (event.ctrlKey || event.metaKey)) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else {
    router.push(path);
  }
}

function onTemplateSelectFromPalette(templateId: string): void {
  showCommandPalette.value = false;
  paletteAutoOpenId.value = templateId;
  paletteAutoOpenKind.value = "workflow";
  activeTab.value = "templates" as typeof activeTab.value;
}

function onNodeTemplateSelectFromPalette(template: NodeTemplate): void {
  showCommandPalette.value = false;
  paletteAutoOpenId.value = template.id;
  paletteAutoOpenKind.value = "node";
  activeTab.value = "templates" as typeof activeTab.value;
}

onMounted(async () => {
  await authStore.fetchUser();
  quickDrawerStore.hydratePreferences();
  await Promise.all([loadWorkflows(), folderStore.fetchFolderTree(), loadRecentTemplates()]);
  document.addEventListener("click", closeContextMenu);
  window.addEventListener("keydown", handleKeyDown);
  window.addEventListener("storage", onQuickDrawerPreferencesStorage);
  removeOverlayDismiss = onDismissOverlays(() => {
    showCreateDialog.value = false;
    showEditDialog.value = false;
    historyOpen.value = false;
    showFolderDialog.value = false;
    showRenameFolderDialog.value = false;
    showContextMenu.value = false;
    contextMenuFolder.value = null;
    showCommandPalette.value = false;
    showWorkflowActionSheet.value = false;
    workflowActionWorkflow.value = null;
    actionSheetConsumedId.value = null;
  });
});

onUnmounted(() => {
  document.removeEventListener("click", closeContextMenu);
  window.removeEventListener("keydown", handleKeyDown);
  window.removeEventListener("storage", onQuickDrawerPreferencesStorage);
  removeOverlayDismiss?.();
  removeOverlayDismiss = null;
});

async function loadWorkflows(): Promise<void> {
  loading.value = true;
  try {
    workflows.value = await workflowApi.list();
  } finally {
    loading.value = false;
  }
}

async function createWorkflow(): Promise<void> {
  if (!newWorkflowName.value.trim()) return;

  creating.value = true;
  try {
    const workflow = await workflowApi.create({
      name: newWorkflowName.value,
      description: newWorkflowDescription.value || undefined,
    });
    showCreateDialog.value = false;
    newWorkflowName.value = "";
    newWorkflowDescription.value = "";
    addRecent(workflow.id, workflow.name);
    router.push({ name: "editor", params: { id: workflow.id } });
  } finally {
    creating.value = false;
  }
}

async function deleteWorkflow(id: string, event: Event): Promise<void> {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this workflow?")) return;

  try {
    await workflowApi.delete(id);
    workflows.value = workflows.value.filter((w) => w.id !== id);
    await folderStore.fetchFolderTree();
    showToast("Workflow deleted successfully", "success");
  } catch (error) {
    if (error instanceof Error && error.message.includes("403")) {
      showToast("Only the owner can delete this workflow");
    } else if (error instanceof Error) {
      showToast(error.message);
    }
  }
}

function openWorkflow(id: string, event?: MouseEvent): void {
  if (actionSheetConsumedId.value === id) {
    actionSheetConsumedId.value = null;
    return;
  }
  const workflow = workflows.value.find((w) => w.id === id);
  if (workflow) {
    addRecent(id, workflow.name);
  }
  if (event && (event.ctrlKey || event.metaKey)) {
    const route = router.resolve({ name: "editor", params: { id } });
    window.open(route.href, "_blank");
  } else {
    router.push({ name: "editor", params: { id } });
  }
}

function openEditDialog(workflow: WorkflowListItem, event: Event): void {
  event.stopPropagation();
  editingWorkflow.value = workflow;
  editWorkflowName.value = workflow.name;
  editWorkflowDescription.value = workflow.description || "";
  showEditDialog.value = true;
  pushOverlayState();
}

async function updateWorkflow(): Promise<void> {
  if (!editingWorkflow.value) return;
  if (!editWorkflowName.value.trim()) return;

  editing.value = true;
  try {
    const updated = await workflowApi.update(editingWorkflow.value.id, {
      name: editWorkflowName.value.trim(),
      description: editWorkflowDescription.value.trim() || null,
    });
    const index = workflows.value.findIndex((w) => w.id === editingWorkflow.value?.id);
    if (index !== -1) {
      workflows.value[index] = { ...workflows.value[index], name: updated.name, description: updated.description };
    }
    if (editingWorkflow.value.folder_id) {
      await folderStore.fetchFolderTree();
    }
    showEditDialog.value = false;
    editingWorkflow.value = null;
  } finally {
    editing.value = false;
  }
}

async function copyWorkflow(id: string, event: Event): Promise<void> {
  event.stopPropagation();
  if (copyingId.value) return;

  copyingId.value = id;
  try {
    const sourceWorkflow = await workflowApi.get(id);
    const newWorkflow = await workflowApi.create({
      name: `${sourceWorkflow.name} (Copy)`,
      description: sourceWorkflow.description || undefined,
    });
    await workflowApi.update(newWorkflow.id, {
      nodes: sourceWorkflow.nodes,
      edges: sourceWorkflow.edges,
    });
    await loadWorkflows();
    await folderStore.fetchFolderTree();
    showToast("Workflow copied successfully", "success");
  } finally {
    copyingId.value = null;
  }
}

function openCreateFolderDialog(parentId: string | null = null): void {
  parentFolderIdForNew.value = parentId;
  newFolderName.value = "";
  showFolderDialog.value = true;
  pushOverlayState();
  closeContextMenu();
}

async function createFolder(): Promise<void> {
  if (!newFolderName.value.trim()) return;

  creatingFolder.value = true;
  try {
    await folderStore.createFolder(newFolderName.value.trim(), parentFolderIdForNew.value);
    showFolderDialog.value = false;
    newFolderName.value = "";
    parentFolderIdForNew.value = null;
    showToast("Folder created successfully", "success");
  } catch (error) {
    if (error instanceof Error) {
      showToast(error.message);
    }
  } finally {
    creatingFolder.value = false;
  }
}

function openRenameFolderDialog(folder: FolderTree): void {
  renamingFolder.value = folder;
  renameFolderName.value = folder.name;
  showRenameFolderDialog.value = true;
  pushOverlayState();
  closeContextMenu();
}

async function renameFolder(): Promise<void> {
  if (!renamingFolder.value) return;
  if (!renameFolderName.value.trim()) return;

  savingFolderRename.value = true;
  try {
    await folderStore.renameFolder(renamingFolder.value.id, renameFolderName.value.trim());
    showRenameFolderDialog.value = false;
    renamingFolder.value = null;
    showToast("Folder renamed successfully", "success");
  } catch (error) {
    if (error instanceof Error) {
      showToast(error.message);
    }
  } finally {
    savingFolderRename.value = false;
  }
}

async function deleteFolder(folder: FolderTree): Promise<void> {
  closeContextMenu();

  const workflowCount = countWorkflowsInFolder(folder);
  const message = workflowCount > 0
    ? `Are you sure you want to delete this folder? This will also delete ${workflowCount} workflow(s) inside.`
    : "Are you sure you want to delete this folder?";

  if (!confirm(message)) return;

  try {
    await folderStore.deleteFolder(folder.id);
    await loadWorkflows();
    showToast("Folder deleted successfully", "success");
  } catch (error) {
    if (error instanceof Error) {
      showToast(error.message);
    }
  }
}

function countWorkflowsInFolder(folder: FolderTree): number {
  let count = folder.workflows.length;
  for (const child of folder.children) {
    count += countWorkflowsInFolder(child);
  }
  return count;
}

function onDragStartWorkflow(event: DragEvent, workflowId: string): void {
  event.dataTransfer?.setData("workflowId", workflowId);
  draggedWorkflowId.value = workflowId;
}

function onDragEndWorkflow(): void {
  draggedWorkflowId.value = null;
  dragOverFolderId.value = null;
  dragOverRoot.value = false;
}

function onDragOverFolder(_event: DragEvent, folderId: string): void {
  dragOverFolderId.value = folderId;
}

function onDragLeaveFolder(): void {
  dragOverFolderId.value = null;
}

function onDragEnterDropZone(event: DragEvent): void {
  event.preventDefault();
}

function onDragOverRoot(event: DragEvent): void {
  event.preventDefault();
  dragOverRoot.value = true;
}

function onDragLeaveRoot(): void {
  dragOverRoot.value = false;
}

async function onDropToFolder(event: DragEvent, folderId: string): Promise<void> {
  event.preventDefault();
  const workflowId = event.dataTransfer?.getData("workflowId");

  if (workflowId) {
    try {
      await folderStore.moveWorkflowToFolder(folderId, workflowId);
      await loadWorkflows();
      folderStore.expandFolder(folderId);
      showToast("Workflow moved successfully", "success");
    } catch (error) {
      if (error instanceof Error) {
        showToast(error.message);
      }
    }
  }

  dragOverFolderId.value = null;
  draggedWorkflowId.value = null;
}

async function onDropToRoot(event: DragEvent): Promise<void> {
  event.preventDefault();
  const workflowId = event.dataTransfer?.getData("workflowId");

  if (workflowId) {
    const workflow = workflows.value.find((w) => w.id === workflowId);
    if (workflow?.scheduled_for_deletion) {
      try {
        const updated = await workflowApi.unscheduleForDeletion(workflowId);
        const index = workflows.value.findIndex((w) => w.id === workflowId);
        if (index !== -1) {
          workflows.value[index] = updated;
        }
        showToast("Workflow restored", "success");
      } catch (error) {
        if (error instanceof Error) {
          showToast(error.message);
        }
      }
    } else if (workflow?.folder_id) {
      try {
        await folderStore.removeWorkflowFromFolder(workflowId);
        await loadWorkflows();
        showToast("Workflow moved to root", "success");
      } catch (error) {
        if (error instanceof Error) {
          showToast(error.message);
        }
      }
    }
  }

  dragOverRoot.value = false;
  draggedWorkflowId.value = null;
}

function openContextMenu(event: MouseEvent, folder: FolderTree): void {
  event.preventDefault();
  event.stopPropagation();
  contextMenuFolder.value = folder;

  const menuWidth = 160;
  const menuHeight = 150;
  const padding = 8;

  let x = event.clientX;
  let y = event.clientY;

  if (x + menuWidth > window.innerWidth) {
    x = window.innerWidth - menuWidth - padding;
  }
  if (x < padding) {
    x = padding;
  }

  if (y + menuHeight > window.innerHeight) {
    y = window.innerHeight - menuHeight - padding;
  }
  if (y < padding) {
    y = padding;
  }

  contextMenuPosition.value = { x, y };
  showContextMenu.value = true;
  pushOverlayState();
}

function toggleFolder(folderId: string): void {
  folderStore.toggleFolder(folderId);
}

async function downloadFolderAsZip(folder: FolderTree): Promise<void> {
  try {
    const blob = await folderApi.exportZip(folder.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${folder.name}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch {
    showToast("Failed to download folder");
  }
}

function handleJsonDragOver(event: DragEvent): void {
  event.preventDefault();
  if (event.dataTransfer) {
    const items = event.dataTransfer.items;
    if (items && items.length > 0 && items[0].kind === "file") {
      isDraggingJsonFile.value = true;
      event.dataTransfer.dropEffect = "copy";
    }
  }
}

function handleJsonDragLeave(event: DragEvent): void {
  const relatedTarget = event.relatedTarget as HTMLElement;
  if (!relatedTarget || !event.currentTarget || !(event.currentTarget as HTMLElement).contains(relatedTarget)) {
    isDraggingJsonFile.value = false;
  }
}

const IMPORT_CREDENTIAL_FIELDS = [
  "credentialId",
  "fallbackCredentialId",
  "guardrailCredentialId",
  "rerankerCredentialId",
] as const;

interface WorkflowImportSanitizeContext {
  availableWorkflowIds: Set<string>;
  ownedCredentialIds: Set<string>;
}

function sanitizeImportedNode(
  node: WorkflowNode,
  context: WorkflowImportSanitizeContext,
): WorkflowNode {
  const nextData = { ...node.data } as NodeData & Record<string, unknown>;

  for (const field of IMPORT_CREDENTIAL_FIELDS) {
    const credentialId = typeof nextData[field] === "string" ? nextData[field].trim() : "";
    if (credentialId !== "" && !context.ownedCredentialIds.has(credentialId)) {
      nextData[field] = "";
      if (field === "credentialId" && typeof nextData.model === "string") {
        nextData.model = "";
      }
      if (field === "fallbackCredentialId" && typeof nextData.fallbackModel === "string") {
        nextData.fallbackModel = "";
      }
      if (field === "guardrailCredentialId" && typeof nextData.guardrailModel === "string") {
        nextData.guardrailModel = "";
      }
    }
  }

  if (Array.isArray(nextData.playwrightSteps)) {
    nextData.playwrightSteps = nextData.playwrightSteps.map((step) => {
      if (
        step &&
        typeof step === "object" &&
        "action" in step &&
        step.action === "aiStep" &&
        typeof step.credentialId === "string" &&
        step.credentialId.trim() !== "" &&
        !context.ownedCredentialIds.has(step.credentialId)
      ) {
        return {
          ...step,
          credentialId: "",
          model: "",
        };
      }
      return step;
    });
  }

  if (node.type === "execute") {
    const executeWorkflowId =
      typeof nextData.executeWorkflowId === "string" ? nextData.executeWorkflowId.trim() : "";
    if (executeWorkflowId !== "" && !context.availableWorkflowIds.has(executeWorkflowId)) {
      nextData.executeWorkflowId = "";
      nextData.targetWorkflowName = "";
      nextData.targetWorkflowInputFields = [];
    }
  }

  if (node.type === "agent") {
    const subWorkflowIds = Array.isArray(nextData.subWorkflowIds)
      ? nextData.subWorkflowIds.filter(
        (id): id is string =>
          typeof id === "string" && context.availableWorkflowIds.has(id),
      )
      : [];
    const subWorkflowNamesRaw =
      nextData.subWorkflowNames && typeof nextData.subWorkflowNames === "object"
        ? nextData.subWorkflowNames as Record<string, unknown>
        : {};
    const subWorkflowNames = Object.fromEntries(
      subWorkflowIds.map((id) => {
        const value = subWorkflowNamesRaw[id];
        return [id, typeof value === "string" ? value : ""];
      }),
    );
    nextData.subWorkflowIds = subWorkflowIds;
    nextData.subWorkflowNames = subWorkflowNames;
  }

  return {
    ...node,
    data: nextData as NodeData,
  };
}

async function importZipFile(file: File): Promise<void> {
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(file);
  } catch {
    showToast("Invalid ZIP file");
    return;
  }

  const jsonFiles: { path: string; content: string }[] = [];
  const promises: Promise<void>[] = [];

  zip.forEach((relativePath, entry) => {
    if (!entry.dir && relativePath.endsWith(".json")) {
      promises.push(
        entry.async("string").then((content) => {
          jsonFiles.push({ path: relativePath, content });
        }),
      );
    }
  });

  await Promise.all(promises);

  if (jsonFiles.length === 0) {
    showToast("No workflows found in ZIP");
    return;
  }

  const folderIdMap = new Map<string, string>();

  const allFolderPaths = new Set<string>();
  for (const { path } of jsonFiles) {
    const parts = path.split("/");
    for (let i = 1; i < parts.length; i++) {
      allFolderPaths.add(parts.slice(0, i).join("/"));
    }
  }

  const sortedPaths = Array.from(allFolderPaths).sort(
    (a, b) => a.split("/").length - b.split("/").length,
  );

  for (const folderPath of sortedPaths) {
    const parts = folderPath.split("/");
    const name = parts[parts.length - 1];
    const parentPath = parts.slice(0, -1).join("/");
    const parentId = parentPath ? (folderIdMap.get(parentPath) ?? null) : null;

    try {
      const folder = await folderApi.create({ name, parent_id: parentId });
      folderIdMap.set(folderPath, folder.id);
    } catch {
      showToast(`Failed to create folder: ${name}`);
      return;
    }
  }

  let importedCount = 0;
  let credentials: CredentialListItem[] = [];
  try {
    credentials = await credentialsApi.list();
  } catch {
    credentials = [];
  }

  const sanitizeContext: WorkflowImportSanitizeContext = {
    availableWorkflowIds: new Set(workflows.value.map((w) => w.id)),
    ownedCredentialIds: new Set(
      credentials
        .filter((c) => c.is_shared !== true)
        .map((c) => c.id),
    ),
  };

  for (const { path, content } of jsonFiles) {
    try {
      const parsed = JSON.parse(content) as { nodes?: WorkflowNode[]; edges?: WorkflowEdge[]; name?: string };
      if (!parsed.nodes || !Array.isArray(parsed.nodes)) continue;

      const parts = path.split("/");
      const fileName = parts[parts.length - 1].replace(/\.json$/i, "");
      const folderPath = parts.slice(0, -1).join("/");
      const folderId = folderIdMap.get(folderPath) ?? null;

      const workflowName = parsed.name || fileName || "Imported Workflow";
      const sanitizedNodes = parsed.nodes.map((node) => sanitizeImportedNode(node, sanitizeContext));

      const workflow = await workflowApi.create({
        name: workflowName,
        description: `Imported from ${file.name}`,
      });
      await workflowApi.update(workflow.id, {
        nodes: sanitizedNodes,
        edges: parsed.edges || [],
      });

      if (folderId) {
        await folderApi.moveWorkflowToFolder(folderId, workflow.id);
      }

      importedCount++;
    } catch {
      // Continue with remaining workflows
    }
  }

  const total = jsonFiles.length;
  if (importedCount === total) {
    showToast(
      importedCount === 1
        ? "Folder imported successfully (1 workflow)"
        : `Folder imported successfully (${importedCount} workflows)`,
      "success",
    );
  } else {
    showToast(`${importedCount}/${total} workflows imported`);
  }

  await folderStore.fetchFolderTree();
  await loadWorkflows();
}

async function handleJsonDrop(event: DragEvent): Promise<void> {
  event.preventDefault();
  isDraggingJsonFile.value = false;

  const files = event.dataTransfer?.files;
  if (!files || files.length === 0) return;

  const file = files[0];

  if (file.type === "application/zip" || file.type === "application/x-zip-compressed" || file.name.endsWith(".zip")) {
    await importZipFile(file);
    return;
  }

  const isJson = file.type === "application/json" || file.name.endsWith(".json");
  if (!isJson) {
    showToast("Please drop a JSON or ZIP file");
    return;
  }

  const fileName = file.name.replace(/\.json$/i, "");

  try {
    const content = await file.text();
    const parsed = JSON.parse(content) as { nodes?: WorkflowNode[]; edges?: WorkflowEdge[]; name?: string };

    if (!parsed.nodes || !Array.isArray(parsed.nodes)) {
      showToast("Invalid workflow file");
      return;
    }

    let credentials: CredentialListItem[] = [];
    try {
      credentials = await credentialsApi.list();
    } catch {
      credentials = [];
    }

    const sanitizeContext: WorkflowImportSanitizeContext = {
      availableWorkflowIds: new Set(workflows.value.map((workflow) => workflow.id)),
      ownedCredentialIds: new Set(
        credentials
          .filter((credential) => credential.is_shared !== true)
          .map((credential) => credential.id),
      ),
    };
    const sanitizedNodes = parsed.nodes.map((node) => sanitizeImportedNode(node, sanitizeContext));

    const workflowName = parsed.name || fileName || "Imported Workflow";
    const workflow = await workflowApi.create({
      name: workflowName,
      description: `Imported from ${file.name}`,
    });

    await workflowApi.update(workflow.id, {
      nodes: sanitizedNodes,
      edges: parsed.edges || [],
    });

    showToast(`Workflow "${workflowName}" imported successfully`, "success");
    router.push({ name: "editor", params: { id: workflow.id } });
  } catch {
    showToast("Failed to import workflow file");
  }
}

function onDragOverTrash(event: DragEvent): void {
  event.preventDefault();
  dragOverTrash.value = true;
}

function onDragLeaveTrash(): void {
  dragOverTrash.value = false;
}

async function onDropToTrash(event: DragEvent): Promise<void> {
  event.preventDefault();
  const workflowId = event.dataTransfer?.getData("workflowId");

  if (workflowId) {
    const workflow = workflows.value.find((w) => w.id === workflowId);
    if (workflow && !workflow.scheduled_for_deletion) {
      try {
        const updated = await workflowApi.scheduleForDeletion(workflowId);
        const index = workflows.value.findIndex((w) => w.id === workflowId);
        if (index !== -1) {
          workflows.value[index] = updated;
        }
        await folderStore.fetchFolderTree();
        showToast("Workflow scheduled for deletion", "success");
      } catch (error) {
        if (error instanceof Error) {
          showToast(error.message);
        }
      }
    }
  }

  dragOverTrash.value = false;
  draggedWorkflowId.value = null;
}

async function onActionSheetMoveToFolder(folderId: string): Promise<void> {
  if (!workflowActionWorkflow.value) return;
  try {
    await folderStore.moveWorkflowToFolder(folderId, workflowActionWorkflow.value.id);
    await loadWorkflows();
    showToast("Workflow moved", "success");
  } catch (e) {
    if (e instanceof Error) showToast(e.message);
  }
}

async function onActionSheetMoveToRoot(): Promise<void> {
  if (!workflowActionWorkflow.value) return;
  try {
    await folderStore.removeWorkflowFromFolder(workflowActionWorkflow.value.id);
    await loadWorkflows();
    showToast("Moved to root", "success");
  } catch (e) {
    if (e instanceof Error) showToast(e.message);
  }
}

async function onActionSheetScheduleDeletion(): Promise<void> {
  if (!workflowActionWorkflow.value) return;
  try {
    await workflowApi.scheduleForDeletion(workflowActionWorkflow.value.id);
    await loadWorkflows();
    await folderStore.fetchFolderTree();
    showToast("Scheduled for deletion", "success");
  } catch (e) {
    if (e instanceof Error) showToast(e.message);
  }
}

async function onActionSheetRestore(): Promise<void> {
  if (!workflowActionWorkflow.value) return;
  try {
    await workflowApi.unscheduleForDeletion(workflowActionWorkflow.value.id);
    await loadWorkflows();
    showToast("Restored", "success");
  } catch (e) {
    if (e instanceof Error) showToast(e.message);
  }
}

function onActionSheetCopy(e: Event): void {
  if (workflowActionWorkflow.value) copyWorkflow(workflowActionWorkflow.value.id, e);
}

function onActionSheetEdit(e: Event): void {
  if (workflowActionWorkflow.value) openEditDialog(workflowActionWorkflow.value, e);
}

function onActionSheetDelete(e: Event): void {
  if (workflowActionWorkflow.value) deleteWorkflow(workflowActionWorkflow.value.id, e);
}

async function restoreFromTrash(workflowId: string, event: Event): Promise<void> {
  event.stopPropagation();
  try {
    const updated = await workflowApi.unscheduleForDeletion(workflowId);
    const index = workflows.value.findIndex((w) => w.id === workflowId);
    if (index !== -1) {
      workflows.value[index] = updated;
    }
    showToast("Workflow restored", "success");
  } catch (error) {
    if (error instanceof Error) {
      showToast(error.message);
    }
  }
}

</script>

<template>
  <WorkspaceShell
    :enabled="true"
    :showcase-context="showcaseContext"
  >
    <div
      :class="cn(
        'min-h-screen bg-background overflow-x-hidden',
        activeTab === 'chat' && 'h-screen flex flex-col overflow-hidden'
      )"
    >
      <AppHeader :on-open-command-palette="() => { showCommandPalette = true; pushOverlayState(); }">
        <template #actions>
          <Button
            variant="ghost"
            size="sm"
            class="gap-2 min-h-[44px] min-w-[44px] sm:min-w-auto text-foreground"
            @click="historyOpen = true; pushOverlayState()"
          >
            <History class="w-4 h-4" />
            <span class="hidden sm:inline">History</span>
          </Button>
        </template>
      </AppHeader>

      <main
        :class="cn(
          'dashboard-main px-3 sm:px-4 py-4 sm:py-6 md:py-8',
          activeTab === 'chat' && 'flex-1 flex flex-col min-h-0 overflow-hidden py-3 sm:py-4'
        )"
      >
        <div class="absolute top-0 left-0 right-0 h-[500px] pointer-events-none overflow-hidden">
          <div class="absolute inset-0 bg-gradient-to-b from-primary/[0.03] via-transparent to-transparent" />
          <div class="absolute inset-0 bg-dots-pattern opacity-30" />
        </div>
        <div
          :class="cn(
            'w-full max-w-7xl mx-auto relative',
            activeTab === 'chat' && 'flex-1 flex flex-col min-h-0 overflow-hidden'
          )"
        >
          <DashboardNav />

          <div
            v-if="activeTab === 'chat'"
            class="flex-1 min-h-0 overflow-hidden flex flex-col w-full"
          >
            <DashboardChatPanel />
          </div>

          <div
            v-if="activeTab === 'workflows'"
            class="relative"
            @dragover="handleJsonDragOver"
            @dragleave="handleJsonDragLeave"
            @drop="handleJsonDrop"
          >
            <Transition
              enter-active-class="transition-opacity duration-200"
              leave-active-class="transition-opacity duration-200"
              enter-from-class="opacity-0"
              leave-to-class="opacity-0"
            >
              <div
                v-if="isDraggingJsonFile"
                class="absolute inset-0 z-50 flex items-center justify-center bg-background/90 backdrop-blur-sm border-2 border-dashed border-primary rounded-2xl pointer-events-none"
              >
                <div class="flex flex-col items-center gap-3 text-primary">
                  <div class="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center">
                    <FileJson class="w-10 h-10" />
                  </div>
                  <span class="text-lg font-medium">Drop JSON or ZIP to import</span>
                </div>
              </div>
            </Transition>

            <div class="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-5">
              <div>
                <div class="flex items-center gap-3">
                  <h2 class="text-xl md:text-2xl font-bold tracking-tight">
                    Workflows
                  </h2>
                  <span
                    v-if="!loading && workflows.length > 0"
                    class="inline-flex items-center px-2 py-px rounded-full text-xs font-medium bg-primary/10 text-primary ring-1 ring-inset ring-primary/20 mt-0.5"
                  >
                    {{ workflows.length }}
                  </span>
                </div>
                <p class="text-muted-foreground mt-0.5 text-sm">
                  Create and manage your AI workflows
                  <span class="sm:hidden"> · Long press for move/delete</span>
                </p>
              </div>
              <div class="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  class="sm:hidden min-h-[36px] min-w-[36px]"
                  @click="openCreateFolderDialog(null)"
                >
                  <FolderPlus class="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  class="hidden sm:inline-flex"
                  @click="openCreateFolderDialog(null)"
                >
                  <FolderPlus class="w-3.5 h-3.5" />
                  New Folder
                </Button>
                <Button
                  variant="gradient"
                  size="sm"
                  @click="showCreateDialog = true; pushOverlayState()"
                >
                  <Plus class="w-3.5 h-3.5" />
                  <span class="hidden sm:inline">New Workflow</span>
                  <span class="sm:hidden">New</span>
                </Button>
              </div>
            </div>

            <div
              v-if="loading"
              class="relative z-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
            >
              <Card
                v-for="i in 3"
                :key="i"
                class="p-3.5"
              >
                <div class="flex items-start gap-3 mb-2.5">
                  <div class="w-9 h-9 rounded-lg bg-muted animate-pulse shrink-0" />
                  <div class="flex-1">
                    <div class="h-5 bg-muted rounded-lg w-3/4 mb-2.5 animate-pulse" />
                    <div class="h-3.5 bg-muted rounded-md w-1/3 animate-pulse" />
                  </div>
                </div>
                <div class="ml-[48px] pt-2 border-t border-border/30">
                  <div class="h-3.5 bg-muted rounded-md w-full mb-2 animate-pulse" />
                  <div class="h-3.5 bg-muted rounded-md w-2/3 animate-pulse" />
                </div>
              </Card>
            </div>

            <div
              v-else-if="workflows.length === 0 && folderStore.folderTree.length === 0"
              class="relative z-10 flex flex-col items-center justify-center text-center py-24 px-4 gap-4"
            >
              <Workflow class="w-12 h-12 text-primary opacity-50" />
              <p class="text-sm text-muted-foreground max-w-md">
                Create a workflow or start from a template
              </p>

              <!-- Template chips -->
              <div
                v-if="recentTemplates.length > 0"
                class="flex flex-col items-center gap-3 mt-2 w-full max-w-xl"
              >
                <div class="flex items-center gap-2 text-xs text-muted-foreground/70">
                  <LayoutTemplate class="w-3.5 h-3.5" />
                  <span>Quick start templates</span>
                </div>
                <div class="flex flex-wrap justify-center gap-2">
                  <button
                    v-for="t in recentTemplates"
                    :key="t.id"
                    class="px-3 py-1.5 text-xs rounded-full border border-border/50 bg-muted/20 hover:bg-muted/50 hover:border-primary/30 text-muted-foreground hover:text-foreground transition-all"
                    type="button"
                    @click="activeTab = 'templates'"
                  >
                    {{ t.name }}
                  </button>
                  <button
                    class="px-3 py-1.5 text-xs rounded-full border border-border/50 bg-muted/20 hover:bg-muted/50 hover:border-primary/30 text-muted-foreground hover:text-primary transition-all"
                    type="button"
                    @click="activeTab = 'templates'"
                  >
                    Browse all →
                  </button>
                </div>
              </div>

              <!-- Action buttons -->
              <div class="flex flex-col sm:flex-row items-center justify-center gap-2 mt-4">
                <Button
                  variant="gradient"
                  size="sm"
                  class="px-6"
                  @click="showCreateDialog = true; pushOverlayState()"
                >
                  <Plus class="w-4 h-4" />
                  Create Workflow
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  class="px-4"
                  @click="openCreateFolderDialog(null)"
                >
                  <FolderPlus class="w-4 h-4" />
                  New Folder
                </Button>
              </div>
            </div>

            <div
              v-else
              class="relative z-10 space-y-1.5"
            >
              <div
                v-if="pinnedDrawerWorkflows.length > 0"
                class="mb-6 space-y-4"
              >
                <div class="flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  <Pin class="h-3.5 w-3.5 text-primary" />
                  Pinned
                </div>

                <div class="px-3">
                  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    <Card
                      v-for="(workflow, index) in pinnedDrawerWorkflows"
                      :key="workflow.id"
                      variant="interactive"
                      :class="cn(
                        'workflow-card cursor-pointer group relative p-3.5',
                        draggedWorkflowId === workflow.id && 'opacity-50 scale-[0.98]'
                      )"
                      :style="{ animationDelay: `${index * 60}ms` }"
                      :hover="false"
                      draggable="true"
                      @click="openWorkflow(workflow.id, $event)"
                      @touchstart.passive="isMobile && onWorkflowCardTouchStart($event, workflow)"
                      @touchend="isMobile && onWorkflowCardTouchEnd()"
                      @touchmove="isMobile && onWorkflowCardTouchMove()"
                      @dragstart="onDragStartWorkflow($event, workflow.id)"
                      @dragend="onDragEndWorkflow"
                    >
                      <div class="flex items-start justify-between mb-2 gap-1.5">
                        <div class="flex items-start gap-3 min-w-0 flex-1">
                          <div
                            class="workflow-icon relative flex items-center justify-center w-9 h-9 rounded-lg text-primary shrink-0"
                          >
                            <div
                              class="absolute inset-0 rounded-lg bg-gradient-to-br from-primary/15 via-primary/10 to-primary/5"
                            />
                            <div class="absolute inset-0 rounded-lg ring-1 ring-inset ring-primary/20" />
                            <component
                              :is="workflow.first_node_type && nodeIcons[workflow.first_node_type] ? nodeIcons[workflow.first_node_type] : Workflow"
                              class="relative z-10 h-4 w-4"
                            />
                          </div>
                          <div class="min-w-0">
                            <h3
                              class="workflow-card-title font-semibold text-sm line-clamp-2 leading-snug transition-colors duration-200"
                            >
                              {{ workflow.name }}
                            </h3>
                            <div class="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                              <Clock class="w-3 h-3" />
                              <span>{{ formatDate(workflow.updated_at) }}</span>
                            </div>
                          </div>
                        </div>
                        <div class="flex items-center gap-0.5 shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
                            title="Copy workflow"
                            :disabled="copyingId === workflow.id"
                            @click="copyWorkflow(workflow.id, $event)"
                          >
                            <Copy
                              class="w-3.5 h-3.5"
                              :class="{ 'animate-spin-slow': copyingId === workflow.id }"
                            />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
                            title="Edit workflow"
                            @click="openEditDialog(workflow, $event)"
                          >
                            <Settings class="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg"
                            title="Delete workflow"
                            @click="deleteWorkflow(workflow.id, $event)"
                          >
                            <Trash2 class="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>
                      <div
                        v-if="workflow.description"
                        class="mt-0.5 pt-2 border-t border-border/40 ml-[48px]"
                      >
                        <p class="text-muted-foreground text-xs line-clamp-2 leading-relaxed">
                          {{ workflow.description }}
                        </p>
                      </div>
                    </Card>
                  </div>
                </div>
              </div>

              <div
                v-for="folder in folderStore.folderTree"
                :key="folder.id"
                class="folder-item"
              >
                <FolderTreeItem
                  :folder="folder"
                  :is-expanded="folderStore.isFolderExpanded(folder.id)"
                  :drag-over-folder-id="dragOverFolderId"
                  :dragged-workflow-id="draggedWorkflowId"
                  :copying-id="copyingId"
                  :is-mobile="isMobile"
                  :on-workflow-touch-start="onWorkflowCardTouchStart"
                  :on-workflow-touch-end="onWorkflowCardTouchEnd"
                  :on-workflow-touch-move="onWorkflowCardTouchMove"
                  @toggle="toggleFolder"
                  @drag-over="onDragOverFolder"
                  @drag-leave="onDragLeaveFolder"
                  @drop="onDropToFolder"
                  @context-menu="openContextMenu"
                  @create-subfolder="openCreateFolderDialog"
                  @open-workflow="(id, e) => openWorkflow(id, e)"
                  @edit-workflow="openEditDialog"
                  @copy-workflow="copyWorkflow"
                  @delete-workflow="deleteWorkflow"
                  @drag-start-workflow="onDragStartWorkflow"
                  @drag-end-workflow="onDragEndWorkflow"
                />
              </div>

              <div
                :class="cn(
                  'rounded-xl border-2 border-dashed p-3 transition-all',
                  dragOverRoot ? 'border-primary bg-primary/5' : 'border-transparent'
                )"
                @dragenter="onDragEnterDropZone"
                @dragover="onDragOverRoot"
                @dragleave="onDragLeaveRoot"
                @drop="onDropToRoot"
              >
                <div
                  v-if="draggedWorkflowId && workflows.find((w) => w.id === draggedWorkflowId)?.folder_id"
                  class="text-center text-sm text-muted-foreground py-2"
                >
                  Drop here to move to root
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  <Card
                    v-for="(workflow, index) in rootWorkflows"
                    :key="workflow.id"
                    variant="interactive"
                    :class="cn(
                      'workflow-card p-3.5 cursor-pointer group relative',
                      draggedWorkflowId === workflow.id && 'opacity-50 scale-[0.98]'
                    )"
                    :style="{ animationDelay: `${index * 60}ms` }"
                    :hover="false"
                    draggable="true"
                    @click="openWorkflow(workflow.id, $event)"
                    @touchstart.passive="isMobile && onWorkflowCardTouchStart($event, workflow)"
                    @touchend="isMobile && onWorkflowCardTouchEnd()"
                    @touchmove="isMobile && onWorkflowCardTouchMove()"
                    @dragstart="onDragStartWorkflow($event, workflow.id)"
                    @dragend="onDragEndWorkflow"
                  >
                    <div class="flex items-start justify-between mb-2 gap-1.5">
                      <div class="flex items-start gap-3 min-w-0 flex-1">
                        <div
                          class="workflow-icon relative flex items-center justify-center w-9 h-9 rounded-lg text-primary shrink-0"
                        >
                          <div
                            class="absolute inset-0 rounded-lg bg-gradient-to-br from-primary/15 via-primary/10 to-primary/5"
                          />
                          <div class="absolute inset-0 rounded-lg ring-1 ring-inset ring-primary/20" />
                          <component
                            :is="workflow.first_node_type && nodeIcons[workflow.first_node_type] ? nodeIcons[workflow.first_node_type] : Workflow"
                            class="w-4 h-4 relative z-10"
                          />
                        </div>
                        <div class="min-w-0">
                          <h3 class="workflow-card-title font-semibold text-sm line-clamp-2 leading-snug transition-colors duration-200">
                            {{ workflow.name }}
                          </h3>
                          <div class="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                            <Clock class="w-3 h-3" />
                            <span>{{ formatDate(workflow.updated_at) }}</span>
                          </div>
                        </div>
                      </div>
                      <div class="flex items-center gap-0.5 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
                          title="Copy workflow"
                          :disabled="copyingId === workflow.id"
                          @click="copyWorkflow(workflow.id, $event)"
                        >
                          <Copy
                            class="w-3.5 h-3.5"
                            :class="{ 'animate-spin-slow': copyingId === workflow.id }"
                          />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
                          title="Edit workflow"
                          @click="openEditDialog(workflow, $event)"
                        >
                          <Settings class="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg"
                          title="Delete workflow"
                          @click="deleteWorkflow(workflow.id, $event)"
                        >
                          <Trash2 class="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>
                    <div
                      v-if="workflow.description"
                      class="mt-0.5 pt-2 border-t border-border/40 ml-[48px]"
                    >
                      <p class="text-muted-foreground text-xs line-clamp-2 leading-relaxed">
                        {{ workflow.description }}
                      </p>
                    </div>
                  </Card>
                </div>
              </div>

              <div
                :class="cn(
                  'mt-6 rounded-xl border-2 border-dashed p-3 transition-all duration-300',
                  dragOverTrash ? 'border-destructive bg-destructive/5' : 'border-border/40 bg-muted/5'
                )"
                @dragenter="onDragEnterDropZone"
                @dragover="onDragOverTrash"
                @dragleave="onDragLeaveTrash"
                @drop="onDropToTrash"
              >
                <div
                  class="flex items-center gap-2"
                  :class="{ 'mb-3': scheduledWorkflows.length > 0 || draggedWorkflowId }"
                >
                  <div class="flex items-center justify-center w-8 h-8 rounded-lg bg-destructive/10 text-destructive">
                    <Trash2 class="w-4 h-4" />
                  </div>
                  <div>
                    <h3 class="font-semibold text-sm text-muted-foreground">
                      Scheduled for Deletion
                    </h3>
                    <p class="text-xs text-muted-foreground/70 hidden sm:block">
                      Drag workflows here - they will be deleted at 23:59 if all start nodes are deactivated
                    </p>
                  </div>
                </div>

                <div
                  v-if="draggedWorkflowId && !workflows.find((w) => w.id === draggedWorkflowId)?.scheduled_for_deletion"
                  class="text-center text-sm text-destructive py-4 border border-dashed border-destructive/30 rounded-xl mb-4 mt-4"
                >
                  Drop here to schedule for deletion
                </div>

                <div
                  v-if="scheduledWorkflows.length > 0"
                  class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
                >
                  <Card
                    v-for="(workflow, index) in scheduledWorkflows"
                    :key="workflow.id"
                    variant="interactive"
                    :class="cn(
                      'workflow-card p-3.5 cursor-pointer group relative border-destructive/20 bg-destructive/5 hover:border-destructive/40',
                      draggedWorkflowId === workflow.id && 'opacity-50 scale-[0.98]'
                    )"
                    :style="{ animationDelay: `${index * 60}ms` }"
                    :hover="false"
                    draggable="true"
                    @click="openWorkflow(workflow.id, $event)"
                    @touchstart.passive="isMobile && onWorkflowCardTouchStart($event, workflow)"
                    @touchend="isMobile && onWorkflowCardTouchEnd()"
                    @touchmove="isMobile && onWorkflowCardTouchMove()"
                    @dragstart="onDragStartWorkflow($event, workflow.id)"
                    @dragend="onDragEndWorkflow"
                  >
                    <div class="flex items-start justify-between mb-2 gap-1.5">
                      <div class="flex items-start gap-3 min-w-0 flex-1">
                        <div
                          class="workflow-icon relative flex items-center justify-center w-9 h-9 rounded-lg text-destructive shrink-0"
                        >
                          <div
                            class="absolute inset-0 rounded-lg bg-gradient-to-br from-destructive/15 via-destructive/10 to-destructive/5"
                          />
                          <div class="absolute inset-0 rounded-lg ring-1 ring-inset ring-destructive/20" />
                          <component
                            :is="workflow.first_node_type && nodeIcons[workflow.first_node_type] ? nodeIcons[workflow.first_node_type] : Workflow"
                            class="w-4 h-4 relative z-10"
                          />
                        </div>
                        <div class="min-w-0">
                          <h3 class="workflow-card-title font-semibold text-sm line-clamp-2 leading-snug transition-colors duration-200 group-hover:text-destructive">
                            {{ workflow.name }}
                          </h3>
                          <div class="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                            <Clock class="w-3 h-3" />
                            <span>Scheduled {{ formatDate(workflow.scheduled_for_deletion!) }}</span>
                          </div>
                        </div>
                      </div>
                      <div class="flex items-center gap-0.5 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg"
                          title="Restore workflow"
                          @click="restoreFromTrash(workflow.id, $event)"
                        >
                          <RotateCcw class="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-8 w-8 md:h-7 md:w-7 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all duration-200 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg"
                          title="Delete immediately"
                          @click="deleteWorkflow(workflow.id, $event)"
                        >
                          <Trash2 class="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </div>
                    <div
                      v-if="workflow.description"
                      class="mt-0.5 pt-2 border-t border-border/40 ml-[48px]"
                    >
                      <p class="text-muted-foreground text-xs line-clamp-2 leading-relaxed">
                        {{ workflow.description }}
                      </p>
                    </div>
                  </Card>
                </div>
              </div>
            </div>
          </div>

          <CredentialsPanel v-else-if="activeTab === 'credentials'" />

          <GlobalVariablesPanel v-else-if="activeTab === 'globalvariables'" />

          <TemplatesPage
            v-else-if="activeTab === 'templates'"
            :key="paletteAutoOpenId ?? 'templates'"
          />

          <DrivePanel v-else-if="activeTab === 'drive'" />

          <DataTablePanel
            v-else-if="activeTab === 'datatable'"
            :initial-table-id="dataTableInitialId"
            @navigate="onDataTableNavigate"
          />

          <VectorStoresPanel v-else-if="activeTab === 'vectorstores'" />

          <MCPPanel v-else-if="activeTab === 'mcp'" />

          <ScheduledView v-else-if="activeTab === 'schedules'" />

          <TracesPanel v-else-if="activeTab === 'traces'" />

          <AnalyticsDashboard
            v-else-if="activeTab === 'analytics'"
            @open-error-history="(wfId) => { historyWorkflowId = wfId; historyInitialStatus = 'error'; historyOpen = true; pushOverlayState(); }"
          />

          <TeamsPanel v-else-if="activeTab === 'teams'" />

          <div
            v-else-if="activeTab === 'logs'"
            class="flex h-[calc(100vh-14rem)] flex-col"
          >
            <DockerLogsViewer />
          </div>
        </div>
      </main>

      <Dialog
        :open="showCreateDialog"
        title="Create New Workflow"
        @close="showCreateDialog = false"
      >
        <form
          class="space-y-4"
          @submit.prevent="createWorkflow"
        >
          <div class="space-y-2">
            <Label for="name">Name</Label>
            <Input
              id="name"
              v-model="newWorkflowName"
              placeholder="My Workflow"
              required
            />
          </div>
          <div class="space-y-2">
            <Label for="description">Description (optional)</Label>
            <Textarea
              id="description"
              v-model="newWorkflowDescription"
              placeholder="What does this workflow do?"
              :rows="3"
            />
          </div>
          <div class="flex flex-col-reverse sm:flex-row justify-end gap-3 pt-4">
            <Button
              variant="outline"
              type="button"
              @click="showCreateDialog = false"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="gradient"
              :loading="creating"
              :disabled="!newWorkflowName.trim()"
            >
              Create Workflow
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        :open="showEditDialog"
        title="Workflow Settings"
        @close="showEditDialog = false"
      >
        <form
          class="space-y-4"
          @submit.prevent="updateWorkflow"
        >
          <div class="space-y-2">
            <Label for="edit-name">Name</Label>
            <Input
              id="edit-name"
              v-model="editWorkflowName"
              placeholder="Workflow name"
              required
            />
          </div>
          <div class="space-y-2">
            <Label for="edit-description">Description (optional)</Label>
            <Textarea
              id="edit-description"
              v-model="editWorkflowDescription"
              placeholder="What does this workflow do?"
              :rows="3"
            />
          </div>
          <div class="flex flex-col-reverse sm:flex-row justify-end gap-3 pt-4">
            <Button
              variant="outline"
              type="button"
              @click="showEditDialog = false"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              :loading="editing"
              :disabled="!editWorkflowName.trim()"
            >
              Save Changes
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        :open="showFolderDialog"
        title="Create New Folder"
        @close="showFolderDialog = false"
      >
        <form
          class="space-y-4"
          @submit.prevent="createFolder"
        >
          <div class="space-y-2">
            <Label for="folder-name">Folder Name</Label>
            <Input
              id="folder-name"
              v-model="newFolderName"
              placeholder="My Folder"
              required
            />
          </div>
          <div class="flex flex-col-reverse sm:flex-row justify-end gap-3 pt-4">
            <Button
              variant="outline"
              type="button"
              @click="showFolderDialog = false"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              :loading="creatingFolder"
              :disabled="!newFolderName.trim()"
            >
              Create
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        :open="showRenameFolderDialog"
        title="Rename Folder"
        @close="showRenameFolderDialog = false"
      >
        <form
          class="space-y-4"
          @submit.prevent="renameFolder"
        >
          <div class="space-y-2">
            <Label for="rename-folder-name">Folder Name</Label>
            <Input
              id="rename-folder-name"
              v-model="renameFolderName"
              placeholder="Folder name"
              required
            />
          </div>
          <div class="flex flex-col-reverse sm:flex-row justify-end gap-3 pt-4">
            <Button
              variant="outline"
              type="button"
              @click="showRenameFolderDialog = false"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              :loading="savingFolderRename"
              :disabled="!renameFolderName.trim()"
            >
              Save
            </Button>
          </div>
        </form>
      </Dialog>

      <Teleport to="body">
        <div
          v-if="showContextMenu && contextMenuFolder"
          :style="{ left: contextMenuPosition.x + 'px', top: contextMenuPosition.y + 'px' }"
          class="fixed z-50 min-w-[160px] bg-popover/95 backdrop-blur-xl border border-border/50 rounded-xl shadow-metallic py-1.5"
        >
          <button
            class="w-full px-3 py-2 text-sm text-left flex items-center gap-2 hover:bg-accent/50 rounded-lg mx-1 transition-colors"
            style="width: calc(100% - 8px)"
            @click="openCreateFolderDialog(contextMenuFolder.id)"
          >
            <FolderPlus class="w-4 h-4" />
            New Subfolder
          </button>
          <div class="border-t border-border/50 my-1.5" />
          <button
            class="w-full px-3 py-2 text-sm text-left flex items-center gap-2 hover:bg-accent/50 rounded-lg mx-1 transition-colors"
            style="width: calc(100% - 8px)"
            @click="openRenameFolderDialog(contextMenuFolder)"
          >
            <Edit2 class="w-4 h-4" />
            Rename
          </button>
          <div class="border-t border-border/50 my-1.5" />
          <button
            class="w-full px-3 py-2 text-sm text-left flex items-center gap-2 hover:bg-accent/50 rounded-lg mx-1 transition-colors"
            style="width: calc(100% - 8px)"
            @click="downloadFolderAsZip(contextMenuFolder); showContextMenu = false"
          >
            <Download class="w-4 h-4" />
            Download as ZIP
          </button>
          <div class="border-t border-border/50 my-1.5" />
          <button
            class="w-full px-3 py-2 text-sm text-left flex items-center gap-2 text-destructive hover:bg-destructive/10 rounded-lg mx-1 transition-colors"
            style="width: calc(100% - 8px)"
            @click="deleteFolder(contextMenuFolder)"
          >
            <Trash2 class="w-4 h-4" />
            Delete
          </button>
        </div>
      </Teleport>

      <ExecutionHistoryAllDialog
        :open="historyOpen"
        :workflow-id="historyWorkflowId"
        :initial-status="historyInitialStatus"
        @close="historyOpen = false; historyWorkflowId = undefined; historyInitialStatus = undefined"
      />

      <WorkflowCommandPalette
        :open="showCommandPalette"
        :workflows="workflows"
        context="dashboard"
        :active-tab="activeTab"
        @select="openWorkflowFromPalette"
        @tab-select="handleTabSelectFromPalette"
        @doc-select="onDocSelectFromPalette"
        @template-select="onTemplateSelectFromPalette"
        @node-template-select="onNodeTemplateSelectFromPalette"
        @close="showCommandPalette = false"
      />

      <WorkflowActionSheet
        :open="showWorkflowActionSheet"
        :workflow="workflowActionWorkflow"
        :folder-tree="folderStore.folderTree"
        @close="closeWorkflowActionSheet"
        @move-to-folder="onActionSheetMoveToFolder"
        @move-to-root="onActionSheetMoveToRoot"
        @schedule-deletion="onActionSheetScheduleDeletion"
        @restore="onActionSheetRestore"
        @copy="onActionSheetCopy"
        @edit="onActionSheetEdit"
        @delete="onActionSheetDelete"
      />

      <Transition
        enter-active-class="transition ease-out duration-300"
        enter-from-class="translate-y-2 opacity-0"
        enter-to-class="translate-y-0 opacity-100"
        leave-active-class="transition ease-in duration-200"
        leave-from-class="translate-y-0 opacity-100"
        leave-to-class="translate-y-2 opacity-0"
      >
        <div
          v-if="toastVisible"
          :class="cn(
            'toast-notification fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-metallic max-w-sm',
            toastType === 'error' ? 'bg-destructive text-white' : 'bg-emerald-500 text-white'
          )"
        >
          <AlertTriangle
            v-if="toastType === 'error'"
            class="w-5 h-5 shrink-0"
          />
          <Check
            v-else
            class="w-5 h-5 shrink-0"
          />
          <span class="text-sm font-medium">{{ toastMessage }}</span>
          <button
            class="ml-auto p-1.5 hover:bg-white/20 rounded-lg transition-colors"
            @click="toastVisible = false"
          >
            <X class="w-4 h-4" />
          </button>
        </div>
      </Transition>
    </div>
  </WorkspaceShell>
</template>

<style scoped>
.dashboard-main {
  background: hsl(var(--background));
  min-height: calc(100vh - 4rem);
  position: relative;
}

.tab-container {
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.tab-container::-webkit-scrollbar {
  display: none;
}

.tab-item {
  position: relative;
}

.tab-item::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  opacity: 0;
  background: linear-gradient(135deg,
      hsl(var(--primary) / 0.1) 0%,
      transparent 100%);
  transition: opacity 0.2s ease;
}

.tab-item:hover::before {
  opacity: 1;
}

.empty-state-icon {
  box-shadow:
    0 0 60px hsl(var(--primary) / 0.15),
    0 0 120px hsl(var(--primary) / 0.08);
}

/* ── Workflow Card ── */

.workflow-card {
  animation: fade-in-card 0.35s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.workflow-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg,
      hsl(var(--primary)) 0%,
      hsl(var(--primary) / 0.3) 60%,
      transparent 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.workflow-card:hover::after {
  opacity: 1;
}

.workflow-card:hover {
  box-shadow:
    0 6px 20px hsl(var(--primary) / 0.08),
    0 2px 8px hsl(0 0% 0% / 0.03);
}

.dark .workflow-card:hover {
  box-shadow:
    0 6px 20px hsl(var(--primary) / 0.12),
    0 2px 8px hsl(0 0% 0% / 0.15);
}

.workflow-icon {
  transition: all 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

.workflow-card:hover .workflow-icon {
  transform: scale(1.05);
  box-shadow: 0 4px 14px hsl(var(--primary) / 0.25);
}

/* ── Toast ── */

.toast-notification {
  box-shadow:
    0 8px 32px hsl(0 0% 0% / 0.25),
    0 0 0 1px hsl(0 0% 100% / 0.05);
  animation: toast-enter 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

/* ── Animations ── */

@keyframes fade-in-card {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.97);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes toast-enter {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.96);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
