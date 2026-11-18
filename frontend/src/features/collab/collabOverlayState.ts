import type { CollabStatus } from "@/features/collab/collabClient";
import type { CollabIdentity } from "@/features/collab/types";
import type { CollabUser } from "@/features/collab/usePresence";

export const MAX_VISIBLE_COLLAB_AVATARS = 5;

export interface CollabOverlayState<TUser extends CollabUser = CollabUser> {
  others: TUser[];
  visible: TUser[];
  hiddenCount: number;
  showBar: boolean;
  showReconnecting: boolean;
  showOverlay: boolean;
}

export function computeCollabOverlayState<TUser extends CollabUser>(params: {
  me: CollabIdentity | null;
  users: readonly TUser[];
  status: CollabStatus;
  maxVisible?: number;
}): CollabOverlayState<TUser> {
  const { me, users, status, maxVisible = MAX_VISIBLE_COLLAB_AVATARS } = params;
  if (!me) {
    return {
      others: [],
      visible: [],
      hiddenCount: 0,
      showBar: false,
      showReconnecting: false,
      showOverlay: false,
    };
  }
  const others = users.filter((user) => !user.isSelf);
  const visible = others.slice(0, maxVisible);
  const hiddenCount = Math.max(0, others.length - maxVisible);
  const showBar = others.length > 0;
  const showReconnecting = status !== "open";
  return {
    others,
    visible,
    hiddenCount,
    showBar,
    showReconnecting,
    showOverlay: showBar || showReconnecting,
  };
}
