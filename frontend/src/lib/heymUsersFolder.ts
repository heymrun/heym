import type { FolderTree, WorkflowListItem } from "@/types/workflow";

/** Stable id for the client-only folder that holds other people's workflows. */
export const HEYM_USERS_FOLDER_ID = "heym-users";

export function heymUserFolderId(email: string): string {
  return `heym-user:${email.trim().toLowerCase()}`;
}

/** True for the Heym Users folder and each per-user folder under it. */
export function isHeymUsersFolderId(folderId: string): boolean {
  return folderId === HEYM_USERS_FOLDER_ID || folderId.startsWith("heym-user:");
}

/**
 * Groups workflows owned by other people into a Heym Users folder.
 * The list API only sends `owner_email` to instance admins, so everyone else gets nothing.
 * Workflows already filed into a real folder, pinned, or scheduled for deletion stay where they are.
 */
export function buildHeymUsersFolder(
  workflows: readonly WorkflowListItem[],
  currentUserEmail: string | null | undefined,
  pinnedWorkflowIds: ReadonlySet<string> = new Set(),
): FolderTree | null {
  const mine = currentUserEmail?.trim().toLowerCase() ?? "";
  if (!mine) return null;

  const byOwner = new Map<string, { name: string; workflows: WorkflowListItem[] }>();
  for (const workflow of workflows) {
    const email = workflow.owner_email?.trim();
    if (!email) continue;
    const key = email.toLowerCase();
    if (key === mine) continue;
    if (workflow.folder_id || workflow.scheduled_for_deletion || pinnedWorkflowIds.has(workflow.id)) {
      continue;
    }
    const group = byOwner.get(key);
    if (group) {
      group.workflows.push(workflow);
    } else {
      byOwner.set(key, { name: email, workflows: [workflow] });
    }
  }

  if (byOwner.size === 0) return null;

  const children: FolderTree[] = [...byOwner.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([, group]) => ({
      id: heymUserFolderId(group.name),
      name: group.name,
      parent_id: HEYM_USERS_FOLDER_ID,
      virtual: true,
      children: [],
      workflows: group.workflows,
    }));

  return {
    id: HEYM_USERS_FOLDER_ID,
    name: "Heym Users",
    description: "Workflows owned by other people on this instance",
    parent_id: null,
    icon: "Users",
    virtual: true,
    children,
    workflows: [],
  };
}

export function collectHeymUsersWorkflowIds(folder: FolderTree | null): Set<string> {
  const ids = new Set<string>();
  if (!folder) return ids;
  for (const child of folder.children) {
    for (const workflow of child.workflows) ids.add(workflow.id);
  }
  return ids;
}
