import { describe, expect, it } from "vitest";

import type { BoardCard, CardFields } from "@/types/board";
import {
  cardBadgeModel,
  cardMatches,
  dueState,
  emptyCardFields,
  fieldChanges,
  formatDueDate,
  formFromCard,
  localDate,
  parseLabels,
  PRIORITY_LABELS,
} from "@/lib/boardCardFields";

const today = "2026-11-05";

function card(partial: Partial<CardFields>, extra: Partial<BoardCard> = {}): BoardCard {
  return {
    id: "c",
    board_id: "b",
    column_id: "col",
    title: "T",
    content: "",
    position: 0,
    run_status: "idle",
    card_metadata: {},
    created_at: "",
    updated_at: "",
    edit_version: "v",
    fields: { ...emptyCardFields(), ...partial },
    ...extra,
  };
}

describe("dueState", () => {
  it("names overdue, today, soon and later", () => {
    expect(dueState("2026-11-04", today)).toBe("overdue");
    expect(dueState("2026-11-05", today)).toBe("today");
    expect(dueState("2026-11-11", today)).toBe("soon");
    expect(dueState("2026-11-12", today)).toBe("later");
    expect(dueState(null, today)).toBeNull();
  });
});

describe("cardMatches", () => {
  const me = "u1";
  const context = { userId: me, today };

  it("filters by assignee", () => {
    const mine = card({ assignee_user_id: me });
    expect(cardMatches(mine, { assignee: "me" }, context)).toBe(true);
    expect(cardMatches(mine, { assignee: "unassigned" }, context)).toBe(false);
    expect(cardMatches(card({}), { assignee: "unassigned" }, context)).toBe(true);
    expect(cardMatches(mine, { assignee: "u2" }, context)).toBe(false);
    expect(cardMatches(mine, { assignee: "me" }, { userId: null, today })).toBe(false);
  });

  it("filters by priority, label, column and review state", () => {
    const tagged = card({ priority: "high", labels: ["Acme"] });
    expect(cardMatches(tagged, { priority: "high", label: "acme" }, context)).toBe(true);
    expect(cardMatches(tagged, { priority: "low" }, context)).toBe(false);
    expect(cardMatches(tagged, { columnIds: ["other"] }, context)).toBe(false);
    expect(cardMatches(tagged, { columnIds: ["col"] }, context)).toBe(true);
    const waiting = card({}, { run_status: "pending" });
    expect(cardMatches(waiting, { runStatus: "pending" }, context)).toBe(true);
    expect(cardMatches(tagged, { runStatus: "pending" }, context)).toBe(false);
  });

  it("filters by due window, in every column", () => {
    const late = card({ due_date: "2026-11-01" });
    expect(cardMatches(late, { due: "overdue" }, context)).toBe(true);
    expect(cardMatches(card({ due_date: today }), { due: "today" }, context)).toBe(true);
    expect(cardMatches(card({ due_date: "2026-11-08" }), { due: "week" }, context)).toBe(true);
    expect(cardMatches(late, { due: "week" }, context)).toBe(false);
    expect(cardMatches(card({}), { due: "week" }, context)).toBe(false);
  });
});

describe("localDate", () => {
  it("formats a date as YYYY-MM-DD in local time", () => {
    expect(localDate(new Date(2026, 10, 5, 23, 30))).toBe("2026-11-05");
  });
});

describe("parseLabels", () => {
  it("trims, drops empties and repeats in any case", () => {
    expect(parseLabels(" Acme, acme ,NDA,, ")).toEqual(["Acme", "NDA"]);
  });
});

describe("fieldChanges", () => {
  it("sends only the fields that changed", () => {
    const current = card({ priority: "low", labels: ["Acme"] });
    const form = formFromCard(current);
    expect(fieldChanges(current, form)).toEqual({});
    form.priority = "urgent";
    form.dueDate = "2026-11-10";
    expect(fieldChanges(current, form)).toEqual({ priority: "urgent", due_date: "2026-11-10" });
  });

  it("clears with null and keeps labels that only differ in spacing", () => {
    const current = card({ assignee_user_id: "u1", labels: ["Acme"] });
    const form = formFromCard(current);
    form.assigneeUserId = "";
    form.labels = " Acme ";
    expect(fieldChanges(current, form)).toEqual({ assignee_user_id: null });
  });
});

it("labels every priority, most urgent first", () => {
  expect(Object.keys(PRIORITY_LABELS)).toEqual(["urgent", "high", "medium", "low"]);
});

describe("cardBadgeModel", () => {
  const members = [
    { user_id: "u1", name: "Ada", email: "ada@example.com", permission: "owner" as const },
  ];

  it("is empty for a card without fields", () => {
    expect(cardBadgeModel(card({}), members, today)).toEqual({
      assignee: null,
      priority: null,
      due: null,
      labels: [],
      moreLabels: 0,
    });
  });

  it("names the assignee, the due state and the extra labels", () => {
    const model = cardBadgeModel(
      card({
        assignee_user_id: "u1",
        priority: "urgent",
        due_date: "2026-11-04",
        labels: ["Acme", "NDA", "Q4"],
      }),
      members,
      today,
    );
    expect(model.assignee).toEqual({ userId: "u1", name: "Ada", email: "ada@example.com" });
    expect(model.priority).toBe("urgent");
    expect(model.due).toEqual({ date: "2026-11-04", label: "Nov 4", state: "overdue" });
    expect(model.labels).toEqual(["Acme", "NDA"]);
    expect(model.moreLabels).toBe(1);
  });

  it("keeps an assignee who is no longer a member", () => {
    const model = cardBadgeModel(card({ assignee_user_id: "gone" }), members, today);
    expect(model.assignee).toEqual({ userId: "gone", name: "Former member", email: null });
  });
});

it("formats a due date without a time zone shift", () => {
  expect(formatDueDate("2026-01-01")).toBe("Jan 1");
});
