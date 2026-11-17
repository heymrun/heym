import { describe, expect, it } from "vitest";

import { overlayUsers, shouldShowOverlay } from "@/features/collab/overlayUsers";
import type { CollabUserView } from "@/features/collab/useCanvasCollab";

function user(userId: string, isSelf: boolean): CollabUserView {
  return {
    userId,
    name: userId,
    color: "#6366F1",
    permission: "write",
    sids: [`${userId}-sid`],
    isSelf,
    mic: false,
    speaking: false,
    audioFailed: false,
    following: false,
  } satisfies CollabUserView;
}

describe("overlayUsers", () => {
  it("never lists the current user", () => {
    expect(overlayUsers([user("a", true)])).toEqual([]);
  });

  it("lists only other users when someone joins", () => {
    const result = overlayUsers([user("a", true), user("b", false)]);
    expect(result.map((entry) => entry.userId)).toEqual(["b"]);
  });

  it("drops the bar entry again when the other user leaves", () => {
    expect(overlayUsers([user("a", true)])).toHaveLength(0);
  });
});

describe("shouldShowOverlay", () => {
  it("hides the bar when alone, even with several own tabs (merged into the self entry)", () => {
    expect(shouldShowOverlay(overlayUsers([user("a", true)]), "open")).toBe(false);
  });

  it("shows the bar when another user is present", () => {
    expect(shouldShowOverlay(overlayUsers([user("a", true), user("b", false)]), "open")).toBe(true);
  });

  it("keeps the Reconnecting notice visible when alone", () => {
    expect(shouldShowOverlay([], "connecting")).toBe(true);
  });
});
