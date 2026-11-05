import type {
  BoardCard,
  CardFields,
  CardFieldsPayload,
  CardPriority,
  CardRunStatus,
} from "@/types/board";

/**
 * Card fields as the board tools on the server read them
 * (backend `app/services/board_card_fields.py`): due windows, filters and the form
 * a card's fields are edited in. No API, store or router imports, so Heym Work uses
 * the same rules.
 */

export const PRIORITY_LABELS: Record<CardPriority, string> = {
  urgent: "Urgent",
  high: "High",
  medium: "Medium",
  low: "Low",
};

/** Days, counting today, that "due this week" covers. */
export const DUE_WINDOW_DAYS = 7;

export type DueState = "overdue" | "today" | "soon" | "later";

export interface CardFilter {
  /** "me", "unassigned" or a user id. */
  assignee?: string;
  columnIds?: string[];
  priority?: CardPriority;
  due?: "overdue" | "today" | "week";
  label?: string;
  runStatus?: CardRunStatus;
}

export interface FilterContext {
  userId: string | null;
  /** Today as YYYY-MM-DD in the viewer's time zone. */
  today: string;
  /** Columns whose cards are never overdue: the board's last column. */
  doneColumnIds?: string[];
}

/** The fields a card's editor holds; empty strings mean "not set". */
export interface CardFieldForm {
  assigneeUserId: string;
  priority: CardPriority | "";
  dueDate: string;
  /** Comma-separated. */
  labels: string;
  /** The links the viewer can see; hidden ones are kept by the server. */
  links: { workflow_id: string; execution_id: string }[];
}

export function emptyCardFields(): CardFields {
  return { assignee_user_id: null, priority: null, due_date: null, labels: [], links: [] };
}

export function localDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function addDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return localDate(new Date(year, month - 1, day + days));
}

export function dueState(due: string | null, today: string): DueState | null {
  if (!due) return null;
  if (due < today) return "overdue";
  if (due === today) return "today";
  return due < addDays(today, DUE_WINDOW_DAYS) ? "soon" : "later";
}

function dueMatches(card: BoardCard, due: NonNullable<CardFilter["due"]>, context: FilterContext): boolean {
  const state = dueState(card.fields.due_date, context.today);
  if (due === "overdue") {
    return state === "overdue" && !(context.doneColumnIds ?? []).includes(card.column_id);
  }
  if (due === "today") return state === "today";
  return state === "today" || state === "soon";
}

export function cardMatches(card: BoardCard, filter: CardFilter, context: FilterContext): boolean {
  const fields = card.fields;
  if (filter.assignee === "unassigned") {
    if (fields.assignee_user_id) return false;
  } else if (filter.assignee) {
    const wanted = filter.assignee === "me" ? context.userId : filter.assignee;
    if (!wanted || fields.assignee_user_id !== wanted) return false;
  }
  if (filter.columnIds && !filter.columnIds.includes(card.column_id)) return false;
  if (filter.priority && fields.priority !== filter.priority) return false;
  if (filter.label) {
    const label = filter.label.toLocaleLowerCase();
    if (!fields.labels.some((item) => item.toLocaleLowerCase() === label)) return false;
  }
  if (filter.runStatus && card.run_status !== filter.runStatus) return false;
  return !filter.due || dueMatches(card, filter.due, context);
}

export function parseLabels(text: string): string[] {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const part of text.split(",")) {
    const label = part.trim();
    const key = label.toLocaleLowerCase();
    if (!label || seen.has(key)) continue;
    seen.add(key);
    labels.push(label);
  }
  return labels;
}

export function formFromCard(card: BoardCard): CardFieldForm {
  return {
    assigneeUserId: card.fields.assignee_user_id ?? "",
    priority: card.fields.priority ?? "",
    dueDate: card.fields.due_date ?? "",
    labels: card.fields.labels.join(", "),
    links: card.fields.links
      .filter((link) => !link.hidden && link.workflow_id)
      .map((link) => ({ workflow_id: link.workflow_id ?? "", execution_id: link.execution_id ?? "" })),
  };
}

function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

/** The fields of `form` that differ from `card`, as a write payload; null clears a field. */
export function fieldChanges(card: BoardCard, form: CardFieldForm): CardFieldsPayload {
  const before = formFromCard(card);
  const changes: CardFieldsPayload = {};
  if (form.assigneeUserId !== before.assigneeUserId) {
    changes.assignee_user_id = form.assigneeUserId || null;
  }
  if (form.priority !== before.priority) changes.priority = form.priority || null;
  if (form.dueDate !== before.dueDate) changes.due_date = form.dueDate || null;
  const labels = parseLabels(form.labels);
  if (!sameList(labels, card.fields.labels)) changes.labels = labels;
  const key = (link: { workflow_id: string; execution_id: string }): string =>
    `${link.workflow_id}:${link.execution_id.trim()}`;
  const links = form.links.filter((link) => link.workflow_id);
  if (!sameList(links.map(key), before.links.map(key))) {
    changes.links = links.map((link) => ({
      workflow_id: link.workflow_id,
      execution_id: link.execution_id.trim() || null,
    }));
  }
  return changes;
}
