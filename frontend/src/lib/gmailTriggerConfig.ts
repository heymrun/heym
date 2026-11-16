import type { GmailAfterAction, GmailMailbox, NodeData } from "@/types/workflow";

export interface GmailOption<T extends string> {
  value: T;
  label: string;
}

export const GMAIL_MAILBOX_OPTIONS: GmailOption<GmailMailbox>[] = [
  { value: "inbox", label: "Inbox" },
  { value: "primary", label: "Primary tab" },
  { value: "social", label: "Social tab" },
  { value: "promotions", label: "Promotions tab" },
  { value: "updates", label: "Updates tab" },
  { value: "forums", label: "Forums tab" },
  { value: "important", label: "Important" },
  { value: "starred", label: "Starred" },
  { value: "sent", label: "Sent" },
  { value: "all", label: "All mail (received, archived included)" },
  { value: "label", label: "A label…" },
];

export const GMAIL_AFTER_ACTION_OPTIONS: GmailOption<GmailAfterAction>[] = [
  { value: "none", label: "No action" },
  { value: "markRead", label: "Mark as read" },
  { value: "archive", label: "Archive" },
  { value: "markReadAndArchive", label: "Mark as read and archive" },
  { value: "trash", label: "Delete (move to Trash)" },
];

export function gmailMailbox(raw: unknown): GmailMailbox {
  return GMAIL_MAILBOX_OPTIONS.some((option) => option.value === raw)
    ? (raw as GmailMailbox)
    : "inbox";
}

export function gmailAfterAction(raw: unknown): GmailAfterAction {
  return GMAIL_AFTER_ACTION_OPTIONS.some((option) => option.value === raw)
    ? (raw as GmailAfterAction)
    : "none";
}

/** Addresses from text or a stored list: trimmed, lowercased, deduplicated, emails only. */
export function parseGmailAliases(raw: unknown): string[] {
  const items = Array.isArray(raw) ? raw : String(raw ?? "").split(/[,;\s]+/);
  const aliases: string[] = [];
  for (const item of items) {
    const value = String(item ?? "").trim().toLowerCase();
    if (value.includes("@") && !aliases.includes(value)) aliases.push(value);
  }
  return aliases;
}

/** Adds the address when missing, removes it when present. */
export function toggleGmailAlias(current: string[], address: string): string[] {
  const value = address.trim().toLowerCase();
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

/** Save-time problems besides the credential, which the store checks for every trigger. */
export function gmailTriggerProblems(data: NodeData): string[] {
  const problems: string[] = [];
  const interval =
    typeof data.pollIntervalMinutes === "number"
      ? data.pollIntervalMinutes
      : Number.parseInt(String(data.pollIntervalMinutes ?? ""), 10);
  if (!Number.isInteger(interval) || interval < 1) {
    problems.push("Poll interval must be at least 1 minute");
  }
  if (gmailMailbox(data.gmailMailbox) === "label" && !String(data.gmailLabelId ?? "").trim()) {
    problems.push("Choose the label to watch");
  }
  return problems;
}
