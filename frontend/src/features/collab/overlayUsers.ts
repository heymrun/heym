import type { CollabUserView } from "@/features/collab/useCanvasCollab";

/** Users to draw in the collaboration bar: everyone except the current user. */
export function overlayUsers(users: CollabUserView[]): CollabUserView[] {
  return users.filter((user) => !user.isSelf);
}

/**
 * The bar is shown when another user is in the room, or on its own while the
 * connection is down so the "Reconnecting…" notice stays visible.
 */
export function shouldShowOverlay(others: CollabUserView[], status: string): boolean {
  return others.length > 0 || status !== "open";
}
