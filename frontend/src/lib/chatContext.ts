/**
 * Context chips the Chat tab sends along with a user message.
 *
 * Other screens (the canvas Execution History dialog) hand items over through a
 * sessionStorage draft, like `showcaseChatDraft.ts`. On send the remaining items are
 * appended to the message as a `[HEYM CONTEXT]` block carrying full ids, which the
 * chat model passes to `get_workflow_run_history` / `get_workflow_definition`. The
 * UI parses the block back out and renders it as chips.
 */

export interface ChatContextItem {
  kind: "workflow" | "execution";
  /** Workflow id for both kinds; a run is looked up through its workflow. */
  workflowId: string;
  /** Display name of the workflow (workflow kind). */
  workflowName?: string;
  /** Execution history row id (execution kind). */
  executionId?: string;
}

export interface ExtractedChatContext {
  text: string;
  items: ChatContextItem[];
}

export const CHAT_CONTEXT_HEADER = "[HEYM CONTEXT]";
export const CHAT_CONTEXT_DRAFT_STORAGE_KEY = "heym-chat-context-draft";
export const CHAT_CONTEXT_DRAFT_EVENT = "heym:chat-context-draft";

const SHORT_EXECUTION_ID_LENGTH = 8;
const UNTITLED_WORKFLOW = "Untitled workflow";
const WORKFLOW_LINE = /^- Workflow: (.*) \(workflow_id: ([^\s)]+)\)$/;
const EXECUTION_LINE = /^- Execution: (\S+) \(workflow_id: ([^\s)]+)\)$/;

function normalizeWorkflowName(name: string | undefined): string {
  const collapsed = (name ?? "").replace(/\s+/g, " ").trim();
  return collapsed || UNTITLED_WORKFLOW;
}

function formatContextLine(item: ChatContextItem): string {
  if (item.kind === "execution") {
    return `- Execution: ${item.executionId} (workflow_id: ${item.workflowId})`;
  }
  return `- Workflow: ${normalizeWorkflowName(item.workflowName)} (workflow_id: ${item.workflowId})`;
}

function parseContextLine(line: string): ChatContextItem | null {
  const workflow = WORKFLOW_LINE.exec(line);
  if (workflow) {
    return { kind: "workflow", workflowId: workflow[2], workflowName: workflow[1] };
  }
  const execution = EXECUTION_LINE.exec(line);
  if (execution) {
    return { kind: "execution", workflowId: execution[2], executionId: execution[1] };
  }
  return null;
}

/** Append the items to a user message; returns the text unchanged when there are none. */
export function appendChatContext(text: string, items: readonly ChatContextItem[]): string {
  if (items.length === 0) return text;
  return [text, "", CHAT_CONTEXT_HEADER, ...items.map(formatContextLine)].join("\n");
}

/** Split a stored user message into its visible text and its context items. */
export function extractChatContext(content: string): ExtractedChatContext {
  const marker = `\n\n${CHAT_CONTEXT_HEADER}\n`;
  const start = content.indexOf(marker);
  if (start === -1) return { text: content, items: [] };

  const lines = content.slice(start + marker.length).split("\n");
  const items: ChatContextItem[] = [];
  for (const line of lines) {
    const item = parseContextLine(line);
    if (!item) break;
    items.push(item);
  }
  if (items.length === 0) return { text: content, items: [] };

  const rest = lines.slice(items.length).join("\n");
  const after = rest.trim() ? `\n${rest}` : "";
  return { text: `${content.slice(0, start)}${after}`, items };
}

/** Short chip label: the workflow name, or the first characters of the run id. */
export function formatChatContextLabel(item: ChatContextItem): string {
  if (item.kind === "execution") {
    const id = item.executionId ?? "";
    const short = id.length > SHORT_EXECUTION_ID_LENGTH
      ? `${id.slice(0, SHORT_EXECUTION_ID_LENGTH)}…`
      : id;
    return `Execution: ${short}`;
  }
  return `Workflow: ${normalizeWorkflowName(item.workflowName)}`;
}

/** Full values for the chip tooltip. */
export function formatChatContextTitle(item: ChatContextItem): string {
  if (item.kind === "execution") return item.executionId ?? "";
  return `${normalizeWorkflowName(item.workflowName)} (${item.workflowId})`;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function toChatContextItem(value: unknown): ChatContextItem | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (!isNonEmptyString(raw.workflowId)) return null;
  if (raw.kind === "workflow") {
    return {
      kind: "workflow",
      workflowId: raw.workflowId,
      workflowName: typeof raw.workflowName === "string" ? raw.workflowName : undefined,
    };
  }
  if (raw.kind === "execution" && isNonEmptyString(raw.executionId)) {
    return { kind: "execution", workflowId: raw.workflowId, executionId: raw.executionId };
  }
  return null;
}

export function saveChatContextDraft(items: readonly ChatContextItem[]): void {
  if (typeof window === "undefined") return;

  try {
    window.sessionStorage.setItem(CHAT_CONTEXT_DRAFT_STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Ignore storage failures so the chat flow can still attempt navigation.
  }

  window.dispatchEvent(new CustomEvent(CHAT_CONTEXT_DRAFT_EVENT));
}

/** True when a screen handed context to the Chat tab and it has not been consumed yet. */
export function hasChatContextDraftPending(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return Boolean(window.sessionStorage.getItem(CHAT_CONTEXT_DRAFT_STORAGE_KEY));
  } catch {
    return false;
  }
}

export function consumeChatContextDraft(): ChatContextItem[] {
  if (typeof window === "undefined") return [];

  let raw: string | null = null;
  try {
    raw = window.sessionStorage.getItem(CHAT_CONTEXT_DRAFT_STORAGE_KEY);
    if (raw !== null) {
      window.sessionStorage.removeItem(CHAT_CONTEXT_DRAFT_STORAGE_KEY);
    }
  } catch {
    return [];
  }
  if (!raw) return [];

  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(toChatContextItem)
      .filter((item): item is ChatContextItem => item !== null);
  } catch {
    return [];
  }
}
