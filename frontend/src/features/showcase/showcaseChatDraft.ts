export const SHOWCASE_CHAT_DRAFT_STORAGE_KEY = "heym-showcase-chat-draft";
export const SHOWCASE_CHAT_DRAFT_EVENT = "heym:showcase-chat-draft";

export function saveShowcaseChatDraft(draft: string): void {
  if (typeof window === "undefined") return;

  try {
    window.sessionStorage.setItem(SHOWCASE_CHAT_DRAFT_STORAGE_KEY, draft);
  } catch {
    // Ignore storage failures so the chat flow can still attempt navigation.
  }

  window.dispatchEvent(new CustomEvent(SHOWCASE_CHAT_DRAFT_EVENT));
}

export function consumeShowcaseChatDraft(): string {
  if (typeof window === "undefined") return "";

  try {
    const draft = window.sessionStorage.getItem(SHOWCASE_CHAT_DRAFT_STORAGE_KEY) ?? "";
    if (draft) {
      window.sessionStorage.removeItem(SHOWCASE_CHAT_DRAFT_STORAGE_KEY);
    }
    return draft;
  } catch {
    return "";
  }
}
