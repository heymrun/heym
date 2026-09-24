import { reactive } from "vue";

export type AvatarLoadState = "loaded" | "missing";

// Shared across every avatar on the page, so a user without a Gravatar is asked for once.
const avatarLoadStates = reactive(new Map<string, AvatarLoadState>());

export function getAvatarLoadState(userId: string): AvatarLoadState | undefined {
  return avatarLoadStates.get(userId);
}

export function setAvatarLoadState(userId: string, state: AvatarLoadState): void {
  avatarLoadStates.set(userId, state);
}

export function userInitial(name?: string | null, email?: string | null): string {
  const source = name?.trim() || email?.trim() || "?";
  return source.charAt(0).toUpperCase();
}
