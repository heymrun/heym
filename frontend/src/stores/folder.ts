import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { folderApi } from "@/services/api";
import type { Folder, FolderTree, WorkflowListItem } from "@/types/workflow";

export const useFolderStore = defineStore("folder", () => {
  const folders = ref<Folder[]>([]);
  const folderTree = ref<FolderTree[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const expandedFolders = ref<Set<string>>(new Set());
  const currentFolderId = ref<string | null>(null);

  const rootFolders = computed(() => folders.value.filter((f) => !f.parent_id));

  async function fetchFolders(): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      folders.value = await folderApi.list();
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
    } finally {
      loading.value = false;
    }
  }

  async function fetchFolderTree(): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      folderTree.value = await folderApi.getTree();
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
    } finally {
      loading.value = false;
    }
  }

  async function createFolder(
    name: string,
    parentId: string | null = null,
  ): Promise<Folder> {
    const folder = await folderApi.create({
      name,
      parent_id: parentId,
    });
    await fetchFolderTree();
    return folder;
  }

  async function renameFolder(id: string, name: string): Promise<Folder> {
    const folder = await folderApi.update(id, { name });
    await fetchFolderTree();
    return folder;
  }

  async function moveFolder(
    id: string,
    parentId: string | null,
  ): Promise<Folder> {
    const folder = await folderApi.update(id, { parent_id: parentId });
    await fetchFolderTree();
    return folder;
  }

  async function deleteFolder(id: string): Promise<void> {
    await folderApi.delete(id);
    expandedFolders.value.delete(id);
    if (currentFolderId.value === id) {
      currentFolderId.value = null;
    }
    await fetchFolderTree();
  }

  async function moveWorkflowToFolder(
    folderId: string,
    workflowId: string,
  ): Promise<WorkflowListItem> {
    const workflow = await folderApi.moveWorkflowToFolder(folderId, workflowId);
    await fetchFolderTree();
    return workflow;
  }

  async function removeWorkflowFromFolder(
    workflowId: string,
  ): Promise<WorkflowListItem> {
    const workflow = await folderApi.removeWorkflowFromFolder(workflowId);
    await fetchFolderTree();
    return workflow;
  }

  function toggleFolder(id: string): void {
    if (expandedFolders.value.has(id)) {
      expandedFolders.value.delete(id);
    } else {
      expandedFolders.value.add(id);
    }
  }

  function expandFolder(id: string): void {
    expandedFolders.value.add(id);
  }

  function collapseFolder(id: string): void {
    expandedFolders.value.delete(id);
  }

  function isFolderExpanded(id: string): boolean {
    return expandedFolders.value.has(id);
  }

  function setCurrentFolder(id: string | null): void {
    currentFolderId.value = id;
  }

  function findFolderById(id: string): FolderTree | null {
    function search(folders: FolderTree[]): FolderTree | null {
      for (const folder of folders) {
        if (folder.id === id) return folder;
        const found = search(folder.children);
        if (found) return found;
      }
      return null;
    }
    return search(folderTree.value);
  }

  function getBreadcrumb(folderId: string): Folder[] {
    const breadcrumb: Folder[] = [];
    let current = findFolderById(folderId);

    while (current) {
      breadcrumb.unshift({
        id: current.id,
        name: current.name,
        parent_id: current.parent_id,
        owner_id: "",
        created_at: "",
        updated_at: "",
      });
      if (current.parent_id) {
        current = findFolderById(current.parent_id);
      } else {
        break;
      }
    }

    return breadcrumb;
  }

  return {
    folders,
    folderTree,
    loading,
    error,
    expandedFolders,
    currentFolderId,
    rootFolders,
    fetchFolders,
    fetchFolderTree,
    createFolder,
    renameFolder,
    moveFolder,
    deleteFolder,
    moveWorkflowToFolder,
    removeWorkflowFromFolder,
    toggleFolder,
    expandFolder,
    collapseFolder,
    isFolderExpanded,
    setCurrentFolder,
    findFolderById,
    getBreadcrumb,
  };
});
