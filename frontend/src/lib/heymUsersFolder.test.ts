import { describe, expect, it } from "vitest";

import {
  HEYM_USERS_FOLDER_ID,
  buildHeymUsersFolder,
  collectHeymUsersWorkflowIds,
  heymUserFolderId,
  isHeymUsersFolderId,
} from "@/lib/heymUsersFolder";
import type { WorkflowListItem } from "@/types/workflow";

function workflow(overrides: Partial<WorkflowListItem> = {}): WorkflowListItem {
  return {
    id: "wf-1",
    name: "Weekly report",
    description: null,
    folder_id: null,
    first_node_type: null,
    trigger_status: "manual",
    scheduled_for_deletion: null,
    owner_email: "ada@example.com",
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    ...overrides,
  };
}

describe("buildHeymUsersFolder", () => {
  it("groups other people's root workflows under one folder per owner", () => {
    const folder = buildHeymUsersFolder(
      [
        workflow({ id: "kai-late", name: "Late", owner_email: "Kai@Example.com", updated_at: "2026-10-03T00:00:00Z" }),
        workflow({ id: "mine", owner_email: "Admin@Example.com" }),
        workflow({ id: "ada-a", name: "A", owner_email: "ada@example.com" }),
        workflow({ id: "ada-b", name: "B", owner_email: "Ada@Example.com" }),
        workflow({ id: "kai-early", name: "Early", owner_email: "kai@example.com" }),
      ],
      "admin@example.com",
    );

    expect(folder?.id).toBe(HEYM_USERS_FOLDER_ID);
    expect(folder?.virtual).toBe(true);
    expect(folder?.icon).toBe("Users");
    expect(folder?.children.map((child) => child.name)).toEqual(["ada@example.com", "Kai@Example.com"]);
    expect(folder?.children.map((child) => child.id)).toEqual([
      heymUserFolderId("ada@example.com"),
      heymUserFolderId("kai@example.com"),
    ]);
    expect(folder?.children.every((child) => child.virtual)).toBe(true);
    expect(folder?.children[0]?.workflows.map((item) => item.id)).toEqual(["ada-a", "ada-b"]);
    expect(folder?.children[1]?.workflows.map((item) => item.id)).toEqual(["kai-late", "kai-early"]);
    expect(collectHeymUsersWorkflowIds(folder)).toEqual(new Set(["ada-a", "ada-b", "kai-late", "kai-early"]));
  });

  it("leaves filed, pinned, and scheduled workflows out of the grouping", () => {
    const folder = buildHeymUsersFolder(
      [
        workflow({ id: "filed", folder_id: "folder-1" }),
        workflow({ id: "pinned", owner_email: "kai@example.com" }),
        workflow({ id: "scheduled", owner_email: "kai@example.com", scheduled_for_deletion: "2026-10-18T23:59:00Z" }),
        workflow({ id: "loose", owner_email: "ada@example.com" }),
      ],
      "admin@example.com",
      new Set(["pinned"]),
    );

    expect(collectHeymUsersWorkflowIds(folder)).toEqual(new Set(["loose"]));
  });

  it("returns nothing when the viewer is unknown or owns every visible workflow", () => {
    const own = [workflow({ owner_email: "admin@example.com" })];
    expect(buildHeymUsersFolder(own, "admin@example.com")).toBeNull();
    expect(buildHeymUsersFolder([workflow()], null)).toBeNull();
    expect(buildHeymUsersFolder([workflow()], "  ")).toBeNull();
    expect(buildHeymUsersFolder([workflow({ owner_email: null })], "admin@example.com")).toBeNull();
  });

  it("recognizes only the virtual folder ids", () => {
    expect(isHeymUsersFolderId(HEYM_USERS_FOLDER_ID)).toBe(true);
    expect(isHeymUsersFolderId(heymUserFolderId("ada@example.com"))).toBe(true);
    expect(isHeymUsersFolderId("folder-1")).toBe(false);
  });
});
