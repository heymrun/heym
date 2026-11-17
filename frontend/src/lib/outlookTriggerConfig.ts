import type { NodeData, OutlookAfterAction, OutlookMailbox } from "@/types/workflow";
import type { GmailOption } from "@/lib/gmailTriggerConfig";

export { parseGmailAliases as parseOutlookAliases, toggleGmailAlias as toggleOutlookAlias } from "@/lib/gmailTriggerConfig";

export const OUTLOOK_MAILBOX_OPTIONS: GmailOption<OutlookMailbox>[] = [
  { value: "inbox", label: "Inbox" },
  { value: "focused", label: "Focused Inbox" },
  { value: "other", label: "Other (Focused Inbox)" },
  { value: "important", label: "High importance" },
  { value: "sent", label: "Sent Items" },
  { value: "all", label: "All mail (every received folder, archive included)" },
  { value: "folder", label: "A folder…" },
];

export const OUTLOOK_AFTER_ACTION_OPTIONS: GmailOption<OutlookAfterAction>[] = [
  { value: "none", label: "No action" },
  { value: "markRead", label: "Mark as read" },
  { value: "archive", label: "Move to Archive" },
  { value: "markReadAndArchive", label: "Mark as read and move to Archive" },
  { value: "delete", label: "Delete (move to Deleted Items)" },
];

export function outlookMailbox(raw: unknown): OutlookMailbox {
  return OUTLOOK_MAILBOX_OPTIONS.some((option) => option.value === raw)
    ? (raw as OutlookMailbox)
    : "inbox";
}

export function outlookAfterAction(raw: unknown): OutlookAfterAction {
  return OUTLOOK_AFTER_ACTION_OPTIONS.some((option) => option.value === raw)
    ? (raw as OutlookAfterAction)
    : "none";
}

/** Save-time problems besides the credential, which the store checks for every trigger. */
export function outlookTriggerProblems(data: NodeData): string[] {
  const problems: string[] = [];
  const interval =
    typeof data.pollIntervalMinutes === "number"
      ? data.pollIntervalMinutes
      : Number.parseInt(String(data.pollIntervalMinutes ?? ""), 10);
  if (!Number.isInteger(interval) || interval < 1) {
    problems.push("Poll interval must be at least 1 minute");
  }
  if (outlookMailbox(data.outlookMailbox) === "folder" && !String(data.outlookFolderId ?? "").trim()) {
    problems.push("Choose the folder to watch");
  }
  return problems;
}
