import type { GoogleTriggerEvent, NodeData, NodeType } from "@/types/workflow";

export const GOOGLE_TRIGGER_EVENTS: readonly GoogleTriggerEvent[] = ["created", "updated", "deleted"];

export interface GoogleTriggerEventOption {
  value: GoogleTriggerEvent;
  label: string;
}

const DRIVE_EVENT_OPTIONS: GoogleTriggerEventOption[] = [
  { value: "created", label: "File created" },
  { value: "updated", label: "File updated" },
  { value: "deleted", label: "File deleted" },
];

export const SHEETS_EVENT_OPTIONS: GoogleTriggerEventOption[] = [
  { value: "created", label: "Row added" },
  { value: "updated", label: "Row updated" },
  { value: "deleted", label: "Row deleted" },
];

/** A single watched file cannot be created, so file scope offers update and delete only. */
export function driveEventOptions(scope: "folder" | "file"): GoogleTriggerEventOption[] {
  return scope === "file"
    ? DRIVE_EVENT_OPTIONS.filter((option) => option.value !== "created")
    : DRIVE_EVENT_OPTIONS;
}

/** Events stored on the node; a missing list means every event, as on the backend. */
export function selectedEvents(raw: unknown): GoogleTriggerEvent[] {
  if (!Array.isArray(raw)) return [...GOOGLE_TRIGGER_EVENTS];
  return GOOGLE_TRIGGER_EVENTS.filter((event) => raw.includes(event));
}

export function toggleEvent(
  current: GoogleTriggerEvent[],
  event: GoogleTriggerEvent,
  enabled: boolean,
): GoogleTriggerEvent[] {
  const next = new Set(current);
  if (enabled) next.add(event);
  else next.delete(event);
  return GOOGLE_TRIGGER_EVENTS.filter((item) => next.has(item));
}

/** Validation messages for a Google trigger node, excluding the credential check. */
export function googleTriggerProblems(type: NodeType, data: NodeData): string[] {
  const problems: string[] = [];
  if (type === "googleDriveTrigger") {
    const scope = data.gdtScope === "file" ? "file" : "folder";
    if (scope === "file" && !String(data.gdtFileId ?? "").trim()) {
      problems.push("File is not specified");
    }
    const allowed = driveEventOptions(scope).map((option) => option.value);
    if (!selectedEvents(data.gdtEvents).some((event) => allowed.includes(event))) {
      problems.push("Select at least one event");
    }
  } else if (type === "googleSheetsTrigger") {
    if (!String(data.gstSpreadsheetId ?? "").trim()) problems.push("Spreadsheet is not specified");
    if (data.gstSheetName !== undefined && !String(data.gstSheetName).trim()) {
      problems.push("Sheet name is not specified");
    }
    if (selectedEvents(data.gstEvents).length === 0) problems.push("Select at least one event");
  } else {
    return problems;
  }
  const interval =
    typeof data.pollIntervalMinutes === "number"
      ? data.pollIntervalMinutes
      : Number.parseInt(String(data.pollIntervalMinutes ?? "1"), 10);
  if (!Number.isInteger(interval) || interval < 1) {
    problems.push("Poll interval must be at least 1 minute");
  }
  return problems;
}
