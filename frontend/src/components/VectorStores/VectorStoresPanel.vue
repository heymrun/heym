<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { AlertTriangle, ChevronDown, ChevronRight, Copy, Database, File, FileUp, Pencil, Plus, Share2, Trash2, Upload, Users, X } from "lucide-vue-next";

import type { CredentialListItem } from "@/types/credential";
import type { Team, TeamShare } from "@/types/team";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { formatDate, formatFileSize } from "@/lib/utils";
import {
  credentialsApi,
  teamsApi,
  vectorStoresApi,
  type DuplicateFile,
  type VectorStoreListItem,
  type VectorStoreShare,
  type VectorStoreSourceGroup,
} from "@/services/api";

const vectorStores = ref<VectorStoreListItem[]>([]);
const loading = ref(true);
const showCreateDialog = ref(false);
const showDeleteDialog = ref(false);
const showUploadDialog = ref(false);
const deletingStore = ref<VectorStoreListItem | null>(null);
const deleteCollection = ref(true);
const uploadingStore = ref<VectorStoreListItem | null>(null);

const showShareDialog = ref(false);
const sharingStore = ref<VectorStoreListItem | null>(null);
const storeShares = ref<VectorStoreShare[]>([]);
const storeTeamShares = ref<TeamShare[]>([]);
const teams = ref<Team[]>([]);
const shareEmail = ref("");
const shareTeamId = ref("");
const sharingLoading = ref(false);
const shareError = ref("");

const showEditDialog = ref(false);
const editingStore = ref<VectorStoreListItem | null>(null);
const editStoreName = ref("");
const editStoreDescription = ref("");
const editSaving = ref(false);
const editError = ref("");

const newStoreName = ref("");
const newStoreDescription = ref("");
const newStoreCredentialId = ref("");
const newStoreCollectionName = ref("");
const qdrantCredentials = ref<CredentialListItem[]>([]);
const saving = ref(false);
const createError = ref("");

const uploadFiles = ref<File[]>([]);
const uploading = ref(false);
const uploadError = ref("");
const uploadSuccess = ref("");
const dropActive = ref(false);
const overrideDuplicates = ref(false);
const duplicateWarning = ref<DuplicateFile[]>([]);
const uploadProgress = ref({ current: 0, total: 0 });

const showItemsDialog = ref(false);
const itemsStore = ref<VectorStoreListItem | null>(null);
const itemsSourceGroups = ref<VectorStoreSourceGroup[]>([]);
const itemsTotalCount = ref(0);
const itemsLoading = ref(false);
const itemsError = ref("");
const expandedSources = ref<Set<string>>(new Set());
const deletingSource = ref<string | null>(null);
const deletingItem = ref<string | null>(null);

const credentialOptions = computed(() => {
  return [
    { value: "", label: "Select a credential" },
    ...qdrantCredentials.value.map((c) => ({
      value: c.id,
      label: c.name,
    })),
  ];
});

const unsubDismissOverlays = onDismissOverlays(() => {
  showCreateDialog.value = false;
  showDeleteDialog.value = false;
  showUploadDialog.value = false;
  showShareDialog.value = false;
  showEditDialog.value = false;
  showItemsDialog.value = false;
});

onMounted(async () => {
  await Promise.all([loadVectorStores(), loadCredentials()]);
});

onUnmounted(() => {
  unsubDismissOverlays();
});

async function loadVectorStores(): Promise<void> {
  loading.value = true;
  try {
    vectorStores.value = await vectorStoresApi.list();
  } finally {
    loading.value = false;
  }
}

async function loadCredentials(): Promise<void> {
  try {
    qdrantCredentials.value = await credentialsApi.listByType("qdrant");
  } catch {
    qdrantCredentials.value = [];
  }
}

function openCreateDialog(): void {
  newStoreName.value = "";
  newStoreDescription.value = "";
  newStoreCredentialId.value = "";
  newStoreCollectionName.value = "";
  createError.value = "";
  showCreateDialog.value = true;
}

async function createVectorStore(): Promise<void> {
  if (!newStoreName.value.trim() || !newStoreCredentialId.value) return;

  saving.value = true;
  createError.value = "";
  try {
    const store = await vectorStoresApi.create({
      name: newStoreName.value.trim(),
      description: newStoreDescription.value.trim() || undefined,
      credential_id: newStoreCredentialId.value,
      collection_name: newStoreCollectionName.value.trim() || undefined,
    });
    vectorStores.value.unshift({
      id: store.id,
      name: store.name,
      description: store.description,
      collection_name: store.collection_name,
      created_at: store.created_at,
      updated_at: store.updated_at,
      is_shared: false,
      shared_by: null,
      stats: store.stats,
    });
    showCreateDialog.value = false;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    createError.value = err.response?.data?.detail || "Failed to create vector store";
  } finally {
    saving.value = false;
  }
}

function openDeleteDialog(store: VectorStoreListItem, event: Event): void {
  event.stopPropagation();
  deletingStore.value = store;
  deleteCollection.value = true;
  showDeleteDialog.value = true;
}

async function confirmDelete(): Promise<void> {
  if (!deletingStore.value) return;

  try {
    await vectorStoresApi.delete(deletingStore.value.id, deleteCollection.value);
    vectorStores.value = vectorStores.value.filter((s) => s.id !== deletingStore.value?.id);
    showDeleteDialog.value = false;
    deletingStore.value = null;
  } catch {
    createError.value = "Failed to delete vector store";
  }
}

async function cloneVectorStore(store: VectorStoreListItem, event: Event): Promise<void> {
  event.stopPropagation();
  try {
    const cloned = await vectorStoresApi.clone(store.id);
    vectorStores.value.unshift({
      id: cloned.id,
      name: cloned.name,
      description: cloned.description,
      collection_name: cloned.collection_name,
      created_at: cloned.created_at,
      updated_at: cloned.updated_at,
      is_shared: false,
      shared_by: null,
      stats: cloned.stats,
    });
  } catch {
    alert("Failed to clone vector store");
  }
}

function openEditDialog(store: VectorStoreListItem, event: Event): void {
  event.stopPropagation();
  editingStore.value = store;
  editStoreName.value = store.name;
  editStoreDescription.value = store.description || "";
  editError.value = "";
  showEditDialog.value = true;
}

async function updateVectorStore(): Promise<void> {
  if (!editingStore.value || !editStoreName.value.trim()) return;

  editSaving.value = true;
  editError.value = "";
  try {
    const updated = await vectorStoresApi.update(editingStore.value.id, {
      name: editStoreName.value.trim(),
      description: editStoreDescription.value.trim() || undefined,
    });
    const idx = vectorStores.value.findIndex((s) => s.id === editingStore.value?.id);
    if (idx !== -1) {
      vectorStores.value[idx] = {
        ...vectorStores.value[idx],
        name: updated.name,
        description: updated.description,
        updated_at: updated.updated_at,
      };
    }
    showEditDialog.value = false;
    editingStore.value = null;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    editError.value = err.response?.data?.detail || "Failed to update vector store";
  } finally {
    editSaving.value = false;
  }
}

function openUploadDialog(store: VectorStoreListItem, event?: Event): void {
  if (event) {
    event.stopPropagation();
  }
  uploadingStore.value = store;
  uploadFiles.value = [];
  uploadError.value = "";
  uploadSuccess.value = "";
  overrideDuplicates.value = false;
  duplicateWarning.value = [];
  uploadProgress.value = { current: 0, total: 0 };
  showItemsDialog.value = false;
  showUploadDialog.value = true;
}

function handleFileDrop(event: DragEvent): void {
  dropActive.value = false;
  const files = event.dataTransfer?.files;
  if (files && files.length > 0) {
    const newFiles = Array.from(files);
    const existing = new Set(uploadFiles.value.map((f) => `${f.name}:${f.size}`));
    for (const file of newFiles) {
      if (!existing.has(`${file.name}:${file.size}`)) {
        uploadFiles.value.push(file);
      }
    }
    duplicateWarning.value = [];
  }
}

function handleFileSelect(event: Event): void {
  const input = event.target as HTMLInputElement;
  if (input.files && input.files.length > 0) {
    const newFiles = Array.from(input.files);
    const existing = new Set(uploadFiles.value.map((f) => `${f.name}:${f.size}`));
    for (const file of newFiles) {
      if (!existing.has(`${file.name}:${file.size}`)) {
        uploadFiles.value.push(file);
      }
    }
    duplicateWarning.value = [];
  }
  input.value = "";
}

function removeFile(index: number): void {
  uploadFiles.value.splice(index, 1);
  duplicateWarning.value = [];
}

async function submitUpload(): Promise<void> {
  if (!uploadingStore.value || uploadFiles.value.length === 0) return;

  uploading.value = true;
  uploadError.value = "";
  uploadSuccess.value = "";
  duplicateWarning.value = [];

  try {
    const filesToCheck = uploadFiles.value.map((f) => ({
      filename: f.name,
      file_size: f.size,
    }));

    const checkResult = await vectorStoresApi.checkDuplicates(
      uploadingStore.value.id,
      filesToCheck
    );

    if (checkResult.duplicates.length > 0 && !overrideDuplicates.value) {
      duplicateWarning.value = checkResult.duplicates;
      uploading.value = false;
      return;
    }

    let totalChunks = 0;
    let totalPoints = 0;
    uploadProgress.value = { current: 0, total: uploadFiles.value.length };

    for (let i = 0; i < uploadFiles.value.length; i++) {
      const file = uploadFiles.value[i];
      uploadProgress.value.current = i + 1;

      const result = await vectorStoresApi.uploadFile(
        uploadingStore.value.id,
        file,
        overrideDuplicates.value
      );
      totalChunks += result.chunks_processed;
      totalPoints += result.points_inserted;
    }

    uploadSuccess.value = `Uploaded ${uploadFiles.value.length} file(s): ${totalChunks} chunks, ${totalPoints} vectors`;
    uploadFiles.value = [];
    overrideDuplicates.value = false;
    await loadVectorStores();
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    uploadError.value = err.response?.data?.detail || "Failed to upload files";
  } finally {
    uploading.value = false;
    uploadProgress.value = { current: 0, total: 0 };
  }
}

async function openShareDialog(store: VectorStoreListItem, event: Event): Promise<void> {
  event.stopPropagation();
  sharingStore.value = store;
  shareEmail.value = "";
  shareTeamId.value = "";
  shareError.value = "";
  sharingLoading.value = true;
  showShareDialog.value = true;
  try {
    const [userShares, teamShares, teamList] = await Promise.all([
      vectorStoresApi.listShares(store.id),
      vectorStoresApi.listTeamShares(store.id),
      teamsApi.list(),
    ]);
    storeShares.value = userShares;
    storeTeamShares.value = teamShares;
    teams.value = teamList;
  } catch {
    storeShares.value = [];
    storeTeamShares.value = [];
    teams.value = [];
  } finally {
    sharingLoading.value = false;
  }
}

async function addShare(): Promise<void> {
  if (!sharingStore.value || !shareEmail.value.trim()) return;
  shareError.value = "";
  sharingLoading.value = true;
  try {
    const share = await vectorStoresApi.addShare(sharingStore.value.id, shareEmail.value.trim());
    if (!storeShares.value.find((s) => s.id === share.id)) {
      storeShares.value.push(share);
    }
    shareEmail.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    shareError.value = err.response?.data?.detail || "Failed to share vector store";
  } finally {
    sharingLoading.value = false;
  }
}

async function removeShare(userId: string): Promise<void> {
  if (!sharingStore.value) return;
  try {
    await vectorStoresApi.removeShare(sharingStore.value.id, userId);
    storeShares.value = storeShares.value.filter((s) => s.user_id !== userId);
  } catch {
    shareError.value = "Failed to remove share";
  }
}

const storeTeamOptions = computed(() => {
  const shared = new Set(storeTeamShares.value.map((s) => s.team_id));
  return [
    { value: "", label: "Select a team" },
    ...teams.value
      .filter((t) => !shared.has(t.id))
      .map((t) => ({ value: t.id, label: t.name })),
  ];
});

async function addTeamShare(): Promise<void> {
  if (!sharingStore.value || !shareTeamId.value) return;
  shareError.value = "";
  sharingLoading.value = true;
  try {
    const share = await vectorStoresApi.addTeamShare(sharingStore.value.id, shareTeamId.value);
    storeTeamShares.value = [...storeTeamShares.value, share];
    shareTeamId.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    shareError.value = err.response?.data?.detail || "Failed to share with team";
  } finally {
    sharingLoading.value = false;
  }
}

async function removeTeamShare(teamId: string): Promise<void> {
  if (!sharingStore.value) return;
  try {
    await vectorStoresApi.removeTeamShare(sharingStore.value.id, teamId);
    storeTeamShares.value = storeTeamShares.value.filter((s) => s.team_id !== teamId);
  } catch {
    shareError.value = "Failed to remove team share";
  }
}

function formatVectorCount(stats: VectorStoreListItem["stats"]): string {
  if (!stats) return "N/A";
  return stats.vector_count.toLocaleString();
}

async function openItemsDialog(store: VectorStoreListItem): Promise<void> {
  itemsStore.value = store;
  itemsSourceGroups.value = [];
  itemsTotalCount.value = 0;
  itemsError.value = "";
  expandedSources.value = new Set();
  showItemsDialog.value = true;
  await loadItems();
}

async function loadItems(): Promise<void> {
  if (!itemsStore.value) return;
  itemsLoading.value = true;
  itemsError.value = "";
  try {
    const result = await vectorStoresApi.listItems(itemsStore.value.id);
    itemsSourceGroups.value = result.sources;
    itemsTotalCount.value = result.total_items;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    itemsError.value = err.response?.data?.detail || "Failed to load items";
  } finally {
    itemsLoading.value = false;
  }
}

function toggleSourceExpanded(source: string): void {
  if (expandedSources.value.has(source)) {
    expandedSources.value.delete(source);
  } else {
    expandedSources.value.add(source);
  }
}

async function deleteSource(source: string): Promise<void> {
  if (!itemsStore.value) return;
  deletingSource.value = source;
  try {
    await vectorStoresApi.deleteItemsBySource(itemsStore.value.id, source);
    await loadItems();
    await loadVectorStores();
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    itemsError.value = err.response?.data?.detail || "Failed to delete source";
  } finally {
    deletingSource.value = null;
  }
}

async function deleteItem(pointId: string): Promise<void> {
  if (!itemsStore.value) return;
  deletingItem.value = pointId;
  try {
    await vectorStoresApi.deleteItem(itemsStore.value.id, pointId);
    await loadItems();
    await loadVectorStores();
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    itemsError.value = err.response?.data?.detail || "Failed to delete item";
  } finally {
    deletingItem.value = null;
  }
}
</script>

<template>
  <div class="overflow-x-hidden">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold tracking-tight">
          Vector Stores
        </h2>
        <p class="text-muted-foreground mt-1">
          Manage QDrant vector stores for RAG workflows
        </p>
      </div>
      <Button @click="openCreateDialog">
        <Plus class="w-4 h-4" />
        New Vector Store
      </Button>
    </div>

    <div
      v-if="loading"
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
    >
      <Card
        v-for="i in 3"
        :key="i"
        class="p-6 animate-pulse"
      >
        <div class="h-6 bg-muted rounded w-2/3 mb-3" />
        <div class="h-4 bg-muted rounded w-full mb-2" />
        <div class="h-4 bg-muted rounded w-1/2" />
      </Card>
    </div>

    <div
      v-else-if="vectorStores.length === 0"
      class="text-center py-16"
    >
      <div class="flex items-center justify-center w-16 h-16 rounded-full bg-muted mx-auto mb-4">
        <Database class="w-8 h-8 text-muted-foreground" />
      </div>
      <h3 class="text-xl font-semibold mb-2">
        No vector stores yet
      </h3>
      <p class="text-muted-foreground mb-6">
        Create a vector store to start using RAG in your workflows
      </p>
      <Button @click="openCreateDialog">
        <Plus class="w-4 h-4" />
        Create Vector Store
      </Button>
    </div>

    <div
      v-else
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
    >
      <Card
        v-for="store in vectorStores"
        :key="store.id"
        :class="`p-5 transition-all hover:border-primary/50 hover:shadow-md group cursor-pointer ${store.is_shared ? 'border-l-4 border-l-blue-500' : ''}`"
        @click="openItemsDialog(store)"
      >
        <div class="flex items-start justify-between mb-3">
          <div class="flex items-center gap-3">
            <div class="flex items-center justify-center w-10 h-10 rounded-lg bg-node-rag/10 text-node-rag">
              <Database class="w-5 h-5" />
            </div>
            <div>
              <div class="flex items-center gap-2">
                <h3 class="font-semibold text-base group-hover:text-primary transition-colors">
                  {{ store.name }}
                </h3>
                <span
                  v-if="store.is_shared"
                  class="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-blue-500/10 text-blue-500"
                >
                  <Users class="w-3 h-3" />
                  Shared
                </span>
              </div>
              <p class="text-xs text-muted-foreground">
                {{ formatVectorCount(store.stats) }} vectors
              </p>
            </div>
          </div>
          <div
            v-if="!store.is_shared"
            class="flex items-center gap-1"
          >
            <Button
              variant="ghost"
              size="icon"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary h-8 w-8"
              title="Upload files"
              @click="openUploadDialog(store, $event)"
            >
              <Upload class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary h-8 w-8"
              title="Edit"
              @click="openEditDialog(store, $event)"
            >
              <Pencil class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary h-8 w-8"
              title="Clone"
              @click="cloneVectorStore(store, $event)"
            >
              <Copy class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary h-8 w-8"
              title="Share"
              @click="openShareDialog(store, $event)"
            >
              <Share2 class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive h-8 w-8"
              title="Delete"
              @click="openDeleteDialog(store, $event)"
            >
              <Trash2 class="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div class="space-y-2">
          <p
            v-if="store.description"
            class="text-sm text-muted-foreground line-clamp-2"
          >
            {{ store.description }}
          </p>
          <div class="text-xs font-mono text-muted-foreground bg-muted/50 px-2 py-1 rounded">
            {{ store.collection_name }}
          </div>
          <div class="text-xs text-muted-foreground">
            <span v-if="store.is_shared && store.shared_by">
              Shared by {{ store.shared_by }}
            </span>
            <span v-else>
              Created {{ formatDate(store.created_at) }}
            </span>
          </div>
        </div>
      </Card>
    </div>

    <Dialog
      :open="showCreateDialog"
      title="New Vector Store"
      @close="showCreateDialog = false"
    >
      <form
        class="space-y-4"
        @submit.prevent="createVectorStore"
      >
        <div class="space-y-2">
          <Label for="store-name">Name <span class="text-destructive">*</span></Label>
          <Input
            id="store-name"
            v-model="newStoreName"
            placeholder="My Vector Store"
            :disabled="saving"
          />
        </div>

        <div class="space-y-2">
          <Label for="store-description">Description</Label>
          <Textarea
            id="store-description"
            v-model="newStoreDescription"
            placeholder="Optional description"
            :rows="2"
            :disabled="saving"
          />
        </div>

        <div class="space-y-2">
          <Label for="store-credential">Credential <span class="text-destructive">*</span></Label>
          <Select
            id="store-credential"
            v-model="newStoreCredentialId"
            :options="credentialOptions"
            :disabled="saving"
          />
          <p
            v-if="qdrantCredentials.length === 0"
            class="text-xs text-amber-500"
          >
            No QDrant credentials found.
            <a
              href="/?tab=credentials"
              class="text-primary hover:underline"
              @click.prevent="$router.push('/?tab=credentials')"
            >Create one</a> first.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="store-collection">Collection Name (optional)</Label>
          <Input
            id="store-collection"
            v-model="newStoreCollectionName"
            placeholder="heym_vs_auto_generated"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Leave empty for auto-generated name
          </p>
        </div>

        <p
          v-if="createError"
          class="text-sm text-destructive"
        >
          {{ createError }}
        </p>

        <div class="flex justify-end gap-3 pt-4">
          <Button
            variant="outline"
            type="button"
            :disabled="saving"
            @click="showCreateDialog = false"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            :loading="saving"
            :disabled="!newStoreName.trim() || !newStoreCredentialId"
          >
            Create
          </Button>
        </div>
      </form>
    </Dialog>

    <Dialog
      :open="showDeleteDialog"
      title="Delete Vector Store"
      @close="showDeleteDialog = false"
    >
      <div class="space-y-4">
        <p class="text-sm text-muted-foreground">
          Are you sure you want to delete <strong>{{ deletingStore?.name }}</strong>?
        </p>

        <label class="flex items-center gap-2 cursor-pointer">
          <input
            v-model="deleteCollection"
            type="checkbox"
            class="rounded border-border"
          >
          <span class="text-sm">Also delete QDrant collection</span>
        </label>

        <p
          v-if="!deleteCollection"
          class="text-xs text-amber-500"
        >
          The QDrant collection will remain and can be reused later.
        </p>

        <div class="flex justify-end gap-3 pt-4">
          <Button
            variant="outline"
            @click="showDeleteDialog = false"
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            @click="confirmDelete"
          >
            Delete
          </Button>
        </div>
      </div>
    </Dialog>

    <Dialog
      :open="showUploadDialog"
      title="Upload Files"
      @close="showUploadDialog = false"
    >
      <div class="space-y-4">
        <p class="text-sm text-muted-foreground">
          Upload files to <strong>{{ uploadingStore?.name }}</strong>.
          Supported formats: PDF, Markdown, Text, CSV, JSON
        </p>

        <div
          class="border-2 border-dashed rounded-lg p-6 text-center transition-colors"
          :class="dropActive ? 'border-primary bg-primary/5' : 'border-border'"
          @dragover.prevent="dropActive = true"
          @dragleave="dropActive = false"
          @drop.prevent="handleFileDrop"
        >
          <FileUp class="w-8 h-8 mx-auto mb-2 text-muted-foreground" />
          <p class="text-sm text-muted-foreground mb-1">
            Drag & drop files here, or
          </p>
          <label class="cursor-pointer">
            <span class="text-primary hover:underline text-sm">browse</span>
            <input
              type="file"
              accept=".pdf,.md,.markdown,.txt,.csv,.json"
              multiple
              class="hidden"
              @change="handleFileSelect"
            >
          </label>
        </div>

        <div
          v-if="uploadFiles.length > 0"
          class="space-y-2"
        >
          <Label>Selected files ({{ uploadFiles.length }})</Label>
          <div class="max-h-40 overflow-y-auto space-y-1">
            <div
              v-for="(file, index) in uploadFiles"
              :key="`${file.name}-${file.size}`"
              class="flex items-center justify-between p-2 rounded bg-muted/50 text-sm"
            >
              <div class="flex items-center gap-2 min-w-0">
                <File class="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <span class="truncate">{{ file.name }}</span>
                <span class="text-xs text-muted-foreground flex-shrink-0">
                  ({{ formatFileSize(file.size) }})
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                class="h-6 w-6 text-muted-foreground hover:text-destructive flex-shrink-0"
                :disabled="uploading"
                @click="removeFile(index)"
              >
                <X class="w-3 h-3" />
              </Button>
            </div>
          </div>
        </div>

        <label class="flex items-center gap-2 cursor-pointer">
          <input
            v-model="overrideDuplicates"
            type="checkbox"
            class="rounded border-border"
            :disabled="uploading"
          >
          <span class="text-sm">Override existing files with same name</span>
        </label>

        <div
          v-if="duplicateWarning.length > 0"
          class="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30"
        >
          <AlertTriangle class="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
          <div class="text-sm">
            <p class="font-medium text-amber-600 dark:text-amber-400 mb-1">
              Duplicate files detected
            </p>
            <p class="text-muted-foreground mb-2">
              The following files already exist in this vector store:
            </p>
            <ul class="list-disc list-inside text-muted-foreground space-y-0.5">
              <li
                v-for="dup in duplicateWarning"
                :key="dup.filename"
              >
                {{ dup.filename }} ({{ dup.chunk_count }} chunks)
              </li>
            </ul>
            <p class="mt-2 text-amber-600 dark:text-amber-400">
              Enable "Override existing files" to replace them.
            </p>
          </div>
        </div>

        <p
          v-if="uploadError"
          class="text-sm text-destructive"
        >
          {{ uploadError }}
        </p>

        <p
          v-if="uploadSuccess"
          class="text-sm text-green-500"
        >
          {{ uploadSuccess }}
        </p>

        <p
          v-if="uploading && uploadProgress.total > 0"
          class="text-sm text-muted-foreground"
        >
          Uploading file {{ uploadProgress.current }} of {{ uploadProgress.total }}...
        </p>

        <div class="flex justify-end gap-3 pt-4">
          <Button
            variant="outline"
            :disabled="uploading"
            @click="showUploadDialog = false"
          >
            Close
          </Button>
          <Button
            :loading="uploading"
            :disabled="uploadFiles.length === 0"
            @click="submitUpload"
          >
            Upload {{ uploadFiles.length > 0 ? `(${uploadFiles.length})` : '' }}
          </Button>
        </div>
      </div>
    </Dialog>

    <Dialog
      :open="showShareDialog"
      title="Share Vector Store"
      @close="showShareDialog = false"
    >
      <div class="space-y-4">
        <p class="text-sm text-muted-foreground">
          Share <strong>{{ sharingStore?.name }}</strong> with other users.
          They will be able to use this vector store in their workflows.
        </p>

        <div class="space-y-3">
          <div>
            <Label class="text-xs">Share with user</Label>
            <div class="flex gap-2 mt-1">
              <Input
                v-model="shareEmail"
                type="email"
                placeholder="user@example.com"
                class="flex-1"
                @keyup.enter="addShare"
              />
              <Button
                :disabled="!shareEmail.trim() || sharingLoading"
                @click="addShare"
              >
                Share
              </Button>
            </div>
          </div>
          <div>
            <Label class="text-xs">Share with team</Label>
            <div class="flex gap-2 mt-1">
              <Select
                v-model="shareTeamId"
                :options="storeTeamOptions"
                class="flex-1"
              />
              <Button
                :disabled="!shareTeamId || sharingLoading"
                @click="addTeamShare"
              >
                <Users class="w-4 h-4" />
                Add
              </Button>
            </div>
          </div>
        </div>

        <p
          v-if="shareError"
          class="text-sm text-destructive"
        >
          {{ shareError }}
        </p>

        <div class="space-y-2">
          <Label>Shared with users:</Label>
          <div
            v-if="storeShares.length > 0"
            class="space-y-2 max-h-32 overflow-y-auto"
          >
            <div
              v-for="share in storeShares"
              :key="share.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <div>
                <p class="text-sm font-medium">
                  {{ share.name }}
                </p>
                <p class="text-xs text-muted-foreground">
                  {{ share.email }}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeShare(share.user_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
          <p
            v-else-if="!sharingLoading"
            class="text-sm text-muted-foreground"
          >
            No users
          </p>
        </div>
        <div class="space-y-2">
          <Label>Shared with teams:</Label>
          <div
            v-if="storeTeamShares.length > 0"
            class="space-y-2 max-h-32 overflow-y-auto"
          >
            <div
              v-for="share in storeTeamShares"
              :key="share.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <p class="text-sm font-medium">
                {{ share.team_name }}
              </p>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeTeamShare(share.team_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
          <p
            v-else-if="!sharingLoading"
            class="text-sm text-muted-foreground"
          >
            No teams
          </p>
        </div>
      </div>
    </Dialog>

    <Dialog
      :open="showEditDialog"
      title="Edit Vector Store"
      @close="showEditDialog = false"
    >
      <form
        class="space-y-4"
        @submit.prevent="updateVectorStore"
      >
        <div class="space-y-2">
          <Label for="edit-store-name">Name <span class="text-destructive">*</span></Label>
          <Input
            id="edit-store-name"
            v-model="editStoreName"
            placeholder="My Vector Store"
            :disabled="editSaving"
          />
        </div>

        <div class="space-y-2">
          <Label for="edit-store-description">Description</Label>
          <Textarea
            id="edit-store-description"
            v-model="editStoreDescription"
            placeholder="Optional description"
            :rows="2"
            :disabled="editSaving"
          />
        </div>

        <div class="text-xs font-mono text-muted-foreground bg-muted/50 px-2 py-1 rounded">
          Collection: {{ editingStore?.collection_name }}
        </div>

        <p
          v-if="editError"
          class="text-sm text-destructive"
        >
          {{ editError }}
        </p>

        <div class="flex justify-end gap-3 pt-4">
          <Button
            variant="outline"
            type="button"
            :disabled="editSaving"
            @click="showEditDialog = false"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            :loading="editSaving"
            :disabled="!editStoreName.trim()"
          >
            Save
          </Button>
        </div>
      </form>
    </Dialog>

    <Dialog
      :open="showItemsDialog"
      :title="itemsStore?.name || 'Vector Store Items'"
      size="4xl"
      @close="showItemsDialog = false"
    >
      <template #header-actions>
        <Button
          v-if="itemsStore && !itemsStore.is_shared"
          variant="outline"
          size="sm"
          @click="openUploadDialog(itemsStore)"
        >
          <Upload class="w-4 h-4 mr-2" />
          Add New
        </Button>
      </template>
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <p class="text-sm text-muted-foreground">
            {{ itemsTotalCount.toLocaleString() }} items in
            {{ itemsSourceGroups.length }} source(s)
          </p>
          <Button
            variant="outline"
            size="sm"
            :loading="itemsLoading"
            @click="loadItems"
          >
            Refresh
          </Button>
        </div>

        <p
          v-if="itemsError"
          class="text-sm text-destructive"
        >
          {{ itemsError }}
        </p>

        <div
          v-if="itemsLoading && itemsSourceGroups.length === 0"
          class="py-8 text-center text-muted-foreground"
        >
          Loading items...
        </div>

        <div
          v-else-if="itemsSourceGroups.length === 0"
          class="py-8 text-center text-muted-foreground"
        >
          <Database class="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p>No items in this vector store</p>
        </div>

        <div
          v-else
          class="max-h-[70vh] overflow-y-auto space-y-2"
        >
          <div
            v-for="group in itemsSourceGroups"
            :key="group.source"
            class="border rounded-lg overflow-hidden"
          >
            <div
              class="flex items-center justify-between p-3 bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors"
              @click="toggleSourceExpanded(group.source)"
            >
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <component
                  :is="expandedSources.has(group.source) ? ChevronDown : ChevronRight"
                  class="w-4 h-4 text-muted-foreground flex-shrink-0"
                />
                <File class="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <span class="font-medium line-clamp-2 break-words min-w-0 flex-1">{{ group.source }}</span>
                <span class="text-xs text-muted-foreground flex-shrink-0 whitespace-nowrap">
                  ({{ group.chunk_count }} chunks)
                </span>
                <span
                  v-if="group.file_size"
                  class="text-xs text-muted-foreground flex-shrink-0 whitespace-nowrap"
                >
                  {{ formatFileSize(group.file_size) }}
                </span>
              </div>
              <Button
                v-if="!itemsStore?.is_shared"
                variant="ghost"
                size="icon"
                class="h-7 w-7 text-muted-foreground hover:text-destructive flex-shrink-0"
                :loading="deletingSource === group.source"
                title="Delete all chunks from this source"
                @click.stop="deleteSource(group.source)"
              >
                <Trash2 class="w-3.5 h-3.5" />
              </Button>
            </div>

            <div
              v-if="expandedSources.has(group.source)"
              class="border-t divide-y"
            >
              <div
                v-for="item in group.items"
                :key="item.id"
                class="p-4 hover:bg-muted/20 border-b border-border/50 last:border-b-0"
              >
                <div class="flex items-start justify-between gap-4">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm text-foreground whitespace-pre-wrap break-words leading-relaxed">
                      {{ item.text }}
                    </p>
                    <p class="text-xs text-muted-foreground mt-2 font-mono">
                      ID: {{ item.id }}
                    </p>
                  </div>
                  <Button
                    v-if="!itemsStore?.is_shared"
                    variant="ghost"
                    size="icon"
                    class="h-6 w-6 text-muted-foreground hover:text-destructive flex-shrink-0"
                    :loading="deletingItem === item.id"
                    title="Delete this chunk"
                    @click="deleteItem(item.id)"
                  >
                    <X class="w-3 h-3" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="flex justify-end pt-2">
          <Button
            variant="outline"
            @click="showItemsDialog = false"
          >
            Close
          </Button>
        </div>
      </div>
    </Dialog>
  </div>
</template>